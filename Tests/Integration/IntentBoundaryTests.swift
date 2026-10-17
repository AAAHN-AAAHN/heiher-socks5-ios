import Foundation

/// The driver inserts the unchanged AppRoot routing methods below. These small
/// facades observe routing; the live-storage build additionally uses the actual
/// SettingsStore, LoopAudioService, progress monitor and execution lease.
@MainActor private enum Trace {
    static var events: [String] = []
    static func add(_ event: String) { events.append(event) }
    static func check(_ condition: Bool, _ reason: String) {
        if !condition { fatalError("ROOT_INTENT_" + reason) }
    }
}

struct Binding<Value> {
    let get: () -> Value
    let set: (Value) -> Void
    init(get: @escaping () -> Value, set: @escaping (Value) -> Void) {
        self.get = get
        self.set = set
    }
    var wrappedValue: Value {
        get { get() }
        nonmutating set { set(newValue) }
    }
}

#if !LIVE_SETTINGS
struct ServerSettings: Equatable { var listenPort = "1080" }
struct AppSettings: Equatable {
    struct Background: Equatable {
        var continuousLocation = false
        var silentAudio = false
    }
    enum Tab { case statistics, server, background, settings }
    var server = ServerSettings()
    var serverRunning = false
    var background = Background()
    var selectedTab = Tab.statistics
}

@MainActor final class SettingsStore {
    enum LoadState { case loading, ready, failed }
    enum Origin { case user, load, imported }
    struct Change: Equatable { let revision: UInt64; let origin: Origin }
    var value = AppSettings()
    var loadState = LoadState.ready
    var change = Change(revision: 0, origin: .load)
    var audioChange = Change(revision: 0, origin: .load)
    var locationChange = Change(revision: 0, origin: .load)
    var serverRunningChange = Change(revision: 0, origin: .load)
    var acceptsNewIntent = true
    private(set) var audioWrites: [Bool] = []
    private(set) var runningWrites: [Bool] = []

    func set<Value>(_ path: WritableKeyPath<AppSettings, Value>, _ next: Value,
                    origin: Origin = .user) {
        if !acceptsNewIntent, next as? Bool != false {
            loadState = .failed
            Trace.add("settings.rejected")
            return
        }
        value[keyPath: path] = next
        if acceptsNewIntent { change = Change(revision: change.revision + 1, origin: origin) }
        if path == \AppSettings.self || path == \.background || path == \.background.silentAudio {
            audioChange = change
            audioWrites.append(value.background.silentAudio)
        }
        if path == \AppSettings.self || path == \.background || path == \.background.continuousLocation {
            locationChange = change
        }
        if path == \AppSettings.self || path == \.serverRunning {
            serverRunningChange = change
            runningWrites.append(value.serverRunning)
        }
        Trace.add("settings.\(change.revision)")
    }
}
#else
@MainActor protocol ObservableObject {}
@MainActor final class ObservableObjectPublisher { func send() {} }
#if !canImport(Darwin)
final class NSFileCoordinator {
    init(filePresenter: Any?) {}
    func coordinate(readingItemAt url: URL, options: [Int],
                    error: UnsafeMutablePointer<NSError?>?, byAccessor: (URL) -> Void) {
        byAccessor(url)
    }
}
extension URL {
    func startAccessingSecurityScopedResource() -> Bool { true }
    func stopAccessingSecurityScopedResource() {}
}
#endif

private final class AudioProbe: LoopAudioEndpoint, @unchecked Sendable {
    private let queue: DispatchQueue
    init(_ queue: DispatchQueue) { self.queue = queue }
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        dispatchPrecondition(condition: .onQueue(queue))
        switch command {
        case .stop: completion(.init())
        case .inspect, .start:
            let now = ProcessInfo.processInfo.systemUptime
            completion(.init(sample: .init(generation: 1, epoch: context.epoch,
                playing: true, configured: true, position: now.truncatingRemainder(dividingBy: 0.05),
                deviceTime: now, duration: 0.05, rate: 1, startedAt: now, finishedAt: now,
                bufferDuration: 0.005)))
        }
    }
}

