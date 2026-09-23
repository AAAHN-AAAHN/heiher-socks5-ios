import SwiftUI

/// A complete server-only app: settings are intentionally held in memory.
@MainActor
struct AppRoot: View {
    @State private var configuration = ServerSettings()
    @State private var running = false
    @StateObject private var server = ServerController()

    var body: some View {
        ScrollView {
            ContentView(configuration: $configuration, server: server,
                        desiredRunning: running, setRunning: { running = $0 })
        }
        .onChange(of: configuration) { _, value in
            server.apply(value, running: running)
        }
        .onChange(of: running, initial: true) { _, value in
            server.apply(configuration, running: value)
        }
    }
}
