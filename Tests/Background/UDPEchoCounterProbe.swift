import Foundation
#if canImport(Combine)
import Combine
#endif

/// Only the post-syscall observation is held; the production client, admission,
/// scheduler and model run unchanged against independent real SOCKS5 peers.
private final class AcceptedDatagrams: @unchecked Sendable {
    private let lock = NSLock()
    private let release = DispatchSemaphore(value: 0)
    private let reached = DispatchSemaphore(value: 0)
    private let relayPorts: Set<UInt16>
    private var writes = 0
    private var holdAt = 0
    private var held = false
    private var notifyHold = false

    init(relayPorts: Set<UInt16>) { self.relayPorts = relayPorts }

    func observe(_ peer: Socks5UDPClient.Address, bytes: Int, sent: Bool) {
        // These no-auth IPv4 fixtures write 3/10-byte TCP requests and complete
        // 11-byte UDP requests. Both checks disambiguate any cross-protocol port reuse.
        guard sent, bytes == 11, relayPorts.contains(peer.port) else { return }
        lock.lock()
        writes += 1
        let shouldHold = writes == holdAt
        let shouldNotify = shouldHold && notifyHold
        if shouldHold { held = true }
        lock.unlock()
        if shouldHold {
            if shouldNotify { reached.signal() }
            precondition(release.wait(timeout: .now() + 3) == .success, "COUNT_OBSERVER_RELEASE")
        }
    }

    func arm(at count: Int, notify: Bool = false) {
        lock.lock()
        holdAt = count
        held = false
        notifyHold = notify
        lock.unlock()
    }

    func resume() { release.signal() }

    func waitUntilHeld() {
        precondition(reached.wait(timeout: .now() + 2) == .success, "COUNT_MAIN_EXECUTOR_HOLD")
    }

    func snapshot() -> (writes: Int, held: Bool) {
        lock.lock()
        defer { lock.unlock() }
        return (writes, held)
    }
}

@main
private struct UDPEchoCounterProbe {
    @MainActor
    private static func require(_ condition: Bool, _ marker: String) {
        guard condition else {
            FileHandle.standardError.write(Data(("COUNTER_PREDICATE: " + marker + "\n").utf8))
            preconditionFailure(marker)
        }
    }

    @MainActor
    private static func wait(_ marker: String, until condition: () -> Bool) async throws {
        let deadline = DispatchTime.now().uptimeNanoseconds + 2_000_000_000
        while !condition() {
            require(DispatchTime.now().uptimeNanoseconds < deadline, marker)
            try await Task.sleep(for: .milliseconds(5))
        }
    }