private final class LeaseProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var requests = 0
    private var endings: [Int] = []
    func begin(_ receipt: @Sendable (Int?) -> Void) {
        lock.lock(); requests += 1; let id = requests; lock.unlock()
        receipt(id)
    }
    func end(_ id: Int) { lock.lock(); endings.append(id); lock.unlock() }
    func balanced() -> Bool {
        lock.lock(); defer { lock.unlock() }
        return requests == endings.count && Set(endings).count == endings.count
    }
}
#endif

@MainActor final class BackgroundKeepAlive {
    private(set) var locationEnabled = false
    private(set) var audioEnabled = false
    var onAudio: ((Bool) -> Void)?
    var onSync: (() -> Void)?
    var onLocation: (() -> Void)?
    #if LIVE_SETTINGS
    private let leases = LeaseProbe()
    private let service: LoopAudioService
    private var owner: UInt64 = 0
    private(set) var audioState = "Off"
    init() {
        let leases = leases
        service = LoopAudioService(leaseProvider: {
            .init(request: { _, receipt in leases.begin(receipt) }, end: { leases.end($0) })
        }, endpointFactory: { queue, _ in AudioProbe(queue) })
        owner = service.register { [weak self] state in self?.audioState = state.text }
    }
    deinit { service.unregister(owner) }
    func diagnostics() async -> LoopAudioService.Diagnostics {
        await withCheckedContinuation { continuation in
            service.diagnostics { continuation.resume(returning: $0) }
        }
    }
    func claimsBalanced() -> Bool { leases.balanced() }
    #endif

    func setAudio(_ enabled: Bool) {
        Trace.add("audio.explicit.\(enabled)")
        #if LIVE_SETTINGS
        service.setEnabled(enabled, owner: owner)
        #endif
        audioEnabled = enabled
        let callback = onAudio; onAudio = nil
        callback?(enabled)
    }
    func syncAudio(_ enabled: Bool) {
        Trace.add("audio.sync.\(enabled)")
        if audioEnabled != enabled {
            #if LIVE_SETTINGS
            service.setEnabled(enabled, owner: owner, explicit: false)
            #endif
            audioEnabled = enabled
        }
        let callback = onSync; onSync = nil
        callback?()
    }
    func setLocation(_ enabled: Bool) {
        Trace.add("location.\(enabled)")
        locationEnabled = enabled
        let callback = onLocation; onLocation = nil
        callback?()
    }
}

@MainActor final class ServerController {
    var onApply: (() -> Void)?
    func apply(_ value: ServerSettings, running: Bool, retry: Bool = false) {
        Trace.add("server.\(running).\(value.listenPort).\(retry)")
        let callback = onApply; onApply = nil
        callback?()
    }
}

// INSERT_ROOT_INTENT_HOST

