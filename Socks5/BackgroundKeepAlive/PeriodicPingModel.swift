import Combine
import Foundation

/// The three user choices, not network status. Text is retained verbatim, including
/// unfinished input; the sender validates it without silently replacing it.
struct PeriodicPingPreferences: Codable, Equatable, Sendable {
    var enabled = false
    var destinations = "1.1.1.1"
    var period = "1000"

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.enabled == rhs.enabled &&
        lhs.destinations.utf8.elementsEqual(rhs.destinations.utf8) &&
        lhs.period.utf8.elementsEqual(rhs.period.utf8)
    }
}

/// App-root lifetime. Integrated uses SettingsStore as its only disk owner;
/// standalone supplies fileURL and uses one serial JSON lane below.
@MainActor
final class PeriodicPingModel: @MainActor ObservableObject {
    let objectWillChange = ObservableObjectPublisher()
    private var preferences = PeriodicPingPreferences()
    var enabled: Bool { preferences.enabled }
    var destinations: String { preferences.destinations }
    var period: String { preferences.period }
    private(set) var status = "Off"
    private(set) var storageError: String?
    private(set) var savePending = false
    var hasOwnStorage: Bool { fileURL != nil }
    var persistenceState: String {
        if let storageError { return "Settings error: " + storageError }
        if loading { return "Loading settings" }
        return savePending ? "Saving settings" : "Settings saved"
    }
    var canExport: Bool { ready }
    private let service = PeriodicPingService()
    private var request = UUID()
    private var intent = UUID()
    private struct Status: Sendable { let request: UUID; let text: String }
    private let updates: AsyncStream<Status>.Continuation
    private var delivery: Task<Void, Never>?

