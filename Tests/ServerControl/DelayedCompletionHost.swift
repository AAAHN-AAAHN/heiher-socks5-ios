import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

// Test only: delay delivery of a completed native call to its owning actor.
@main struct LateCompletion {
    @MainActor static func main() async throws {
        let controller = ServerController()
        var bad = ServerSettings()
        bad.listenAddress = "127.0.0.1"
        bad.listenPort = CommandLine.arguments[1]
        bad.udpListenPort = "0"
        var good = bad
        good.listenPort = CommandLine.arguments[2]
        let mode = CommandLine.arguments.count > 3 ? Int(CommandLine.arguments[3])! : 0
        bad.workers = CommandLine.arguments.count > 4 ? CommandLine.arguments[4] : "4"
        good.workers = bad.workers
        controller.apply(bad, running: true)
        // The occupied-port native failure completes while its MainActor reply waits.
        usleep(300_000)
        print("Before pending completion:", controller.isRunning, controller.status)
        if mode == 1 || mode == 2 { controller.apply(bad, running: false) }
        if mode == 1 { try await Task.sleep(for: .milliseconds(100)) }
        controller.apply(good, running: true)
        if mode == 3 { controller.apply(good, running: false) }
        try await Task.sleep(for: .milliseconds(500))
        let observed = mode == 3 ? !controller.isRunning : controller.isRunning
        print("LATEST_DESIRED_RESULT", observed, controller.status)
        controller.apply(good, running: false)
        try await Task.sleep(for: .milliseconds(200))
        if !observed { exit(42) }
    }
}
