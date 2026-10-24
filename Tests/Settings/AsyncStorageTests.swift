import Foundation
#if canImport(Combine)
import Combine
#endif

private final class DiskProbe: @unchecked Sendable {
    private let lock = NSLock()
    private let gate = DispatchSemaphore(value: 0)
    private var readBlock = false
    private var providerBlock = false
    private var writeBlock = false
    private var blockAfterWrite = false
    private var failingRead = false
    private var failingWrite = false
    private var reads = 0, writes = 0, providerReads = 0, waiting = 0, active = 0, peak = 0
    func armRead() { lock.lock(); readBlock = true; lock.unlock() }
    func armProvider() { lock.lock(); providerBlock = true; lock.unlock() }
    func armWrite(after: Bool = false) { lock.lock(); writeBlock = true; blockAfterWrite = after; lock.unlock() }
    func failRead(_ value: Bool) { lock.lock(); failingRead = value; lock.unlock() }
    func failWrite(_ value: Bool) { lock.lock(); failingWrite = value; lock.unlock() }
    func release() { gate.signal() }
    func counts() -> (reads: Int, writes: Int, providerReads: Int, waiting: Int, peak: Int) {
        lock.lock(); defer { lock.unlock() }; return (reads,writes,providerReads,waiting,peak)
    }
    private func enter() {
        dispatchPrecondition(condition: .notOnQueue(.main))
        lock.lock(); active += 1; peak = max(peak,active); lock.unlock()
    }
    private func leave() { lock.lock(); active -= 1; lock.unlock() }
    private func wait() {
        lock.lock(); waiting += 1; lock.unlock()
        precondition(gate.wait(timeout: .now()+10) == .success, "test gate timed out")
    }
    func read(_ url: URL) throws -> Data {
        enter(); defer { leave() }
        lock.lock(); reads += 1; let block=readBlock, fail=failingRead; readBlock=false; lock.unlock()
        if block { wait() }
        if fail { throw CocoaError(.fileReadNoPermission) }
        let handle=try FileHandle(forReadingFrom:url); defer { try? handle.close() }
        return try handle.readToEnd() ?? Data()
    }
    func imported(_ url: URL) throws -> Data {
        enter(); defer { leave() }
        lock.lock(); providerReads += 1; let block=providerBlock; providerBlock=false; lock.unlock()
        if block { wait() }
        return try Data(contentsOf:url)
    }
    func write(_ data: Data, _ url: URL) throws {
        enter(); defer { leave() }
        lock.lock(); writes += 1
        let block=writeBlock, after=blockAfterWrite, fail=failingWrite
        writeBlock=false; lock.unlock()
        if block && !after { wait() }
        if fail { throw CocoaError(.fileWriteNoPermission) }
        try FileManager.default.createDirectory(at:url.deletingLastPathComponent(),withIntermediateDirectories:true)
        try data.write(to:url,options:.atomic)
        if block && after { wait() }
    }
}

@main
struct AsyncStorageTests {
    @MainActor static var assertions=0
    @MainActor static func check(_ condition: Bool, _ message: String) {
        assertions += 1
        if !condition { fatalError(message) }
    }
    @MainActor static func waitFor(_ condition: () -> Bool) async throws {
        let end=ProcessInfo.processInfo.systemUptime+5
        while !condition() {
            if ProcessInfo.processInfo.systemUptime >= end { fatalError("test observation deadline") }
            try await Task.sleep(nanoseconds:1_000_000)
        }
        assertions += 1
    }
    @MainActor static func rejects(_ operation: () async throws -> Void) async {
        do { try await operation(); fatalError("operation unexpectedly accepted") }
        catch { assertions += 1 }
    }
    @MainActor private static func make(_ url: URL, _ defaults: UserDefaults, _ p: DiskProbe) -> SettingsStore {
        SettingsStore(fileURL:url,legacy:defaults,
            storage:.init(read:{ try p.read($0) },write:{ try p.write($0,$1) },imported:{ try p.imported($0) }))
    }
    @MainActor static func seed(_ url: URL, audio: Bool = false) throws -> AppSettings {
        var value=AppSettings();value.background.silentAudio=audio
        value.server.listenPort="23456"; value.server.authUsername="unchanged";value.server.authPassword="test-only"
        try value.encoded().write(to:url,options:.atomic)
        return value
    }
    @MainActor static func noBackup(_ root: URL) throws {
        check(try FileManager.default.contentsOfDirectory(atPath:root.path).allSatisfy{ !$0.hasPrefix(".settings-") },"transaction backup leaked")
    }

