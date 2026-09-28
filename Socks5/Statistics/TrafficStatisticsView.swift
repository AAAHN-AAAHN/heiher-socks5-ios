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
                Section("Transfer speed") {
                    Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 12) {
                        GridRow {
                            Text("Direction")
                            Text("Speed")
                        }
                        .font(.headline)
                        Divider()
                        GridRow {
                            Text("In")
                            Text(TrafficStatistics.speed(statistics.receiveRate))
                        }
                        GridRow {
                            Text("Out")
                            Text(TrafficStatistics.speed(statistics.sendRate))
                        }
                    }
                    .monospacedDigit()
                }
                Section {
                    LabeledContent("Total In", value: TrafficStatistics.capacity(Double(statistics.received)))
                    LabeledContent("Total Out", value: TrafficStatistics.capacity(Double(statistics.sent)))
                    LabeledContent("Total", value: TrafficStatistics.capacity(
                        Double(statistics.received) + Double(statistics.sent)))
                        .fontWeight(.semibold)
                } header: {
                    Text("Transferred")
                } footer: {
                    Text("Since app launch; stopping the server does not reset totals. In: external network to this app. Out: this app to the external network. TCP and UDP payload only.")
                }
                .monospacedDigit()
                Section {
                    if clientRows.isEmpty {
                        Text("No client payload recorded yet.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(clientRows) { client in
                        DisclosureGroup(client.address) {
                            LabeledContent("In speed", value: TrafficStatistics.speed(client.traffic.receiveRate))
                            LabeledContent("Out speed", value: TrafficStatistics.speed(client.traffic.sendRate))
                            LabeledContent("Total In", value: TrafficStatistics.capacity(Double(client.traffic.received)))
                            LabeledContent("Total Out", value: TrafficStatistics.capacity(Double(client.traffic.sent)))
                            LabeledContent("Total", value: TrafficStatistics.capacity(
                                Double(client.traffic.received) + Double(client.traffic.sent)))
                        }
                        .accessibilityIdentifier("client-\(client.id)")
                    }
                    if clientsIncomplete {
                        Text("New clients will be included in the next sample.")
                            .font(.footnote)
                    }
                } header: {
                    Text("Clients by IP")
                } footer: {
                    Text("Observed SOCKS control-peer IP, not a device identity. TCP and UDP are combined per IP; ports are ignored. Unattributed preserves bytes when IP lookup or registration fails. Totals and client rows are independent live reads and may briefly differ.")
                }
                .monospacedDigit()
                Section {
                    Text("Speed uses the last sampling interval (about 1 second). KB/MB/GB use 1,000-based bytes; Kbps/Mbps/Gbps use bits per second. Sampling pauses when this tab is hidden or the app is inactive; native totals keep accumulating while the server runs.")
                        .font(.footnote)
                }
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
