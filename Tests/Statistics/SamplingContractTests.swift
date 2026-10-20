import Foundation

/// Test substitutes only: setter counts do not measure SwiftUI render passes.
@propertyWrapper struct Recorded<Value> {
    final class Storage {
        var value: Value
        var writes = 0
        init(_ value: Value) { self.value = value }
    }
    private let storage: Storage
    init(wrappedValue: Value) { storage = Storage(wrappedValue) }
    var wrappedValue: Value {
        get { storage.value }
        nonmutating set { storage.writes += 1; storage.value = newValue }
    }
    var projectedValue: Storage { storage }
}

// Same 64-byte caller-owned address storage as the native public struct.
struct HevSocks5EndpointStats {
    var id: UInt64 = 0
    var received: UInt64 = 0
    var sent: UInt64 = 0
    var address = (UInt64(0), UInt64(0), UInt64(0), UInt64(0),
                   UInt64(0), UInt64(0), UInt64(0), UInt64(0))
    init() {}
    init(id: UInt64, received: UInt64, sent: UInt64) {
        self.id = id; self.received = received; self.sent = sent
        let text = id == 0 ? "Unattributed" : "2001:db8::\(String(id, radix: 16))"
        withUnsafeMutableBytes(of: &address) { destination in
            for (index, byte) in text.utf8.enumerated() { destination[index] = byte }
        }
    }
}

@MainActor enum ProcessInfo {
    static let processInfo = Clock()
    final class Clock { var systemUptime = 100.0 }
}
@MainActor enum NativeSnapshot {
    static var rows = [HevSocks5EndpointStats(id: 0, received: 0, sent: 0)]
    static var registerDuringCopy = 0
    static var queries = 0
    static var copies = 0
    static var addressReads = 0
}
@MainActor func withUnsafePointer<T, Result>(to value: inout T,
    _ body: (UnsafePointer<T>) throws -> Result) rethrows -> Result {
    NativeSnapshot.addressReads += 1
    return try Swift.withUnsafePointer(to: &value, body)
}
@MainActor func hev_socks5_server_endpoint_stats(_ received: inout UInt64, _ sent: inout UInt64) {
    received = NativeSnapshot.rows.reduce(0) { $0 &+ $1.received }
    sent = NativeSnapshot.rows.reduce(0) { $0 &+ $1.sent }
}
@MainActor func hev_socks5_server_endpoint_rows(_ rows: UnsafeMutablePointer<HevSocks5EndpointStats>?,
                                             _ capacity: Int) -> Int {
    guard let rows else { NativeSnapshot.queries += 1; return NativeSnapshot.rows.count }
    NativeSnapshot.copies += 1
    for _ in 0..<NativeSnapshot.registerDuringCopy {
        let id = UInt64(NativeSnapshot.rows.count)
        NativeSnapshot.rows.append(HevSocks5EndpointStats(id: id, received: id * 17, sent: id * 31))
    }
    NativeSnapshot.registerDuringCopy = 0
    for index in 0..<min(capacity, NativeSnapshot.rows.count) { rows[index] = NativeSnapshot.rows[index] }
    return NativeSnapshot.rows.count
}

@MainActor struct SamplingHarness {
    @Recorded var statistics = TrafficStatistics()
    @Recorded var clients = EndpointTrafficStatistics()
    @Recorded var clientsIncomplete = false
    // INSERT_EXACT_SAMPLE_METHOD
    func run() { sample() }
}

