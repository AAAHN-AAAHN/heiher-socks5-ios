import AVFAudio
import Combine
import SwiftUI

/// Holds background services for the app lifetime, independently of the server UI.
@MainActor
struct BackgroundKeepAliveRoot: View {
    @StateObject private var keepAlive = BackgroundKeepAlive()
    @State private var selectedTab = 0

    private let audioEvents = Publishers.MergeMany([
        AVAudioSession.interruptionNotification,
        AVAudioSession.routeChangeNotification,
        AVAudioSession.mediaServicesWereLostNotification,
        AVAudioSession.mediaServicesWereResetNotification
    ].map { NotificationCenter.default.publisher(for: $0) })
        .receive(on: RunLoop.main)

    var body: some View {
        TabView(selection: $selectedTab) {
            ScrollView { ContentView() }
                .tabItem { Label("Server", systemImage: "network") }
                .tag(0)
            TrafficStatisticsView(isVisible: selectedTab == 1)
                .tabItem { Label("Statistics", systemImage: "chart.bar") }
                .tag(1)
            NavigationStack {
                Form {
                    Section {
                        Toggle("Continuous location", isOn: Binding(
                            get: { keepAlive.locationEnabled }, set: { keepAlive.setLocation($0) }))
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
                        Toggle("Loop silent WAV", isOn: Binding(
                            get: { keepAlive.audioEnabled }, set: { keepAlive.setAudio($0) }))
                        Text(keepAlive.audioState).font(.footnote)
                    } header: {
                        Text("Audio")
                    } footer: {
                        Text("Loops digital silence and mixes with other audio. Automatically attempts recovery after interruptions; the switch stays on while waiting for iOS.")
                    }
                    Section {
                        Text("Settings are saved and restored when this app opens. Background services are independent of Server Start/Stop. iOS may suspend or terminate the app; recovery runs only while the app can execute.")
                            .font(.footnote)
                    }
                }
                .navigationTitle("Background")
            }
            .tabItem { Label("Background", systemImage: "switch.2") }
            .tag(2)
        }
        .task { keepAlive.restore() }
        .onReceive(audioEvents) { keepAlive.audioEvent($0) }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
            .receive(on: RunLoop.main)) { _ in keepAlive.restore() }
    }
}
