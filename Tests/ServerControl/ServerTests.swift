import Foundation

@main struct ServerTests {
    @MainActor static func main() async {
        let server = ServerController()
        var value = (server: ServerSettings(), serverRunning: false)
        server.apply(value.server, running: value.serverRunning)
        precondition(!server.isRunning && EngineProbe.snapshot().0 == 0)
        value.serverRunning = true
        server.apply(value.server, running: value.serverRunning)
        await waitUntil { EngineProbe.snapshot().0 == 1 }
        for _ in 0..<100 { server.apply(value.server, running: value.serverRunning) }
        precondition(EngineProbe.snapshot().0 == 1)
        print("PASS: saved Start restores once; tab/settings notifications do not duplicate the server")
        value.server.listenPort = "12345"
        server.apply(value.server, running: value.serverRunning)
        await waitUntil { EngineProbe.snapshot().0 == 2 && server.isRunning }
        precondition(EngineProbe.snapshot().2.last!.contains("port: 12345"))
        print("PASS: imported running configuration stops the old server before starting the new one")
        for _ in 0..<50 {
            value.serverRunning = false
            server.apply(value.server, running: value.serverRunning)
            value.serverRunning = true
            server.apply(value.server, running: value.serverRunning)
            await waitUntil { server.status == "Running" }
        }
        precondition(EngineProbe.snapshot().1 == 1)
        value.serverRunning = false
        server.apply(value.server, running: value.serverRunning)
        await waitUntil { !server.isRunning }
        print("PASS: rapid Stop/Start is serialized; only one engine runs")
        value.server.listenPort = "bad"
        value.serverRunning = true
        let previous = EngineProbe.snapshot().0
        server.apply(value.server, running: value.serverRunning)
        precondition(!server.isRunning && EngineProbe.snapshot().0 == previous)
        print("PASS: invalid saved startup configuration reports an error without running the engine")
        value.server.listenPort = "12345"
        EngineProbe.failNext(-1)
        server.apply(value.server, running: value.serverRunning)
        await waitUntil { !server.isRunning }
        let failedCount = EngineProbe.snapshot().0
        for _ in 0..<100 { server.apply(value.server, running: value.serverRunning) }
        precondition(EngineProbe.snapshot().0 == failedCount)
        print("PASS: tab and foreground notifications do not retry a failed configuration")
        server.apply(value.server, running: value.serverRunning, retry: true)
        await waitUntil { EngineProbe.snapshot().0 == failedCount + 1 }
        value.serverRunning = false
        server.apply(value.server, running: value.serverRunning)
        await waitUntil { !server.isRunning }
        value.serverRunning = true
        server.apply(value.server, running: value.serverRunning)
        await waitUntil { EngineProbe.snapshot().0 == failedCount + 2 }
        value.serverRunning = false
        server.apply(value.server, running: value.serverRunning)
        await waitUntil { !server.isRunning }
        print("PASS: explicit retry and a completed Stop/Start each start exactly once")
        value.serverRunning = true
        value.server.listenPort = "invalid"
        server.apply(value.server, running: value.serverRunning)
        value.serverRunning = false
        server.apply(value.server, running: value.serverRunning)
        precondition(server.status == "Stopped" && !server.isRunning)
        print("PASS: Stop clears a failed configuration status without launching")
    }

    @MainActor static func waitUntil(_ condition: () -> Bool) async {
        for _ in 0..<1000 {
            if condition() { return }
            try? await Task.sleep(for: .milliseconds(5))
        }
        preconditionFailure("Engine lifecycle timed out")
    }
}
