import SwiftUI

@MainActor
struct AppRoot: View {
    @StateObject private var settings = SettingsStore()
    @StateObject private var server = ServerController()

    private var selectedTab: Binding<AppSettings.Tab> {
        Binding(get: { settings.value.selectedTab == .settings ? .settings : .server },
                set: { settings.set(\.selectedTab, $0) })
    }

    private func restoreServices() {
        guard settings.loadState == .ready else { return }
        server.apply(settings.value.server, running: settings.value.serverRunning)
    }

    var body: some View {
        TabView(selection: selectedTab) {
            ScrollView {
                ContentView(configuration: settings.binding(\.server), server: server,
                            start: {
                                server.apply(settings.value.server, running: true, retry: true)
                                settings.set(\.serverRunning, true)
                            }, stop: {
                                server.apply(settings.value.server, running: false)
                                settings.set(\.serverRunning, false)
                            }, stopEnabled: server.isRunning || settings.value.serverRunning,
                            errorMessage: settings.errorMessage)
            }
                .tabItem { Label("Server", systemImage: "network") }
                .tag(AppSettings.Tab.server)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .onChange(of: settings.value, initial: true) { _, _ in restoreServices() }
        .onChange(of: settings.loadState) { _, _ in restoreServices() }
    }
}
