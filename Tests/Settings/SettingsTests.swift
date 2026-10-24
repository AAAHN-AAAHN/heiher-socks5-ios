import Foundation

@main struct SettingsTests {
    @MainActor static func main() async throws {
        var checks = 0
        func check(_ condition: Bool, _ name: String) {
            precondition(condition, name)
            checks += 1
            print("PASS: \(name)")
        }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let file = directory.appendingPathComponent("settings.json")
        let suite = "SettingsTests.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer {
            try? FileManager.default.removeItem(at: directory)
            legacy.removePersistentDomain(forName: suite)
        }
        legacy.set(true, forKey: "background.continuousLocation")
        legacy.set(true, forKey: "background.silentAudio")
        let store = SettingsStore(fileURL: file, legacy: legacy)
        await store.whenLoaded()
        try await store.flush()
        check(store.errorMessage == nil && store.value.background.continuousLocation && store.value.background.silentAudio, "Legacy background preferences migrate into JSON")
        check(legacy.object(forKey: "background.silentAudio") == nil, "Legacy keys removed only after save")
        check(store.value.selectedTab == .statistics && !store.value.serverRunning, "New defaults select Statistics and leave server stopped")
        let fields: [(WritableKeyPath<AppSettings, String>, String)] = [
            (\.server.workers, "2"), (\.server.listenAddress, "127.0.0.1"),
            (\.server.listenPort, "9876"), (\.server.udpListenAddress, "127.0.0.1"),
            (\.server.udpListenPort, "0"), (\.server.bindIPv4Address, "0.0.0.0"),
            (\.server.bindIPv6Address, "::"), (\.server.bindInterface, ""),
            (\.server.authUsername, "user's name"), (\.server.authPassword, "test-'password")
        ]
        for (path, value) in fields {
            store.set(path, value)
            check(store.value[keyPath: path] == value, "Server field accepted before setter returns")
            try await store.flush()
            let loaded = await loadedSettings(fileURL: file, legacy: legacy)
            check(loaded.value[keyPath: path] == value, "Server field durable after flush")
        }
        store.set(\.server.listenIPv6Only, true)
        store.set(\.serverRunning, true)
        for tab in [AppSettings.Tab.statistics, .server, .background, .settings] {
            store.set(\.selectedTab, tab)
            try await store.flush()
            let loaded = await loadedSettings(fileURL: file)
            check(loaded.value.selectedTab == tab, "Last selected tab survives recreation")
        }
        let saved = store.value
        let restored = await loadedSettings(fileURL: file)
        check(restored.value == saved, "All server and background values and running intent restore exactly")
        let configuration = try saved.server.configuration()
        check(configuration.contains("username: 'user''s name'") && configuration.contains("password: 'test-''password'"), "YAML quotes preserve literal authentication values")
        let exported = try saved.encoded()
        check(try AppSettings.decoded(exported) == saved, "Complete JSON round trip")
        var next = saved
        next.server.listenPort = "12345"
        next.serverRunning = false
        next.background.silentAudio = false
        next.background.continuousLocation = false
        next.selectedTab = .server
        try await store.importData(next.encoded())
        let imported = await loadedSettings(fileURL: file)
        check(store.value == next && imported.value == next, "Import replaces all settings transactionally")
        let importURL = directory.appendingPathComponent("import.json")
        try saved.encoded().write(to: importURL)
        try await store.importFile(importURL)
        check(store.value == saved, "Coordinated file import applies the complete document")
        try await store.importData(next.encoded())
        for bad in [Data("{".utf8), Data(repeating: 32, count: 65_537),
                    try JSONSerialization.data(withJSONObject: ["version": 99])] {
            do { try await store.importData(bad); preconditionFailure("Invalid import accepted") } catch {}
            let loaded = await loadedSettings(fileURL: file)
            check(store.value == next && loaded.value == next, "Invalid import leaves memory and JSON intact")
        }
        for invalidPort in ["", "-1", "65536", "1\nmain:"] {
            var bad = next
            bad.server.listenPort = invalidPort
            do { try await store.importData(bad.encoded()); preconditionFailure("Invalid port accepted") } catch {}
            check(store.value == next, "Invalid server configuration rejected before applying")
        }
        store.set(\.server.listenPort, "")
        try await store.flush()
        let draft = await loadedSettings(fileURL: file)
        check(draft.value.server.listenPort.isEmpty, "Incomplete text edits are saved without executing them")
        store.set(\.serverRunning, false)
        try await store.flush()
        let raw = try Data(contentsOf: file)
        let same = store.value.server.listenPort
        store.set(\.server.listenPort, same)
        try await store.flush()
        check(try Data(contentsOf: file) == raw, "Unchanged value needs no new serialization")
        let unavailable = SettingsStore(fileURL: URL(fileURLWithPath: "/dev/null/settings.json"), legacy: legacy)
        unavailable.set(\.serverRunning, true)
        await unavailable.whenLoaded()
        check(unavailable.errorMessage != nil, "Storage failure is reported, never presented as saved")
        unavailable.set(\.serverRunning, false)
        check(!unavailable.value.serverRunning, "Storage failure cannot prevent user Stop")
        await unavailable.whenLoaded()
        try Data("broken JSON".utf8).write(to: file)
        let broken = await loadedSettings(fileURL: file)
        check(broken.errorMessage != nil && !broken.value.serverRunning, "Unreadable saved settings fail closed with visible error")
        check(try Data(contentsOf: file) == Data("broken JSON".utf8), "Unreadable original file is not silently overwritten")
        for separator in ["\u{0085}", "\u{2028}", "\u{2029}"] {
            var injected = AppSettings()
            injected.server.authUsername = "user" + separator + "main:"
            injected.server.authPassword = "password"
            do { _ = try injected.server.configuration(); preconditionFailure("YAML newline accepted") } catch {}
            check(true, "Unicode YAML line separator rejected")
        }
        var oversized = AppSettings()
        oversized.server.authPassword = String(repeating: "x", count: 70_000)
        check(try AppSettings.decoded(oversized.encoded()) == oversized, "Large configuration JSON remains reloadable")
        print("SUMMARY: \(checks) settings checks passed")
    }
}
