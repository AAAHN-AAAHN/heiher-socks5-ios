import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Test-only command adapter; store, model, controller and Hev are production code.
@main struct NativePersistenceHost {
    struct Command: Decodable {
        let id: Int
        let operation: String
        var settings: ServerSettings?
        var running: Bool?
        var password: String?
        var path: String?
        var payload: String?
    }
    @MainActor static func main() async throws {
        guard let path = ProcessInfo.processInfo.environment["PERSISTENCE_TEST_FILE"] else {
            fatalError("Missing isolated test path")
        }
        let suite = "NativePersistence.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer { legacy.removePersistentDomain(forName: suite) }
        let settings = SettingsStore(fileURL: URL(fileURLWithPath: path), legacy: legacy)
        let server = ServerController()
        // Match root initial application; this is not a SwiftUI rendering test.
        server.apply(settings.value.server, running: settings.value.serverRunning)
        while let line = await Task.detached(operation: { readLine() }).value {
            let command = try JSONDecoder().decode(Command.self, from: Data(line.utf8))
            let before = settings.value
            var error = ""
            do {
                switch command.operation {
                case "apply":
                    guard let value = command.settings, let running = command.running else {
                        fatalError("Missing server inputs")
                    }
                    settings.set(\.server, value)
                    settings.set(\.serverRunning, running)
                    server.apply(settings.value.server, running: running, retry: running)
                case "set-password":
                    guard let password = command.password else { fatalError("Missing password") }
                    settings.binding(\.server.authPassword).wrappedValue = password
                case "import-file":
                    guard let path = command.path else { fatalError("Missing import URL") }
                    try await settings.importFile(URL(fileURLWithPath: path))
                case "import-data":
                    guard let payload = command.payload else { fatalError("Missing import data") }
                    try settings.importData(Data(payload.utf8))
                case "state": break
                case "exit":
                    // End this test process without changing durable running intent.
                    server.apply(settings.value.server, running: false)
                    for _ in 0..<1000 {
                        if !server.isRunning { break }
                        try await Task.sleep(for: .milliseconds(2))
                    }
                    guard !server.isRunning else { fatalError("Test engine failed to stop") }
                default: fatalError("Unknown test operation")
                }
            } catch let failure { error = failure.localizedDescription }
            if command.operation != "exit", before != settings.value {
                server.apply(settings.value.server, running: settings.value.serverRunning)
            }
            let reply: [String: Any] = ["id": command.id, "running": server.isRunning,
                "status": server.status, "savedRunning": settings.value.serverRunning,
                "storageError": settings.errorMessage ?? "", "operationError": error,
                "passwordBytes": Array(settings.value.server.authPassword.utf8)]
            let data = try JSONSerialization.data(withJSONObject: reply, options: .sortedKeys)
            print("SERVER_CONTROL_RESULT " + String(decoding: data, as: UTF8.self))
            fflush(stdout)
            if command.operation == "exit" { return }
        }
        fatalError("Unexpected test input EOF; clients must close through exit")
    }
}