#if !LIVE_SETTINGS
@MainActor private extension RootIntentHost {
    static func routing(_ name: String) {
        let settings = SettingsStore()
        let host = RootIntentHost(settings: settings)
        Trace.events = []
        switch name {
        case "direct":
            host.audioEnabled.wrappedValue = true
            Trace.check(Trace.events == ["audio.explicit.true", "settings.1"], "DIRECT_ORDER")
            Trace.check(settings.value.background.silentAudio, "DIRECT_MEMORY")
        case "repeated":
            host.applyAudioIntent(true)
            host.applyAudioIntent(true)
            host.applyAudioIntent(false)
            host.applyAudioIntent(false)
            Trace.check(Trace.events.filter { $0.hasPrefix("audio.explicit") } == [
                "audio.explicit.true", "audio.explicit.true", "audio.explicit.false", "audio.explicit.false"], "REPEATED_INPUT")
            Trace.check(settings.change.revision == 4, "REPEATED_REVISION")
        case "echo":
            host.applyAudioIntent(true)
            host.restoreServices()
            let first = Trace.events
            host.restoreServices()
            Trace.check(Trace.events.filter { $0.hasPrefix("audio.explicit") }.count == 1, "ECHO_EXPLICIT")
            Trace.check(Trace.events == first, "ECHO_DUPLICATE")
        case "off-on":
            host.applyAudioIntent(true)
            Trace.events = []
            host.applyAudioIntent(false)
            host.applyAudioIntent(true)
            host.restoreServices()
            Trace.check(Trace.events.filter { $0.hasPrefix("audio.explicit") } == [
                "audio.explicit.false", "audio.explicit.true"], "OFF_ON_COALESCED")
        case "loading":
            settings.loadState = .loading
            host.restoreServices()
            Trace.check(Trace.events.isEmpty, "LOADING_APPLIED")
            host.startServer()
            Trace.check(!Trace.events.contains { $0.hasPrefix("server.") }, "LOADING_DEFAULT_START")
            settings.value.server.listenPort = "23456"
            settings.change = .init(revision: settings.change.revision, origin: .load)
            settings.loadState = .ready
            host.restoreServices()
            Trace.check(Trace.events.contains("server.true.23456.false"), "READY_NOT_APPLIED")
        case "failed-stop":
            settings.loadState = .failed
            host.restoreServices()
            Trace.check(Trace.events.isEmpty, "FAILED_LOAD_APPLIED")
            host.stopServer()
            Trace.check(Trace.events.first == "server.false.1080.false", "STOP_GATED_BY_LOAD")
            Trace.check(settings.runningWrites == [false], "STOP_NOT_RECORDED")
        case "origin":
            settings.change = .init(revision: 7, origin: .load)
            settings.value.background.silentAudio = true
            host.restoreServices()
            settings.change = .init(revision: 7, origin: .imported)
            settings.value.background.silentAudio = false
            host.restoreServices()
            Trace.check(Trace.events.filter { $0.hasPrefix("audio.sync") } == [
                "audio.sync.true", "audio.sync.false"], "ORIGIN_IGNORED")
            Trace.check(!host.keepAlive.audioEnabled, "IMPORT_NOT_APPLIED")
        case "location-reentry":
            settings.value.background = .init(continuousLocation: true, silentAudio: true)
            settings.value.serverRunning = true
            host.keepAlive.onLocation = {
                host.applyAudioIntent(false)
                host.stopServer()
            }
            host.restoreServices()
            Trace.check(!Trace.events.contains("audio.sync.true"), "STALE_AUDIO_AFTER_LOCATION")
            Trace.check(!Trace.events.contains("server.true.1080.false"), "STALE_SERVER_AFTER_LOCATION")
            Trace.check(!settings.value.background.silentAudio && !settings.value.serverRunning, "LOCATION_REENTRY_MEMORY")
        case "audio-reentry":
            settings.value.background.silentAudio = true
            settings.value.serverRunning = true
            host.keepAlive.onSync = { host.stopServer() }
            host.restoreServices()
            Trace.check(!Trace.events.contains("server.true.1080.false"), "STALE_SERVER_AFTER_AUDIO")
        case "direct-reentry":
            host.keepAlive.onAudio = { _ in host.applyAudioIntent(false) }
            host.applyAudioIntent(true)
            Trace.check(!settings.value.background.silentAudio && !host.keepAlive.audioEnabled, "STALE_DIRECT_MEMORY")
            Trace.check(settings.audioWrites == [false], "STALE_DIRECT_WRITE")
        case "direct-unrelated":
            settings.value.background.silentAudio = true
            host.keepAlive.setAudio(true)
            host.keepAlive.onAudio = { _ in host.stopServer() }
            host.applyAudioIntent(false)
            host.restoreServices()
            Trace.check(!settings.value.background.silentAudio && !host.keepAlive.audioEnabled, "UNRELATED_DROPPED_OFF")
            Trace.check(settings.audioWrites == [false], "UNRELATED_DROPPED_OFF_WRITE")
        case "direct-newer-unrelated":
            host.keepAlive.onAudio = { _ in
                host.applyAudioIntent(false)
                settings.set(\.selectedTab, .server)
            }
            host.applyAudioIntent(true)
            host.restoreServices()
            Trace.check(!settings.value.background.silentAudio && !host.keepAlive.audioEnabled, "NEWER_THEN_UNRELATED_OFF")
            Trace.check(settings.audioWrites == [false], "NEWER_THEN_UNRELATED_WRITE")
        case "direct-identical-reentry":
            host.keepAlive.onAudio = { _ in host.applyAudioIntent(true) }
            host.applyAudioIntent(true)
            Trace.check(settings.audioWrites == [true], "STALE_IDENTICAL_AUDIO_WRITE")
            Trace.check(Trace.events.filter { $0 == "audio.explicit.true" }.count == 2, "IDENTICAL_AUDIO_LOST")
        case "start-unrelated":
            host.server.onApply = { settings.set(\.selectedTab, .background) }
            host.startServer()
            host.restoreServices()
            Trace.check(settings.value.serverRunning && settings.runningWrites == [true], "UNRELATED_DROPPED_START")
        case "stop-unrelated":
            settings.value.serverRunning = true
            host.server.onApply = { settings.set(\.selectedTab, .background) }
            host.stopServer()
            host.restoreServices()
            Trace.check(!settings.value.serverRunning && settings.runningWrites == [false], "UNRELATED_DROPPED_STOP")
            Trace.check(!Trace.events.contains("server.true.1080.false"), "UNRELATED_RESTARTED_SERVER")
        case "stop-newer-unrelated":
            settings.value.serverRunning = true
            host.server.onApply = {
                host.startServer()
                settings.set(\.selectedTab, .background)
            }
            host.stopServer()
            Trace.check(settings.value.serverRunning && settings.runningWrites == [true], "NEWER_THEN_UNRELATED_START")
        case "start-identical-reentry":
            host.server.onApply = { host.startServer() }
            host.startServer()
            Trace.check(settings.value.serverRunning && settings.runningWrites == [true], "STALE_IDENTICAL_START_WRITE")
        case "start-reentry":
            host.server.onApply = { host.stopServer() }
            host.startServer()
            Trace.check(!settings.value.serverRunning && settings.runningWrites == [false], "STALE_START_MEMORY")
        case "readiness-reentry":
            settings.value.background.silentAudio = true
            settings.value.serverRunning = true
            host.keepAlive.onSync = { settings.loadState = .failed }
            host.restoreServices()
            Trace.check(!Trace.events.contains("server.true.1080.false"), "FAILED_AFTER_AUDIO")
        case "terminal-on":
            settings.change = .init(revision: .max, origin: .user)
            settings.acceptsNewIntent = false
            host.applyAudioIntent(true)
            Trace.check(Trace.events == ["settings.rejected"] && !host.keepAlive.audioEnabled, "TERMINAL_AUDIO_ON")
        case "terminal-start":
            settings.change = .init(revision: .max, origin: .user)
            settings.acceptsNewIntent = false
            host.startServer()
            Trace.check(Trace.events == ["settings.rejected"] && !settings.value.serverRunning, "TERMINAL_SERVER_START")
        case "terminal-off":
            settings.change = .init(revision: .max, origin: .user)
            settings.value.background.silentAudio = true
            settings.value.serverRunning = true
            settings.acceptsNewIntent = false
            host.applyAudioIntent(false)
            host.stopServer()
            Trace.check(Trace.events.first == "audio.explicit.false", "TERMINAL_OFF_GATED")
            Trace.check(Trace.events.contains("server.false.1080.false"), "TERMINAL_STOP_GATED")
            Trace.check(!settings.value.background.silentAudio && !settings.value.serverRunning, "TERMINAL_OFF_MEMORY")
        default: fatalError("Unknown routing case: " + name)
        }
        print("PASS: AppRoot routing " + name)
    }
}
#else
private final class DiskProbe: @unchecked Sendable {
    private let lock = NSLock()
    private let gate = DispatchSemaphore(value: 0)
    private var blockRead = false
    private var blockWrite = false
    private var blockImport = false
    private var waiting = 0
    private var active = 0
    private var peak = 0
    func arm(_ mode: String) {
        lock.lock(); defer { lock.unlock() }
        blockRead = mode == "read"
        blockWrite = mode == "write"
        blockImport = mode == "import"
    }
    func release() { gate.signal() }
    func counts() -> (waiting: Int, peak: Int) {
        lock.lock(); defer { lock.unlock() }; return (waiting, peak)
    }
    private func enter(_ kind: String) {
        dispatchPrecondition(condition: .notOnQueue(.main))
        lock.lock()
        active += 1; peak = max(peak, active)
        let block = kind == "read" ? blockRead : (kind == "write" ? blockWrite : blockImport)
        if kind == "read" { blockRead = false }
        else if kind == "write" { blockWrite = false }
        else { blockImport = false }
        if block { waiting += 1 }
        lock.unlock()
        if block {
            precondition(gate.wait(timeout: .now() + 10) == .success, "Disk fixture deadline")
        }
    }
    private func leave() { lock.lock(); active -= 1; lock.unlock() }
    func read(_ url: URL) throws -> Data {
        enter("read"); defer { leave() }
        return try Data(contentsOf: url)
    }
    func imported(_ url: URL) throws -> Data {
        enter("import"); defer { leave() }
        return try Data(contentsOf: url)
    }
    func write(_ data: Data, _ url: URL) throws {
        enter("write"); defer { leave() }
        try data.write(to: url, options: .atomic)
    }
}