    struct Storage: Sendable {
        var read: @Sendable (URL) throws -> Data = { try Data(contentsOf: $0) }
        var write: @Sendable (Data, URL) throws -> Void = { data, url in
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            var options: Data.WritingOptions = [.atomic]
            #if os(iOS)
            options.insert(.completeFileProtectionUntilFirstUserAuthentication)
            #endif
            try data.write(to: url, options: options)
        }
    }
    static var standaloneURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Socks5/periodic-ping.json")
    }
    private let fileURL: URL?
    private let storage: Storage
    private let io = DispatchQueue(label: "hev.Socks5.periodic-ping.json", qos: .utility)
    private var loading = false
    private var ready = false
    private var loadID = UUID()
    private enum Field: Hashable { case enabled, destinations, period }
    private var earlyEdits = Set<Field>()
    private var durable: PeriodicPingPreferences?
    private var saving: PeriodicPingPreferences?
    private var waiters: [CheckedContinuation<Void, Error>] = []

    init(fileURL: URL? = nil, storage: Storage = Storage()) {
        self.fileURL = fileURL
        self.storage = storage
        ready = fileURL == nil
        let (stream, continuation) = AsyncStream<Status>.makeStream(bufferingPolicy: .bufferingNewest(1))
        updates = continuation
        delivery = Task { @MainActor [weak self] in
            for await value in stream { self?.receive(value) }
        }
        if fileURL != nil { load() }
    }

    deinit {
        updates.finish()
        delivery?.cancel()
        for waiter in waiters { waiter.resume(throwing: CancellationError()) }
        // Preserve the latest accepted edit after any already submitted write.
        // Releasing the sender never waits for disk I/O.
        let saved = durable
        if ready, let fileURL, preferences != (saving ?? saved) {
            let snapshot = preferences, write = storage.write
            io.async { try? write(JSONEncoder().encode(snapshot), fileURL) }
        }
    }

    private func receive(_ value: Status) {
        guard value.request == request, status != value.text else { return }
        status = value.text
        objectWillChange.send()
    }

    func setEnabled(_ value: Bool) {
        intent = UUID()
        // Even an unchanged explicit Off supersedes a delayed load/import.
        guard enabled != value || !value else { return }
        earlyEdits.insert(.enabled)
        preferences.enabled = value
        update()
    }

    func setDestinations(_ value: String) {
        guard !destinations.utf8.elementsEqual(value.utf8) else { return }
        intent = UUID()
        earlyEdits.insert(.destinations)
        preferences.destinations = value
        update()
    }

    func setPeriod(_ value: String) {
        guard !period.utf8.elementsEqual(value.utf8) else { return }
        intent = UUID()
        earlyEdits.insert(.period)
        preferences.period = value
        update()
    }

    /// Apply a loaded/imported snapshot as one intent, never three partial sends.
    func restore(enabled: Bool, destinations: String, period: String) {
        let next = PeriodicPingPreferences(enabled: enabled, destinations: destinations, period: period)
        guard preferences != next else { return }
        preferences = next
        update()
    }

    private func update() {
        let id = UUID()
        request = id
        status = ready ? (enabled ? "Starting" : "Off - stopping") : "Loading settings"
        let updates = self.updates
        if ready {
            service.configure(enabled: enabled, destinations: destinations, period: period) { value in
                updates.yield(Status(request: id, text: value))
            }
        } else {
            service.configure(nil) { _ in }
        }
        save()
        // Commit and submit before publication; synchronous reentrant Off wins.
        objectWillChange.send()
    }

    private func load() {
        guard let fileURL, !loading else { return }
        loading = true
        status = "Loading settings"
        let id = UUID()
        loadID = id
        let read = storage.read, lane = io
        Task { @MainActor [weak self] in
            let result: Result<(PeriodicPingPreferences, Bool), Error> = await withCheckedContinuation { receipt in
                lane.async {
                    receipt.resume(returning: Result {
                        do { return (try JSONDecoder().decode(PeriodicPingPreferences.self, from: read(fileURL)), false) }
                        catch let error as CocoaError where error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile {
                            return (PeriodicPingPreferences(), true)
                        }
                    })
                }
            }
            guard let self, self.loadID == id else { return }
            self.loading = false
            switch result {
            case .success(let (value, missing)):
                self.durable = missing ? nil : value
                // A user's edits made during loading override only their own fields.
                if !self.earlyEdits.contains(.enabled) { self.preferences.enabled = value.enabled }
                if !self.earlyEdits.contains(.destinations) { self.preferences.destinations = value.destinations }
                if !self.earlyEdits.contains(.period) { self.preferences.period = value.period }
                self.earlyEdits.removeAll()
                self.ready = true
                self.storageError = nil
                self.update()
                self.completeWaiters()
            case .failure(let error):
                self.storageError = error.localizedDescription
                self.status = "Settings could not be loaded"
                self.completeWaiters(error)
                self.objectWillChange.send()
            }
        }
    }

    private func save() {
        guard let fileURL, ready else { return }
        savePending = preferences != durable || saving != nil
        guard saving == nil, preferences != durable else { return }
        let snapshot = preferences, write = storage.write
        saving = snapshot
        savePending = true
        // Submit before returning so deinit can append the final edit after it.
        io.async { [weak self] in
            let result = Result { try write(JSONEncoder().encode(snapshot), fileURL) }
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.saving = nil
                switch result {
                case .success:
                    self.durable = snapshot
                    self.storageError = nil
                    self.savePending = self.preferences != snapshot
                    if self.savePending { self.save() }
                    else { self.completeWaiters() }
                case .failure(let error):
                    // A failed write leaves the disk snapshot uncertain.
                    self.durable = nil
                    self.storageError = error.localizedDescription
                    self.savePending = true
                    // A newer accepted edit gets its own attempt; never spin on failure.
                    if self.preferences != snapshot { self.save() }
                    else { self.completeWaiters(error) }
                }
                self.objectWillChange.send()
            }
        }
    }

    private func completeWaiters(_ error: Error? = nil) {
        guard error != nil || (!loading && saving == nil && !savePending) else { return }
        let pending = waiters
        waiters.removeAll()
        for waiter in pending {
            if let error { waiter.resume(throwing: error) } else { waiter.resume() }
        }
    }

    func flush() async throws {
        guard hasOwnStorage else { return }
        if !ready && !loading { load() }
        if ready && saving == nil && preferences != durable { save() }
        if ready && !savePending { return }
        try await withCheckedThrowingContinuation { waiters.append($0) }
    }

    func exportData() async throws -> Data {
        guard ready else { throw CocoaError(.fileReadUnknown) }
        let snapshot = preferences
        return try await Task.detached(priority: .utility) { try JSONEncoder().encode(snapshot) }.value
    }

    func importData(_ data: Data) async throws {
        let expected = UUID()
        intent = expected
        try await importData(data, expected: expected)
    }

    #if os(iOS)
    func importFile(_ url: URL) async throws {
        let expected = UUID()
        intent = expected
        let data = try await Task.detached(priority: .utility) {
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            var failure: NSError?
            var result: Result<Data, Error>?
            NSFileCoordinator(filePresenter: nil).coordinate(readingItemAt: url, options: [], error: &failure) { source in
                result = Result { try Data(contentsOf: source) }
            }
            if let failure { throw failure }
            guard let result else { throw CocoaError(.fileReadUnknown) }
            return try result.get()
        }.value
        try await importData(data, expected: expected)
    }
    #endif

    private func importData(_ data: Data, expected: UUID) async throws {
        let next = try await Task.detached(priority: .utility) {
            try JSONDecoder().decode(PeriodicPingPreferences.self, from: data)
        }.value
        try Task.checkCancellation()
        guard intent == expected else { throw CancellationError() }
        loadID = UUID()
        loading = false
        ready = true
        earlyEdits.removeAll()
        preferences = next
        storageError = nil
        update()
        try await flush()
    }
}
