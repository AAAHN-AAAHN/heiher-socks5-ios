import Dispatch
import Foundation

@_silgen_name("ping_probe_value") private func probe(_ key: Int32) -> Int32
@_silgen_name("ping_probe_mode") private func mode(_ value: Int32)
@_silgen_name("ping_probe_span") private func span() -> Double

private final class Reports: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [String] = []
    func add(_ value: String) { lock.lock(); items.append(value); lock.unlock() }
    var values: [String] { lock.lock(); defer { lock.unlock() }; return items }
}

@main
struct PeriodicPingTests {
    static func require(_ value: @autoclosure () -> Bool, _ label: String) {
        guard value() else { fatalError(label) }
    }
    static func wait(_ label: String, _ check: () -> Bool) {
        let until = Date().addingTimeInterval(3)
        while !check(), Date() < until { Thread.sleep(forTimeInterval: 0.002) }
        require(check(), label)
    }
    static func main() throws {
        let config = try PeriodicPingConfiguration(destinations: "1.1.1.1, 192.168.0.9, ::1, 0:0:0:0:0:0:0:1, ::ffff:1.1.1.1", period: "1000")
        require(config.destinations.count == 3 && config.periodMilliseconds == 1000, "configuration")
        for invalid in ["", "example.com", "127.1", "1.2.3.999", "127.0.0.1:80", "127.0.0.1,", "::1%", "::1%0", "::1%no-such-ping-interface", "1.1.1.1\0suffix", ",1.1.1.1"] {
            do { _ = try PeriodicPingConfiguration(destinations: invalid, period: "1000"); fatalError("invalid IP accepted") }
            catch is PingInputError { }
        }
        for invalid in ["", "0", "-1", "+1", "1.5", "nan", "1e3", "1000ms", "99999999999999999999999", String(Int.max / 1_000_000 + 1)] {
            do { _ = try PeriodicPingConfiguration(destinations: "1.1.1.1", period: invalid); fatalError("invalid period accepted") }
            catch is PingInputError { }
        }
        _ = try PeriodicPingConfiguration(destinations: "127.0.0.1\n::1", period: " 1 ")
        _ = try PeriodicPingConfiguration(destinations: "::1%1", period: String(Int.max / 1_000_000))
        let many = (1...64).map { "10.0.0.\($0)" }.joined(separator: ",")
        let maximum = try PeriodicPingConfiguration(destinations: many, period: "1")
        require(maximum.destinations.count == 64, "64 IPs")
        do { _ = try PeriodicPingConfiguration(destinations: many + ",10.0.0.65", period: "1"); fatalError("too many accepted") }
        catch is PingInputError { }
        for sequence in UInt32(0)...65535 {
            let bytes = PingPacket.echo(ipv6: false, identifier: 0x1234, sequence: UInt16(sequence))
            var sum = stride(from: 0, to: 8, by: 2).reduce(UInt32(0)) { $0 + UInt32(bytes[$1]) * 256 + UInt32(bytes[$1 + 1]) }
            while sum > 65535 { sum = (sum & 65535) + (sum >> 16) }
            require(sum == 65535 && bytes[0] == 8, "checksum")
        }
        require(PingPacket.echo(ipv6: true, identifier: 0x1234, sequence: 0xffff) == [128, 0, 0, 0, 18, 52, 255, 255], "ICMPv6")
        let reports = Reports()
        var service: PeriodicPingService? = PeriodicPingService()
        Thread.sleep(forTimeInterval: 0.03)
        require(probe(0) == 0, "default allocated a socket")
        let live = try PeriodicPingConfiguration(destinations: "127.0.0.1,127.0.0.2,::1", period: "20")
        service!.configure(live) { reports.add($0) }
        wait("periodic sends") { probe(3) >= 15 }
        require(probe(0) == 2 && probe(1) == 0 && probe(5) == 0, "resource bound or packet")
        require(probe(257) >= 5 && probe(258) >= 5 && probe(511) >= 5, "multi-destination")
        require(reports.values == ["Sending ICMP to 3 destination(s)"], "UI publication per tick")
        require(span() >= 0.06, "period ignored")
        mode(3)
        wait("single destination error") { reports.values.last?.contains("127.0.0.2:") == true }
        let before = probe(257)
        wait("other destination must continue") { probe(257) >= before + 3 }
        mode(0)
        wait("recover next period") { reports.values.last == "Sending ICMP to 3 destination(s)" }
        mode(4)
        let reads = probe(4)
        wait("bounded receive flood") { probe(4) > reads }
        mode(0)
        service!.configure(nil) { reports.add($0) }
        wait("off acknowledgement") { reports.values.last == "Off" }
        let stopped = probe(2)
        Thread.sleep(forTimeInterval: 0.08)
        require(probe(2) == stopped && probe(0) == probe(1), "Off leaked work")
        mode(1)
        service!.configure(live) { reports.add($0) }
        wait("open failure") { reports.values.last?.contains("Send error:") == true }
        mode(0)
        wait("open recovery") { reports.values.last == "Sending ICMP to 3 destination(s)" }
        mode(5)
        wait("partial send rejection") { reports.values.last?.contains("Send error:") == true }
        mode(0)
        for _ in 0..<100 {
            service!.configure(live) { reports.add($0) }
            service!.configure(nil) { reports.add($0) }
        }
        let end = DispatchSemaphore(value: 0)
        service!.configure(nil) { _ in end.signal() }
        require(end.wait(timeout: .now() + 3) == .success, "rapid Off acknowledgement")
        let final = probe(2)
        Thread.sleep(forTimeInterval: 0.06)
        require(probe(2) == final && probe(0) == probe(1), "stale timer")
        service!.configure(live) { reports.add($0) }
        wait("restart") { probe(0) > probe(1) }
        service = nil
        wait("deinit cleanup") { probe(0) == probe(1) }
        require(probe(5) == 0, "wire mismatch")
        print("PASS: numeric parsing, 65536 IPv4 checksums, ICMPv6, multi-IP scheduling, errors, recovery, publication, Off, rapid changes, deinit")
        print("CONTROLLED_SYSCALLS opens=\(probe(0)) closes=\(probe(1)) send_calls=\(probe(2)); not a network reachability test")
    }
}
