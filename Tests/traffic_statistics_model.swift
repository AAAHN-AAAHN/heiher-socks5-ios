import Foundation

@main
struct TrafficStatisticsTests {
    static func main() {
        var value = TrafficStatistics()
        value.sample(received: 100, sent: 500, at: 20)
        precondition(value.receiveRate == 0 && value.sendRate == 0)
        value.sample(received: 1_100, sent: 2_500, at: 21)
        precondition(value.receiveRate == 1_000 && value.sendRate == 2_000)
        value.sample(received: 4_100, sent: 3_500, at: 23)
        precondition(value.receiveRate == 1_500 && value.sendRate == 500)
        value.sample(received: 4_100, sent: 3_500, at: 24)
        precondition(value.receiveRate == 0 && value.sendRate == 0)
        value = TrafficStatistics()
        value.sample(received: 100_000, sent: 200_000, at: 60)
        precondition(value.receiveRate == 0 && value.sent == 200_000)
        value.sample(received: 1, sent: 2, at: 61)
        precondition(value.receiveRate == 0 && value.sendRate == 0)
        precondition(TrafficStatistics.capacity(999) == "1.00 KB")
        precondition(TrafficStatistics.capacity(1_000) == "1.00 KB")
        precondition(TrafficStatistics.capacity(1_000_000) == "1.00 MB")
        precondition(TrafficStatistics.capacity(1_000_000_000) == "1.00 GB")
        precondition(TrafficStatistics.speed(125) == "1.00 Kbps")
        precondition(TrafficStatistics.speed(125_000) == "1.00 Mbps")
        precondition(TrafficStatistics.speed(125_000_000) == "1.00 Gbps")
        precondition(TrafficStatistics.speed(0) == "0.00 Kbps")
        value.sample(received: 10, sent: 20, at: 61)
        precondition(value.receiveRate == 0 && value.sendRate == 0)
        value.sample(received: 20, sent: 30, at: 60)
        precondition(value.receiveRate == 0 && value.sendRate == 0)
        value.sample(received: 30, sent: 50, at: 60.25)
        precondition(value.receiveRate == 40 && value.sendRate == 80)
        value = TrafficStatistics()
        let large = UInt64.max - 100_000
        value.sample(received: large, sent: large, at: 1)
        value.sample(received: large + 1, sent: large + 3, at: 1.5)
        precondition(value.receiveRate == 2 && value.sendRate == 6)
        let total = Double(UInt64.max) + Double(UInt64.max)
        precondition(total.isFinite && TrafficStatistics.capacity(total).hasSuffix(" GB"))
        var received = UInt64(1) << 60
        var sent = received
        var time = 100.0
        value = TrafficStatistics()
        value.sample(received: received, sent: sent, at: time)
        for index in 1...10_000 {
            let incoming = UInt64(index % 113)
            let outgoing = UInt64(index % 197)
            let interval = Double(index % 7 + 1) / 4
            received += incoming
            sent += outgoing
            time += interval
            value.sample(received: received, sent: sent, at: time)
            precondition(value.receiveRate == Double(incoming) / interval)
            precondition(value.sendRate == Double(outgoing) / interval)
        }
        print("PASS: 10000 generated samples, large UInt64 deltas, clock boundaries and total conversion")
        print("PASS: direction deltas, elapsed time, idle, re-entry, counter decrease and SI units")
    }
}
