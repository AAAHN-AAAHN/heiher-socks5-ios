import Foundation

/// Run as a normal user: deny traversal while an existing valid JSON is present.
@main struct LoadAccessTests {
    @MainActor static func main() throws {
        var checks = 0
        var failures = 0
        func check(_ result: Bool, _ name: String) {
            checks += 1
            if result { print("PASS: \(name)") }
            else { failures += 1; print("FAIL: \(name)") }
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let parent = root.appendingPathComponent("denied")
        let file = parent.appendingPathComponent("settings.json")
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
        let suite = "LoadAccessTests.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer {
            try? FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: parent.path)
            try? FileManager.default.removeItem(at: root)
            legacy.removePersistentDomain(forName: suite)
        }
        legacy.set(true, forKey: "background.silentAudio")
        legacy.set(true, forKey: "background.continuousLocation")
        var saved = AppSettings(); saved.server.listenPort = "23456"
        let original = try saved.encoded()
        try original.write(to: file)
        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: parent.path)
        check(!FileManager.default.fileExists(atPath: file.path), "Fixture proves inaccessible file existence is reported as false")
        let store = SettingsStore(fileURL: file, legacy: legacy)
        check(store.errorMessage != nil, "Denied startup read reports an error")
        check(!store.value.serverRunning && !store.value.background.silentAudio && !store.value.background.continuousLocation,
              "Unknown/inaccessible file is not a first launch and never restores legacy On")
        check(legacy.object(forKey: "background.silentAudio") != nil, "Denied startup leaves old keys untouched")
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: parent.path)
        store.set(\.serverRunning, false)
        check(try Data(contentsOf: file) == original, "Unchanged Stop after denied load cannot overwrite the existing saved file")
        check(SettingsStore(fileURL: file, legacy: legacy).value == saved, "Reopening after access recovers the original file without migration")
        print("SUMMARY: \(checks) access-boundary assertions; \(failures) failed; filesystem permissions, not iOS file protection")
        if failures != 0 { exit(1) }
    }
}
