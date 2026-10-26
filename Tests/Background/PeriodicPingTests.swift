import Dispatch
import Foundation

@_silgen_name("ping_probe_value") private func probe(_ key: Int32) -> Int32
@_silgen_name("ping_probe_mode") private func mode(_ value: Int32)
@_silgen_name("ping_probe_span") private func span() -> Double
@_silgen_name("ping_probe_server") private func server(_ enabled: Int32)
@_silgen_name("ping_probe_budget") private func budget(_ value: Int32)

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
        for invalid in ["", "example.com", "127.1", "1.2.3.999", "127.0.0.1:80", "127.0.0.1,", "::1%", "::1%0", "::1%no-such-ping-interface", "1.1.1.1\0suffix", ",1.1.1.1",
                        "\r\n127.0.0.1", "127.0.0.1\r\n", "127.0.0.1\r\n\r\n::1",
                        "::1%1%2", "::1%%1", "::1" + String(repeating: "%", count: 4096)] {
            do { _ = try PeriodicPingConfiguration(destinations: invalid, period: "1000"); fatalError("invalid IP accepted") }
            catch is PingInputError { }
        }
        for invalid in ["", "0", "-1", "+1", "1.5", "nan", "1e3", "1000ms", "99999999999999999999999", String(Int.max / 1_000_000 + 1)] {
            do { _ = try PeriodicPingConfiguration(destinations: "1.1.1.1", period: invalid); fatalError("invalid period accepted") }
            catch is PingInputError { }
        }
        for newline in ["\n", "\r\n", "\r", "\u{0085}", "\u{2028}", "\u{2029}"] {
            let separated = try PeriodicPingConfiguration(destinations: "127.0.0.1" + newline + "::1", period: " 1 ")
            require(separated.destinations.map(\.name) == ["127.0.0.1", "::1"] && separated.periodMilliseconds == 1, "newline parsing")
        }
        _ = try PeriodicPingConfiguration(destinations: "::1%1", period: String(Int.max / 1_000_000))
        let scoped = try PeriodicPingConfiguration(destinations: "fe80::1%1,fe80:0:0:0:0:0:0:1%01,fe80::1%2", period: "1")
        require(scoped.destinations.map(\.name) == ["fe80::1%1", "fe80::1%2"], "scope normalization and deduplication")
        let many = (0..<65_536).map { "10.1.\($0 / 256).\($0 % 256)" }.joined(separator: ",")
        for period in ["", "0", String(Int.max / 1_000_000 + 1)] {
            var checks = 0
            do {
                _ = try PeriodicPingConfiguration(destinations: many, period: period) { checks += 1; return false }
                fatalError("invalid period accepted")
            } catch let error as PingInputError { require(error == .period, "period error priority") }
            require(checks == 1, "invalid period parsed the address list")
        }
        for period in ["0", "1"] {
            do {
                _ = try PeriodicPingConfiguration(destinations: many, period: period) { true }
                fatalError("pre-cancelled input accepted")
            } catch is CancellationError { }
        }
        var checks = 0
        do {
            _ = try PeriodicPingConfiguration(destinations: many, period: "1") { checks += 1; return checks == 2 }
            fatalError("superseded parsing continued")
        } catch is CancellationError { }
        require(checks == 2, "parsing cancellation checkpoint")
        let maximum = try PeriodicPingConfiguration(destinations: many, period: "1")
        require(maximum.destinations.count == 65_536, "65536 IPs")
        do { _ = try PeriodicPingConfiguration(destinations: many + ",10.2.0.0", period: "1"); fatalError("too many accepted") }
        catch let error as PingInputError { require(error == .count, "distinct destination limit") }
        let duplicates = String(repeating: "127.0.0.1,", count: 100_000) + "127.0.0.1"
        let compacted = try PeriodicPingConfiguration(destinations: duplicates, period: "1")
        require(compacted.destinations.count == 1 && duplicates.utf8.count > 8192, "no byte/token cap")
        let repeatedMaximum = try PeriodicPingConfiguration(destinations: many + ",10.1.0.0,::ffff:10.1.0.0", period: "1")
        require(repeatedMaximum.destinations.count == 65_536, "duplicate at maximum")
        let reports = Reports()
        var service: PeriodicPingService? = PeriodicPingService()
        Thread.sleep(forTimeInterval: 0.03)
        require(probe(0) == 0, "default allocated a native client")
        let live = try PeriodicPingConfiguration(destinations: "127.0.0.1,127.0.0.2,::1", period: "20")
        server(0)
        service!.configure(live) { reports.add($0) }
        wait("native readiness") { reports.values.last == "Waiting for native ICMP server" }
        Thread.sleep(forTimeInterval: 0.06)
        require(probe(0) == 0 && probe(2) == 0, "unavailable server caused fallback I/O")
        server(1)
        wait("periodic native sends") { probe(3) >= 15 }
        require(probe(0) == 1 && probe(1) == 0 && probe(5) == 0, "client bound or native request")
        require(probe(257) >= 5 && probe(258) >= 5 && probe(511) >= 5, "multi-destination")
        require(reports.values == ["Waiting for native ICMP server", "Sending ICMP to 3 destination(s)"], "UI publication per tick")
        require(span() >= 0.06, "period ignored")
        mode(3)
        wait("single destination error") { reports.values.last?.contains("127.0.0.2:") == true }
        let before = probe(257)
        wait("other destination must continue") { probe(257) >= before + 3 }
        mode(0)
        wait("recover next period") { reports.values.last == "Sending ICMP to 3 destination(s)" }
        for state in [Int32(8), Int32(9)] {
            mode(state)
            let count = reports.values.count, sent = probe(3)
            wait("terminal or duplicate event after SENT") { probe(3) >= sent + 9 }
            require(reports.values.count == count, "reply/timeout/duplicate changed send status")
        }
        mode(0)
        server(0)
        wait("server stop releases client") { reports.values.last == "Waiting for native ICMP server" && probe(0) == probe(1) }
        let waiting = probe(2)
        Thread.sleep(forTimeInterval: 0.05)
        require(probe(2) == waiting, "stopped server still received requests")
        server(1)
        wait("new server generation") { reports.values.last == "Sending ICMP to 3 destination(s)" && probe(0) == 2 }
        service!.configure(nil) { reports.add($0) }
        wait("off acknowledgement") { reports.values.last == "Off" && probe(0) == probe(1) }
        let stopped = probe(3)
        Thread.sleep(forTimeInterval: 0.08)
        require(probe(3) == stopped && probe(8) == 0, "Off leaked native work")
        mode(1)
        service!.configure(live) { reports.add($0) }
        wait("native client failure") { reports.values.last?.contains("Send error:") == true }
        mode(0)
        wait("client recovery") { reports.values.last == "Sending ICMP to 3 destination(s)" }
        mode(5)
        wait("native send rejection") { reports.values.last?.contains("Send error:") == true }
        mode(0)
        service!.configure(nil) { reports.add($0) }
        wait("before pressure") { reports.values.last == "Off" && probe(0) == probe(1) }
        mode(4)
        let slow = try PeriodicPingConfiguration(destinations: "127.0.0.1,::1", period: "1000")
        service!.configure(slow) { reports.add($0) }
        wait("explicit capacity wait") { reports.values.last == "Waiting for native ICMP capacity; 0/2 destinations processed" }
        let full = probe(2)
        Thread.sleep(forTimeInterval: 0.08)
        require(probe(2) == full, "full native queue caused a retry loop")
        service!.configure(nil) { reports.add($0) }
        wait("after pressure") { reports.values.last == "Off" && probe(0) == probe(1) }
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
        mode(6)
        service!.configure(maximum) { reports.add($0) }
        wait("one bounded batch") { probe(8) == 256 }
        let held = probe(2)
        Thread.sleep(forTimeInterval: 0.06)
        require(probe(2) == held && probe(6) <= 256, "held native batch accumulated timer work")
        let off = DispatchSemaphore(value: 0)
        let offStart = Date(), cancellations = probe(7)
        service!.configure(nil) { _ in off.signal() }
        require(probe(7) > cancellations && probe(8) == 0, "Off delayed native cancellation")
        require(off.wait(timeout: .now() + 3) == .success, "large batch Off")
        require(Date().timeIntervalSince(offStart) < 1, "large batch did not yield to Off")
        mode(0)
        let chunked = try PeriodicPingConfiguration(destinations: (0..<600).map {
            "10.2.\($0 / 256).\($0 % 256)"
        }.joined(separator: ","), period: "20")
        budget(300)
        let chunkStart = probe(3)
        service!.configure(chunked) { reports.add($0) }
        wait("capacity preserves a partial round") {
            reports.values.last == "Waiting for native ICMP capacity; 300/600 destinations processed"
        }
        require(probe(3) == chunkStart + 300 && probe(11) == 299, "partial native round")
        budget(300)
        wait("capacity resumes at the next destination") {
            reports.values.contains("Sending ICMP to 600 destination(s)")
        }
        require(probe(3) == chunkStart + 600 && probe(11) == 599, "capacity restarted or starved later destinations")
        require(probe(6) <= 256, "multiple batches exceeded one bounded native batch")
        service!.configure(nil) { reports.add($0) }
        wait("after complete round") { reports.values.last == "Off" && probe(0) == probe(1) }
        budget(17)
        service!.configure(chunked) { reports.add($0) }
        wait("partial round before editing") {
            reports.values.last == "Waiting for native ICMP capacity; 17/600 destinations processed"
        }
        let edited = try PeriodicPingConfiguration(destinations: "10.3.0.9,10.3.0.10", period: "20")
        service!.configure(edited) { reports.add($0) }
        wait("editing resets pending cursor") {
            reports.values.last == "Waiting for native ICMP capacity; 0/2 destinations processed"
        }
        budget(1)
        wait("edited list begins at its first destination") {
            reports.values.last == "Waiting for native ICMP capacity; 1/2 destinations processed"
        }
        require(probe(11) == 9, "editing retained the previous list cursor")
        service!.configure(nil) { reports.add($0) }
        wait("Off while waiting for capacity") { reports.values.last == "Off" && probe(0) == probe(1) }
        let capacityOff = probe(2), capacitySent = probe(3)
        budget(100)
        Thread.sleep(forTimeInterval: 0.06)
        require(probe(2) == capacityOff && probe(3) == capacitySent, "Off resumed a pending capacity round")
        budget(7)
        service!.configure(chunked) { reports.add($0) }
        wait("partial round before restart") {
            reports.values.last == "Waiting for native ICMP capacity; 7/600 destinations processed"
        }
        server(0)
        wait("capacity wait observes server stop") {
            reports.values.last == "Waiting for native ICMP server" && probe(0) == probe(1)
        }
        server(1)
        wait("server generation resets pending cursor") {
            reports.values.last == "Waiting for native ICMP capacity; 0/600 destinations processed"
        }
        budget(9)
        wait("new generation begins a fresh round") {
            reports.values.last == "Waiting for native ICMP capacity; 9/600 destinations processed"
        }
        require(probe(11) == 8, "new generation resumed old generation's round")
        service!.configure(nil) { reports.add($0) }
        wait("before admission race") { reports.values.last == "Off" && probe(0) == probe(1) }
        budget(-1)
        mode(7)
        let entered = probe(10)
        service!.configure(live) { reports.add($0) }
        wait("native submission boundary") { probe(10) > entered }
        let returned = DispatchSemaphore(value: 0), acknowledged = DispatchSemaphore(value: 0)
        let owner = service!
        DispatchQueue.global().async {
            owner.configure(nil) { _ in acknowledged.signal() }
            returned.signal()
        }
        require(returned.wait(timeout: .now() + 0.05) == .timedOut, "Off returned across held native admission")
        mode(0)
        require(returned.wait(timeout: .now() + 3) == .success, "Off admission gate did not finish")
        require(acknowledged.wait(timeout: .now() + 3) == .success, "Off after admission race")
        let afterRace = probe(3)
        Thread.sleep(forTimeInterval: 0.06)
        require(probe(3) == afterRace && probe(0) == probe(1), "post-Off request entered a fresh cancellation epoch")
        mode(6)
        service!.configure(live) { reports.add($0) }
        wait("held old generation") { probe(8) == 3 }
        server(0)
        server(1)
        mode(0)
        wait("old generation callbacks discarded") { reports.values.last == "Sending ICMP to 3 destination(s)" && probe(8) == 0 }
        service = nil
        // The local owner above remains until this scope ends; explicitly Off it
        // before independently testing the public handle's deinit boundary.
        owner.configure(nil) { reports.add($0) }
        wait("owner Off") { probe(0) == probe(1) }
        var released: PeriodicPingService? = PeriodicPingService()
        mode(6)
        released!.configure(live) { reports.add($0) }
        wait("deinit with native work") { probe(8) == 3 }
        released = nil
        wait("deinit cleanup") { probe(0) == probe(1) && probe(8) == 0 }
        mode(0)
        require(probe(5) == 0, "direct ICMP I/O or native ABI mismatch")
        print("PASS: numeric input, bounded native client/batches, readiness/generation, actual SENT status, failures/backpressure, stale events, Off admission, deinit")
        print("CONTROLLED_NATIVE_API clients=\(probe(0)) freed=\(probe(1)) requests=\(probe(2)); no device or direct ICMP execution")
    }
}
