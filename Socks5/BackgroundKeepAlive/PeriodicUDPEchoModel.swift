import Foundation
#if canImport(Combine)
import Combine
#endif

/// User intent and UI publication. Scheduling and file I/O have separate owners.
@MainActor
final class PeriodicUDPEchoModel: @MainActor ObservableObject {
    let objectWillChange = ObservableObjectPublisher()
    private(set) var settings = PeriodicUDPEchoSettings()
    private(set) var state = "Off"
    private(set) var sentCount: UInt64 = 0
    private(set) var storageError: String?
    private(set) var savePending = false
    private(set) var intentRevision: UInt64 = 0
    var enabled: Bool { settings.enabled }
    var destinations: String { settings.destinations }
    var period: String { settings.period }

    private let store: PeriodicUDPEchoStore?
    private let save: (@MainActor (PeriodicUDPEchoSettings) -> Void)?
    private var service: PeriodicUDPEchoService!
    private var saveTicket: UUID?

    init(store: PeriodicUDPEchoStore? = .init(),
         save: (@MainActor (PeriodicUDPEchoSettings) -> Void)? = nil,
         prepareObserver: (@Sendable () -> PeriodicUDPEchoService.IOObserver?)? = nil) {
        self.store = save == nil ? store : nil
        self.save = save
        service = PeriodicUDPEchoService(prepareObserver: prepareObserver) { [weak self] value in
            Task { @MainActor [weak self] in
                guard let self, service.isCurrent(value.generation),
                      state != value.text || sentCount != value.sentCount else { return }
                state = value.text
                sentCount = value.sentCount
                objectWillChange.send()
            }
        }
        self.store?.load { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self, intentRevision == 0 else { return }
                switch result {
                case .success(let value):
                    if let value { restore(value, ifRevision: 0) }
                case .failure(let error):
                    storageError = error.localizedDescription
                    objectWillChange.send()
                }
            }
        }
    }

    deinit { service.shutdown() }

    func setEnabled(_ value: Bool) {
        var next = settings
        next.enabled = value
        apply(next, persist: true)
    }

    func setDestinations(_ value: String) {
        var next = settings
        next.destinations = value
        apply(next, persist: true)
    }

    func setPeriod(_ value: String) {
        var next = settings
        next.period = value
        apply(next, persist: true)
    }

    /// The caller can bind a delayed import/load to the intent it observed.
    func restore(_ value: PeriodicUDPEchoSettings, ifRevision expected: UInt64? = nil) {
        guard expected == nil || expected == intentRevision else { return }
        apply(value, persist: false)
    }

    func setServer(_ configuration: Socks5UDPClient.Configuration?, runID: UUID?) {
        service.setServer(configuration, runID: runID)
    }

    func setServer(resolve: PeriodicUDPEchoService.ServerResolver?, runID: UUID?) {
        service.setServer(resolve: resolve, runID: runID)
    }

    func retrySave() {
        persist(settings, revision: intentRevision)
        objectWillChange.send()
    }

    private func apply(_ value: PeriodicUDPEchoSettings, persist shouldPersist: Bool) {
        let changed = settings != value
        if value.enabled && !settings.enabled { sentCount = 0 }
        settings = value
        intentRevision &+= 1
        // Even an explicit Off matching defaults invalidates a pending old load.
        if changed || !value.enabled {
            service.update(value)
            state = value.enabled ? "Preparing UDP Echo" : "Off"
        }
        storageError = nil
        if shouldPersist { persist(value, revision: intentRevision) }
        else {
            saveTicket = nil
            savePending = false
        }
        // Every field is settled before reentrant observers can accept a newer intent.
        objectWillChange.send()
    }

    private func persist(_ value: PeriodicUDPEchoSettings, revision: UInt64) {
        if let save {
            save(value)
        } else if let store {
            let ticket = UUID()
            saveTicket = ticket
            savePending = true
            store.save(value) { [weak self] result in
                Task { @MainActor [weak self] in
                    guard let self, intentRevision == revision, saveTicket == ticket else { return }
                    saveTicket = nil
                    savePending = false
                    if case .failure(let error) = result { storageError = error.localizedDescription }
                    else { storageError = nil }
                    objectWillChange.send()
                }
            }
        }
    }
}
