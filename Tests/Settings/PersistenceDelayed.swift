import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

@main struct PersistenceDelayed {
    @MainActor static func main() async throws {
        let file = URL(fileURLWithPath: CommandLine.arguments[1])
        let legacy = UserDefaults(suiteName: "DelayedPersistence.\(getpid())")!
        let store = SettingsStore(fileURL: file, legacy: legacy)
        defer { legacy.removePersistentDomain(forName: "DelayedPersistence.\(getpid())") }
        let controller = ServerController()
        var bad = AppSettings()
        bad.server.listenAddress = "127.0.0.1"
        bad.server.workers = CommandLine.arguments[4]
        bad.server.listenPort = CommandLine.arguments[2]
        bad.server.udpListenPort = "0"
        bad.serverRunning = true
        try store.importData(bad.encoded())
        controller.apply(store.value.server, running: store.value.serverRunning)
        usleep(300_000)
        var good = bad
        good.server.listenPort = CommandLine.arguments[3]
        try store.importData(good.encoded())
        // Test adapter applies the production root contract; this is not SwiftUI rendering.
        controller.apply(store.value.server, running: store.value.serverRunning)
        try await Task.sleep(for: .milliseconds(500))
        let persisted = try AppSettings.decoded(Data(contentsOf: file))
        let correctStore = persisted == good && store.value == good
        let running = controller.isRunning
        print("PERSISTENCE_DELAYED_RESULT", correctStore, running, controller.status)
        controller.apply(good.server, running: false)
        try await Task.sleep(for: .milliseconds(200))
        if !correctStore || !running { exit(42) }
    }
}
