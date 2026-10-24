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
    static func main() async throws {
        var owner: PeriodicPingModel? = PeriodicPingModel()
        weak var weakOwner = owner
        require(owner!.enabled == false && owner!.destinations == "1.1.1.1" && owner!.period == "1000" && owner!.status == "Off", "defaults")
        owner!.setDestinations("127.0.0.1, ::1")
        owner!.setPeriod("10")
        try await wait("off settles") { owner!.status == "Off" }
        require(probe(0) == 0, "off creates no sockets")
        owner!.setEnabled(true)
        try await wait("On") { owner!.status.hasPrefix("Sending ICMP") }
        owner!.setPeriod("invalid")
        try await wait("invalid stops") { probe(0) == probe(1) }
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
        print("PASS: defaults, disabled edits, input rejection/recovery, synchronous publication reentry, 100 On-Off pairs, stale status, root release cleanup")
        print("CONTROLLED_SYSCALLS opens=\(probe(0)) closes=\(probe(1)); no UIKit or physical ICMP execution")
    }
}
