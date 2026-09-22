import SwiftUI

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
            ScrollView { ContentView() }
                .tabItem { Label("Server", systemImage: "network") }
                .tag(AppSettings.Tab.server)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .environmentObject(settings)
        .environmentObject(server)
        .onChange(of: settings.value, initial: true) { _, value in
            server.apply(value)
        }
    }
}
