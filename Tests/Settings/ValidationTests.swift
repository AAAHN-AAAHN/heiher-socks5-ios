import Foundation

/// Boundary checks use real JSON and files; they do not grant device permissions.
@main struct ValidationTests {
    @MainActor static func main() throws {
        var checks = 0
        func check(_ condition: Bool, _ name: String) {
            precondition(condition, name); checks += 1; print("PASS: \(name)")
        }
        func rejects(_ work: () throws -> Void, _ name: String) {
            do { try work(); preconditionFailure(name) } catch {}
            check(true, name)
        }
        let defaults = AppSettings()
        let fields: [(WritableKeyPath<ServerSettings, String>, String)] = [
            (\.workers, "4"), (\.listenAddress, "::"), (\.listenPort, "1080"),
            (\.udpListenAddress, ""), (\.udpListenPort, "1080"),
            (\.bindIPv4Address, "0.0.0.0"), (\.bindIPv6Address, "::"),
            (\.bindInterface, ""), (\.authUsername, ""), (\.authPassword, "")
        ]
        check(fields.allSatisfy { defaults.server[keyPath: $0.0] == $0.1 }
              && !defaults.server.listenIPv6Only && !defaults.serverRunning,
              "All original server defaults and stopped intent are preserved")
        for (path, valid, invalid) in [
            (\ServerSettings.workers, ["1", "64"], ["0", "65", "", "1.5", "1\n", "9999999999999999999999"]),
            (\ServerSettings.listenPort, ["1", "65535"], ["0", "65536", "-1", "", "1\nmain:", "1.5"]),
            (\ServerSettings.udpListenPort, ["0", "65535"], ["-1", "65536", "", " 1 ", "1\n", "1.5"])
        ] {
            for value in valid {
                var server = defaults.server; server[keyPath: path] = value
                _ = try server.configuration(); check(true, "Numeric boundary accepted: \(value)")
            }
            for value in invalid {
                var server = defaults.server; server[keyPath: path] = value
                rejects({ _ = try server.configuration() }, "Invalid numeric input rejected")
            }
        }
        let texts: [WritableKeyPath<ServerSettings, String>] = [
            \.listenAddress, \.udpListenAddress, \.bindIPv4Address, \.bindIPv6Address,
            \.bindInterface, \.authUsername, \.authPassword
        ]
        for path in texts {
            for separator in ["\0", "\t", "\n", "\r", "\u{0085}", "\u{2028}", "\u{2029}"] {
                var server = defaults.server
                server.authUsername = "user"; server.authPassword = "password"
                server[keyPath: path] = "a" + separator + "b"
                rejects({ _ = try server.configuration() }, "Every YAML text field rejects control/line separators")
            }
        }
        var auth = defaults.server
        auth.authUsername = String(repeating: "a", count: 255)
        auth.authPassword = String(repeating: "b", count: 255)
        _ = try auth.configuration(); check(true, "255-byte credentials accepted")
        auth.authUsername += "a"
        rejects({ _ = try auth.configuration() }, "256-byte username rejected")
        auth.authUsername = "user"; auth.authPassword = String(repeating: "가", count: 86)
        rejects({ _ = try auth.configuration() }, "UTF-8 byte length rather than character count is enforced")
        auth.authPassword = ""
        rejects({ _ = try auth.configuration() }, "Half-empty credentials rejected")
        auth.authUsername = ""; auth.authPassword = "password"
        rejects({ _ = try auth.configuration() }, "Other half-empty credentials rejected")
        for path in texts {
            var bounded = defaults.server
            bounded.authUsername = "user"; bounded.authPassword = "password"
            bounded[keyPath: path] = String(repeating: "a", count: 255)
            _ = try bounded.configuration()
            check(true, "255-byte field fits the native parser without truncation")
            bounded[keyPath: path] += "a"
            rejects({ _ = try bounded.configuration() }, "256-byte field rejected before native truncation")
        }
        auth.authUsername = "user'# : \\ \""; auth.authPassword = "암호'&*[]{}"
        let yaml = try auth.configuration()
        check(yaml.contains("username: 'user''# : \\ \"'") && yaml.contains("password: '암호''&*[]{}'"),
              "YAML punctuation, quotes and non-ASCII text stay quoted literal data")
        var json = try JSONSerialization.jsonObject(with: defaults.encoded()) as! [String: Any]
        check(Set(json.keys) == Set(["version", "server", "serverRunning", "background", "selectedTab"]),
              "JSON contains only the five declared schema groups")
        json["version"] = 2
        rejects({ _ = try AppSettings.decoded(JSONSerialization.data(withJSONObject: json)) }, "Future schema version rejected")
        json["version"] = 1; json["selectedTab"] = "future"
        rejects({ _ = try AppSettings.decoded(JSONSerialization.data(withJSONObject: json)) }, "Unknown tab rejected")
        for bytes in [Data(), Data("[]".utf8), Data("null".utf8), Data("{}".utf8)] {
            rejects({ _ = try AppSettings.decoded(bytes) }, "Incomplete document rejected without partial defaults")
        }
        for tab in [AppSettings.Tab.statistics, .server, .background, .settings] {
            var value = defaults; value.selectedTab = tab
            value.background.silentAudio = true; value.background.continuousLocation = true
            check(try AppSettings.decoded(value.encoded()) == value, "All tabs and unavailable-feature choices round-trip")
        }
        let compact = try JSONSerialization.data(withJSONObject: JSONSerialization.jsonObject(with: defaults.encoded()))
        let exact = compact + Data(repeating: 32, count: 65_536 - compact.count)
        check(try AppSettings.decoded(exact) == defaults, "Exactly 65536 input bytes accepted")
        rejects({ _ = try AppSettings.decoded(exact + Data([32])) }, "65537 input bytes rejected")

        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let file = root.appendingPathComponent("settings.json")
        let suite = "Validation.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer { try? FileManager.default.removeItem(at: root); legacy.removePersistentDomain(forName: suite) }
        let store = SettingsStore(fileURL: file, legacy: legacy)
        try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 1)], ofItemAtPath: file.path)
        let stamp = try FileManager.default.attributesOfItem(atPath: file.path)[.modificationDate] as! Date
        store.set(\.serverRunning, false)
        check(try FileManager.default.attributesOfItem(atPath: file.path)[.modificationDate] as? Date == stamp,
              "Identical setter leaves file timestamp unchanged, not merely equal JSON bytes")
        var incoming = defaults; incoming.serverRunning = true; incoming.server.listenPort = "20000"
        let previous = try Data(contentsOf: file)
        let parked = root.appendingPathComponent("previous.json")
        try FileManager.default.moveItem(at: file, to: parked)
        try FileManager.default.createDirectory(at: file, withIntermediateDirectories: false)
        rejects({ try store.importData(incoming.encoded()) }, "A failed import write does not commit live state")
        let preserved = try Data(contentsOf: parked)
        check(store.value == defaults && preserved == previous,
              "Write-failed import preserves prior state and parked bytes")
        store.set(\.serverRunning, true)
        store.set(\.background.silentAudio, true)
        store.set(\.serverRunning, false)
        store.set(\.background.silentAudio, false)
        check(!store.value.serverRunning && !store.value.background.silentAudio && store.errorMessage != nil,
              "Storage failure never blocks Stop or background Off")
        try FileManager.default.removeItem(at: file)
        try FileManager.default.moveItem(at: parked, to: file)
        for bad in [Data("broken".utf8), exact + Data([32])] {
            try bad.write(to: file)
            legacy.set(true, forKey: "background.silentAudio")
            let failed = SettingsStore(fileURL: file, legacy: legacy)
            check(failed.errorMessage != nil && !failed.value.serverRunning && !failed.value.background.silentAudio,
                  "Corrupt/oversized existing files fail closed instead of migrating enabled services")
            let disk = try Data(contentsOf: file)
            check(disk == bad && legacy.object(forKey: "background.silentAudio") != nil,
                  "Failed load preserves original file and legacy keys")
        }
        try store.importData(defaults.encoded())
        for i in 0..<250 {
            var value = defaults
            value.server.listenPort = String(10000 + i)
            value.server.authUsername = "u'\(i)"; value.server.authPassword = "p\\\(i)"
            value.serverRunning = i % 2 == 0
            value.background.silentAudio = i % 3 == 0
            try store.importData(value.encoded())
            let restored = try AppSettings.decoded(Data(contentsOf: file))
            precondition(restored == value)
        }
        check(true, "250 sequential atomic import/readback cycles preserve complete snapshots")
        print("SUMMARY: \(checks) validation assertions passed; repeated writes are not crash/power-loss tests")
    }
}
