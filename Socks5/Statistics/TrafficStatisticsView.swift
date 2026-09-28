import SwiftUI
import HevSocks5Server

@MainActor
struct TrafficStatisticsView: View {
    let isVisible: Bool
    @Environment(\.scenePhase) private var scenePhase
    @State private var statistics = TrafficStatistics()
    @State private var clients = ClientTrafficStatistics()
    @State private var clientsIncomplete = false

    var body: some View {
        let clientRows = clients.rows
        NavigationStack {
            Form {
                Section {
                    summary(statistics, id: "total")
                } header: {
                    Text("Total")
                        .accessibilityIdentifier("total-title")
                }
                ForEach(clientRows) { client in
                    Section {
                        summary(client.traffic, id: "client-\(client.id)")
                    } header: {
                        Text(client.address)
                            .textCase(nil)
                            .accessibilityIdentifier("client-\(client.id)")
                    }
                }
                if clientRows.isEmpty || clientsIncomplete {
                    Section {
                        if clientRows.isEmpty {
                            Text("No client payload recorded yet.")
                                .foregroundStyle(.secondary)
                        }
                        if clientsIncomplete {
                            Text("New clients will be included in the next sample.")
                                .font(.footnote)
                        }
                    }
                }
                Section {
                    Text("Speed: In / Out. Transferred: In / Out / Total. Clients follow IP registration order; Unattributed appears first when needed.")
                    Text("Since app launch; stopping the server does not reset totals. In: external network to this app. Out: this app to the external network. TCP and UDP payload only.")
                    Text("Observed SOCKS control-peer IP, not a device identity. Ports are ignored. Unattributed preserves bytes when IP lookup or registration fails. Totals and client rows are independent live reads and may briefly differ.")
                    Text("Speed uses the last sampling interval (about 1 second). KB/MB/GB use 1,000-based bytes; Kbps/Mbps/Gbps use bits per second. Sampling pauses when this tab is hidden or the app is inactive; native totals keep accumulating while the server runs.")
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
            }
            .navigationTitle("Statistics")
        }
        .task(id: isVisible && scenePhase == .active) {
            guard isVisible && scenePhase == .active else { return }
            statistics = TrafficStatistics()
            clients = ClientTrafficStatistics()
            clientsIncomplete = false
            sample()
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(1)) }
                catch { return }
                guard !Task.isCancelled else { return }
                sample()
            }
        }
    }

    /// One shared two-line layout for the aggregate and every registered client.
    private func summary(_ statistics: TrafficStatistics, id: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                metric("In", TrafficStatistics.speed(statistics.receiveRate))
                metric("Out", TrafficStatistics.speed(statistics.sendRate))
            }
            .font(.subheadline)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("\(id)-speed")
            HStack(spacing: 8) {
                metric("In", TrafficStatistics.capacity(Double(statistics.received)))
                metric("Out", TrafficStatistics.capacity(Double(statistics.sent)))
                metric("Total", TrafficStatistics.capacity(
                    Double(statistics.received) + Double(statistics.sent)))
            }
            .font(.footnote)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("\(id)-usage")
        }
        .monospacedDigit()
        .padding(.vertical, 4)
    }

    private func metric(_ label: String, _ value: String) -> some View {
        Text("\(label) \(value)")
            .lineLimit(1)
            .minimumScaleFactor(0.7)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func sample() {
        var received: UInt64 = 0
        var sent: UInt64 = 0
        hev_socks5_server_stats(&received, &sent)
        // Native entries are append-only. If a registration races this size query,
        // all older rows still fit and newer rows appear on the next visible sample.
        let capacity = hev_socks5_server_client_stats(nil, 0)
        var rows = [HevSocks5ClientStats](repeating: HevSocks5ClientStats(), count: capacity)
        let required = rows.withUnsafeMutableBufferPointer {
            hev_socks5_server_client_stats($0.baseAddress, $0.count)
        }
        clientsIncomplete = required > capacity
        let time = ProcessInfo.processInfo.systemUptime
        statistics.sample(received: received, sent: sent, at: time)
        for var row in rows.prefix(min(capacity, required)) {
            let address = withUnsafePointer(to: &row.address) {
                $0.withMemoryRebound(to: CChar.self, capacity: 64) { String(cString: $0) }
            }
            clients.sample(id: row.id, address: address, received: row.received,
                           sent: row.sent, at: time)
        }
    }
}
