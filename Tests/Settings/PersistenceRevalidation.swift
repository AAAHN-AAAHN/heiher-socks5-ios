import Foundation

/// Real Foundation persistence. The runner substitutes only Linux UI/provider APIs.
@main struct PersistenceRevalidation {
    @MainActor static func main() async throws {
        var checks = 0
        var failures = 0
        func check(_ value: Bool, _ label: String) {
            checks += 1
            if value { print("PASS: \(label)") }
            else { failures += 1; print("FAIL: \(label)") }
        }
        func same(_ a: String, _ b: String) -> Bool { a.utf8.elementsEqual(b.utf8) }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let suite = "PersistenceRevalidation.\(UUID().uuidString)"
        let legacy = UserDefaults(suiteName: suite)!
        defer { try? FileManager.default.removeItem(at: root); legacy.removePersistentDomain(forName: suite) }
        let url = root.appendingPathComponent("store/settings.json")
        // Apple Foundation and corelibs can use different documented absence codes.
        // Record the actual open-error contract, rather than inferring absence from
        // a false fileExists result or treating a permission error as a new file.
        for missing in [url, root.appendingPathComponent("absent.json")] {
            do {
                let handle = try FileHandle(forReadingFrom: missing)
                try handle.close()
                preconditionFailure("Missing-file fixture unexpectedly exists")
            } catch let error as CocoaError {
                print("READ_ABSENCE: code=\(error.code.rawValue); path=\(missing.lastPathComponent)")
                check(error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile,
                      "Direct missing-file read uses an explicit Cocoa absence code")
            }
        }
        let store = SettingsStore(fileURL: url, legacy: legacy)
        check(store.errorMessage == nil && store.value == AppSettings(), "Missing file initializes the unchanged default schema")
        let binding = store.binding(\.server.authPassword)
        store.set(\.server.authUsername, "user")
        for pair in [("\u{00e9}", "e\u{0301}"), ("\u{ac00}", "\u{1100}\u{1161}")] {
            check(pair.0 == pair.1 && !same(pair.0, pair.1), "Fixture has canonical equality but distinct UTF-8")
            binding.wrappedValue = pair.0
            let before = try Data(contentsOf: url)
            binding.wrappedValue = pair.1
            let after = try Data(contentsOf: url)
            check(same(store.value.server.authPassword, pair.1), "Binding preserves changed credential bytes in memory")
            check(before != after && same(SettingsStore(fileURL: url, legacy: legacy).value.server.authPassword, pair.1),
                  "Inherited byte equality propagates through save and reconstruction")
            var next = store.value; next.server.authPassword = pair.0
            try store.importData(next.encoded())
            check(same(store.value.server.authPassword, pair.0), "Full-document import replaces exact credential bytes")
            let decoded = try AppSettings.decoded(store.value.encoded())
            check(same(decoded.server.authPassword, pair.0), "Export/JSON decode retains the exact imported bytes")
        }
        store.set(\.serverRunning, true)
        let savedRunning = try Data(contentsOf: url)
        let parked = root.appendingPathComponent("parked.json")
        try FileManager.default.moveItem(at: url, to: parked)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
        store.set(\.serverRunning, false)
        check(!store.value.serverRunning && store.errorMessage != nil, "Write failure applies Stop in memory and reports failure")
        check(try Data(contentsOf: parked) == savedRunning, "Failed Stop does not modify the last durable bytes")
        try FileManager.default.removeItem(at: url)
        try FileManager.default.moveItem(at: parked, to: url)
        store.set(\.serverRunning, false)
        check(store.errorMessage == nil, "Explicit identical Stop retries a previously failed save")
        check(!SettingsStore(fileURL: url, legacy: legacy).value.serverRunning, "Retried Stop survives store recreation")
        try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 1)], ofItemAtPath: url.path)
        let stamp = try FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as! Date
        store.set(\.serverRunning, false)
        check(try FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as? Date == stamp,
              "Clean identical choice still suppresses writes after save recovery")

        let missingParent = root.appendingPathComponent("missing-readonly")
        try FileManager.default.createDirectory(at: missingParent, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o500], ofItemAtPath: missingParent.path)
        legacy.set(true, forKey: "background.silentAudio")
        let pendingMigration = SettingsStore(fileURL: missingParent.appendingPathComponent("settings.json"), legacy: legacy)
        check(pendingMigration.value.background.silentAudio && pendingMigration.errorMessage != nil,
              "Confirmed absence may migrate in memory when first write fails")
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: missingParent.path)
        pendingMigration.set(\.background.silentAudio, true)
        check(pendingMigration.errorMessage == nil && FileManager.default.fileExists(atPath: pendingMigration.fileURL.path),
              "An identical explicit choice completes a pending initial save after access returns")
        check(legacy.object(forKey: "background.silentAudio") == nil,
              "Pending migration cleanup also completes on the identical-choice save")

        let blockedParent = root.appendingPathComponent("migration-blocked")
        try Data([1]).write(to: blockedParent)
        legacy.set(true, forKey: "background.silentAudio")
        legacy.set(true, forKey: "background.continuousLocation")
        let migration = SettingsStore(fileURL: blockedParent.appendingPathComponent("settings.json"), legacy: legacy)
        check(migration.errorMessage != nil, "Unreadable startup path is reported rather than silently replaced")
        // A real missing writable directory is a separate first-launch migration.
        let migrationURL = root.appendingPathComponent("migration/settings.json")
        let migrated = SettingsStore(fileURL: migrationURL, legacy: legacy)
        check(migrated.value.background.silentAudio && migrated.value.background.continuousLocation,
              "Successful first-file creation still migrates the same two choices")
        check(legacy.object(forKey: "background.silentAudio") == nil && legacy.object(forKey: "background.continuousLocation") == nil,
              "Successful migration cleans only the old keys")

        // Failed import writes must not turn a clean snapshot into a pending save.
        let clean = store.value
        let durable = try Data(contentsOf: url)
        try FileManager.default.moveItem(at: url, to: parked)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false)
        var incoming = clean; incoming.serverRunning = true
        var rejected = false
        do { try store.importData(incoming.encoded()) } catch { rejected = true }
        check(rejected && store.value == clean, "Failed import commit never changes the live snapshot")
        try FileManager.default.removeItem(at: url)
        try FileManager.default.moveItem(at: parked, to: url)
        try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 2)], ofItemAtPath: url.path)
        let cleanStamp = try FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as! Date
        store.set(\.serverRunning, clean.serverRunning)
        check(try FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as? Date == cleanStamp,
              "A rejected import does not schedule an unrelated rewrite of a clean snapshot")
        check(try Data(contentsOf: url) == durable, "Rejected import keeps exact original file bytes")

        let corrupt = Data("not JSON".utf8)
        try corrupt.write(to: url)
        legacy.set(true, forKey: "background.silentAudio")
        let broken = SettingsStore(fileURL: url, legacy: legacy)
        broken.set(\.serverRunning, false)
        check(!broken.value.serverRunning && !broken.value.background.silentAudio && broken.errorMessage != nil,
              "Corrupt existing file fails closed even with legacy On and unchanged Stop")
        check(try Data(contentsOf: url) == corrupt, "Unchanged setter after load failure does not erase unreadable original")
        try broken.importData(AppSettings().encoded())
        check(broken.errorMessage == nil && SettingsStore(fileURL: url, legacy: legacy).value == AppSettings(),
              "Explicit valid import repairs a corrupt store transactionally")
        check(legacy.object(forKey: "background.silentAudio") != nil,
              "Repairing existing JSON never starts legacy migration cleanup")
        let input = root.appendingPathComponent("regular-provider.json")
        try broken.value.encoded().write(to: input)
        try await broken.importFile(input)
        check(broken.value == AppSettings(), "Actual regular-file import uses the unchanged schema and coordination path")

        var seed: UInt64 = 27
        for _ in 0..<200 {
            seed = seed &* 6364136223846793005 &+ 1
            var next = broken.value
            next.server.authUsername = seed % 2 == 0 ? "\u{00e9}" : "e\u{0301}"
            next.server.authPassword = seed % 3 == 0 ? "\u{ac00}" : "\u{1100}\u{1161}"
            next.serverRunning = seed % 2 != 0
            next.background.continuousLocation = seed % 3 == 0
            next.selectedTab = [.server, .statistics, .background, .settings][Int(seed % 4)]
            try broken.importData(next.encoded())
            let loaded = SettingsStore(fileURL: url, legacy: legacy)
            precondition(loaded.value == next)
            precondition(same(loaded.value.server.authUsername, next.server.authUsername))
            precondition(same(loaded.value.server.authPassword, next.server.authPassword))
        }
        check(true, "200 sequential mixed byte-sensitive save/import/recreation cycles preserve complete snapshots")
        print("SUMMARY: \(checks) persistence revalidation assertions; \(failures) failed; real files, not iOS UI/provider policy")
        if failures != 0 { exit(1) }
    }
}
