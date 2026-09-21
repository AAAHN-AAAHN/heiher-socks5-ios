import Foundation

/// External-side payload totals. Sampling never changes the native counters.
struct TrafficStatistics {
    private(set) var received: UInt64 = 0
    private(set) var sent: UInt64 = 0
    private(set) var receiveRate = 0.0
    private(set) var sendRate = 0.0
    private var sampledAt: TimeInterval?

    mutating func sample(received: UInt64, sent: UInt64, at time: TimeInterval) {
        if let previous = sampledAt, time > previous,
           received >= self.received, sent >= self.sent {
            receiveRate = Double(received - self.received) / (time - previous)
            sendRate = Double(sent - self.sent) / (time - previous)
        } else {
            receiveRate = 0
            sendRate = 0
        }
        self.received = received
        self.sent = sent
        sampledAt = time
    }

    static func capacity(_ bytes: Double) -> String {
        scaled(bytes, units: ["KB", "MB", "GB"])
    }

    static func speed(_ bytesPerSecond: Double) -> String {
        scaled(bytesPerSecond * 8, units: ["Kbps", "Mbps", "Gbps"])
    }

    private static func scaled(_ amount: Double, units: [String]) -> String {
        let index = amount >= 1_000_000_000 ? 2 : (amount >= 1_000_000 ? 1 : 0)
        let divisor = [1_000.0, 1_000_000.0, 1_000_000_000.0][index]
        return String(format: "%.2f %@", amount / divisor, units[index])
    }
}
