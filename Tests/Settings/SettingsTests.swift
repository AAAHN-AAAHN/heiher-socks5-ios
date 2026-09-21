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
            let loaded = SettingsStore(fileURL: file, legacy: legacy)
            check(loaded.value[keyPath: path] == value, "Server field written before setter returns")
        }
        store.set(\.server.listenIPv6Only, true)
        store.set(\.serverRunning, true)
        for tab in [AppSettings.Tab.statistics, .server, .background, .settings] {
            store.set(\.selectedTab, tab)
            check(SettingsStore(fileURL: file).value.selectedTab == tab, "Last selected tab survives recreation")
        }
        let saved = store.value
        check(SettingsStore(fileURL: file).value == saved, "All server and background values and running intent restore exactly")
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
        try store.importData(next.encoded())
        check(store.value == next && SettingsStore(fileURL: file).value == next, "Import replaces all settings transactionally")
        let importURL = directory.appendingPathComponent("import.json")
        try saved.encoded().write(to: importURL)
        try await store.importFile(importURL)
        check(store.value == saved, "Coordinated file import applies the complete document")
        try store.importData(next.encoded())
        for bad in [Data("{".utf8), Data(repeating: 32, count: 65_537),
                    try JSONSerialization.data(withJSONObject: ["version": 99])] {
            do { try store.importData(bad); preconditionFailure("Invalid import accepted") } catch {}
            check(store.value == next && SettingsStore(fileURL: file).value == next, "Invalid import leaves memory and JSON intact")
        }
        for invalidPort in ["", "-1", "65536", "1\nmain:"] {
            var bad = next
            bad.server.listenPort = invalidPort
            do { try store.importData(bad.encoded()); preconditionFailure("Invalid port accepted") } catch {}
            check(store.value == next, "Invalid server configuration rejected before applying")
        }
        store.set(\.server.listenPort, "")
        check(SettingsStore(fileURL: file).value.server.listenPort.isEmpty, "Incomplete text edits are saved without executing them")
        store.set(\.serverRunning, false)
        let raw = try Data(contentsOf: file)
        let same = store.value.server.listenPort
        store.set(\.server.listenPort, same)
        check(try Data(contentsOf: file) == raw, "Unchanged value needs no new serialization")
        let unavailable = SettingsStore(fileURL: URL(fileURLWithPath: "/dev/null/settings.json"), legacy: legacy)
        unavailable.set(\.serverRunning, true)
        check(unavailable.errorMessage != nil, "Storage failure is reported, never presented as saved")
        unavailable.set(\.serverRunning, false)
        check(!unavailable.value.serverRunning, "Storage failure cannot prevent user Stop")
        try Data("broken JSON".utf8).write(to: file)
        let broken = SettingsStore(fileURL: file)
        check(broken.errorMessage != nil && !broken.value.serverRunning, "Unreadable saved settings fail closed with visible error")
        check(try Data(contentsOf: file) == Data("broken JSON".utf8), "Unreadable original file is not silently overwritten")
        print("SUMMARY: \(checks) settings checks passed")
    }
}
