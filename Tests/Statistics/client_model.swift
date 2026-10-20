import Foundation

@main struct ClientModelTests {
    static func main() {
        var model = EndpointTrafficStatistics()
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
        precondition(model.rows[0].traffic.sumRate == 150)
        model.sample(id: 0, address: "Unattributed", received: 10, sent: 5, at: 3)
        precondition(model.rows.map(\.id) == [0, 1, 2])
        model.sample(id: 1, address: "127.0.0.1", received: 300, sent: 160, at: 4)
        precondition(model.rows[1].traffic.receiveRate == 0 && model.rows[1].traffic.received == 300)
        model.sample(id: 1, address: "127.0.0.1", received: 1, sent: 2, at: 5)
        precondition(model.rows[1].traffic.receiveRate == 0)
        precondition(model.rows[1].traffic.sumRate == 0)
        model.sample(id: 1, address: "127.0.0.1", received: 9, sent: 12, at: 5)
        precondition(model.rows[1].traffic.sendRate == 0)
        model.sample(id: 3, address: "fe80::1%3", received: UInt64.max, sent: UInt64.max, at: 5)
        precondition(model.rows.last!.traffic.receiveRate == 0)
        model.sample(id: 3, address: "fe80::1%3", received: UInt64.max, sent: UInt64.max, at: 6)
        precondition(model.rows.last!.traffic.sendRate == 0)
        // Hidden-tab resumption resets only sampling, not native cumulative totals.
        model = EndpointTrafficStatistics()
        model.sample(id: 1, address: "127.0.0.1", received: 10000, sent: 9000, at: 50)
        precondition(model.rows[0].traffic.receiveRate == 0 && model.rows[0].traffic.received == 10000)
        checkTableRounding()
        checkExtendedUnits()
        print("PASS: per-IP independent deltas, first sample, idle/reconnect totals, stable rows, unknown, counter/time edges")
    }

    private static func checkTableRounding() {
        let amounts: [(Double, String)] = [
            (0, "0.00 KB"), (1, "0.00 KB"), (64, "0.06 KB"),
            (999, "1.00 KB"), (1_000, "1.00 KB"),
            (1_234_999, "1.23 MB"), (1_235_000, "1.24 MB"),
            (1_235_001, "1.24 MB"), (1_235_000_000, "1.24 GB"),
            (999_994, "999.99 KB"), (999_995, "1000.00 KB"),
            (1_000_000, "1.00 MB"), (999_999_999, "1000.00 MB")
        ]
        for (input, expected) in amounts {
            precondition(TrafficStatistics.capacity(input) == expected, "Rounding \(input)")
        }
        for (input, expected) in [
            (0.5, "0.00 Kbps"), (0.625, "0.01 Kbps"),
            (408_123.75, "3.26 Mbps"), (408_125.0, "3.27 Mbps"),
            (408_126.25, "3.27 Mbps"), (125_000_000.0, "1.00 Gbps")
        ] {
            precondition(TrafficStatistics.speed(input) == expected)
        }
        var traffic = TrafficStatistics()
        traffic.sample(received: 0, sent: 0, at: 0)
        traffic.sample(received: 1, sent: 1, at: 2)
        precondition(traffic.sumRate == 1)
        precondition(TrafficStatistics.speed(traffic.receiveRate) == "0.00 Kbps")
        precondition(TrafficStatistics.speed(traffic.sumRate) == "0.01 Kbps")
        for _ in 0..<100 { _ = TrafficStatistics.speed(traffic.sumRate) }
        precondition(traffic.receiveRate == 0.5 && traffic.received == 1)
        traffic.sample(received: 4, sent: 6, at: 4)
        precondition(traffic.sumRate == 4 && traffic.receiveRate == 1.5)
        precondition(TrafficStatistics.speed(traffic.sumRate) == "0.03 Kbps")
        // Independent decimal arithmetic checks every third-decimal boundary
        // across a dense interval without sharing the production rounding formula.
        for input in 1_230_000...1_240_000 {
            var decimal = Decimal(input) / Decimal(1_000_000)
            var rounded = Decimal()
            NSDecimalRound(&rounded, &decimal, 2, .plain)
            let expected = String(format: "%.2f MB", NSDecimalNumber(decimal: rounded).doubleValue)
            precondition(TrafficStatistics.capacity(Double(input)) == expected)
        }
        let large = Double(UInt64.max) + Double(UInt64.max)
        precondition(large.isFinite && TrafficStatistics.capacity(large).hasSuffix(" PB"))
        var clients = EndpointTrafficStatistics()
        clients.sample(id: 2, address: "::1", received: 0, sent: 0, at: 0)
        clients.sample(id: 1, address: "127.0.0.1", received: 0, sent: 0, at: 0)
        clients.sample(id: 1, address: "127.0.0.1", received: 1, sent: 1, at: 2)
        precondition(clients.rows.map(\.id) == [1, 2])
        precondition(TrafficStatistics.speed(clients.rows[0].traffic.sumRate) == "0.01 Kbps")
        print("PASS: 10001 independent decimal controls, half-up boundaries, two digits, raw-first Sum, unmodified counter/rate baselines, per-IP order")
    }