@MainActor private extension RootIntentHost {
    static func wait(_ condition: () -> Bool) async throws {
        let limit = ProcessInfo.processInfo.systemUptime + 5
        while !condition() {
            Trace.check(ProcessInfo.processInfo.systemUptime < limit, "LIVE_DEADLINE")
            try await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    static func live(_ name: String) async throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("Release-intent-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        let target = folder.appendingPathComponent("settings.json")
        let imported = folder.appendingPathComponent("import.json")
        let suite = "Release-intent-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        var saved = AppSettings()
        saved.server.listenPort = "23456"
        saved.background.silentAudio = true
        try saved.encoded().write(to: target)
        let disk = DiskProbe()
        if name == "blocked-load" { disk.arm("read") }
        let settings = SettingsStore(fileURL: target, legacy: defaults,
            storage: .init(read: { try disk.read($0) }, write: { try disk.write($0, $1) },
                           imported: { try disk.imported($0) }))
        let host = RootIntentHost(settings: settings)
        Trace.events = []
        if name == "blocked-load" {
            try await wait { disk.counts().waiting == 1 }
            host.restoreServices()
            Trace.check(Trace.events.isEmpty, "LIVE_LOADING_APPLIED")
            host.applyAudioIntent(false)
            Trace.check(!settings.value.background.silentAudio, "LIVE_EARLY_OFF")
            disk.release()
            await settings.whenLoaded()
            host.restoreServices()
            try await settings.flush()
            Trace.check(settings.value.server == saved.server && !settings.value.background.silentAudio, "LIVE_LOAD_UNDID_OFF")
        } else {
            await settings.whenLoaded()
            Trace.check(settings.loadState == .ready, "LIVE_LOAD_FAILED")
            host.restoreServices()
            try await wait { host.keepAlive.audioState == "Playing silent WAV continuously" }
            if name == "blocked-save" {
                disk.arm("write")
                host.applyAudioIntent(false)
                try await wait { disk.counts().waiting == 1 }
                // Storage is still blocked while the real audio service stops and
                // releases its claim. Neither MainActor nor audio control waits on it.
                try await wait { host.keepAlive.audioState == "Off" && host.keepAlive.claimsBalanced() }
                let audio = await host.keepAlive.diagnostics()
                Trace.check(audio.operation == nil && !audio.timerActive && audio.maximumOutstanding <= 1, "LIVE_AUDIO_BLOCKED_BY_DISK")
                Trace.check(settings.savePending, "LIVE_SAVE_NOT_PENDING")
                disk.release()
                try await settings.flush()
            } else if name == "stale-import" {
                var replacement = saved
                replacement.server.listenPort = "34567"
                try replacement.encoded().write(to: imported)
                disk.arm("import")
                let task = Task { try await settings.importFile(imported) }
                try await wait { disk.counts().waiting == 1 }
                host.applyAudioIntent(false)
                try await wait { host.keepAlive.audioState == "Off" }
                disk.release()
                do { try await task.value; fatalError("ROOT_INTENT_STALE_IMPORT_ACCEPTED") }
                catch { }
                try await settings.flush()
                host.restoreServices()
                Trace.check(!settings.value.background.silentAudio && !host.keepAlive.audioEnabled, "LIVE_IMPORT_UNDID_OFF")
                Trace.check(settings.value.server == saved.server, "LIVE_STALE_IMPORT_FIELDS")
            } else if name == "unrelated-reentry" {
                host.keepAlive.onAudio = { _ in
                    host.stopServer()
                    settings.set(\.selectedTab, .background)
                }
                host.applyAudioIntent(false)
                host.restoreServices()
                Trace.check(!settings.value.background.silentAudio && !host.keepAlive.audioEnabled,
                    "LIVE_UNRELATED_DROPPED_OFF")
                Trace.check(!settings.value.serverRunning, "LIVE_UNRELATED_STOP")
                try await settings.flush()
            } else if name == "same-field-reentry" {
                host.keepAlive.onAudio = { _ in
                    host.applyAudioIntent(true)
                    settings.set(\.selectedTab, .background)
                }
                host.applyAudioIntent(false)
                host.restoreServices()
                Trace.check(settings.value.background.silentAudio && host.keepAlive.audioEnabled,
                    "LIVE_NEWER_THEN_UNRELATED_ON")
                host.applyAudioIntent(false)
                try await settings.flush()
            } else if name == "whole-field-reentry" {
                host.keepAlive.onAudio = { _ in
                    var replacement = settings.value.background
                    replacement.silentAudio = true
                    settings.set(\.background, replacement)
                    settings.set(\.selectedTab, .background)
                }
                host.applyAudioIntent(false)
                host.restoreServices()
                Trace.check(settings.value.background.silentAudio && host.keepAlive.audioEnabled,
                    "LIVE_WHOLE_FIELD_LOST")
                host.applyAudioIntent(false)
                try await settings.flush()
            } else if name == "import-intent" {
                var replacement = saved
                replacement.background.silentAudio = false
                replacement.server.listenPort = "34567"
                replacement.selectedTab = .background
                try await settings.importData(replacement.encoded())
                host.restoreServices()
                Trace.check(settings.value == replacement && !host.keepAlive.audioEnabled, "LIVE_IMPORT_INTENT")
                Trace.check(settings.change.origin == .imported && settings.audioChange == settings.change &&
                    settings.locationChange == settings.change && settings.serverRunningChange == settings.change,
                    "LIVE_IMPORT_STAMPS")
            } else if name == "invalid-import" {
                let before = try Data(contentsOf: target)
                let change = settings.change
                do { try await settings.importData(Data("invalid JSON".utf8)); fatalError("ROOT_INTENT_INVALID_IMPORT_ACCEPTED") }
                catch { }
                host.restoreServices()
                Trace.check(try Data(contentsOf: target) == before && settings.value == saved, "LIVE_INVALID_IMPORT_CHANGED")
                Trace.check(settings.change == change && host.keepAlive.audioEnabled, "LIVE_INVALID_IMPORT_PUBLISHED")
                host.applyAudioIntent(false)
                try await settings.flush()
            } else { fatalError("Unknown live case: " + name) }
        }
        host.applyAudioIntent(false)
        try await settings.flush()
        try await wait { host.keepAlive.audioState == "Off" && host.keepAlive.claimsBalanced() }
        Trace.check(try AppSettings.decoded(Data(contentsOf: target)) == settings.value, "LIVE_DURABLE_MISMATCH")
        Trace.check(disk.counts().peak == 1, "LIVE_STORAGE_OVERLAP")
        Trace.check(try FileManager.default.contentsOfDirectory(atPath: folder.path).allSatisfy { !$0.hasSuffix(".backup") }, "LIVE_BACKUP_LEAK")
        print("PASS: actual SettingsStore/audio service integration " + name)
    }
}
#endif

@main private enum IntentBoundaryTests {
    @MainActor static func main() async throws {
        let name = CommandLine.arguments.dropFirst().first ?? "direct"
        #if LIVE_SETTINGS
        try await RootIntentHost.live(name)
        #else
        RootIntentHost.routing(name)
        #endif
    }
}
