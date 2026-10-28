import SwiftUI

@MainActor
private final class DeferredSettings {
    lazy var value = SettingsStore()
}

@MainActor
struct AppRoot: View {
    @StateObject private var settings: SettingsStore
    @StateObject private var udpEcho: PeriodicUDPEchoModel
    @StateObject private var server = ServerController()
    @StateObject private var keepAlive = BackgroundKeepAlive()
    @State private var appliedSettingsChange: SettingsStore.Change?

    init() {
        let owner = DeferredSettings()
        _settings = StateObject(wrappedValue: owner.value)
        _udpEcho = StateObject(wrappedValue: PeriodicUDPEchoModel(store: nil, save: { value in
            let settings = owner.value
            if settings.acceptsNewIntent {
                settings.set(\.background.periodicUDPEcho, .init(
                    enabled: value.enabled, destinations: value.destinations, period: value.period))
            } else if !value.enabled {
                settings.set(\.background.periodicUDPEcho.enabled, false)
            }
        }, prepareObserver: {
            guard let writer = SocketIOWriter() else { return nil }
            return { address, bytes, sent in
                address.withSockAddr { writer.record($0, length: $1, bytes: bytes, sent: sent) }
            }
        }))
    }

    private func syncEchoServer() {
        guard let run = server.run else {
            udpEcho.setServer(nil, runID: nil)
            return
        }
        let credentials: Socks5UDPClient.Credentials? = run.settings.authUsername.isEmpty ? nil :
            .init(username: run.settings.authUsername, password: run.settings.authPassword)
        let preferIPv4 = Socks5UDPClient.Address(host: run.settings.udpListenAddress, port: 0)?.family == AF_INET
        udpEcho.setServer(resolve: {
            guard let endpoint = Socks5ServerEndpoint.resolve(preferIPv4: preferIPv4) else { return nil }
            return .init(server: endpoint, credentials: credentials)
        }, runID: run.id)
    }

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
        udpEcho.setServer(nil, runID: nil)
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
        let echo = value.background.periodicUDPEcho
        let restored = PeriodicUDPEchoSettings(enabled: echo.enabled, destinations: echo.destinations, period: echo.period)
        if udpEcho.settings != restored { udpEcho.restore(restored) }
        guard settings.loadState == .ready, settings.change == change else { return }
        server.apply(value.server, running: value.serverRunning)
        syncEchoServer()
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
            BackgroundKeepAliveView(keepAlive: keepAlive, udpEcho: udpEcho,
                                    locationEnabled: locationEnabled,
                                    audioEnabled: audioEnabled,
                                    acceptsNewIntent: settings.acceptsNewIntent)
                .tabItem { Label("Background", systemImage: "switch.2") }
                .tag(AppSettings.Tab.background)
            SettingsView(settings: settings)
                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }
                .tag(AppSettings.Tab.settings)
        }
        .onChange(of: settings.change, initial: true) { _, _ in restoreServices() }
        .onChange(of: settings.loadState) { _, _ in restoreServices() }
        .onReceive(server.objectWillChange) { syncEchoServer() }
        .modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))
    }
}
