import AVFAudio
import SwiftUI

/// Holds the experiments for the app lifetime, independently of the server UI.
@MainActor
struct BackgroundKeepAliveRoot: View {
    @StateObject private var keepAlive = BackgroundKeepAlive()

    var body: some View {
        TabView {
            ScrollView { ContentView() }
                .tabItem { Label("Server", systemImage: "network") }
            NavigationStack {
                Form {
                    Section {
                        locationToggle("1. Continuous location", mode: .continuous)
                        locationToggle("2. Keep open, read every 5 s", mode: .held)
                        locationToggle("3. Read, close, wait 5 s", mode: .cycled)
                    } header: {
                        Text("Location experiments")
                    } footer: {
                        Text("Select one location mode. Mode 2 limits consumption, not GPS updates. Mode 3 stops the service between reads; iOS may suspend the app before the next read.")
                    }
                    Section("Location state") {
                        Text(keepAlive.locationState)
                        LabeledContent("Reads", value: String(keepAlive.readCount))
                        if let date = keepAlive.lastRead {
                            LabeledContent("Last read") { Text(date, style: .time) }
                        }
                        Text("Choose Always in iOS location settings for restart experiments. Coordinates are not saved or transmitted.")
                            .font(.footnote)
                    }
                    Section {
                        Toggle("4. Loop silent WAV", isOn: Binding(
                            get: { keepAlive.audioEnabled }, set: { keepAlive.setAudio($0) }))
                        Text(keepAlive.audioState).font(.footnote)
                    } header: {
                        Text("Audio experiment")
                    } footer: {
                        Text("Independent of location. Mixes with other audio. iOS interruptions and termination can still stop playback.")
                    }
                    Section {
                        Text("All options start off. They stay on until you turn them off or quit the app, even after stopping the SOCKS5 server.")
                            .font(.footnote)
                    }
                }
                .navigationTitle("Background")
            }
            .tabItem { Label("Background", systemImage: "switch.2") }
        }
        .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)
            .receive(on: RunLoop.main)) { keepAlive.audioInterruption($0) }
        .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.mediaServicesWereResetNotification)
            .receive(on: RunLoop.main)) { _ in keepAlive.audioServicesReset() }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
            .receive(on: RunLoop.main)) { _ in keepAlive.becameActive() }
    }

    private func locationToggle(_ title: String, mode: BackgroundKeepAlive.LocationMode) -> some View {
        Toggle(title, isOn: Binding(
            get: { keepAlive.locationMode == mode },
            set: { keepAlive.selectLocation($0 ? mode : .off) }))
    }
}
