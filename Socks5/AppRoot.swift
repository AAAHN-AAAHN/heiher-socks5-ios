import SwiftUI

@MainActor
struct AppRoot: View {
    @State private var selectedTab = "server"
    @StateObject private var keepAlive = BackgroundKeepAlive()
    @AppStorage("background.continuousLocation") private var locationEnabled = false
    @AppStorage("background.silentAudio") private var audioEnabled = false

    var body: some View {
        TabView(selection: $selectedTab) {
            ScrollView { ContentView() }
                .tabItem { Label("Server", systemImage: "network") }
                .tag("server")
            BackgroundKeepAliveView(keepAlive: keepAlive,
                                    locationEnabled: $locationEnabled,
                                    audioEnabled: $audioEnabled)
                .tabItem { Label("Background", systemImage: "switch.2") }
                .tag("background")
        }
        .onChange(of: locationEnabled, initial: true) { _, value in keepAlive.setLocation(value) }
        .onChange(of: audioEnabled, initial: true) { _, value in keepAlive.setAudio(value) }
        .modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))
    }
}
