import SwiftUI

/// Persistence is connected here; the reusable server form/controller stay storage-free.
@MainActor
struct AppRoot: View {
    @StateObject private var settings = SettingsStore()
    @StateObject private var server = ServerController()

    private var selectedTab: Binding<AppSettings.Tab> {
        Binding(get: { settings.value.selectedTab == .settings ? .settings : .server },
                set: { settings.set(\.selectedTab, $0) })
    }

    var body: some View {
        TabView(selection: selectedTab) {
            ScrollView {
                VStack {
                    ContentView(configuration: settings.binding(\.server), server: server,
                                desiredRunning: settings.value.serverRunning,
                                setRunning: { settings.set(\.serverRunning, $0) })
                    if let error = settings.errorMessage { Text(error).font(.footnote).padding() }
                }
            }
            .tabItem { Label("Server", systemImage: "network") }
            .tag(AppSettings.Tab.server)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .onChange(of: settings.value, initial: true) { _, value in
            server.apply(value.server, running: value.serverRunning)
        }
    }
}
