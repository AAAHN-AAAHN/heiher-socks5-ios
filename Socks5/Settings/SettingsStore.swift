import SwiftUI
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

/// Live state belongs to MainActor. One storage operation and one latest pending
/// snapshot are retained; no file operation or queue wait runs on MainActor.
@MainActor
final class SettingsStore: ObservableObject {
    enum LoadState: Equatable { case loading, ready, failed }
    @Published private(set) var value = AppSettings()
    @Published private(set) var errorMessage: String?
    @Published private(set) var loadState = LoadState.loading
    @Published private(set) var savePending = false
    let fileURL: URL

    struct Storage: Sendable {
        var read: @Sendable (URL) throws -> Data = SettingsStore.read
        var write: @Sendable (Data, URL) throws -> Void = SettingsStore.write
        var imported: @Sendable (URL) throws -> Data = SettingsStore.readImported
    }
    private enum Input: Sendable { case data(Data), file(URL) }
    private struct Import: Sendable {
        let revision: UInt64
        let input: Input
        let cancellation: Cancellation
        let receipt: CheckedContinuation<Void, Error>
    }
    /// Cancellation is accepted synchronously, including while file I/O is blocked.
    private final class Cancellation: @unchecked Sendable {
        private let lock = NSLock()
        private var cancelled = false
        func cancel() { lock.lock(); cancelled = true; lock.unlock() }
        func check() throws {
            lock.lock(); let stopped = cancelled; lock.unlock()
            if stopped { throw CancellationError() }
        }
    }
    /// UserDefaults is thread-safe. This immutable reference is only used by the
    /// storage lane, including legacy reads and removal after a successful write.
    private final class Legacy: @unchecked Sendable {
        let defaults: UserDefaults
        init(_ defaults: UserDefaults) { self.defaults = defaults }
        func migrated() -> AppSettings {
            var result = AppSettings()
            result.background.continuousLocation = defaults.bool(forKey: "background.continuousLocation")
            result.background.silentAudio = defaults.bool(forKey: "background.silentAudio")
            return result
        }
        func clear() {
            defaults.removeObject(forKey: "background.continuousLocation")
            defaults.removeObject(forKey: "background.silentAudio")
        }
    }
    private struct Loaded: Sendable { let value: AppSettings; let migrated: Bool }
    private struct Prepared: Sendable { let value: AppSettings; let backup: URL? }

    private let io = DispatchQueue(label: "Socks5.settings.io", qos: .utility)
    private let storage: Storage
    private let legacy: Legacy
    private var migrationPending = false
    private var busy = false
    private var revision: UInt64 = 0
    private var revisionExhausted = false
    private var durable: AppSettings?
    private var pending: AppSettings?
    private var pendingImport: Import?
    private var activeImport: Import?
    private var earlyEdits: [PartialKeyPath<AppSettings>: (inout AppSettings) -> Void] = [:]
    private var loadedWaiters: [CheckedContinuation<Void, Never>] = []
    private var flushWaiters: [CheckedContinuation<Void, Error>] = []
    private var storageFailure: Error?

    init(fileURL: URL? = nil, legacy: UserDefaults = .standard, storage: Storage = Storage()) {
        self.fileURL = fileURL ?? FileManager.default.urls(for: .applicationSupportDirectory,
            in: .userDomainMask)[0].appendingPathComponent("Socks5/settings.json")
        self.legacy = Legacy(legacy)
        self.storage = storage
        load()
    }

    func whenLoaded() async {
        guard loadState == .loading else { return }
        await withCheckedContinuation { loadedWaiters.append($0) }
    }

    func binding<Value>(_ path: WritableKeyPath<AppSettings, Value>) -> Binding<Value> {
        Binding(get: { self.value[keyPath: path] }, set: { self.set(path, $0) })
    }

    func set<Value>(_ path: WritableKeyPath<AppSettings, Value>, _ newValue: Value) {
        // Even an unchanged explicit Off invalidates a delayed import.
        advanceRevision()
        supersedeImports()
        var next = value
        next[keyPath: path] = newValue
        if loadState != .ready { earlyEdits[path] = { $0[keyPath: path] = newValue } }
        if next != value || savePending {
            pending = next // Reserve before publication: a reentrant newer edit wins.
            savePending = true
            value = next
        }
        if loadState == .failed, !busy { load() }
        else { pump() }
    }

