import Foundation
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

private struct FixtureFailure: Error { let marker: String }
private func require(_ condition: Bool, _ marker: String) throws {
    if !condition { throw FixtureFailure(marker: marker) }
}

// A controlled filesystem fault at the application's Storage.write boundary.
// The original production prepare/rollback/finishImport bodies execute intact.
// This is not evidence that an iOS kernel or a physical provider generated it.
private final class FaultDisk: @unchecked Sendable {
    enum Fault: String {
        case writeFailure = "write-failure", cancelled = "cancelled", superseded = "superseded"
        case ordinaryFailure = "ordinary-failure", cleanupFailure = "cleanup-failure"
        case failedLoadWrite = "failed-load-write", failedLoadCancelled = "failed-load-cancelled"
        case failedLoadSuperseded = "failed-load-superseded"
        case revisionWrite = "revision-write", revisionCancelled = "revision-cancelled"
        var startsFailed: Bool {
            self == .failedLoadWrite || self == .failedLoadCancelled || self == .failedLoadSuperseded
        }
        var revisionBoundary: Bool { self == .revisionWrite || self == .revisionCancelled }
        var throwsAfterWrite: Bool { self == .writeFailure || self == .failedLoadWrite || self == .revisionWrite }
        var cancelsTask: Bool { self == .cancelled || self == .failedLoadCancelled }
        var supersedes: Bool { self == .superseded || self == .failedLoadSuperseded || revisionBoundary }
    }
    private let lock = NSLock()
    private let releaseGate = DispatchSemaphore(value: 0)
    private var armed = true
    private var waiting = false
    private var writes = 0, reads = 0
    let fault: Fault
    let parked: URL
    init(_ fault: Fault, _ parked: URL) { self.fault = fault; self.parked = parked }
    func observed() -> (waiting: Bool, writes: Int, reads: Int) {
        lock.lock(); defer { lock.unlock() }; return (waiting, writes, reads)
    }
    func release() { releaseGate.signal() }
    func read(_ target: URL) throws -> Data {
        dispatchPrecondition(condition: .notOnQueue(.main))
        lock.lock(); reads += 1; lock.unlock()
        let handle = try FileHandle(forReadingFrom: target)
        defer { try? handle.close() }
        return try handle.read(upToCount: 65_537) ?? Data()
    }
    func write(_ bytes: Data, _ target: URL) throws {
        dispatchPrecondition(condition: .notOnQueue(.main))
        lock.lock(); writes += 1; let inject = armed; armed = false; lock.unlock()
        if inject && fault == .ordinaryFailure { throw CocoaError(.fileWriteUnknown) }
        try bytes.write(to: target, options: .atomic)
        guard inject else { return }
        if fault == .cleanupFailure {
            // Preserve the original under another path. The production cleanup
            // will find its former backup path absent, after a known good commit.
            let backups = try FileManager.default.contentsOfDirectory(
                at: target.deletingLastPathComponent(), includingPropertiesForKeys: nil)
                .filter { $0.lastPathComponent.hasPrefix(".settings-") && $0.pathExtension == "backup" }
            try require(backups.count == 1, "CLEANUP_FAULT_BACKUP_COUNT")
            try FileManager.default.moveItem(at: backups[0], to: parked)
            return
        }
        // Keep the newly written file intact and replace its destination with a
        // directory. Production rename(backup, target) now really fails EISDIR.
        try FileManager.default.moveItem(at: target, to: parked)
        try FileManager.default.createDirectory(at: target, withIntermediateDirectories: false)
        lock.lock(); waiting = true; lock.unlock()
        try require(releaseGate.wait(timeout: .now() + 10) == .success, "FAULT_GATE_TIMEOUT")
        if fault.throwsAfterWrite { throw CocoaError(.fileWriteUnknown) }
    }
}

