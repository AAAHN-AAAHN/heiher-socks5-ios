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
                                guard settings.acceptsNewIntent else {
                                    settings.set(\.serverRunning, true)
                                    return
                                }
                                let previous = settings.serverRunningChange
                                // A pre-load Start is retained, then applied with
                                // the saved configuration once its read completes.
                                if settings.loadState == .ready {
                                    server.apply(settings.value.server, running: true, retry: true)
                                }
                                if settings.serverRunningChange == previous { settings.set(\.serverRunning, true) }
                            }, stop: {
                                let previous = settings.serverRunningChange
                                server.apply(settings.value.server, running: false)
                                if settings.serverRunningChange == previous { settings.set(\.serverRunning, false) }
                            }, stopEnabled: server.isRunning || settings.value.serverRunning,
                            errorMessage: settings.errorMessage)
            }
                .tabItem { Label("Server", systemImage: "network") }
                .tag(AppSettings.Tab.server)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .onChange(of: settings.change, initial: true) { _, _ in restoreServices() }
        .onChange(of: settings.loadState) { _, _ in restoreServices() }
    }
}
