import Foundation
#if canImport(Combine)
import Combine
#endif

@main struct RunSnapshotTests {
    @MainActor static func main() async {
        let server = ServerController()
        var settings = ServerSettings()
        settings.authUsername = "first"
        settings.authPassword = "secret"
        var stoppedSynchronously = false
        var firstID: UUID?
        let onChange = {
            if !stoppedSynchronously, let run = server.run {
                precondition(server.isRunning && server.status == "Running")
                precondition(run.settings == settings)
                firstID = run.id
                stoppedSynchronously = true
                server.apply(settings, running: false)
                precondition(server.run == nil && server.status == "Stopping")
            }
        }
#if canImport(Combine)
        let observation = server.objectWillChange.sink { _ in onChange() }
        defer { observation.cancel() }
#else
        server.objectWillChange.receive = onChange
#endif
        server.apply(settings, running: true)
        precondition(stoppedSynchronously && server.run == nil)
        await settle { !server.isRunning }
        precondition(server.status == "Stopped")

        server.apply(settings, running: true)
        let before = server.run!
        precondition(before.id != firstID && before.settings == settings)
        settings.authPassword = "edited"
        precondition(server.run!.settings.authPassword == "secret")
        server.apply(settings, running: true)
        precondition(server.run == nil)
        await settle { server.run?.settings == settings }
        precondition(server.run!.id != before.id)
        server.apply(settings, running: false)
        precondition(server.run == nil)
        await settle { !server.isRunning }

        settings.listenPort = "invalid"
        server.apply(settings, running: true)
        precondition(server.run == nil && !server.isRunning)
        settings.listenPort = "1080"
        EngineProbe.failNext(-1)
        server.apply(settings, running: true)
        await settle { !server.isRunning }
        precondition(server.run == nil)
        print("PASS: actual run settings and identities; synchronous Off, reconfigure and failure invalidate snapshots")
    }

    @MainActor static func settle(_ condition: () -> Bool) async {
        for _ in 0..<1000 {
            if condition() { return }
            try? await Task.sleep(for: .milliseconds(5))
        }
        preconditionFailure("Run snapshot lifecycle timed out")
    }
}
