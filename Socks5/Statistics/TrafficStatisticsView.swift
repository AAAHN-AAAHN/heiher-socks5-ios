import SwiftUI
import HevSocks5Server

@MainActor
struct TrafficStatisticsView: View {
    let isVisible: Bool
    @Environment(\.scenePhase) private var scenePhase
    @ScaledMetric(relativeTo: .caption) private var labelColumnWidth: CGFloat = 40
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
                        .font(.body.weight(.bold))
                        .textCase(nil)
                        .accessibilityIdentifier("total-title")
                }
                ForEach(clientRows) { client in
                    Section {
                        summary(client.traffic, id: "client-\(client.id)")
                    } header: {
                        Text(client.address)
                            .font(.body.weight(.bold))
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
                    Text("Spd. (speed): average TCP/UDP payload transfer rate at this proxy's destination-side sockets over the last sample (about 1 second), in bits per second. This is observed traffic, not the network link's maximum speed.")
                        .accessibilityIdentifier("measurement-speed")
                    Text("Vol. (volume): cumulative TCP/UDP payload bytes read from or successfully written to destination-side sockets since this app process started. Server Stop/Start does not reset it; a new app process does.")
                        .accessibilityIdentifier("measurement-volume")
                    Text("In: payload read from destination sockets into this app. Out: payload successfully written by this app to destination sockets. Sum: In + Out before display rounding. SOCKS and transport headers, retransmissions and system-resolver traffic are excluded; these are not VPN, radio or billed data totals.")
                    Text("Total combines all clients. Each IP table contains traffic attributed to that observed SOCKS control-peer IP, not a device identity. IPs follow registration order; Unattributed appears first when needed. Independent live reads can briefly differ from the aggregate.")
                    Text("Values use three decimal places. KB/MB/GB/TB/PB are 1,000-based bytes; Kbps/Mbps/Gbps/Tbps/Pbps are bits per second. Visible sampling pauses while this tab is hidden or the app is inactive; native totals continue as traffic is processed.")
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
                rowLabel("Spd.")
                    .accessibilityIdentifier("\(id)-label-speed")
                tableCell(TrafficStatistics.speed(statistics.receiveRate), id: "\(id)-speed-in")
                tableCell(TrafficStatistics.speed(statistics.sendRate), id: "\(id)-speed-out")
                tableCell(TrafficStatistics.speed(statistics.sumRate), id: "\(id)-speed-sum")
            }
            GridRow {
                rowLabel("Vol.")
                    .accessibilityIdentifier("\(id)-label-volume")
                tableCell(TrafficStatistics.capacity(Double(statistics.received)), id: "\(id)-usage-in")
                tableCell(TrafficStatistics.capacity(Double(statistics.sent)), id: "\(id)-usage-out")
                tableCell(TrafficStatistics.capacity(
                    Double(statistics.received) + Double(statistics.sent)), id: "\(id)-usage-sum")
            }
        }
        .font(.callout)
        .foregroundStyle(.black)
        .background(.white)
        .listRowBackground(Color.white)
        .listRowInsets(EdgeInsets(top: 4, leading: 12, bottom: 4, trailing: 12))
    }

    private func rowLabel(_ text: String) -> some View {
        Text(text)
            .fontWeight(.bold)
            .fixedSize(horizontal: true, vertical: false)
            .padding(.vertical, 8)
            .padding(.trailing, 8)
            .frame(width: labelColumnWidth, alignment: .leading)
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
            .padding(.vertical, 8)
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
