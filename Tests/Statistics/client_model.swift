import Foundation

@main struct ClientModelTests {
    static func main() {
        var model = ClientTrafficStatistics()
        model.sample(id: 0, address: "Unattributed", received: 0, sent: 0, at: 1)
        precondition(model.rows.isEmpty)
        model.sample(id: 2, address: "::1", received: 50, sent: 20, at: 1)
        model.sample(id: 1, address: "127.0.0.1", received: 100, sent: 60, at: 1)
        precondition(model.rows.map(\.id) == [1, 2])
        precondition(model.rows.allSatisfy { $0.traffic.receiveRate == 0 && $0.traffic.sendRate == 0 })
        model.sample(id: 1, address: "127.0.0.1", received: 300, sent: 160, at: 3)
        model.sample(id: 2, address: "::1", received: 50, sent: 20, at: 3)
        precondition(model.rows[0].traffic.receiveRate == 100 && model.rows[0].traffic.sendRate == 50)
        precondition(model.rows[1].traffic.receiveRate == 0)
        model.sample(id: 0, address: "Unattributed", received: 10, sent: 5, at: 3)
        precondition(model.rows.map(\.id) == [0, 1, 2])
        model.sample(id: 1, address: "127.0.0.1", received: 300, sent: 160, at: 4)
        precondition(model.rows[1].traffic.receiveRate == 0 && model.rows[1].traffic.received == 300)
        model.sample(id: 1, address: "127.0.0.1", received: 1, sent: 2, at: 5)
        precondition(model.rows[1].traffic.receiveRate == 0)
        model.sample(id: 1, address: "127.0.0.1", received: 9, sent: 12, at: 5)
        precondition(model.rows[1].traffic.sendRate == 0)
        model.sample(id: 3, address: "fe80::1%3", received: UInt64.max, sent: UInt64.max, at: 5)
        precondition(model.rows.last!.traffic.receiveRate == 0)
        model.sample(id: 3, address: "fe80::1%3", received: UInt64.max, sent: UInt64.max, at: 6)
        precondition(model.rows.last!.traffic.sendRate == 0)
        // Hidden-tab resumption resets only sampling, not native cumulative totals.
        model = ClientTrafficStatistics()
        model.sample(id: 1, address: "127.0.0.1", received: 10000, sent: 9000, at: 50)
        precondition(model.rows[0].traffic.receiveRate == 0 && model.rows[0].traffic.received == 10000)
        print("PASS: per-IP independent deltas, first sample, idle/reconnect totals, stable rows, unknown, counter/time edges")
    }
}
