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
                        .textCase(nil)
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
                    Text("Columns: In / Out / Sum. Rows: Speed / Transferred. Sum combines the unrounded In and Out values. Each displayed value is rounded to three decimal places. Clients follow IP registration order; Unattributed appears first when needed.")
                    Text("Since app launch; stopping the server does not reset totals. In: external network to this app. Out: this app to the external network. TCP and UDP payload only.")
                    Text("Observed SOCKS control-peer IP, not a device identity. Ports are ignored. Unattributed preserves bytes when IP lookup or registration fails. Totals and client rows are independent live reads and may briefly differ.")
                    Text("Speed uses the last sampling interval (about 1 second). KB/MB/GB/TB/PB use 1,000-based bytes; Kbps/Mbps/Gbps/Tbps/Pbps use bits per second. Sampling pauses when this tab is hidden or the app is inactive; native totals keep accumulating while the server runs.")
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

    /// One shared table for the aggregate and every registered client.
    private func summary(_ statistics: TrafficStatistics, id: String) -> some View {
        Grid(alignment: .leading, horizontalSpacing: 0, verticalSpacing: 0) {
            GridRow {
                rowLabel(" ").accessibilityHidden(true)
                tableCell("In", id: "\(id)-column-in", bold: true)
                tableCell("Out", id: "\(id)-column-out", bold: true)
                tableCell("Sum", id: "\(id)-column-sum", bold: true)
            }
            Color(white: 0.82)
                .frame(height: 1)
                .gridCellUnsizedAxes(.horizontal)
                .accessibilityHidden(true)
            GridRow {
                rowLabel("Speed")
                tableCell(TrafficStatistics.speed(statistics.receiveRate), id: "\(id)-speed-in")
                tableCell(TrafficStatistics.speed(statistics.sendRate), id: "\(id)-speed-out")
                tableCell(TrafficStatistics.speed(statistics.sumRate), id: "\(id)-speed-sum")
            }
            GridRow {
                rowLabel("Transferred")
                tableCell(TrafficStatistics.capacity(Double(statistics.received)), id: "\(id)-usage-in")
                tableCell(TrafficStatistics.capacity(Double(statistics.sent)), id: "\(id)-usage-out")
                tableCell(TrafficStatistics.capacity(
                    Double(statistics.received) + Double(statistics.sent)), id: "\(id)-usage-sum")
            }
        }
        .font(.caption)
        .foregroundStyle(.black)
        .background(.white)
        .listRowBackground(Color.white)
        .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 12))
    }

    private func rowLabel(_ text: String) -> some View {
        Text(text)
            .fontWeight(.bold)
            .fixedSize(horizontal: true, vertical: false)
            .padding(.vertical, 12)
            .padding(.trailing, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(alignment: .trailing) {
                Color(white: 0.82).frame(width: 1)
            }
    }

    private func tableCell(_ text: String, id: String, bold: Bool = false) -> some View {
        Text(text)
            .fontWeight(bold ? .bold : .regular)
            .monospacedDigit()
            .lineLimit(1)
            .minimumScaleFactor(0.5)
            .padding(.vertical, 12)
            .padding(.horizontal, 4)
            .frame(maxWidth: .infinity, alignment: .center)
            .accessibilityIdentifier(id)
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
        // Build one value snapshot before publishing; per-row State writes can
        // repeatedly copy the dictionary and invalidate the same view state.
        var sampledClients = clients
        for var row in rows.prefix(min(capacity, required)) {
            let address = withUnsafePointer(to: &row.address) {
                $0.withMemoryRebound(to: CChar.self, capacity: 64) { String(cString: $0) }
            }
            sampledClients.sample(id: row.id, address: address, received: row.received,
                                 sent: row.sent, at: time)
        }
        clients = sampledClients
    }
}
