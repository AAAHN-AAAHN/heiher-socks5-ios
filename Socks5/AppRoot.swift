import SwiftUI

@MainActor
struct AppRoot: View {
    @State private var selectedTab = "server"
    @StateObject private var keepAlive = BackgroundKeepAlive()
    @StateObject private var ping = PeriodicPingModel()
    @AppStorage("background.continuousLocation") private var locationEnabled = false
    @AppStorage("background.silentAudio") private var audioEnabled = false

    var body: some View {
        TabView(selection: $selectedTab) {
            ScrollView { ContentView() }
                .tabItem { Label("Server", systemImage: "network") }
                .tag("server")
            BackgroundKeepAliveView(keepAlive: keepAlive, ping: ping,
                                    locationEnabled: $locationEnabled,
                                    audioEnabled: Binding(get: { audioEnabled }, set: { value in
                                        keepAlive.setAudio(value)
                                        // Publication may accept a newer intent synchronously.
                                        audioEnabled = keepAlive.audioEnabled
                                    }))
                .tabItem { Label("Background", systemImage: "switch.2") }
                .tag("background")
        }
        .onChange(of: locationEnabled, initial: true) { _, value in keepAlive.setLocation(value) }
        .onChange(of: audioEnabled, initial: true) { _, value in keepAlive.syncAudio(value) }
        .modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))
    }
}
