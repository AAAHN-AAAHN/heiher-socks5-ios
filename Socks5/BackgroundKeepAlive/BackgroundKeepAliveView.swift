import AVFAudio
import Combine
import SwiftUI

@MainActor
struct BackgroundKeepAliveView: View {
    @ObservedObject var keepAlive: BackgroundKeepAlive
    @Binding var locationEnabled: Bool
    @Binding var audioEnabled: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Loop silent WAV", isOn: $audioEnabled)
                    Text(keepAlive.audioState).font(.footnote)
                        .accessibilityIdentifier("background.audioState")
                    if !keepAlive.audioDetail.isEmpty {
                        Text(keepAlive.audioDetail).font(.footnote)
                            .accessibilityIdentifier("background.audioDetail")
                    }
                } header: {
                    Text("Audio")
                } footer: {
                    Text("Checks playback and retries every 0.5 seconds. Uses finite execution protection during recovery; an unfinished system call is never treated as cancelled. Mixes with other audio.")
                }
                Section {
                    Toggle("Continuous location", isOn: $locationEnabled)
                } header: {
                    Text("Location")
                } footer: {
                    Text("Keeps a standard location session open with approximate accuracy. Updates are scheduled by iOS; coordinates are discarded.")
                }
                Section("Location state") {
                    Text(keepAlive.locationState)
                    LabeledContent("Reads", value: String(keepAlive.readCount))
                    if let date = keepAlive.lastRead {
                        LabeledContent("Last read") { Text(date, format: .dateTime.hour().minute().second()) }
                    }
                    Text("Allow location access in Settings. Precise Location is not required.")
                        .font(.footnote)
                }
                Section {
                    Text("Background services are independent of Server Start/Stop. Recovery runs only while iOS allows the app to execute.")
                        .font(.footnote)
                }
            }
            .navigationTitle("Background")
        }
    }
}

/// Root-only location/foreground restoration. Process-level audio notifications
/// are coalesced by the service on the posting thread, not queued through the UI.
@MainActor
struct BackgroundKeepAliveEvents: ViewModifier {
    let keepAlive: BackgroundKeepAlive
    func body(content: Content) -> some View {
        content
            .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
                .receive(on: RunLoop.main)) { _ in keepAlive.restore() }
    }
}