@main struct RollbackFailureTests {
    @MainActor private static var cleanup: [String: Any] = ["directory_removed": false, "defaults_removed": false]
    @MainActor static func main() async {
        let arguments = Array(CommandLine.arguments.dropFirst())
        if arguments.first == "--cleanup-suite" {
            guard arguments.count == 2, arguments[1].hasPrefix("Settings-rollback-CI-"),
                  let defaults = UserDefaults(suiteName: arguments[1]) else { exit(2) }
            defaults.removePersistentDomain(forName: arguments[1])
            let removed = defaults.persistentDomain(forName: arguments[1])?.isEmpty != false
            let report: [String: Any] = ["kind": "rollback-reassessment-cleanup", "suite": arguments[1],
                                         "defaults_removed": removed]
            do {
                print(String(data: try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), encoding: .utf8)!)
            } catch { exit(2) }
            if !removed { exit(1) }
            return
        }
        var failure: String?
        var unexpected: String?
        do { try await run() }
        catch let error as FixtureFailure { failure = error.marker }
        catch { unexpected = error.localizedDescription }
        let cleaned = cleanup["directory_removed"] as? Bool == true && cleanup["defaults_removed"] as? Bool == true
        if !cleaned && unexpected == nil { unexpected = "fixture cleanup did not complete" }
        let result: [String: Any] = [
            "kind": "rollback-reassessment-result",
            "case": CommandLine.arguments.dropFirst().first ?? "",
            "status": unexpected != nil ? "unexpected-error" : (failure == nil ? "passed" : "failed"),
            "failures": failure.map { [$0] } ?? [],
            "unexpected_error": unexpected.map { $0 as Any } ?? NSNull(),
            "cleanup": cleanup
        ]
        do {
            print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
        } catch { exit(2) }
        if unexpected != nil { exit(1) }
        if failure != nil { exit(74) }
    }
    @MainActor private static func run() async throws {
        guard let text = CommandLine.arguments.dropFirst().first,
              let fault = FaultDisk.Fault(rawValue: text) else { throw FixtureFailure(marker: "UNKNOWN_CASE") }
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("Settings-rollback-" + UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        let target = root.appendingPathComponent("settings.json")
        let parked = root.appendingPathComponent("written-import.json")
        let suite = ProcessInfo.processInfo.environment["ROLLBACK_TEST_DEFAULTS_SUITE"] ??
            ("Settings-rollback-" + UUID().uuidString)
        let defaults = UserDefaults(suiteName: suite)!
        cleanup["defaults_suite"] = suite
        defer {
            defaults.removePersistentDomain(forName: suite)
            do { try fm.removeItem(at: root) }
            catch { cleanup["removal_error"] = error.localizedDescription }
            cleanup["directory_removed"] = !fm.fileExists(atPath: root.path)
            cleanup["defaults_removed"] = defaults.persistentDomain(forName: suite)?.isEmpty != false
        }

        var original = AppSettings()
        original.server.listenPort = "23456"
        original.background.silentAudio = false
        let originalBytes: Data
        if fault.startsFailed { originalBytes = Data("corrupt original\u{0}".utf8) }
        else { originalBytes = try original.encoded() }
        try originalBytes.write(to: target, options: .atomic)
        let disk = FaultDisk(fault, parked)
        let store = SettingsStore(fileURL: target, legacy: defaults,
            storage: .init(read: { try disk.read($0) }, write: { try disk.write($0, $1) }))
        await store.whenLoaded()
        if fault.startsFailed {
            try require(store.loadState == .failed && store.errorMessage != nil, "SEED_NOT_FAILED")
        } else {
            try require(store.loadState == .ready && store.value == original, "SEED_NOT_LOADED")
            try require(!store.savePending && store.errorMessage == nil, "SEED_NOT_CLEAN")
        }
        let liveBefore = store.value
        var incoming = original
        incoming.background.silentAudio = true
        let payload = try incoming.encoded()
        let task = Task { @MainActor in try await store.importData(payload) }

        if fault != .ordinaryFailure && fault != .cleanupFailure {
            let end = ProcessInfo.processInfo.systemUptime + 5
            while !disk.observed().waiting {
                try require(ProcessInfo.processInfo.systemUptime < end, "FAULT_OBSERVATION_TIMEOUT")
                try await Task.sleep(nanoseconds: 1_000_000)
            }
            if fault.cancelsTask { task.cancel() }
            if fault.supersedes { store.set(\.background.silentAudio, false) }
            disk.release()
        }
        var importError: String?
        do { try await task.value } catch { importError = error.localizedDescription }
        try require(importError != nil, "FAILED_IMPORT_ACCEPTED")
        if fault == .cleanupFailure {
            let diskValue = try AppSettings.decoded(Data(contentsOf: target))
            let retainedOriginal = try Data(contentsOf: parked)
            try require(store.value == incoming && diskValue == incoming,
                         "CLEANUP_ONLY_CHANGED_COMMITTED_SNAPSHOT")
            try require(!store.savePending && store.errorMessage != nil,
                         "CLEANUP_ONLY_MARKED_COMMITTED_DATA_UNCERTAIN")
            try require(retainedOriginal == originalBytes, "CLEANUP_CONTROL_LOST_ORIGINAL")
            var flushRejected = false
            do { try await store.flush() } catch { flushRejected = true }
            try require(flushRejected && disk.observed().writes == 1,
                         "CLEANUP_ONLY_REWROTE_KNOWN_COMMIT")
            print("PASS cleanup-failure: committed On remains known; cleanup error visible; no extra write")
            return
        }
        try require(store.value == liveBefore, "FAILED_IMPORT_CHANGED_LIVE_OFF")

        if fault == .ordinaryFailure {
            let restoredBytes = try Data(contentsOf: target)
            try require(restoredBytes == originalBytes, "ORDINARY_FAILURE_LOST_ORIGINAL")
            try require(!store.savePending && store.errorMessage == nil, "ORDINARY_FAILURE_DIRTIED_CLEAN_STORE")
            try await store.flush()
            try require(disk.observed().writes == 1, "ORDINARY_FAILURE_REWROTE_CLEAN_STORE")
            print("PASS ordinary-failure: exact original bytes retained; flush clean; no extra write")
            return
        }

        // Remove the injected obstruction. The live target is now the exact
        // imported On file, while live intent remains the original Off.
        try fm.removeItem(at: target)
        try fm.moveItem(at: parked, to: target)
        let afterObstruction = try AppSettings.decoded(Data(contentsOf: target))
        try require(afterObstruction == incoming, "FAULT_DID_NOT_LEAVE_IMPORTED_ON")
        let backups = try fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
            .filter { $0.lastPathComponent.hasPrefix(".settings-") && $0.pathExtension == "backup" }
        try require(backups.count == 1, "FAILED_ROLLBACK_BACKUP_NOT_RETAINED")
        let backupBytes = try Data(contentsOf: backups[0])
        try require(backupBytes == originalBytes, "FAILED_ROLLBACK_BACKUP_CHANGED")
        if fault.revisionBoundary {
            let terminalMessage = "Settings revision limit reached. New settings operations are unavailable."
            try require(store.revisionExhausted && store.loadState == .failed, "REVISION_BOUNDARY_NOT_REACHED")
            var flushError: String?
            do { try await store.flush() } catch { flushError = error.localizedDescription }
            try require(store.errorMessage == terminalMessage && flushError == terminalMessage,
                        "REVISION_ERROR_REPLACED_BY_ROLLBACK")
            try require(store.savePending, "TERMINAL_ROLLBACK_DURABILITY_NOT_INVALIDATED")
            store.set(\.background.silentAudio, true)
            store.set(\.background.silentAudio, false)
            var importRejected = false
            do { try await store.importData(payload) } catch { importRejected = true }
            let retainedBytes = try Data(contentsOf: backups[0])
            try require(importRejected && !store.value.background.silentAudio &&
                        disk.observed().writes == 1 && disk.observed().reads == 1 && retainedBytes == originalBytes,
                        "TERMINAL_ROLLBACK_STARTED_WORK_OR_LOST_OFF")
            print("PASS " + text + ": terminal revision error and live Off preserved; no new I/O")
            return
        }
        if fault.startsFailed {
            let readsBefore = disk.observed().reads
            var flushRejected = false
            do { try await store.flush() } catch { flushRejected = true }
            let observed: [String: Any] = [
                "case": text, "load_failed_after_flush": store.loadState == .failed,
                "flush_rejected": flushRejected,
                "read_attempts_before": readsBefore, "read_attempts_after": disk.observed().reads,
                "live_audio_after_flush": store.value.background.silentAudio
            ]
            print(String(data: try JSONSerialization.data(withJSONObject: observed, options: [.sortedKeys]), encoding: .utf8)!)
            try require(flushRejected && store.loadState == .failed &&
                         disk.observed().reads == readsBefore && store.value == liveBefore,
                         "FAILED_LOAD_ADOPTED_REJECTED_IMPORT")
            try require(store.savePending && store.errorMessage?.contains("Import a valid configuration") == true,
                         "FAILED_LOAD_RECOVERY_NOT_EXPLAINED")
            store.set(\.background.silentAudio, false)
            store.set(\.selectedTab, .settings)
            let afterEdits = store.value
            var uncertainFlushRejected = false
            do { try await store.flush() } catch { uncertainFlushRejected = true }
            try require(uncertainFlushRejected, "UNCERTAIN_FILE_FLUSH_ACCEPTED")
            try require(store.value == afterEdits && store.loadState == .failed &&
                         disk.observed().reads == readsBefore, "EARLY_EDITS_RELEASED_QUARANTINE")
            var invalidRepairRejected = false
            do { try await store.importData(Data("invalid".utf8)) } catch { invalidRepairRejected = true }
            try require(invalidRepairRejected, "INVALID_REPAIR_ACCEPTED")
            try require(store.value == afterEdits && store.loadState == .failed &&
                         disk.observed().reads == readsBefore, "INVALID_IMPORT_RELEASED_QUARANTINE")
            var replacement = original
            replacement.server.listenPort = "34567"
            replacement.background.silentAudio = false
            replacement.selectedTab = .settings
            try await store.importData(replacement.encoded())
            try await store.flush()
            let recoveredDisk = try AppSettings.decoded(Data(contentsOf: target))
            let retainedBytes = try Data(contentsOf: backups[0])
            try require(store.loadState == .ready && store.value == replacement && recoveredDisk == replacement &&
                         store.errorMessage == nil && !store.savePending, "EXPLICIT_IMPORT_DID_NOT_REPAIR_QUARANTINE")
            try require(disk.observed().reads == readsBefore && disk.observed().writes == 2 &&
                         retainedBytes == originalBytes, "QUARANTINE_REPAIR_LOST_BACKUP_OR_ADDED_IO")
            print("PASS " + text + ": uncertain file stays quarantined; explicit validated import recovers")
            return
        }
        let pendingBefore = store.savePending
        let errorBefore = store.errorMessage
        var flushError: String?
        do { try await store.flush() } catch { flushError = error.localizedDescription }
        let after = try AppSettings.decoded(Data(contentsOf: target))
        let report: [String: Any] = [
            "case": text, "import_error": importError!,
            "save_pending_before_retry": pendingBefore,
            "storage_error_before_retry": errorBefore.map { $0 as Any } ?? NSNull(),
            "flush_error": flushError.map { $0 as Any } ?? NSNull(),
            "disk_audio_after_flush": after.background.silentAudio,
            "live_audio_after_flush": store.value.background.silentAudio,
            "write_attempts": disk.observed().writes
        ]
        print(String(data: try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), encoding: .utf8)!)
        try require(pendingBefore && errorBefore != nil,
                     "ROLLBACK_FAILURE_NOT_MARKED_UNCERTAIN")
        try require(flushError == nil && after == original && store.value == original,
                     "ROLLBACK_FAILURE_RETRY_DID_NOT_PERSIST_LATEST_OFF")
        try require(!store.savePending && store.errorMessage == nil && disk.observed().writes == 2,
                     "ROLLBACK_FAILURE_REPAIR_DID_NOT_SETTLE")
        let retainedAfterRepair = try Data(contentsOf: backups[0])
        try require(retainedAfterRepair == originalBytes, "READY_REPAIR_LOST_RECOVERY_BACKUP")
        print("PASS " + text + ": failed rollback is visible; explicit retry persists latest Off")
    }
}
