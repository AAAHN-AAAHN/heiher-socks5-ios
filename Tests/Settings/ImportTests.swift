import Foundation

@main struct ImportTests {
    @MainActor static func main() async throws {
        var checks = 0
        var failures = 0
        func check(_ condition: Bool, _ label: String) {
            checks += 1
            if condition { print("PASS: \(label)") }
            else { failures += 1; print("FAIL: \(label)") }
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let suite = "ImportTests.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer { try? FileManager.default.removeItem(at: root); legacy.removePersistentDomain(forName: suite) }
        let file = root.appendingPathComponent("settings.json")
        let store = SettingsStore(fileURL: file, legacy: legacy)
        var document = AppSettings()
        document.serverRunning = true
        document.server.listenPort = "12345"
        let input = root.appendingPathComponent("first.json")
        try document.encoded().write(to: input)
        let initial = store.value

        let preCancelled = Task { @MainActor in try await store.importFile(input) }
        preCancelled.cancel()
        do { try await preCancelled.value } catch {}
        check(store.value == initial, "Cancelled-before-start import leaves live state unchanged")
        check(try AppSettings.decoded(Data(contentsOf: file)) == initial, "Cancelled-before-start import leaves disk unchanged")
        try store.importData(initial.encoded())

        for action in 0..<4 {
            var running = initial
            running.serverRunning = true
            try store.importData(running.encoded())
            CoordinationProbe.block(input.path)
            let pending = Task { @MainActor in try await store.importFile(input) }
            await waitFor(input.path)
            switch action {
            case 0: store.set(\.serverRunning, false)
            case 1: store.set(\.server.listenPort, "22345")
            case 2: store.set(\.serverRunning, false); store.set(\.serverRunning, true)
            default: pending.cancel()
            }
            let chosen = store.value
            let before = try Data(contentsOf: file)
            CoordinationProbe.release(input.path)
            var rejected = false
            do { try await pending.value } catch { rejected = true }
            check(rejected && store.value == chosen, "In-flight import respects newer action/cancel \(action) in memory")
            check(try Data(contentsOf: file) == before, "In-flight import respects newer action/cancel \(action) on disk")
        }
        try store.importData(initial.encoded())
        CoordinationProbe.block(input.path)
        let first = Task { @MainActor in try await store.importFile(input) }
        await waitFor(input.path)
        var later = initial
        later.server.listenPort = "23456"
        let secondInput = root.appendingPathComponent("second.json")
        try later.encoded().write(to: secondInput)
        try await store.importFile(secondInput)
        CoordinationProbe.release(input.path)
        do { try await first.value } catch {}
        check(store.value == later, "A slower earlier import cannot replace a later successful import")
        check(try AppSettings.decoded(Data(contentsOf: file)) == later, "Latest import wins on disk as well as memory")

        let blockedParent = root.appendingPathComponent("blocked-parent")
        try FileManager.default.createDirectory(at: blockedParent, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o500], ofItemAtPath: blockedParent.path)
        legacy.set(true, forKey: "background.silentAudio")
        legacy.set(true, forKey: "background.continuousLocation")
        let migrated = SettingsStore(fileURL: blockedParent.appendingPathComponent("settings.json"), legacy: legacy)
        check(migrated.errorMessage != nil && legacy.object(forKey: "background.silentAudio") != nil,
              "Failed initial migration keeps both legacy keys")
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: blockedParent.path)
        migrated.set(\.server.listenPort, "12346")
        check(migrated.errorMessage == nil && migrated.value.background.silentAudio,
              "Recovered storage persists the migrated values")
        check(legacy.object(forKey: "background.silentAudio") == nil && legacy.object(forKey: "background.continuousLocation") == nil,
              "First later successful write completes the previously failed migration cleanup")
        print("SUMMARY: \(checks) import/migration assertions; \(failures) failed (controlled coordination, real Foundation files)")
        if failures != 0 { exit(1) }
    }
    @MainActor static func waitFor(_ path: String) async {
        for _ in 0..<1000 {
            if CoordinationProbe.hasEntered(path) { return }
            try? await Task.sleep(for: .milliseconds(2))
        }
        fatalError("Test import never entered coordination")
    }
}
