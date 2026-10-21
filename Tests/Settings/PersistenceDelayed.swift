import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

// Delivery-only fixture: the native call has actually returned, but its first
// completion is held off MainActor while the real asynchronous import commits.
enum PersistenceCompletionGate {
    static let condition = NSCondition()
    nonisolated(unsafe) private static var held = true
    nonisolated(unsafe) private static var entered = false
    static func wait() {
        condition.lock(); defer { condition.unlock() }
        guard held else { return }
        entered = true
        let deadline = Date().addingTimeInterval(10)
        while held { precondition(condition.wait(until: deadline), "Native completion fixture timed out") }
    }
    static func hasEntered() -> Bool {
        condition.lock(); defer { condition.unlock() }; return entered
    }
    static func release() {
        condition.lock(); held = false; condition.broadcast(); condition.unlock()
    }
}

@main struct PersistenceDelayed {
    @MainActor static func main() async throws {
        let file = URL(fileURLWithPath: CommandLine.arguments[1])
        let legacy = UserDefaults(suiteName: "DelayedPersistence.\(getpid())")!
        let store = SettingsStore(fileURL: file, legacy: legacy)
        await store.whenLoaded()
        defer { legacy.removePersistentDomain(forName: "DelayedPersistence.\(getpid())") }
        let controller = ServerController()
        var bad = AppSettings()
        bad.server.listenAddress = "127.0.0.1"
        bad.server.workers = CommandLine.arguments[4]
        bad.server.listenPort = CommandLine.arguments[2]
        bad.server.udpListenPort = "0"
        bad.serverRunning = true
        try await store.importData(bad.encoded())
        controller.apply(store.value.server, running: store.value.serverRunning)
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        while !PersistenceCompletionGate.hasEntered() {
            precondition(ProcessInfo.processInfo.systemUptime < deadline, "Native call did not reach completion boundary")
            try await Task.sleep(for: .milliseconds(2))
        }
        var good = bad
        good.server.listenPort = CommandLine.arguments[3]
        try await store.importData(good.encoded())
        // Test adapter applies the production root contract; this is not SwiftUI rendering.
        controller.apply(store.value.server, running: store.value.serverRunning)
        PersistenceCompletionGate.release()
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
