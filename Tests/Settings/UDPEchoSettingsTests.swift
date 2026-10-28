import Foundation

/// Exercise the production decoder and actual coordinated file/store path.
@main struct UDPEchoSettingsTests {
    @MainActor static func main() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }
        let file = root.appendingPathComponent("settings.json")
        let imported = root.appendingPathComponent("import.json")
        let store = await loadedSettings(fileURL: file)
        try await store.flush()
        var checks = 0
        func check(_ value: Bool, _ message: String) {
            checks += 1
            precondition(value, message)
        }
        let defaults = AppSettings.Background.UDPEcho()
        check(store.value.background.periodicUDPEcho == defaults, "Fresh Echo defaults")
        let initial = try JSONSerialization.jsonObject(with: store.value.encoded()) as! [String: Any]
        var old = initial
        var oldBackground = old["background"] as! [String: Any]
        oldBackground.removeValue(forKey: "periodicUDPEcho")
        // A historical unknown key must not revive its enabled state.
        oldBackground["periodicPing"] = ["enabled": true, "destinations": "127.0.0.2", "period": "1"]
        old["background"] = oldBackground
        try await store.importData(JSONSerialization.data(withJSONObject: old))
        check(store.value.background.periodicUDPEcho == defaults, "Historical settings leave Echo Off")

        let invalidValues: [Any] = [NSNull(), true, [], [:],
            ["enabled": false, "destinations": "1.1.1.1"],
            ["enabled": "true", "destinations": "", "period": "1000"],
            ["enabled": false, "destinations": NSNull(), "period": "1000"]]
        for invalid in invalidValues {
            var document = initial
            var background = document["background"] as! [String: Any]
            background["periodicUDPEcho"] = invalid
            document["background"] = background
            let prior = store.value
            let disk = try Data(contentsOf: file)
            var failed = false
            do { try await store.importData(JSONSerialization.data(withJSONObject: document)) }
            catch { failed = true }
            check(failed && store.value == prior, "Malformed present Echo cannot supply defaults")
            check(try Data(contentsOf: file) == disk, "Rejected Echo import preserves disk")
        }

        var incoming = store.value
        incoming.background.periodicUDPEcho = .init(enabled: true, destinations: "", period: "")
        try await store.importData(incoming.encoded())
        check(store.value.background.periodicUDPEcho == incoming.background.periodicUDPEcho,
              "Empty raw drafts and On intent are preserved for service validation")
        incoming.background.periodicUDPEcho.destinations =
            (0..<65_536).map { "10.1.\($0 / 256).\($0 % 256)" }.joined(separator: ",\r\n")
        incoming.background.periodicUDPEcho.period = "1000"
        let data = try incoming.encoded()
        check(data.count > 65_536, "Large target fixture crosses former byte cap")
        try data.write(to: imported)
        try await store.importFile(imported)
        check(store.value == incoming, "Large coordinated import reads the complete file")
        let restored = await loadedSettings(fileURL: file)
        check(restored.value == incoming, "Large file survives store recreation")

        var composed = defaults
        composed.destinations = "\u{00e9}"
        var decomposed = composed
        decomposed.destinations = "e\u{0301}"
        check(composed != decomposed, "Raw draft equality compares UTF-8 bytes")
        store.set(\.background.periodicUDPEcho, composed)
        try await store.flush()
        store.set(\.background.periodicUDPEcho, decomposed)
        try await store.flush()
        check(try AppSettings.decoded(Data(contentsOf: file)).background.periodicUDPEcho == decomposed,
              "Unicode-equivalent drafts preserve the newer exact bytes")

        let audio = store.audioChange
        let location = store.locationChange
        let server = store.serverRunningChange
        store.set(\.background.periodicUDPEcho.enabled, false)
        let firstOff = store.echoChange
        store.set(\.background.periodicUDPEcho.enabled, false)
        check(store.echoChange != firstOff, "Repeated explicit Echo Off has a fresh intent")
        check(store.audioChange == audio && store.locationChange == location &&
              store.serverRunningChange == server, "Echo edits do not supersede unrelated service intent")
        var background = store.value.background
        background.periodicUDPEcho.period = "2000"
        store.set(\.background, background)
        check(store.echoChange == store.change, "Whole Background edits include Echo intent")
        try await store.flush()
        print("SUMMARY: \(checks) fresh UDP Echo settings and file assertions passed")
    }
}
