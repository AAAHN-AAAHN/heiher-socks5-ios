import SwiftUI

@MainActor
struct AppRoot: View {
    @State private var selectedTab = "server"
    @StateObject private var keepAlive = BackgroundKeepAlive()
    @StateObject private var udpEcho = PeriodicUDPEchoModel()
    @AppStorage("background.continuousLocation") private var locationEnabled = false
    @AppStorage("background.silentAudio") private var audioEnabled = false

    var body: some View {
        TabView(selection: $selectedTab) {
            ScrollView {
                ContentView { id, credentials, preferIPv4 in
                    guard let id else {
                        udpEcho.setServer(nil, runID: nil)
                        return
                    }
                    udpEcho.setServer(resolve: {
                        guard let endpoint = Socks5ServerEndpoint.resolve(preferIPv4: preferIPv4) else { return nil }
                        return .init(server: endpoint, credentials: credentials)
                    }, runID: id)
                }
            }
                .tabItem { Label("Server", systemImage: "network") }
                .tag("server")
            BackgroundKeepAliveView(keepAlive: keepAlive, udpEcho: udpEcho,
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