    @MainActor static func main() async throws {
        let name=CommandLine.arguments.dropFirst().first ?? "normal"
        let root=FileManager.default.temporaryDirectory.appendingPathComponent("Settings-async-"+UUID().uuidString)
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        let url=root.appendingPathComponent("settings.json"), imported=root.appendingPathComponent("import.json")
        let suite="Settings-async-"+UUID().uuidString
        let defaults=UserDefaults(suiteName:suite)!
        defer { defaults.removePersistentDomain(forName:suite); try? FileManager.default.removeItem(at:root) }
        let p=DiskProbe()
        switch name {
        case "normal":
            _=try seed(url)
            let s=make(url,defaults,p);await s.whenLoaded()
            check(s.loadState == .ready,"ready load")
            s.set(\.background.silentAudio,true)
            check(s.value.background.silentAudio,"live update precedes flush")
            try await s.flush()
            check(try AppSettings.decoded(Data(contentsOf:url)) == s.value,"durable snapshot")
            var next=s.value;next.server.listenPort="34567"
            try await s.importData(next.encoded())
            check(s.value == next,"validated import published")
            check(try AppSettings.decoded(Data(contentsOf:url)) == next,"import disk")
        case "blocked-load":
            var original=try seed(url,audio:true);original.background.continuousLocation=true
            try original.encoded().write(to:url)
            p.armRead()
            let s=make(url,defaults,p)
            s.set(\.background.silentAudio,false)
            s.set(\.serverRunning,false)
            check(!s.value.background.silentAudio && s.loadState == .loading,"Off before blocked read")
            try await waitFor{ p.counts().waiting == 1 }
            p.release();await s.whenLoaded();try await s.flush()
            check(!s.value.background.silentAudio,"load cannot undo explicit Off")
            check(s.value.server == original.server && s.value.background.continuousLocation,"untouched saved fields preserved")
            check(try AppSettings.decoded(Data(contentsOf:url)) == s.value,"merged early edits persisted")
        case "blocked-save":
            _=try seed(url,audio:true)
            let s=make(url,defaults,p);await s.whenLoaded();p.armWrite()
            s.set(\.background.silentAudio,false)
            try await waitFor{ p.counts().waiting == 1 }
            for i in 0..<100_000 { s.set(\.selectedTab,i % 2 == 0 ? .server : .background) }
            s.set(\.selectedTab,.settings)
            check(!s.value.background.silentAudio && s.value.selectedTab == .settings,"edits not blocked by disk")
            check(p.counts().writes == 1 && p.counts().peak == 1,"one blocked write")
            p.release();try await s.flush()
            check(p.counts().writes == 2,"only latest snapshot queued")
            check(try AppSettings.decoded(Data(contentsOf:url)) == s.value,"latest durable after old completion")
        case "same-save":
            _=try seed(url)
            let s=make(url,defaults,p);await s.whenLoaded();p.armWrite()
            s.set(\.background.silentAudio,true)
            try await waitFor{ p.counts().waiting == 1 }
            let first=s.change
            for _ in 0..<10_000 { s.set(\.background.silentAudio,true) }
            check(s.change.revision == first.revision+10_000 && s.change.origin == .user,
                  "equal explicit choices preserve their intent revisions")
            let flush=Task { @MainActor in try await s.flush() }
            await Task.yield();p.release();try await flush.value
            check(p.counts().writes == 1,"SAME_SAVE_DUPLICATED")
            check(!s.savePending && s.errorMessage == nil,"same snapshot became durable")
            check(try AppSettings.decoded(Data(contentsOf:url)) == s.value,"same-save durable snapshot")
        case "early-same-save":
            let original=try seed(url)
            p.armRead();let s=make(url,defaults,p)
            s.set(\.background.silentAudio,false)
            try await waitFor{ p.counts().waiting == 1 }
            p.release();await s.whenLoaded()
            check(s.value == original,"EARLY_LOAD_LOST_UNEDITED_FIELDS")
            check(!s.savePending,"EARLY_EQUAL_LOAD_REWROTE_FILE")
            try await s.flush()
            check(p.counts().writes == 0 && !s.savePending,"EARLY_EQUAL_LOAD_REWROTE_FILE")
            check(try AppSettings.decoded(Data(contentsOf:url)) == original,"early equal edit preserved disk")
        case "early-overlap":
            var expected=try seed(url,audio:true)
            p.armRead();let s=make(url,defaults,p)
            s.set(\.server.listenPort,"34567")
            var whole=ServerSettings();whole.listenPort="45678"
            whole.authUsername="last-user";whole.authPassword="last-password"
            s.set(\.server,whole)
            s.set(\.server.listenPort,"56789")
            expected.server=whole;expected.server.listenPort="56789"
            try await waitFor{ p.counts().waiting == 1 }
            p.release();await s.whenLoaded();try await s.flush()
            check(s.value == expected,"overlapping early paths must follow acceptance order")
            check(try AppSettings.decoded(Data(contentsOf:url)) == expected,"overlapping early edits durable")
        case "save-failure":
            _=try seed(url,audio:true)
            let s=make(url,defaults,p);await s.whenLoaded();p.failWrite(true)
            s.set(\.background.silentAudio,false)
            await rejects { try await s.flush() }
            check(!s.value.background.silentAudio && s.savePending,"failed save must not block Off")
            check(s.errorMessage != nil,"write error retained")
            p.failWrite(false);s.set(\.background.silentAudio,false);try await s.flush()
            check(!s.savePending && s.errorMessage == nil,"explicit same choice retries once")
        case "flush-retry":
            _=try seed(url,audio:true)
            let s=make(url,defaults,p);await s.whenLoaded();p.failWrite(true)
            s.set(\.background.silentAudio,false)
            await rejects { try await s.flush() }
            let failedWrites=p.counts().writes
            await Task.yield()
            check(p.counts().writes == failedWrites,"no automatic save failure loop")
            p.failWrite(false);try await s.flush()
            check(!s.savePending && s.errorMessage == nil,"explicit flush retries failed durability")
            check(!(try AppSettings.decoded(Data(contentsOf:url))).background.silentAudio,"flush retry persisted Off")
        case "invalid-import":
            let original=try seed(url)
            let s=make(url,defaults,p);await s.whenLoaded()
            var wrongVersion=original;wrongVersion.version=2
            var wrongServer=original;wrongServer.server.authPassword=""
            let values=[Data("not json".utf8),try wrongVersion.encoded(),try wrongServer.encoded(),Data(repeating:65,count:65_537)]
            let originalData=try Data(contentsOf:url)
            for data in values {
                await rejects { try await s.importData(data) }
                check(s.value == original,"invalid import live state")
                check(try Data(contentsOf:url) == originalData,"invalid import disk")
                try noBackup(root)
            }
        case "stale-import":
            let original=try seed(url)
            var other=original;other.background.silentAudio=true;try other.encoded().write(to:imported)
            let s=make(url,defaults,p);await s.whenLoaded();p.armProvider()
            let task=Task { try await s.importFile(imported) }
            try await waitFor{ p.counts().waiting == 1 }
            s.set(\.background.silentAudio,false) // Unchanged explicit Off still supersedes import.
            p.release();await rejects { try await task.value }
            try await s.flush()
            check(!s.value.background.silentAudio,"stale import reenabled audio")
            check(try AppSettings.decoded(Data(contentsOf:url)) == original,"stale import changed disk")
        case "cancel-commit", "cancel-corrupt-commit":
            let original: Data
            if name == "cancel-corrupt-commit" { original=Data("malformed original\u{0}".utf8);try original.write(to:url) }
            else { _=try seed(url);original=try Data(contentsOf:url) }
            let s=make(url,defaults,p);await s.whenLoaded()
            let before=s.value
            var other=AppSettings();other.background.silentAudio=true
            p.armWrite(after:true)
            let task=Task { try await s.importData(other.encoded()) }
            try await waitFor{ p.counts().waiting == 1 }
            task.cancel();p.release();await rejects { try await task.value }
            check(s.value == before,"cancelled committed import changed memory")
            check(try Data(contentsOf:url) == original,"cancelled commit failed exact rollback")
        case "supersede-commit":
            _=try seed(url,audio:true)
            let s=make(url,defaults,p);await s.whenLoaded()
            var other=s.value;other.server.listenPort="45678"
            p.armWrite(after:true)
            let task=Task { try await s.importData(other.encoded()) }
            try await waitFor{ p.counts().waiting == 1 }
            s.set(\.background.silentAudio,false);s.set(\.server.listenPort,"56789")
            p.release();await rejects { try await task.value };try await s.flush()
            check(!s.value.background.silentAudio && s.value.server.listenPort == "56789","latest intent lost")
            check(try AppSettings.decoded(Data(contentsOf:url)) == s.value,"rollback clobbered newer save")
        case "ordered-imports":
            let original=try seed(url)
            var other=original;other.server.listenPort="34567";try other.encoded().write(to:imported)
            let s=make(url,defaults,p);await s.whenLoaded();p.armProvider()
            let first=Task { try await s.importFile(imported) }
            try await waitFor{ p.counts().waiting == 1 }
            let second=Task { try await s.importData(other.encoded()) }
            await Task.yield()
            var final=original;final.server.listenPort="45678"
            let last=Task { try await s.importData(final.encoded()) }
            await Task.yield();p.release()
            await rejects { try await first.value };await rejects { try await second.value }
            try await last.value
            check(s.value == final,"newest import did not win")
            check(try AppSettings.decoded(Data(contentsOf:url)) == final,"newest import not durable")
        case "load-failure":
            let original=try seed(url,audio:true)
            defaults.set(true,forKey:"background.silentAudio")
            p.failRead(true)
            let s=make(url,defaults,p);await s.whenLoaded()
            check(s.loadState == .failed && p.counts().writes == 0,"inaccessible file mistaken for absent")
            s.set(\.background.silentAudio,false);await s.whenLoaded()
            check(p.counts().writes == 0 && defaults.bool(forKey:"background.silentAudio"),"unreadable file was overwritten/migrated")
            p.failRead(false);s.set(\.selectedTab,.settings);await s.whenLoaded();try await s.flush()
            check(s.loadState == .ready && s.value.server == original.server,"read recovery lost saved fields")
            check(!s.value.background.silentAudio,"read recovery lost early Off")
        case "migration":
            defaults.set(true,forKey:"background.silentAudio")
            defaults.set(true,forKey:"background.continuousLocation")
            p.failWrite(true)
            let s=make(url,defaults,p);await s.whenLoaded();await rejects { try await s.flush() }
            check(s.value.background.silentAudio && defaults.bool(forKey:"background.silentAudio"),"failed migration discarded old defaults")
            p.failWrite(false);s.set(\.background.silentAudio,false);try await s.flush()
            check(defaults.object(forKey:"background.silentAudio") == nil && defaults.object(forKey:"background.continuousLocation") == nil,"successful migration did not remove keys")
            check(try AppSettings.decoded(Data(contentsOf:url)) == s.value,"migration file")
        case "reentrant-edit":
            _=try seed(url)
            let s=make(url,defaults,p);await s.whenLoaded()
            var armed=true
            let subscription=s.objectWillChange.sink { _ in
                if armed && s.value.serverRunning { armed=false;s.set(\.serverRunning,false) }
            }
            s.set(\.serverRunning,true)
            check(!s.value.serverRunning,"reentrant latest edit lost")
            try await s.flush()
            check(!s.value.serverRunning,"save completion changed the latest reentrant edit")
            check(!(try AppSettings.decoded(Data(contentsOf:url))).serverRunning,"reentrant latest save lost")
            subscription.cancel()
        case "reentrant-load":
            _=try seed(url,audio:true)
            p.armRead();let s=make(url,defaults,p)
            var armed=true
            let subscription=s.objectWillChange.sink { _ in
                if armed && s.loadState == .ready {
                    armed=false
                    check(s.value.background.silentAudio && !s.savePending && s.errorMessage == nil,
                          "load fields were not published coherently")
                    s.set(\.background.silentAudio,false)
                }
            }
            try await waitFor{ p.counts().waiting == 1 }
            p.release();await s.whenLoaded();try await s.flush()
            check(!armed && !s.value.background.silentAudio && s.change.origin == .user,
                  "load publication overwrote newer explicit Off")
            check(!(try AppSettings.decoded(Data(contentsOf:url))).background.silentAudio,"load reentry durable Off")
            subscription.cancel()
        case "reentrant-import":
            _=try seed(url)
            let s=make(url,defaults,p);await s.whenLoaded()
            var armed=true
            let subscription=s.objectWillChange.sink { _ in
                if armed && s.change.origin == .imported {
                    armed=false
                    check(s.loadState == .ready && !s.savePending && s.value.background.silentAudio,
                          "import fields were not published coherently")
                    s.set(\.background.silentAudio,false)
                }
            }
            var imported=s.value;imported.background.silentAudio=true
            try await s.importData(imported.encoded());try await s.flush()
            check(!armed && !s.value.background.silentAudio,"import publication overwrote newer Off")
            check(!(try AppSettings.decoded(Data(contentsOf:url))).background.silentAudio,"import reentry durable Off")
            subscription.cancel()
        case "reentrant-save":
            _=try seed(url)
            let s=make(url,defaults,p);await s.whenLoaded()
            var armed=true
            let subscription=s.objectWillChange.sink { _ in
                if armed && s.value.serverRunning && !s.savePending {
                    armed=false;s.set(\.serverRunning,false)
                }
            }
            s.set(\.serverRunning,true);try await s.flush()
            check(!armed && !s.value.serverRunning,"save completion overwrote newer Off")
            try await s.flush()
            check(!(try AppSettings.decoded(Data(contentsOf:url))).serverRunning,"save reentry durable Off")
            subscription.cancel()
        case "intent-stamps":
            _=try seed(url,audio:true)
            let s=make(url,defaults,p);await s.whenLoaded()
            let loaded=s.change
            check(s.audioChange == loaded && s.locationChange == loaded && s.serverRunningChange == loaded,
                  "load did not commit all service intent stamps")
            let audio=s.audioChange
            s.set(\.serverRunning,false)
            let stopped=s.serverRunningChange
            s.set(\.selectedTab,.settings)
            s.set(\.server.listenPort,"45678")
            check(s.audioChange == audio && s.serverRunningChange == stopped && s.locationChange == loaded,
                  "UNRELATED_EDIT_SUPERSEDED_SERVICE_INTENT")
            s.set(\.background.silentAudio,false)
            let firstOff=s.audioChange
            s.set(\.background.silentAudio,false)
            check(s.audioChange != firstOff && s.serverRunningChange == stopped && s.locationChange == loaded,
                  "same explicit Off must supersede its own earlier service intent")
            let background=s.value.background
            s.set(\.background,background)
            check(s.audioChange == s.change && s.locationChange == s.change && s.serverRunningChange == stopped,
                  "whole background edit did not supersede its overlapping service intents")
            let whole=s.value
            s.set(\AppSettings.self,whole)
            check(s.audioChange == s.change && s.locationChange == s.change && s.serverRunningChange == s.change,
                  "whole settings edit did not supersede all service intents")
            try await s.flush()
            try await s.importData(whole.encoded())
            check(s.change.origin == .imported && s.audioChange == s.change &&
                  s.locationChange == s.change && s.serverRunningChange == s.change,
                  "durable import did not commit all service intent stamps")
        case "import-during-load":
            let original=try seed(url,audio:true)
            p.armRead();let s=make(url,defaults,p)
            var changes=[SettingsStore.Change]()
            let subscription=s.objectWillChange.sink { _ in
                if s.loadState == .ready { changes.append(s.change) }
            }
            var latest=original;latest.background.silentAudio=false;latest.server.listenPort="45678"
            let task=Task { @MainActor in try await s.importData(latest.encoded()) }
            await Task.yield()
            try await waitFor{ p.counts().waiting == 1 }
            p.release();try await task.value;try await s.flush()
            check(s.value == latest && s.change.origin == .imported,"import lost behind initial load")
            check(changes.contains{ $0.origin == .load } && changes.contains{ $0.origin == .imported },
                  "load and import origins must remain distinguishable")
            check(try AppSettings.decoded(Data(contentsOf:url)) == latest,"initial-load import durable")
            subscription.cancel()
        #if SETTINGS_REVISION_BOUNDARY
        case "revision-limit":
            _=try seed(url,audio:true)
            let s=make(url,defaults,p);await s.whenLoaded();p.armWrite(after:true)
            s.set(\.serverRunning,true)
            let last=s.change
            check(last.revision == UInt64.max && !s.acceptsNewIntent,"last revision boundary not reached")
            try await waitFor{ p.counts().waiting == 1 }
            s.set(\.background.silentAudio,false)
            s.set(\.serverRunning,false)
            s.set(\.background.continuousLocation,false)
            s.set(\.background.silentAudio,true)
            check(s.revisionExhausted && s.loadState == .failed && s.change == last,
                  "REVISION_IDENTIFIER_REUSED")
            check(!s.value.serverRunning && !s.value.background.silentAudio,
                  "terminal exhaustion lost a safe Off or accepted On")
            await rejects { try await s.importData(AppSettings().encoded()) }
            await rejects { try await s.flush() }
            p.release();try await waitFor{ s.testStorageIdle }
            check(s.errorMessage != nil && s.savePending && s.loadState == .failed,
                  "late save cleared the terminal failure")
            check(!s.value.serverRunning && !s.value.background.silentAudio && p.counts().writes == 1,
                  "late save revived intent or scheduled new work")
        case "revision-load-limit":
            let original=try seed(url,audio:true)
            p.armRead();let s=make(url,defaults,p)
            s.set(\.selectedTab,.settings)
            s.set(\.background.silentAudio,false)
            await s.whenLoaded()
            check(s.revisionExhausted && !s.value.background.silentAudio,"terminal load lost Off")
            try await waitFor{ p.counts().waiting == 1 }
            p.release();try await waitFor{ s.testStorageIdle }
            check(s.loadState == .failed && !s.value.background.silentAudio,
                  "late load revived terminal intent")
            let preserved=try AppSettings.decoded(Data(contentsOf:url))
            check(p.counts().writes == 0 && preserved == original,
                  "terminal load overwrote the preserved file")
        case "revision-import-limit":
            _=try seed(url,audio:true)
            let s=make(url,defaults,p);await s.whenLoaded()
            let original=try Data(contentsOf:url)
            var next=s.value;next.server.listenPort="45678"
            p.armWrite(after:true)
            let task=Task { @MainActor in try await s.importData(next.encoded()) }
            try await waitFor{ p.counts().waiting == 1 }
            s.set(\.background.silentAudio,false)
            p.release();await rejects { try await task.value }
            try await waitFor{ s.testStorageIdle }
            check(s.revisionExhausted && s.loadState == .failed && !s.value.background.silentAudio,
                  "late import revived terminal intent")
            check(try Data(contentsOf:url) == original,"terminal import failed exact rollback")
        #endif
        default: fatalError("unknown case")
        }
        try noBackup(root)
        check(p.counts().peak <= 1,"storage operations overlapped")
        print("{\"case\":\"\(name)\",\"assertions\":\(assertions),\"reads\":\(p.counts().reads),\"writes\":\(p.counts().writes),\"peakIO\":\(p.counts().peak),\"result\":\"pass\"}")
    }
}
