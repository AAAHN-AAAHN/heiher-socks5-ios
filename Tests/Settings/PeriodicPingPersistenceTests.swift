import Foundation

/// Actual AppSettings and SettingsStore, real files; no iOS or network claim.
@main struct PeriodicPingPersistenceTests {
    @MainActor static func main() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let url = root.appendingPathComponent("settings.json")
        let input = root.appendingPathComponent("backup.json")
        let suite = "PingPersistence.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer { try? fm.removeItem(at: root); legacy.removePersistentDomain(forName: suite) }
        var checks = 0
        func check(_ value: Bool, _ message: String) { checks += 1; precondition(value, message) }
        let store = await loadedSettings(fileURL: url, legacy: legacy)
        try await store.flush()
        check(store.value.background.periodicPing == .init(), "defaults")
        let composed = "\u{00e9}", decomposed = "e\u{0301}"
        check(composed == decomposed && !composed.utf8.elementsEqual(decomposed.utf8), "raw text fixture")
        let textPaths: [WritableKeyPath<AppSettings, String>] = [
            \.background.periodicPing.destinations, \.background.periodicPing.period]
        for path in textPaths {
            store.set(path, composed)
            try await store.flush()
            store.set(path, decomposed)
            try await store.flush()
            let restored = await loadedSettings(fileURL: url, legacy: legacy)
            check(store.value[keyPath: path].utf8.elementsEqual(decomposed.utf8), "latest raw text accepted")
            check(restored.value[keyPath: path].utf8.elementsEqual(decomposed.utf8), "raw text durable after relaunch")
        }
        let large = (0..<65_536).map { "10.8.\($0 / 256).\($0 % 256)" }.joined(separator: ",")
        store.set(\.background.periodicPing.destinations, large)
        store.set(\.background.periodicPing.period, "2500")
        store.set(\.background.periodicPing.enabled, true)
        try await store.flush()
        let snapshot = store.value
        let backup = try snapshot.encoded()
        check(backup.count > 65_536, "large fixture")
        let relaunch = await loadedSettings(fileURL: url, legacy: legacy)
        check(relaunch.value == snapshot, "relaunch must preserve all fields")
        let accepted = relaunch.pingChange
        relaunch.set(\.selectedTab, .background)
        check(relaunch.pingChange == accepted, "unrelated edit does not change ping identity")
        relaunch.set(\.background.periodicPing.enabled, false)
        check(relaunch.pingChange != accepted, "Off changes ping identity")
        try await relaunch.flush()
        try backup.write(to: input)
        try await relaunch.importFile(input)
        check(relaunch.value == snapshot, "large backup file restore")
        check(try AppSettings.decoded(Data(contentsOf: url)) == snapshot, "large restore durable")
        // Arbitrarily large whitespace is valid JSON; no inherited byte limiter.
        let padded = backup + Data(repeating: 32, count: 2_097_152)
        try await relaunch.importData(padded)
        check(relaunch.value == snapshot, "no direct import byte limit")
        var old = try JSONSerialization.jsonObject(with: backup) as! [String: Any]
        var background = old["background"] as! [String: Any]
        background.removeValue(forKey: "periodicPing")
        old["background"] = background
        try await relaunch.importData(JSONSerialization.data(withJSONObject: old))
        check(relaunch.value.background.periodicPing == .init(), "legacy version-1 defaults")
        check(relaunch.value.server == snapshot.server, "legacy server fields unchanged")
        for malformed: Any in [NSNull(), ["enabled": true], ["enabled": "true", "destinations": "1.1.1.1", "period": "1000"]] {
            background["periodicPing"] = malformed
            old["background"] = background
            let before = try Data(contentsOf: url)
            var rejected = false
            do { try await relaunch.importData(JSONSerialization.data(withJSONObject: old)) }
            catch { rejected = true }
            check(try rejected && Data(contentsOf: url) == before, "malformed ping preserves original")
        }
        // Publish delayed import only if no later user Off was accepted.
        let entered = DispatchSemaphore(value: 0), release = DispatchSemaphore(value: 0)
        var io = SettingsStore.Storage()
        io.imported = { _ in entered.signal(); release.wait(); return backup }
        let protected = SettingsStore(fileURL: url, legacy: legacy, storage: io)
        await protected.whenLoaded()
        let operation = Task { @MainActor in try await protected.importFile(input) }
        let reached: Bool = await withCheckedContinuation { receipt in
            DispatchQueue.global().async {
                receipt.resume(returning: entered.wait(timeout: .now() + 3) == .success)
            }
        }
        check(reached, "blocked import boundary")
        protected.set(\.background.periodicPing.enabled, false)
        release.signal()
        var cancelled = false
        do { try await operation.value } catch is CancellationError { cancelled = true }
        try await protected.flush()
        check(cancelled && !protected.value.background.periodicPing.enabled, "latest Off wins import")
        check(!(try AppSettings.decoded(Data(contentsOf: url))).background.periodicPing.enabled, "latest Off durable")
        print("SUMMARY: \(checks) ping JSON migration, large-file, restart, backup and latest-intent checks passed")
    }
}