@main struct SamplingContractTests {
    @MainActor static func main() {
        var checks = 0
        var addressesReadOnce = true
        func check(_ condition: @autoclosure () -> Bool, _ message: String) {
            checks += 1
            if !condition() { print("FAIL:", message); exit(1) }
        }
        func sample(_ view: SamplingHarness) {
            let previousWrites = view.$clients.writes
            let queries = NativeSnapshot.queries
            let copies = NativeSnapshot.copies
            let entries = view.clients.entries.count
            let addressReads = NativeSnapshot.addressReads
            view.run()
            check(view.$clients.writes == previousWrites + 1,
                  "one client-state publication per snapshot; observed \(view.$clients.writes - previousWrites)")
            check(NativeSnapshot.queries == queries + 1 && NativeSnapshot.copies == copies + 1,
                  "one size query and one bounded copy; no retry loop")
            addressesReadOnce = addressesReadOnce &&
                NativeSnapshot.addressReads - addressReads == view.clients.entries.count - entries
        }
        let view = SamplingHarness()
        sample(view)
        check(view.clients.rows.isEmpty && view.statistics.received == 0, "initial Total without a client")
        NativeSnapshot.registerDuringCopy = 512
        sample(view)
        check(view.clientsIncomplete && view.clients.entries.count == 1, "raced registrations wait for next sample")
        ProcessInfo.processInfo.systemUptime += 1
        sample(view)
        check(!view.clientsIncomplete && view.clients.entries.count == 513, "next bounded snapshot includes new rows")
        check(view.clients.rows.map(\.id) == Array(1...512).map(UInt64.init), "stable order and zero unknown hidden")
        check(view.clients.rows.allSatisfy { $0.traffic.sumRate == 0 }, "new clients establish a baseline")
        let retained = view.clients
        for iteration in 1...64 {
            let old = view.clients
            let dt = Double(iteration % 4 + 1) / 4
            ProcessInfo.processInfo.systemUptime += dt
            for index in 0..<NativeSnapshot.rows.count {
                NativeSnapshot.rows[index].received += UInt64(index % 17)
                NativeSnapshot.rows[index].sent += UInt64(index % 31)
            }
            sample(view)
            for row in view.clients.rows {
                let oldRow = old.entries[row.id]!.traffic
                check(row.traffic.receiveRate == Double(row.traffic.received - oldRow.received) / dt,
                      "unchanged per-IP receive delta")
                check(row.traffic.sendRate == Double(row.traffic.sent - oldRow.sent) / dt,
                      "unchanged per-IP send delta")
                check(row.address == "2001:db8::\(String(row.id, radix: 16))", "numeric peer label")
            }
            let totalIn = view.clients.entries.values.reduce(UInt64(0)) { $0 &+ $1.traffic.received }
            let totalOut = view.clients.entries.values.reduce(UInt64(0)) { $0 &+ $1.traffic.sent }
            check(totalIn == view.statistics.received && totalOut == view.statistics.sent,
                  "same quiescent aggregate snapshot and IP totals")
        }
        check(retained.entries[1]!.traffic.received == 17, "old value snapshot not mutated")
        NativeSnapshot.rows[0].received = 100
        NativeSnapshot.rows[0].sent = 200
        NativeSnapshot.rows[7].received = 1
        NativeSnapshot.rows[7].sent = 2
        ProcessInfo.processInfo.systemUptime += 1
        sample(view)
        check(view.clients.rows.first?.id == 0, "nonzero unattributed row remains first")
        check(view.clients.entries[7]!.traffic.sumRate == 0, "decreased counters establish a zero-rate baseline")
        let returned = SamplingHarness()
        sample(returned)
        check(returned.clients.rows.allSatisfy { $0.traffic.sumRate == 0 }, "returning tab starts fresh rates")
        check(returned.statistics.received == view.statistics.received, "view lifetime does not reset native totals")
        // Native snapshots are packed in hash order. Stable IDs are identifiers,
        // not array indices, and concurrent registration may leave gaps.
        NativeSnapshot.rows = [
            HevSocks5EndpointStats(id: 901, received: 90, sent: 91),
            HevSocks5EndpointStats(id: 0, received: 0, sent: 0),
            HevSocks5EndpointStats(id: 7, received: 70, sent: 71),
        ]
        let packed = SamplingHarness()
        sample(packed)
        check(packed.clients.rows.map(\.id) == [7, 901], "packed rows sort by stable, noncontiguous IDs")
        check(packed.clients.entries[901]?.traffic.received == 90, "high ID remains inside the bounded snapshot")
        ProcessInfo.processInfo.systemUptime += 1
        NativeSnapshot.rows.reverse()
        NativeSnapshot.rows[0].sent += 3
        sample(packed)
        check(packed.clients.entries[7]?.traffic.sendRate == 3, "reordered packed rows keep the same per-IP baseline")
        check(packed.statistics.received == 160 && packed.statistics.sent == 165, "packed Total sums endpoint directions")
        check(addressesReadOnce, "decode only newly observed peer addresses")
        print("PASS:", checks, "exact sample-body checks; 512 peers/64 intervals, snapshot growth and packed IDs; no SwiftUI render-count claim")
    }
}