    /// Explicit durability boundary, never a synchronous wait. Normal edits do not
    /// wait for it; a caller that must close/relaunch after saving can await it.
    func flush() async throws {
        await whenLoaded()
        if loadState == .failed { throw storageFailure ?? SettingsError.invalid("Settings are not loaded.") }
        if !busy, pending == nil, pendingImport == nil, !savePending { return }
        if pending == nil, savePending { pending = value }
        try await withCheckedThrowingContinuation { receipt in
            flushWaiters.append(receipt)
            pump()
        }
    }

    /// Validation and storage both run off MainActor. A successful import is
    /// published only after its file commit and a final live-intent revision check.
    func importData(_ data: Data) async throws { try await submit(.data(data)) }
    func importFile(_ url: URL) async throws { try await submit(.file(url)) }

    private func submit(_ input: Input) async throws {
        let cancellation = Cancellation()
        try await withTaskCancellationHandler {
            try Task.checkCancellation()
            try await withCheckedThrowingContinuation { receipt in
                advanceRevision()
                supersedeImports()
                guard !revisionExhausted else {
                    receipt.resume(throwing: SettingsError.invalid("Settings revision limit reached."))
                    return
                }
                pendingImport = Import(revision: revision, input: input,
                    cancellation: cancellation, receipt: receipt)
                pump()
            }
        } onCancel: { cancellation.cancel() }
    }

    private func advanceRevision() {
        if revision == UInt64.max { revisionExhausted = true }
        else { revision += 1 }
    }
    private func supersedeImports() {
        activeImport?.cancellation.cancel()
        if let old = pendingImport {
            pendingImport = nil
            old.cancellation.cancel()
            old.receipt.resume(throwing: CancellationError())
        }
    }

    private func load() {
        guard !busy else { return }
        busy = true
        loadState = .loading
        let target = fileURL, source = storage, legacy = legacy
        io.async { [self] in
            let result = Result { () throws -> Loaded in
                do { return Loaded(value: try AppSettings.decoded(source.read(target)), migrated: false) }
                catch let error as CocoaError where Self.missing(error) {
                    return Loaded(value: legacy.migrated(), migrated: true)
                }
            }
            DispatchQueue.main.async { [self] in
                busy = false
                switch result {
                case .success(let loaded):
                    var next = loaded.value
                    for edit in earlyEdits.values { edit(&next) }
                    earlyEdits.removeAll(keepingCapacity: true)
                    durable = loaded.migrated ? nil : loaded.value
                    migrationPending = loaded.migrated
                    if next != durable { pending = next; savePending = true }
                    value = next
                    storageFailure = nil
                    errorMessage = nil
                    loadState = .ready
                case .failure(let error):
                    // Never turn an inaccessible/corrupt existing file into a default save.
                    storageFailure = error
                    errorMessage = "Settings could not be loaded: \(error.localizedDescription)"
                    loadState = .failed
                }
                let waiters = loadedWaiters; loadedWaiters.removeAll()
                for waiter in waiters { waiter.resume() }
                pump()
            }
        }
    }

    private func pump() {
        guard !busy, loadState != .loading else { return }
        if loadState == .ready, let next = pending {
            pending = nil
            busy = true
            let target = fileURL, source = storage, cleanup = migrationPending ? legacy : nil
            io.async { [self] in
                let result = Result { try source.write(next.encoded(), target); cleanup?.clear() }
                DispatchQueue.main.async { [self] in
                    busy = false
                    switch result {
                    case .success:
                        durable = next
                        if cleanup != nil { migrationPending = false }
                        savePending = value != durable || pending != nil
                        if !savePending { storageFailure = nil; errorMessage = nil }
                    case .failure(let error):
                        storageFailure = error
                        savePending = true
                        errorMessage = "Settings could not be saved: \(error.localizedDescription)"
                    }
                    pump()
                }
            }
        } else if let request = pendingImport {
            pendingImport = nil
            do { try request.cancellation.check() }
            catch { request.receipt.resume(throwing: error); pump(); return }
            busy = true
            activeImport = request
            let target = fileURL, source = storage
            io.async { [self] in
                let result = Result { try Self.prepare(request, target: target, storage: source) }
                DispatchQueue.main.async { [self] in finishImport(request, result) }
            }
        } else {
            let waiters = flushWaiters; flushWaiters.removeAll()
            for waiter in waiters {
                if let failure = storageFailure { waiter.resume(throwing: failure) }
                else if savePending { waiter.resume(throwing: SettingsError.invalid("Settings are not durable yet.")) }
                else { waiter.resume() }
            }
        }
    }

