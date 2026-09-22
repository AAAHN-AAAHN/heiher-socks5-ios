import SwiftUI
import HevSocks5Server

@MainActor
struct TrafficStatisticsView: View {
    let isVisible: Bool
    @Environment(\.scenePhase) private var scenePhase
    @State private var statistics = TrafficStatistics()

    var body: some View {
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
                    Text("Speed uses the last sampling interval (about 1 second). KB/MB/GB use 1,000-based bytes; Kbps/Mbps/Gbps use bits per second. Sampling pauses when this tab is hidden or the app is inactive; native totals keep accumulating while the server runs.")
                        .font(.footnote)
                }
            }
            .navigationTitle("Statistics")
        }
        .task(id: isVisible && scenePhase == .active) {
            guard isVisible && scenePhase == .active else { return }
            statistics = TrafficStatistics()
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
        statistics.sample(received: received, sent: sent,
                          at: ProcessInfo.processInfo.systemUptime)
    }
}
