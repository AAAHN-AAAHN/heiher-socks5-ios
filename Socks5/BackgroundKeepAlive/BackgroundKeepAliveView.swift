import AVFAudio
import Combine
import SwiftUI

/// Holds background services for the app lifetime, independently of the server UI.
@MainActor
struct BackgroundKeepAliveRoot: View {
    @StateObject private var keepAlive = BackgroundKeepAlive()
    @StateObject private var settings = SettingsStore()
    @StateObject private var server = ServerController()

    private let audioEvents = Publishers.MergeMany([
        AVAudioSession.interruptionNotification,
        AVAudioSession.routeChangeNotification,
        AVAudioSession.mediaServicesWereLostNotification,
        AVAudioSession.mediaServicesWereResetNotification
    ].map { NotificationCenter.default.publisher(for: $0) })
        .receive(on: RunLoop.main)

    var body: some View {
        TabView(selection: settings.binding(\.selectedTab)) {
            TrafficStatisticsView(isVisible: settings.value.selectedTab == .statistics)
                .tabItem { Label("Statistics", systemImage: "chart.bar") }
                .tag(AppSettings.Tab.statistics)
            ScrollView { ContentView() }
                .tabItem { Label("Server", systemImage: "network") }
                .tag(AppSettings.Tab.server)
            NavigationStack {
                Form {
                    Section {
                        Toggle("Continuous location", isOn: settings.binding(\.background.continuousLocation))
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
                        Toggle("Loop silent WAV", isOn: settings.binding(\.background.silentAudio))
                        Text(keepAlive.audioState).font(.footnote)
                    } header: {
                        Text("Audio")
                    } footer: {
                        Text("Checks playback every 2 seconds. Interruptions trigger immediate recovery; failures retry every second while On. Mixes with other audio.")
                    }
                    Section {
                        Text("All settings are saved automatically. Use Settings to import or export JSON. Background services are independent of Server Start/Stop. Recovery runs only while iOS allows the app to execute.")
                            .font(.footnote)
                    }
                }
                .navigationTitle("Background")
            }
            .tabItem { Label("Background", systemImage: "switch.2") }
            .tag(AppSettings.Tab.background)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .environmentObject(settings)
        .environmentObject(server)
        .onChange(of: settings.value, initial: true) { _, value in
            if keepAlive.locationEnabled != value.background.continuousLocation {
                keepAlive.setLocation(value.background.continuousLocation)
            }
            if keepAlive.audioEnabled != value.background.silentAudio {
                keepAlive.setAudio(value.background.silentAudio)
            }
            server.apply(value)
        }
        .onReceive(audioEvents) { keepAlive.audioEvent($0) }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
            .receive(on: RunLoop.main)) { _ in keepAlive.restore(); server.apply(settings.value) }
    }
}
