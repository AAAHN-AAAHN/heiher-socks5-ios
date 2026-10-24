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
        // A delayed initial read must not resurrect On over a newer unchanged Off.
        let entered = DispatchSemaphore(value: 0), release = DispatchSemaphore(value: 0)
        let source = PeriodicPingPreferences(enabled: true, destinations: "127.0.0.1", period: "25")
        let data = try JSONEncoder().encode(source)
        var storage = PeriodicPingModel.Storage()
        storage.read = { _ in entered.signal(); release.wait(); return data }
        let slow = PeriodicPingModel(fileURL: directory.appendingPathComponent("slow.json"), storage: storage)
        let enteredOK = await Task.detached { entered.wait(timeout: .now() + 3) == .success }.value
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
        let corruptURL = directory.appendingPathComponent("corrupt.json")
        let corruptBytes = Data("{corrupt".utf8)
        try corruptBytes.write(to: corruptURL)
        let corrupt = PeriodicPingModel(fileURL: corruptURL)
        do { try await corrupt.flush(); fatalError("corrupt initial JSON accepted") } catch { }
        require(!corrupt.canExport && !corrupt.enabled, "failed load became ready")
        let originalCorrupt = try Data(contentsOf: corruptURL)
        require(originalCorrupt == corruptBytes, "corrupt file silently overwritten")
        try await corrupt.importData(backup)
        require(corrupt.enabled && corrupt.canExport, "explicit backup did not recover load")
        corrupt.setEnabled(false)
        try await corrupt.flush()
        try await wait("final sockets close") { probe(0) == probe(1) }
        print("PASS: standalone JSON default save, saved On restart, backup/restore, 65536-IP file, malformed import preservation, delayed-load Off, failed-save latest-Off retry and corrupt-load recovery")
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
        require(probe(0) == 0, "off creates no sockets")
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
        print("CONTROLLED_SYSCALLS opens=\(probe(0)) closes=\(probe(1)); no UIKit or physical ICMP execution")
    }
}