    @MainActor
    static func main() async throws {
        let arguments = CommandLine.arguments
        require(arguments.count == 11, "FIVE_SERVER_AND_RELAY_PORTS")
        let controls = arguments[1...5].map { UInt16($0)! }
        let metrics = AcceptedDatagrams(relayPorts: Set(arguments[6...10].map { UInt16($0)! }))
        let model = PeriodicUDPEchoModel(store: nil, prepareObserver: {
            { metrics.observe($0, bytes: $1, sent: $2) }
        })
        defer { metrics.resume(); model.setEnabled(false) }
        var watchNewZero = false
        var stalePublication = false
        func observePublication() {
            if watchNewZero && model.sentCount != 0 { stalePublication = true }
        }
        #if canImport(Combine)
        let subscription = model.objectWillChange.sink { _ in observePublication() }
        defer { subscription.cancel() }
        #else
        model.objectWillChange.receive = observePublication
        defer { model.objectWillChange.receive = nil }
        #endif
        func server(_ index: Int) {
            model.setServer(.init(server: .init(host: "127.0.0.1", port: controls[index])!), runID: UUID())
        }
        model.setDestinations("127.0.0.1")
        model.setPeriod("20")

        // A successful syscall can finish its observation after Off. It belongs
        // to the ending On episode and is included in its final displayed count.
        metrics.arm(at: 6)
        server(0)
        model.setEnabled(true)
        require(model.sentCount == 0, "FIRST_ON_ZERO")
        try await wait("FIRST_ACCEPTED_SIX") { metrics.snapshot() == (6, true) }
        model.setEnabled(false)
        metrics.resume()
        try await wait("OFF_FLUSHES_ACCEPTED_COUNT") { model.state == "Off" && model.sentCount == 6 }
        let firstEpisode = model.sentCount
        try await Task.sleep(for: .milliseconds(40))
        require(metrics.snapshot().writes == 6 && model.sentCount == 6, "OFF_RETAINS_FINAL_COUNT")

        model.setServer(nil, runID: nil)
        model.setEnabled(true)
        require(model.sentCount == 0, "SECOND_ON_ZERO")
        try await wait("WAITING_ZERO") { model.state == "Waiting for SOCKS5 server" && model.sentCount == 0 }

        // Both a new server run and edited settings are within this same On.
        metrics.arm(at: 12)
        server(1)
        try await wait("SECOND_ACCEPTED_SIX") { metrics.snapshot() == (12, true) }
        metrics.arm(at: 18)
        model.setPeriod("25")
        server(2)
        metrics.resume()
        try await wait("REPLACEMENT_ACCEPTED_SIX") { metrics.snapshot() == (18, true) }
        model.setDestinations("invalid.example")
        metrics.resume()
        try await wait("INVALID_RETAINS_COUNT") {
            model.state.contains("Enter numeric IPv4") && model.sentCount == 12
        }
        let continuingEpisode = model.sentCount

        metrics.arm(at: 24, notify: true)
        model.setDestinations("127.0.0.1")
        server(3)
        // This synchronous test-only hold also leaves the old State tasks queued
        // on MainActor. An async sleep would let them drain before Off/On.
        metrics.waitUntilHeld()
        require(metrics.snapshot() == (24, true), "RESTORED_INPUT_ACCEPTED_SIX")
        // Off and On are deliberately coalesced while the network queue is held.
        // The accepted old datagram and delayed old UI tasks must not enter new On.
        model.setEnabled(false)
        model.setEnabled(true)
        watchNewZero = true
        model.setServer(nil, runID: nil)
        require(model.sentCount == 0, "COALESCED_ON_ZERO")
        metrics.resume()
        try await wait("COALESCED_WAITING_ZERO") {
            model.state == "Waiting for SOCKS5 server" && model.sentCount == 0
        }
        try await Task.sleep(for: .milliseconds(550))
        require(model.sentCount == 0 && metrics.snapshot().writes == 24 && !stalePublication,
                "STALE_EPISODE_REJECTED")
        watchNewZero = false

        metrics.arm(at: 30)
        server(4)
        try await wait("NEW_EPISODE_ACCEPTED_SIX") { metrics.snapshot() == (30, true) }
        model.setEnabled(false)
        metrics.resume()
        try await wait("NEW_EPISODE_OFF_SIX") { model.state == "Off" && model.sentCount == 6 }
        model.setEnabled(false)
        model.setDestinations("invalid.example")
        require(model.sentCount == 6, "OFF_EDIT_PRESERVES_COUNT")
        model.setEnabled(true)
        require(model.sentCount == 0, "INVALID_ON_ZERO")
        try await wait("INVALID_ON_NO_SEND") { model.state.contains("Enter numeric IPv4") }
        require(model.sentCount == 0 && metrics.snapshot().writes == 30, "ERROR_IS_NOT_A_SEND")

        let result: [String: Any] = ["acceptedDatagrams": metrics.snapshot().writes,
                                     "firstEpisode": firstEpisode,
                                     "sameOnAfterServerAndInputChanges": continuingEpisode,
                                     "newEpisodeFinalCount": 6,
                                     "coalescedOffOnReset": true, "staleEpisodeRejected": true,
                                     "replyRequired": false]
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result, options: .sortedKeys) + Data([10]))
    }
}
