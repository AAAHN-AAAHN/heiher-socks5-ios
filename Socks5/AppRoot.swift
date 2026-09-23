import SwiftUI

/// Standalone server control: options and intent are memory-only in this branch.
@MainActor
struct AppRoot: View {
    @State private var configuration = ServerSettings()
    @State private var requestedRunning = false
    @StateObject private var server = ServerController()

    var body: some View {
        ScrollView {
            ContentView(configuration: $configuration, server: server,
                        start: {
                            requestedRunning = true
                            server.apply(configuration, running: true, retry: true)
                        }, stop: {
                            requestedRunning = false
                            server.apply(configuration, running: false)
                        }, stopEnabled: server.isRunning || requestedRunning)
        }
        .onChange(of: configuration) { _, value in
            server.apply(value, running: requestedRunning)
        }
    }
}
