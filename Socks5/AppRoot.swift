import SwiftUI

@MainActor
struct AppRoot: View {
    @StateObject private var settings = SettingsStore()
    @StateObject private var server = ServerController()
    @StateObject private var keepAlive = BackgroundKeepAlive()

    var body: some View {
        TabView(selection: settings.binding(\.selectedTab)) {
            TrafficStatisticsView(isVisible: settings.value.selectedTab == .statistics)
                .tabItem { Label("Statistics", systemImage: "chart.bar") }
                .tag(AppSettings.Tab.statistics)
            ScrollView {
                ContentView(configuration: settings.binding(\.server), server: server,
                            start: {
                                settings.set(\.serverRunning, true)
                                server.apply(settings.value.server, running: true, retry: true)
                            }, stop: {
                                settings.set(\.serverRunning, false)
                                server.apply(settings.value.server, running: false)
                            }, stopEnabled: server.isRunning || settings.value.serverRunning,
                            errorMessage: settings.errorMessage)
            }
                .tabItem { Label("Server", systemImage: "network") }
                .tag(AppSettings.Tab.server)
            BackgroundKeepAliveView(keepAlive: keepAlive,
                                    locationEnabled: settings.binding(\.background.continuousLocation),
                                    audioEnabled: settings.binding(\.background.silentAudio))
                .tabItem { Label("Background", systemImage: "switch.2") }
                .tag(AppSettings.Tab.background)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .onChange(of: settings.value, initial: true) { _, value in
            if keepAlive.locationEnabled != value.background.continuousLocation {
                keepAlive.setLocation(value.background.continuousLocation)
            }
            if keepAlive.audioEnabled != value.background.silentAudio {
                keepAlive.setAudio(value.background.silentAudio)
            }
            server.apply(value.server, running: value.serverRunning)
        }
        .modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))
    }
}
