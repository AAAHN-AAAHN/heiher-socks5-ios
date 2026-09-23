import SwiftUI

/// One small, atomically replaced JSON file; no writes from statistics or audio checks.
@MainActor
final class SettingsStore: ObservableObject {
    @Published private(set) var value = AppSettings()
    @Published private(set) var errorMessage: String?
    let fileURL: URL
    private var importRevision: UInt64 = 0
    private var migrationDefaults: UserDefaults?
    private var savePending = false

    init(fileURL: URL? = nil, legacy: UserDefaults = .standard) {
        self.fileURL = fileURL ?? FileManager.default.urls(for: .applicationSupportDirectory,
            in: .userDomainMask)[0].appendingPathComponent("Socks5/settings.json")
        do {
            do {
                value = try AppSettings.decoded(Self.read(self.fileURL))
            } catch let error as CocoaError where error.code == .fileReadNoSuchFile {
                // An inaccessible existing file is not a first launch.
                // Migrate the two settings saved by the preceding version once.
                value.background.continuousLocation = legacy.bool(forKey: "background.continuousLocation")
                value.background.silentAudio = legacy.bool(forKey: "background.silentAudio")
                migrationDefaults = legacy
                savePending = true
                try write(value)
            }
        } catch {
            errorMessage = "Settings could not be loaded: \(error.localizedDescription)"
        }
    }

    func binding<Value>(_ path: WritableKeyPath<AppSettings, Value>) -> Binding<Value> {
        Binding(get: { self.value[keyPath: path] }, set: { self.set(path, $0) })
    }

    func set<Value>(_ path: WritableKeyPath<AppSettings, Value>, _ newValue: Value) {
        // Even an explicit unchanged Stop supersedes a pending file import.
        importRevision &+= 1
        var next = value
        next[keyPath: path] = newValue
        // A failed explicit save may be retried by the same choice, without polling.
        guard next != value || savePending else { return }
        do {
            try write(next)
            errorMessage = nil
        } catch {
            savePending = true
            errorMessage = "Settings could not be saved: \(error.localizedDescription)"
        }
        // A storage failure must never prevent the user from stopping a service.
        value = next
    }

    /// Decode and validate everything before changing either the file or live services.
    func importData(_ data: Data) throws {
        importRevision &+= 1
        let next = try AppSettings.decoded(data)
        _ = try next.server.configuration()
        try write(next)
        value = next
        errorMessage = nil
    }

    func importFile(_ url: URL) async throws {
        try Task.checkCancellation()
        importRevision &+= 1
        let revision = importRevision
        // File-provider coordination can wait for a download; keep it off MainActor.
        let data = try await Task.detached(priority: .userInitiated) {
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            var coordinationError: NSError?
            var result: Result<Data, Error>?
            NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: url, options: [], error: &coordinationError) { url in
                result = Result { try Self.read(url) }
            }
            if let coordinationError { throw coordinationError }
            guard let result else { throw SettingsError.invalid("The settings file could not be read.") }
            return try result.get()
        }.value
        // A slow provider must not undo Stop, an edit, or a newer import.
        try Task.checkCancellation()
        guard revision == importRevision else {
            throw SettingsError.invalid("Settings changed while the file was being read. Import again to replace them.")
        }
        try importData(data)
    }

    private nonisolated static func read(_ url: URL) throws -> Data {
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        return try file.read(upToCount: 65_537) ?? Data()
    }

    private func write(_ value: AppSettings) throws {
        try FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        var options: Data.WritingOptions = [.atomic]
        #if os(iOS)
        options.insert(.completeFileProtectionUntilFirstUserAuthentication)
        #endif
        try value.encoded().write(to: fileURL, options: options)
        savePending = false
        // Finish migration after the first successful write, including a later retry.
        migrationDefaults?.removeObject(forKey: "background.continuousLocation")
        migrationDefaults?.removeObject(forKey: "background.silentAudio")
        migrationDefaults = nil
    }
}
