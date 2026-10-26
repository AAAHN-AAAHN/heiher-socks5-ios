import Combine
import Foundation

@_silgen_name("ping_probe_value") private func probe(_ key: Int32) -> Int32

@main
@MainActor
struct PeriodicPingModelTests {
    static func require(_ value: @autoclosure () -> Bool, _ reason: String) {
        guard value() else { fatalError(reason) }
    }
    static func wait(_ reason: String, _ predicate: () -> Bool) async throws {
        let limit = Date().addingTimeInterval(3)
        while !predicate(), Date() < limit { try await Task.sleep(nanoseconds: 2_000_000) }
        require(predicate(), reason)
    }
    static func persistence() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let url = directory.appendingPathComponent("ping.json")
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = PeriodicPingModel(fileURL: url)
        try await first.flush()
        require(tryValue(url) == PeriodicPingPreferences(), "default JSON not saved")
        first.setDestinations("127.0.0.1, ::1")
        first.setPeriod("37")
        first.setEnabled(true)
        try await first.flush()
        let backup = try await first.exportData()
        let reopened = PeriodicPingModel(fileURL: url)
        try await reopened.flush()
        try await wait("relaunch resumes saved On") { reopened.status == "Sending ICMP to 2 destination(s)" }
        require(reopened.enabled && reopened.destinations == "127.0.0.1, ::1" && reopened.period == "37", "saved values not restored")
        reopened.setEnabled(false)
        try await reopened.flush()
        try await reopened.importData(backup)
        require(reopened.enabled && tryValue(url).enabled, "backup restore failed")
        reopened.setEnabled(false)
        first.setEnabled(false)
        try await first.flush()
        try await reopened.flush()
        let large = (0..<65_536).map { "10.9.\($0 / 256).\($0 % 256)" }.joined(separator: ",")
        reopened.setDestinations(large)
        reopened.setPeriod("60000")
        try await reopened.flush()
        let bigBackup = try await reopened.exportData()
        require(bigBackup.count > 8192 && bigBackup.count > 65_536, "large backup fixture")
        let largeRestart = PeriodicPingModel(fileURL: url)
        try await largeRestart.flush()
        require(largeRestart.destinations == large && largeRestart.period == "60000" && !largeRestart.enabled, "large restart")
        largeRestart.setDestinations("127.0.0.1")
        try await largeRestart.importData(bigBackup)
        require(largeRestart.destinations == large, "large import truncated")
        let before = try Data(contentsOf: url)
        do { try await largeRestart.importData(Data("{bad".utf8)); fatalError("corrupt import accepted") }
        catch is DecodingError { }
        let after = try Data(contentsOf: url)
        require(before == after, "corrupt backup modified disk")
        // Canonically equivalent drafts still have distinct bytes to preserve.
        let rawURL = directory.appendingPathComponent("raw-text.json")
        let raw = PeriodicPingModel(fileURL: rawURL)
        try await raw.flush()
        let composed = "\u{00e9}", decomposed = "e\u{0301}"
        require(composed == decomposed && !composed.utf8.elementsEqual(decomposed.utf8), "raw text fixture")
        raw.restore(enabled: false, destinations: composed, period: composed)
        try await raw.flush()
        raw.setDestinations(decomposed)
        try await raw.flush()
        require(raw.destinations.utf8.elementsEqual(decomposed.utf8) &&
            tryValue(rawURL).destinations.utf8.elementsEqual(decomposed.utf8), "destination bytes not saved")
        raw.setPeriod(decomposed)
        try await raw.flush()
        require(raw.period.utf8.elementsEqual(decomposed.utf8) &&
            tryValue(rawURL).period.utf8.elementsEqual(decomposed.utf8), "period bytes not saved")
        raw.restore(enabled: false, destinations: composed, period: composed)
        try await raw.flush()
        let rawBackup = try await raw.exportData()
        let exported = try JSONDecoder().decode(PeriodicPingPreferences.self, from: rawBackup)
        require(exported.destinations.utf8.elementsEqual(composed.utf8) &&
            exported.period.utf8.elementsEqual(composed.utf8), "combined restore/export lost raw bytes")
        let rawRestart = PeriodicPingModel(fileURL: rawURL)
        try await rawRestart.flush()
        require(rawRestart.destinations.utf8.elementsEqual(composed.utf8) &&
            rawRestart.period.utf8.elementsEqual(composed.utf8), "relaunch lost raw bytes")
        // A delayed initial read must not resurrect On over a newer unchanged Off.
        let entered = DispatchSemaphore(value: 0), release = DispatchSemaphore(value: 0)
        let source = PeriodicPingPreferences(enabled: true, destinations: "127.0.0.1", period: "25")
        let data = try JSONEncoder().encode(source)
        var storage = PeriodicPingModel.Storage()
        storage.read = { _ in entered.signal(); release.wait(); return data }
        let slow = PeriodicPingModel(fileURL: directory.appendingPathComponent("slow.json"), storage: storage)
        let enteredOK: Bool = await withCheckedContinuation { receipt in
            DispatchQueue.global().async {
                receipt.resume(returning: entered.wait(timeout: .now() + 3) == .success)
            }
        }
        require(enteredOK, "load boundary not entered")
        slow.setEnabled(false)
        release.signal()
        try await slow.flush()
        require(!slow.enabled && slow.destinations == "127.0.0.1" && slow.period == "25", "delayed load overrode latest Off")
        // Failed disk writes cannot block Off or be labelled durable. Retry writes
        // the newest choices, not the earlier saved-On snapshot.
        let failureURL = directory.appendingPathComponent("failure.json")
        let failure = PeriodicPingModel(fileURL: failureURL)
        try await failure.flush()
        try FileManager.default.removeItem(at: failureURL)
        try FileManager.default.createDirectory(at: failureURL, withIntermediateDirectories: true)
        failure.setDestinations("127.0.0.2")
        failure.setPeriod("47")
        failure.setEnabled(true)
        do { try await failure.flush(); fatalError("failed write reported saved") } catch { }
        require(failure.storageError != nil && failure.savePending, "failed write status lost")
        failure.setEnabled(false)
        try await wait("Off during disk failure") { failure.status == "Off" }
        do { try await failure.flush(); fatalError("failed Off write reported saved") } catch { }
        try FileManager.default.removeItem(at: failureURL)
        try await failure.flush()
        require(tryValue(failureURL) == PeriodicPingPreferences(enabled: false, destinations: "127.0.0.2", period: "47"), "retry lost latest Off")
        require(failure.storageError == nil && !failure.savePending, "retry not acknowledged")
        try await supersededSave(directory)
        try await settledSaveFailure(directory)
        try await releasedSave(directory)
        let corruptURL = directory.appendingPathComponent("corrupt.json")
        let corruptBytes = Data("{corrupt".utf8)
        try corruptBytes.write(to: corruptURL)
        let corrupt = PeriodicPingModel(fileURL: corruptURL)
        do { try await corrupt.flush(); fatalError("corrupt initial JSON accepted") } catch { }
        require(!corrupt.canExport && !corrupt.enabled, "failed load became ready")
        corrupt.setDestinations("127.0.0.9")
        require(corrupt.status == "Settings could not be loaded", "failed-load destination edit claimed loading")
        corrupt.setPeriod("501")
        require(corrupt.status == "Settings could not be loaded", "failed-load period edit claimed loading")
        corrupt.setEnabled(true)
        require(corrupt.status == "Settings could not be loaded", "failed-load On claimed loading")
        corrupt.setEnabled(false)
        require(corrupt.status == "Settings could not be loaded", "failed-load Off claimed loading")
        let originalCorrupt = try Data(contentsOf: corruptURL)
        require(originalCorrupt == corruptBytes, "corrupt file silently overwritten")
        try await corrupt.importData(backup)
        require(corrupt.enabled && corrupt.canExport, "explicit backup did not recover load")
        corrupt.setEnabled(false)
        try await corrupt.flush()
        try await wait("final native clients close") { probe(0) == probe(1) }
        print("PASS: standalone JSON default save, saved On restart, backup/restore, 65536-IP file, verbatim UTF-8, malformed import preservation, delayed-load Off, failed-save latest-Off retry, superseded-failure flush, settled-failure recovery, both owner-release write orders and corrupt-load edits/recovery")
    }

    static func supersededSave(_ directory: URL) async throws {
        let url = directory.appendingPathComponent("superseded-save.json")
        let original = PeriodicPingPreferences(enabled: false, destinations: "127.0.0.1", period: "1000")
        try JSONEncoder().encode(original).write(to: url, options: .atomic)
        let entered = DispatchSemaphore(value: 0), release = DispatchSemaphore(value: 0)
        var storage = PeriodicPingModel.Storage()
        let write = storage.write
        storage.write = { data, target in
            if try JSONDecoder().decode(PeriodicPingPreferences.self, from: data).enabled {
                entered.signal()
                precondition(release.wait(timeout: .now() + 3) == .success, "write boundary timed out")
                throw CocoaError(.fileWriteUnknown)
            }
            try write(data, target)
        }
        let model = PeriodicPingModel(fileURL: url, storage: storage)
        try await model.flush()
        model.setEnabled(true)
        let reached: Bool = await withCheckedContinuation { receipt in
            DispatchQueue.global().async {
                receipt.resume(returning: entered.wait(timeout: .now() + 3) == .success)
            }
        }
        require(reached, "superseded write not entered")
        model.setEnabled(false)
        var completed = false
        let receipt = Task { @MainActor in
            defer { completed = true }
            try await model.flush()
        }
        // Observe registration instead of assuming a yield scheduled the caller.
        try await wait("flush waiter not registered") {
            (Mirror(reflecting: model).descendant("waiters") as? [CheckedContinuation<Void, Error>])?.count == 1
        }
        release.signal()
        try await wait("failed older write stranded latest-Off flush") { completed }
        try await receipt.value
        require(!model.enabled && model.storageError == nil && !model.savePending &&
            tryValue(url) == original, "superseded failure did not settle latest durable Off")
    }

    static func settledSaveFailure(_ directory: URL) async throws {
        // Off is accepted after the older failure settles, unlike supersededSave.
        // A controlled write-then-throw tests uncertainty, not Foundation policy.
        for (name, commit, imported) in [("ordinary", false, false),
                                        ("committed", true, false), ("imported", true, true)] {
            let url = directory.appendingPathComponent("settled-\(name).json")
            let original = PeriodicPingPreferences(enabled: false, destinations: "127.0.0.1", period: "1000")
            let data = try JSONEncoder().encode(original)
            try data.write(to: url, options: .atomic)
            let attempts = DispatchSemaphore(value: 0)
            var storage = PeriodicPingModel.Storage()
            let write = storage.write
            storage.write = { data, target in
                defer { attempts.signal() }
                if try JSONDecoder().decode(PeriodicPingPreferences.self, from: data).enabled {
                    if commit { try write(data, target) }
                    throw CocoaError(.fileWriteUnknown)
                }
                try write(data, target)
            }
            let model = PeriodicPingModel(fileURL: url, storage: storage)
            try await model.flush()
            model.setEnabled(true)
            do { try await model.flush(); fatalError("settled write failure reported saved") } catch { }
            require(model.storageError != nil && model.savePending, "settled failure not recorded")
            if imported { try await model.importData(data) }
            else { model.setEnabled(false); try await model.flush() }
            require(!model.enabled && model.storageError == nil && !model.savePending &&
                tryValue(url) == original, "settled failure suppressed latest-Off recovery: \(name)")
            require(attempts.wait(timeout: .now()) == .success && attempts.wait(timeout: .now()) == .success &&
                attempts.wait(timeout: .now()) == .timedOut, "settled recovery did not use exactly two attempts")
            try await model.flush()
            require(attempts.wait(timeout: .now()) == .timedOut, "clean recovery flush duplicated a write")
        }
    }

    static func waitForSignal(_ signal: DispatchSemaphore, _ reason: String) async {
        let reached: Bool = await withCheckedContinuation { receipt in
            DispatchQueue.global().async {
                receipt.resume(returning: signal.wait(timeout: .now() + 3) == .success)
            }
        }
        require(reached, reason)
    }

    static func releasedSave(_ directory: URL) async throws {
        for blocked in [true, false] {
            for revert in [true, false] {
                let url = directory.appendingPathComponent("released-\(blocked)-\(revert).json")
                let original = PeriodicPingPreferences(enabled: false, destinations: "127.0.0.1", period: "1000")
                try JSONEncoder().encode(original).write(to: url, options: .atomic)
                let entered = DispatchSemaphore(value: 0), release = DispatchSemaphore(value: 0)
                let processedOn = DispatchSemaphore(value: 0), attempts = DispatchSemaphore(value: 0)
                var storage = PeriodicPingModel.Storage()
                let write = storage.write
                storage.write = { data, target in
                    defer { attempts.signal() }
                    let enabled = try JSONDecoder().decode(PeriodicPingPreferences.self, from: data).enabled
                    if enabled && blocked {
                        entered.signal()
                        precondition(release.wait(timeout: .now() + 3) == .success, "release write boundary timed out")
                    }
                    try write(data, target)
                    if enabled { processedOn.signal() }
                }
                var owner: PeriodicPingModel? = PeriodicPingModel(fileURL: url, storage: storage)
                try await owner!.flush()
                let lane = Mirror(reflecting: owner!).descendant("io") as! DispatchQueue
                owner!.setEnabled(true)
                if blocked { await waitForSignal(entered, "release write not entered") }
                // Unblocked: On, latest Off and release share one actor turn.
                if revert { owner!.setEnabled(false) }
                weak var weakOwner: PeriodicPingModel?
                weakOwner = owner
                owner = nil
                try await wait("blocked storage retained released owner") { weakOwner == nil }
                if blocked { release.signal() }
                // Observe old On before draining: an immediate barrier could run
                // before a deferred submission and falsely credit old disk Off.
                await waitForSignal(processedOn, "released old On write never processed")
                await withCheckedContinuation { (receipt: CheckedContinuation<Void, Never>) in
                    lane.async { receipt.resume() }
                }
                var expected = original
                expected.enabled = !revert
                require(tryValue(url) == expected, "owner release lost latest choice: blocked=\(blocked), revert=\(revert)")
                require(attempts.wait(timeout: .now()) == .success, "released On was not written")
                if revert { require(attempts.wait(timeout: .now()) == .success, "released Off was not written") }
                require(attempts.wait(timeout: .now()) == .timedOut, "release duplicated an already submitted choice")
            }
        }
    }

    static func tryValue(_ url: URL) -> PeriodicPingPreferences {
        try! JSONDecoder().decode(PeriodicPingPreferences.self, from: Data(contentsOf: url))
    }

    static func main() async throws {
        var owner: PeriodicPingModel? = PeriodicPingModel()
        weak var weakOwner: PeriodicPingModel?
        weakOwner = owner
        require(owner!.enabled == false && owner!.destinations == "1.1.1.1" && owner!.period == "1000" && owner!.status == "Off", "defaults")
        owner!.setDestinations("127.0.0.1, ::1")
        owner!.setPeriod("10")
        try await wait("off settles") { owner!.status == "Off" }
        require(probe(0) == 0, "off creates no native clients")
        owner!.setDestinations(String(repeating: "invalid,", count: 100_000))
        owner!.setPeriod("invalid")
        try await wait("disabled edits skip parsing") { owner!.status == "Off" }
        require(probe(0) == 0, "disabled malformed input opened a native client")
        owner!.setDestinations("127.0.0.1, ::1")
        owner!.setPeriod("10")
        owner!.setEnabled(true)
        try await wait("On") { owner!.status.hasPrefix("Sending ICMP") }
        owner!.setPeriod("invalid")
        try await wait("invalid stops") { probe(0) == probe(1) && owner!.status.contains("positive whole") }
        require(owner!.enabled && owner!.status.contains("positive whole"), "invalid intent or error")
        let paused = probe(2)
        try await Task.sleep(nanoseconds: 50_000_000)
        require(probe(2) == paused, "invalid input still sends")
        owner!.setPeriod("10")
        try await wait("valid restarts") { owner!.status.hasPrefix("Sending ICMP") }
        // Real Combine on Apple; a synchronous publisher double on Linux.
        let token = owner!.objectWillChange.sink { [weak model = owner] _ in
            guard let model, model.enabled else { return }
            model.setEnabled(false)
        }
        owner!.setDestinations("127.0.0.2")
        try await wait("reentrant Off wins") { !owner!.enabled && owner!.status == "Off" }
        let stopped = probe(2)
        try await Task.sleep(nanoseconds: 50_000_000)
        require(probe(2) == stopped && probe(0) == probe(1), "reentrant Off resurrected")
        token.cancel()
        for _ in 0..<100 { owner!.setEnabled(true); owner!.setEnabled(false) }
        try await wait("latest Off wins") { owner!.status == "Off" }
        try await Task.sleep(nanoseconds: 50_000_000)
        require(!owner!.enabled && owner!.status == "Off" && probe(0) == probe(1), "stale report")
        owner!.setEnabled(true)
        try await wait("final start") { owner!.status.hasPrefix("Sending ICMP") }
        owner = nil
        try await wait("model lifetime") { weakOwner == nil && probe(0) == probe(1) }
        try await persistence()
        print("PASS: defaults, disabled edits, input rejection/recovery, synchronous publication reentry, 100 On-Off pairs, stale status, root release cleanup")
        print("CONTROLLED_NATIVE_API clients=\(probe(0)) freed=\(probe(1)); no UIKit or physical ICMP execution")
    }
}
