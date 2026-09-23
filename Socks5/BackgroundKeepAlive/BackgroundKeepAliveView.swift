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
                } header: {
                    Text("Audio")
                } footer: {
                    Text("Checks playback every second. Interruption and stop signals trigger immediate recovery; repeated failures retry every second while On. Mixes with other audio.")
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
                        LabeledContent("Last read") { Text(date, style: .time) }
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

/// Attach once to the app root, not to a tab that may be removed from the view tree.
@MainActor
struct BackgroundKeepAliveEvents: ViewModifier {
    let keepAlive: BackgroundKeepAlive
    private let audioEvents = Publishers.MergeMany(
        BackgroundKeepAlive.audioNotifications.map { NotificationCenter.default.publisher(for: $0) }
    ).receive(on: RunLoop.main)

    func body(content: Content) -> some View {
        content
            .onReceive(audioEvents) { keepAlive.audioEvent($0) }
            .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
                .receive(on: RunLoop.main)) { _ in keepAlive.restore() }
    }
}