    private func finishImport(_ request: Import, _ result: Result<Prepared, Error>) {
        switch result {
        case .failure(let error):
            busy = false
            activeImport = nil
            request.receipt.resume(throwing: error)
            pump()
        case .success(let prepared):
            let rejection: Error?
            do {
                try request.cancellation.check()
                guard request.revision == revision, !revisionExhausted else { throw CancellationError() }
                rejection = nil
            } catch { rejection = error }
            if rejection == nil {
                // This is the import's linearization point. A subsequent edit may
                // supersede it, but no later completion can republish this snapshot.
                durable = prepared.value
                pending = nil
                earlyEdits.removeAll(keepingCapacity: true)
                savePending = false
                storageFailure = nil
                errorMessage = nil
                value = prepared.value
                loadState = .ready
            }
            let target = fileURL, legacy = legacy
            let cleanupMigration = rejection == nil && migrationPending
            io.async { [self] in
                let cleanup = Result {
                    if rejection != nil { try Self.rollback(prepared.backup, target: target) }
                    else if let backup = prepared.backup { try FileManager.default.removeItem(at: backup) }
                    if cleanupMigration { legacy.clear() }
                }
                DispatchQueue.main.async { [self] in
                    busy = false
                    activeImport = nil
                    if case .failure(let error) = cleanup {
                        storageFailure = error
                        errorMessage = "Settings transaction cleanup failed: \(error.localizedDescription)"
                        request.receipt.resume(throwing: error)
                    } else {
                        if cleanupMigration { migrationPending = false }
                        if let rejection { request.receipt.resume(throwing: rejection) }
                        else { request.receipt.resume() }
                    }
                    pump()
                }
            }
        }
    }

    private nonisolated static func prepare(_ request: Import, target: URL, storage: Storage) throws -> Prepared {
        try request.cancellation.check()
        let data: Data
        switch request.input {
        case .data(let input): data = input
        case .file(let url): data = try storage.imported(url)
        }
        try request.cancellation.check()
        let next = try AppSettings.decoded(data)
        _ = try next.server.configuration()
        let encoded = try next.encoded()
        try request.cancellation.check()
        let directory = target.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let copy = directory.appendingPathComponent(".settings-\(UUID().uuidString).backup")
        var backup: URL?
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: target.path)
            guard let type = attributes[.type] as? FileAttributeType,
                  type == .typeRegular || type == .typeSymbolicLink else {
                throw SettingsError.invalid("The settings destination is not a file.")
            }
            try FileManager.default.copyItem(at: target, to: copy)
            backup = copy
        } catch let error as CocoaError where missing(error) { }
        do { try request.cancellation.check() }
        catch {
            if let backup { try FileManager.default.removeItem(at: backup) }
            throw error
        }
        do { try storage.write(encoded, target) }
        catch {
            do { try rollback(backup, target: target) }
            catch { throw SettingsError.invalid("Import rollback failed: \(error.localizedDescription)") }
            throw error
        }
        return Prepared(value: next, backup: backup)
    }

    private nonisolated static func rollback(_ backup: URL?, target: URL) throws {
        if let backup {
            // Same directory/filesystem: atomically restore the original file or
            // symlink, including an unreadable/oversized former configuration.
            guard rename(backup.path, target.path) == 0 else {
                throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
            }
        } else {
            do { try FileManager.default.removeItem(at: target) }
            catch let error as CocoaError where missing(error) { }
        }
    }
    private nonisolated static func missing(_ error: CocoaError) -> Bool {
        error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile
    }
    private nonisolated static func read(_ url: URL) throws -> Data {
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        return try file.read(upToCount: 65_537) ?? Data()
    }
    private nonisolated static func write(_ data: Data, _ url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        var options: Data.WritingOptions = [.atomic]
        #if os(iOS)
        options.insert(.completeFileProtectionUntilFirstUserAuthentication)
        #endif
        try data.write(to: url, options: options)
    }
    private nonisolated static func readImported(_ url: URL) throws -> Data {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        var coordinationError: NSError?
        var result: Result<Data, Error>?
        NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: url, options: [], error: &coordinationError) { url in
            result = Result { try read(url) }
        }
        if let coordinationError { throw coordinationError }
        guard let result else { throw SettingsError.invalid("The settings file could not be read.") }
        return try result.get()
    }
}
