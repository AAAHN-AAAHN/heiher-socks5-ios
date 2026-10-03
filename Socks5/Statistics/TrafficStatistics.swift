import Foundation

/// External-side payload totals. Sampling never changes the native counters.
struct TrafficStatistics {
    private(set) var received: UInt64 = 0
    private(set) var sent: UInt64 = 0
    private(set) var receiveRate = 0.0
    private(set) var sendRate = 0.0
    private var sampledAt: TimeInterval?

    /// Sum before display rounding so small directional rates are not lost.
    var sumRate: Double { receiveRate + sendRate }

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
        scaled(bytes, units: ["KB", "MB", "GB", "TB", "PB"])
    }

    static func speed(_ bytesPerSecond: Double) -> String {
        scaled(bytesPerSecond * 8, units: ["Kbps", "Mbps", "Gbps", "Tbps", "Pbps"])
    }

    private static func scaled(_ amount: Double, units: [String]) -> String {
        var index = 0
        var divisor = 1_000.0
        while index + 1 < units.count && amount >= divisor * 1_000 {
            index += 1
            divisor *= 1_000
        }
        // Round the numeric value in the selected SI unit, then display exactly
        // two decimals. Keep raw counters/rates intact for subsequent samples.
        let rounded = (amount / (divisor / 100)).rounded(.toNearestOrAwayFromZero) / 100
        return String(format: "%.2f %@", locale: Locale(identifier: "en_US_POSIX"), rounded, units[index])
    }
}

/// The native registry owns attribution and lifetime; this is only a visible-tab
/// sampler. Stable IDs combine all connections for the same normalized peer IP.
struct ClientTrafficStatistics {
    struct Entry: Identifiable {
        let id: UInt64
        let address: String
        var traffic = TrafficStatistics()
    }

    private(set) var entries: [UInt64: Entry] = [:]

    var rows: [Entry] {
        entries.values.filter {
            $0.id != 0 || $0.traffic.received != 0 || $0.traffic.sent != 0
        }.sorted { $0.id < $1.id }
    }

    mutating func sample(id: UInt64, address: String, received: UInt64,
                         sent: UInt64, at time: TimeInterval) {
        var entry = entries[id] ?? Entry(id: id, address: address)
        entry.traffic.sample(received: received, sent: sent, at: time)
        entries[id] = entry
    }
}
