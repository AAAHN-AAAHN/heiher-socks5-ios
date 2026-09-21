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
        print("PASS: direction deltas, elapsed time, idle, re-entry, counter decrease and SI units")
    }
}
