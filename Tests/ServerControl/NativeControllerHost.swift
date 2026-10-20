import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Test transport only. The production controller calls the real linked engine.
@main struct NativeControllerHost {
    struct Command: Decodable {
        let id: Int
        let operation: String
        var settings: ServerSettings?
        var running: Bool?
        var retry: Bool?
    }

    @MainActor static func main() async throws {
        let server = ServerController()
        while let line = await Task.detached(operation: { readLine() }).value {
            let command = try JSONDecoder().decode(Command.self, from: Data(line.utf8))
            switch command.operation {
            case "apply":
                guard let options = command.settings, let running = command.running else {
                    fatalError("Incomplete test command")
                }
                server.apply(options, running: running, retry: command.retry ?? false)
            case "state": break
            case "exit":
                server.apply(ServerSettings(), running: false)
                for _ in 0..<1000 {
                    if !server.isRunning { break }
                    try await Task.sleep(for: .milliseconds(2))
                }
                guard !server.isRunning else { fatalError("Test engine failed to stop") }
            default: fatalError("Unknown test command")
            }
            let reply: [String: Any] = ["id": command.id, "running": server.isRunning,
                                        "status": server.status]
            let data = try JSONSerialization.data(withJSONObject: reply, options: .sortedKeys)
            print("SERVER_CONTROL_RESULT " + String(decoding: data, as: UTF8.self))
            fflush(stdout)
            if command.operation == "exit" { return }
        }
        // EOF is not normally used by these checks, but must not orphan the engine.
        server.apply(ServerSettings(), running: false)
        for _ in 0..<1000 {
            if !server.isRunning { return }
            try await Task.sleep(for: .milliseconds(2))
        }
        fatalError("Test engine remained active at EOF")
    }
}
