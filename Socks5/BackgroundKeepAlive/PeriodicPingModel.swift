import Combine
import Foundation

/// App-root lifetime; tab changes never stop the sender. Controls are session-only
/// so the existing portable Settings schema and restoration semantics stay unchanged.
@MainActor
final class PeriodicPingModel: @MainActor ObservableObject {
    let objectWillChange = ObservableObjectPublisher()
    private(set) var enabled = false
    private(set) var destinations = "1.1.1.1"
    private(set) var period = "1000"
    private(set) var status = "Off"
    private let service = PeriodicPingService()
    private var request = UUID()
    private struct Status: Sendable { let request: UUID; let text: String }
    private let updates: AsyncStream<Status>.Continuation
    private var delivery: Task<Void, Never>?

    init() {
        let (stream, continuation) = AsyncStream<Status>.makeStream(bufferingPolicy: .bufferingNewest(1))
        updates = continuation
        delivery = Task { @MainActor [weak self] in
            for await value in stream { self?.receive(value) }
        }
    }

    deinit {
        updates.finish()
        delivery?.cancel()
    }

    private func receive(_ value: Status) {
        guard value.request == request, status != value.text else { return }
        status = value.text
        objectWillChange.send()
    }

    func setEnabled(_ value: Bool) {
        guard enabled != value else { return }
        enabled = value
        update()
    }

    func setDestinations(_ value: String) {
        guard destinations != value else { return }
        destinations = value
        update()
    }

    func setPeriod(_ value: String) {
        guard period != value else { return }
        period = value
        update()
    }

    private func update() {
        let id = UUID()
        request = id
        let configuration: PeriodicPingConfiguration?
        var validation: String?
        do {
            let parsed = try PeriodicPingConfiguration(destinations: destinations, period: period)
            configuration = enabled ? parsed : nil
        } catch {
            configuration = nil
            validation = error.localizedDescription
        }
        let message = validation
        status = message ?? (enabled ? "Starting" : "Off - stopping")
        let updates = self.updates
        service.configure(configuration) { value in
            updates.yield(Status(request: id, text: message ?? value))
        }
        // Publish after submitting intent. A reentrant newer Off is queued last.
        objectWillChange.send()
    }
}
