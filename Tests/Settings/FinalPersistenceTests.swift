import Foundation

/// Real files and the actual model/store. Host execution is not iOS protection proof.
@main struct FinalPersistenceTests {
    @MainActor static func main() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        let suite = "FinalPersistence.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer { try? fm.removeItem(at: root); legacy.removePersistentDomain(forName: suite) }
        let file = root.appendingPathComponent("local/settings.json")
        let input = root.appendingPathComponent("import.json")
        let store = SettingsStore(fileURL: file, legacy: legacy)
        var checks = 0
        func check(_ condition: Bool, _ label: String) {
            checks += 1
            precondition(condition, label)
        }
        func durable() throws -> AppSettings { try AppSettings.decoded(Data(contentsOf: file)) }
        func reject(_ data: Data, _ label: String) throws {
            let before = store.value
            let bytes = try Data(contentsOf: file)
            var failed = false
            do { try store.importData(data) } catch { failed = true }
            check(failed, label + " rejected")
            check(store.value == before, label + " preserves live state")
            check(try Data(contentsOf: file) == bytes, label + " preserves exact disk bytes")
        }
        check(store.errorMessage == nil && store.value == AppSettings(), "Initial schema")
        var settings = store.value
        settings.server.workers = "1"
        settings.server.listenPort = "32109"
        settings.server.udpListenPort = "0"
        settings.server.authUsername = "user'\u{00e9}"
        settings.server.authPassword = "pass'e\u{0301}"
        settings.serverRunning = true
        settings.background.continuousLocation = true
        settings.background.silentAudio = true
        settings.selectedTab = .background
        try store.importData(settings.encoded())
        let ordinary = try settings.encoded()
        for count in [ordinary.count, 65_535, 65_536] {
            var padded = ordinary
            padded.append(Data(repeating: 0x20, count: count - padded.count))
            try padded.write(to: input)
            try await store.importFile(input)
            check(try store.value == settings && durable() == settings, "Bounded regular-file import \(count)")
            check(try Data(contentsOf: file) == ordinary, "Canonical output does not retain padding")
        }
        var tooLarge = ordinary
        tooLarge.append(Data(repeating: 0x20, count: 65_537 - tooLarge.count))
        try reject(tooLarge, "65537-byte direct import")
        try tooLarge.write(to: input)
        let initialBytes = try Data(contentsOf: file)
        var failed = false
        do { try await store.importFile(input) } catch { failed = true }
        check(failed && store.value == settings, "65537-byte coordinated import rejected")
        check(try Data(contentsOf: file) == initialBytes, "Oversize file import preserves disk")
        let document = try JSONSerialization.jsonObject(with: ordinary) as! [String: Any]
        for key in ["version", "server", "serverRunning", "background", "selectedTab"] {
            var missing = document; missing.removeValue(forKey: key)
            try reject(JSONSerialization.data(withJSONObject: missing), "Missing \(key)")
            var null = document; null[key] = NSNull()
            try reject(JSONSerialization.data(withJSONObject: null), "Null \(key)")
        }
        for version in [0, 2, -1, Int.max] {
            var next = document; next["version"] = version
            try reject(JSONSerialization.data(withJSONObject: next), "Version \(version)")
        }
        for invalid in [Data(), Data("[]".utf8), Data("null".utf8), Data("true".utf8),
                        ordinary + Data("x".utf8)] {
            try reject(invalid, "Invalid root or trailing bytes")
        }
        var future = document; future["unrecognized"] = ["ignored": true]
        try store.importData(JSONSerialization.data(withJSONObject: future))
        check(try store.value == settings && durable() == settings, "Unknown fields do not change schema1 fields")

        // A clean unchanged setter/binding performs no writes or inode replacement.
        let stamp = Date(timeIntervalSince1970: 123)
        try fm.setAttributes([.modificationDate: stamp], ofItemAtPath: file.path)
        let attributes = try fm.attributesOfItem(atPath: file.path)
        let began = ProcessInfo.processInfo.systemUptime
        for _ in 0..<10_000 {
            store.set(\.serverRunning, settings.serverRunning)
            store.binding(\.server.authPassword).wrappedValue = settings.server.authPassword
        }
        let elapsed = ProcessInfo.processInfo.systemUptime - began
        let after = try fm.attributesOfItem(atPath: file.path)
        check(after[.modificationDate] as? Date == attributes[.modificationDate] as? Date, "20000 equal requests do not write")
        check(after[.systemFileNumber] as? NSNumber == attributes[.systemFileNumber] as? NSNumber, "20000 equal requests do not replace inode")
        check(try Data(contentsOf: file) == initialBytes, "No-op requests preserve exact bytes")
        print("OBSERVATION: 20000 no-op set/binding calls, elapsed=\(elapsed)s; not a device CPU or durability benchmark")

        // Every actual input field survives JSON replacement and store reconstruction.
        let fields: [(WritableKeyPath<ServerSettings, String>, String)] = [
            (\.workers, "2"), (\.listenAddress, "127.0.0.1"), (\.listenPort, "32110"),
            (\.udpListenAddress, "::"), (\.udpListenPort, "32111"),
            (\.bindIPv4Address, "127.0.0.2"), (\.bindIPv6Address, "::1"),
            (\.bindInterface, "en0"), (\.authUsername, "user'\u{ac00}"),
            (\.authPassword, "pass'\u{1100}\u{1161}")]
        for (path, text) in fields {
            var server = store.value.server; server[keyPath: path] = text
            store.set(\.server, server)
            check(store.value.server[keyPath: path].utf8.elementsEqual(text.utf8), "Field bytes live")
            check(try durable() == store.value, "Field durable")
            check(SettingsStore(fileURL: file, legacy: legacy).value == store.value, "Field recreated")
        }
        store.set(\.server.listenIPv6Only, true)
        check(try durable().server.listenIPv6Only, "Boolean field durable")
        for tab in [AppSettings.Tab.statistics, .server, .background, .settings] {
            store.set(\.selectedTab, tab)
            check(try durable().selectedTab == tab, "All portable tabs remain stored")
        }
        var seed: UInt64 = 20260930
        for i in 0..<256 {
            seed = seed &* 6364136223846793005 &+ 1
            var next = settings
            next.server.workers = String(seed % 64 + 1)
            next.server.listenPort = String(seed % 65535 + 1)
            next.server.authPassword = i % 2 == 0 ? "\u{00e9}" : "e\u{0301}"
            next.serverRunning = seed & 1 == 0
            next.background.silentAudio = seed & 2 == 0
            next.background.continuousLocation = seed & 4 == 0
            next.selectedTab = [.statistics, .server, .background, .settings][Int(seed % 4)]
            try store.importData(next.encoded())
            check(try durable() == next && store.value == next, "Sequence snapshot")
            check(SettingsStore(fileURL: file, legacy: legacy).value == next, "Sequence recreation")
        }
        // A stopped invalid draft is intentionally portable only as local state.
        store.set(\.serverRunning, false)
        store.set(\.server.workers, "")
        let draft = store.value
        check(try durable() == draft, "Stopped invalid draft is saved")
        check(SettingsStore(fileURL: file, legacy: legacy).value == draft, "Stopped draft reloads unchanged")
        try reject(draft.encoded(), "Import of non-executable draft")
        print("SUMMARY: \(checks) final persistence assertions; 0 failed; real model and Foundation files")
    }
}