    private static func checkExtendedUnits() {
        // Both public paths share the same SI thresholds and numeric rounding.
        let cases: [(Double, String)] = [
            (0, "0.00 KB"), (999, "1.00 KB"),
            (1_000, "1.00 KB"), (1_000_000, "1.00 MB"),
            (1_000_000_000, "1.00 GB"),
            (999_999_999_999, "1000.00 GB"),
            (1_000_000_000_000, "1.00 TB"),
            (1_000_000_000_001, "1.00 TB"),
            (999_999_999_999_999, "1000.00 TB"),
            (1_000_000_000_000_000, "1.00 PB"),
            (1_000_000_000_000_001, "1.00 PB"),
            (1_234_999_000_000, "1.23 TB"),
            (1_235_000_000_000, "1.24 TB"),
            (1_235_001_000_000, "1.24 TB"),
            (1_234_999_000_000_000, "1.23 PB"),
            (1_235_000_000_000_000, "1.24 PB"),
            (1_235_001_000_000_000, "1.24 PB"),
            (362_234_567_000_000, "362.23 TB"),
            (1_000_000_000_000_000_000, "1000.00 PB"),
            (Double(UInt64.max), "18446.74 PB"),
            (Double(UInt64.max) + Double(UInt64.max), "36893.49 PB")
        ]
        for (amount, capacity) in cases {
            precondition(TrafficStatistics.capacity(amount) == capacity, "Capacity: \(amount)")
            let rate = capacity.replacingOccurrences(of: "KB", with: "Kbps")
                .replacingOccurrences(of: "MB", with: "Mbps")
                .replacingOccurrences(of: "GB", with: "Gbps")
                .replacingOccurrences(of: "TB", with: "Tbps")
                .replacingOccurrences(of: "PB", with: "Pbps")
            precondition(TrafficStatistics.speed(amount / 8) == rate, "Rate: \(amount)")
        }
        // Independent Decimal reference, repeated at both new magnitudes. The
        // values are exactly representable integers before conversion to Double.
        for (factor, unit) in [(1_000_000, "TB"), (1_000_000_000, "PB")] {
            for input in 1_230_000...1_240_000 {
                var decimal = Decimal(input) / Decimal(1_000_000)
                var rounded = Decimal()
                NSDecimalRound(&rounded, &decimal, 2, .plain)
                let digits = String(format: "%.2f", locale: Locale(identifier: "en_US_POSIX"),
                                    NSDecimalNumber(decimal: rounded).doubleValue)
                let amount = Double(Int64(input) * Int64(factor))
                precondition(TrafficStatistics.capacity(amount) == digits + " " + unit)
                precondition(TrafficStatistics.speed(amount / 8) == digits + " " + unit.prefix(1) + "bps")
            }
        }
        var total = TrafficStatistics()
        total.sample(received: 0, sent: 0, at: 0)
        total.sample(received: 75_000_000_000, sent: 75_000_000_000, at: 1)
        precondition(TrafficStatistics.speed(total.receiveRate) == "600.00 Gbps")
        precondition(TrafficStatistics.speed(total.sumRate) == "1.20 Tbps")
        let oldRate = total.receiveRate
        _ = TrafficStatistics.capacity(Double(total.received))
        precondition(total.receiveRate == oldRate && total.received == 75_000_000_000)
        total.sample(received: 75_000_000_001, sent: 75_000_000_003, at: 1.5)
        precondition(total.receiveRate == 2 && total.sendRate == 6)
        print("PASS: KB-PB/Kbps-Pbps thresholds, ties, 20002 independent Decimal controls, PB cap, UInt64 maxima and raw-first cross-unit Sum")
    }
}
