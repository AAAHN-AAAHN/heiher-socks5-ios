import SwiftUI

/// One small, atomically replaced JSON file; no writes from statistics or audio checks.
@MainActor
final class SettingsStore: ObservableObject {
    @Published private(set) var value = AppSettings()
    @Published private(set) var errorMessage: String?
    let fileURL: URL

    init(fileURL: URL? = nil, legacy: UserDefaults = .standard) {
        self.fileURL = fileURL ?? FileManager.default.urls(for: .applicationSupportDirectory,
            in: .userDomainMask)[0].appendingPathComponent("Socks5/settings.json")
        do {
            if FileManager.default.fileExists(atPath: self.fileURL.path) {
                value = try AppSettings.decoded(Data(contentsOf: self.fileURL))
            } else {
                // Migrate the two settings saved by the preceding version once.
                value.background.continuousLocation = legacy.bool(forKey: "background.continuousLocation")
                value.background.silentAudio = legacy.bool(forKey: "background.silentAudio")
                try write(value)
                legacy.removeObject(forKey: "background.continuousLocation")
                legacy.removeObject(forKey: "background.silentAudio")
            }
        } catch {
            errorMessage = "Settings could not be loaded: \(error.localizedDescription)"
        }
    }

    func binding<Value>(_ path: WritableKeyPath<AppSettings, Value>) -> Binding<Value> {
        Binding(get: { self.value[keyPath: path] }, set: { self.set(path, $0) })
    }

    func set<Value>(_ path: WritableKeyPath<AppSettings, Value>, _ newValue: Value) {
        var next = value
        next[keyPath: path] = newValue
        guard next != value else { return }
        do {
            try write(next)
            errorMessage = nil
        } catch {
            errorMessage = "Settings could not be saved: \(error.localizedDescription)"
        }
        // A storage failure must never prevent the user from stopping a service.
        value = next
    }

    /// Decode and validate everything before changing either the file or live services.
    func importData(_ data: Data) throws {
        let next = try AppSettings.decoded(data)
        _ = try next.server.configuration()
        try write(next)
        value = next
        errorMessage = nil
    }

    func importFile(_ url: URL) async throws {
        // File-provider coordination can wait for a download; keep it off MainActor.
        let data = try await Task.detached(priority: .userInitiated) {
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            var coordinationError: NSError?
            var result: Result<Data, Error>?
            NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordinationError) { url in
                result = Result {
                    let file = try FileHandle(forReadingFrom: url)
                    defer { try? file.close() }
                    return try file.read(upToCount: 65_537) ?? Data()
                }
            }
            if let coordinationError { throw coordinationError }
            guard let result else { throw SettingsError.invalid("The settings file could not be read.") }
            return try result.get()
        }.value
        try importData(data)
    }

    private func write(_ value: AppSettings) throws {
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        var options: Data.WritingOptions = [.atomic]
        #if os(iOS)
        options.insert(.completeFileProtectionUntilFirstUserAuthentication)
        #endif
        try value.encoded().write(to: fileURL, options: options)
    }
}
