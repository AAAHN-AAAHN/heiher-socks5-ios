import SwiftUI

@MainActor
struct AppRoot: View {
    @StateObject private var settings = SettingsStore()
    @StateObject private var server = ServerController()
    @StateObject private var keepAlive = BackgroundKeepAlive()
    @StateObject private var ping = PeriodicPingModel()
    @State private var appliedSettingsChange: SettingsStore.Change?

    private var audioEnabled: Binding<Bool> {
        Binding(get: { self.settings.value.background.silentAudio }, set: { enabled in self.applyAudioIntent(enabled) })
    }

    private var locationEnabled: Binding<Bool> {
        Binding(get: { self.settings.value.background.continuousLocation }, set: { enabled in self.applyLocationIntent(enabled) })
    }

    private func applyLocationIntent(_ enabled: Bool) {
        if !enabled {
            let previous = settings.locationChange
            keepAlive.setLocation(false)
            guard settings.locationChange == previous else { return }
        }
        // On retains the existing loaded-settings and location authorization path.
        settings.set(\.background.continuousLocation, enabled)
    }

    private func applyAudioIntent(_ enabled: Bool) {
        guard !enabled || settings.acceptsNewIntent else {
            settings.set(\.background.silentAudio, enabled, origin: .user)
            return
        }
        let previous = settings.audioChange
        // Every explicit choice reaches the service before persistence, including
        // an unchanged Off or On. Publication may synchronously accept a newer input.
        keepAlive.setAudio(enabled)
        guard settings.audioChange == previous else { return }
        settings.set(\.background.silentAudio, enabled, origin: .user)
    }

    private func startServer() {
        guard settings.acceptsNewIntent else {
            settings.set(\.serverRunning, true)
            return
        }
        let previous = settings.serverRunningChange
        // A Start during initial loading is retained as intent, then applied with
        // the loaded configuration rather than the temporary default fields.
        if settings.loadState == .ready {
            server.apply(settings.value.server, running: true, retry: true)
        }
        guard settings.serverRunningChange == previous else { return }
        settings.set(\.serverRunning, true)
    }

    private func stopServer() {
        let previous = settings.serverRunningChange
        server.apply(settings.value.server, running: false)
        guard settings.serverRunningChange == previous else { return }
        settings.set(\.serverRunning, false)
    }

    private func restoreServices() {
        guard settings.loadState == .ready else { return }
        let change = settings.change
        guard appliedSettingsChange != change else { return }
        let value = settings.value
        // Compare the whole change: a load and its queued import can share an
        // intent revision while having distinct origins. A user change here is
        // its persistence echo; load/import restoration is also non-explicit.
        appliedSettingsChange = change
        if keepAlive.locationEnabled != value.background.continuousLocation {
            keepAlive.setLocation(value.background.continuousLocation)
        }
        guard settings.loadState == .ready, settings.change == change else { return }
        keepAlive.syncAudio(value.background.silentAudio)
        guard settings.loadState == .ready, settings.change == change else { return }
        server.apply(value.server, running: value.serverRunning)
    }

    var body: some View {
        TabView(selection: settings.binding(\.selectedTab)) {
            TrafficStatisticsView(isVisible: settings.value.selectedTab == .statistics)
                .tabItem { Label("Statistics", systemImage: "chart.bar") }
                .tag(AppSettings.Tab.statistics)
            ScrollView {
                ContentView(configuration: settings.binding(\.server), server: server,
                            start: startServer, stop: stopServer,
                            stopEnabled: server.isRunning || settings.value.serverRunning,
                            errorMessage: settings.errorMessage)
            }
                .tabItem { Label("Server", systemImage: "network") }
                .tag(AppSettings.Tab.server)
            BackgroundKeepAliveView(keepAlive: keepAlive, ping: ping,
                                    locationEnabled: locationEnabled,
                                    audioEnabled: audioEnabled)
                .tabItem { Label("Background", systemImage: "switch.2") }
                .tag(AppSettings.Tab.background)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .onChange(of: settings.change, initial: true) { _, _ in restoreServices() }
        .onChange(of: settings.loadState) { _, _ in restoreServices() }
        .modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))
    }
}
