import Foundation

// Controlled state-machine fixture only. This does not invoke AVFAudio or UIKit.
final class RelapseLocked<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

enum RelapseObservation {
    static let clearedEnds = RelapseLocked([Int]())
    // Called in BOTH copied lease inputs immediately after EndGate clears its
    // state, outside its lock. Waiting for provider.end alone races that clear.
    static func endGateDidClear(_ id: Int) { clearedEnds.use { $0.append(id) } }
}

final class RelapseClaims: @unchecked Sendable {
    struct State {
        var requests = 0
        var ended = [Int]()
        var live = Set<Int>()
        var peak = 0
        var expire: (@Sendable () -> Void)?
        var lateReceipt: (@Sendable (Int?) -> Void)?
    }
    let mode: String
    let state = RelapseLocked(State())
    init(_ mode: String) { self.mode = mode }
    var provider: RecoveryExecutionLease.Provider {
        .init(request: { [self] expire, receipt in
            let id = state.use { value -> Int in
                value.requests += 1
                value.expire = expire
                if mode == "missing" { value.lateReceipt = receipt }
                if mode != "denied" && mode != "missing" {
                    value.live.insert(value.requests)
                    value.peak = max(value.peak, value.live.count)
                }
                return value.requests
            }
            if mode == "denied" { receipt(nil) }
            else if mode != "missing" { receipt(id) }
        }, end: { [self] id in
            state.use { value in value.ended.append(id); value.live.remove(id) }
        })
    }
    func expire() { state.use { $0.expire }?() }
    func deliverLateReceipt() {
        let receipt = state.use { value -> (@Sendable (Int?) -> Void)? in
            let receipt = value.lateReceipt
            value.lateReceipt = nil
            if receipt != nil { value.live.insert(1); value.peak = max(value.peak, value.live.count) }
            return receipt
        }
        receipt?(1)
    }
}

final class RelapseEndpoint: LoopAudioEndpoint, @unchecked Sendable {
    struct Pending {
        let name: String
        let context: LoopAudioService.Context
        let generation: UInt64
        let completion: @Sendable (LoopAudioService.Reply) -> Void
    }
    struct State {
        var pending: Pending?
        var commands = [String]()
        var healthyInspectReplies = 0
        var generation: UInt64 = 0
    }
    enum ResultKind { case healthy, stopped, misconfigured, failed, superseded }
    let state = RelapseLocked(State())
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        let name: String
        switch command {
        case .start: name = "start"
        case .inspect: name = "inspect"
        case .stop: name = "stop"
        }
        state.use { value in
            precondition(value.pending == nil, "FIXTURE_OVERLAPPING_OPERATIONS")
            value.commands.append(name)
            if name == "start" { value.generation = context.id }
            if name != "stop" {
                value.pending = Pending(name: name, context: context,
                    generation: value.generation, completion: completion)
            }
        }
        if name == "stop" { completion(.init()) }
    }
    var pendingName: String? { state.use { $0.pending?.name } }
    @discardableResult func reply(_ result: ResultKind) -> UInt64? {
        let pending = state.use { value -> Pending? in
            let pending = value.pending
            value.pending = nil
            if pending?.name == "inspect", case .healthy = result { value.healthyInspectReplies += 1 }
            return pending
        }
        guard let pending else { return nil }
        switch result {
        case .failed: pending.completion(.init(error: "controlled transient failure"))
        case .superseded: pending.completion(.init(superseded: true))
        default:
            let now = ProcessInfo.processInfo.systemUptime
            let playing: Bool
            let configured: Bool
            switch result {
            case .stopped: playing = false; configured = true
            case .misconfigured: playing = true; configured = false
            default: playing = true; configured = true
            }
            pending.completion(.init(sample: .init(generation: pending.generation,
                epoch: pending.context.epoch, playing: playing, configured: configured,
                position: now.truncatingRemainder(dividingBy: 0.05), deviceTime: now,
                duration: 0.05, rate: 1, startedAt: now, finishedAt: now, bufferDuration: 0.001)))
        }
        return pending.context.id
    }
}

struct RelapseFailure: Error { let marker: String }

@main struct EarlyRelapseTests {
    @MainActor static var assertions = 0
    @MainActor static var observations = [[String: String]]()
    @MainActor static func check(_ value: Bool, _ marker: String) throws {
        assertions += 1
        if !value { throw RelapseFailure(marker: marker) }
    }
    @MainActor static func wait(_ condition: () -> Bool, seconds: Double = 3) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + seconds
        while !condition() && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try check(condition(), "FIXTURE_REQUIRED_BOUNDARY_NOT_OBSERVED")
    }
    @MainActor static func diagnostics(_ service: LoopAudioService) async -> LoopAudioService.Diagnostics {
        await withCheckedContinuation { continuation in
            service.diagnostics { value in continuation.resume(returning: value) }
        }
    }
    @MainActor static func complete(_ endpoint: RelapseEndpoint, _ service: LoopAudioService,
                                    _ result: RelapseEndpoint.ResultKind) async throws {
        guard let id = endpoint.reply(result) else { throw RelapseFailure(marker: "FIXTURE_NO_PENDING_REPLY") }
        // reply enqueues finish before returning. This diagnostic is enqueued
        // after it on the same control queue; it is an ordering proof, not sleep.
        let value = await diagnostics(service)
        try check(value.completedOperations >= id, "FIXTURE_REPLY_NOT_CONSUMED")
    }
    @MainActor static func nextStart(_ endpoint: RelapseEndpoint) async throws {
        try await wait {
            // An inspection can already be pending when invalidation is accepted.
            // Never supply healthy inspection evidence in the early-relapse case.
            if endpoint.pendingName == "inspect" { endpoint.reply(.superseded) }
            return endpoint.pendingName == "start"
        }
    }
    @MainActor static func observe(_ label: String, _ claims: RelapseClaims,
                                   _ endpoint: RelapseEndpoint) {
        let value = claims.state.use { $0 }
        observations.append(["boundary": label, "requests": String(value.requests),
            "ends": String(describing: value.ended), "live": String(value.live.count),
            "endGateClears": String(describing: RelapseObservation.clearedEnds.use { $0 }),
            "healthyInspectReplies": String(endpoint.state.use { $0.healthyInspectReplies })])
    }
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 2 else { exit(2) }
        let name = CommandLine.arguments[1]
        let allowed = ["early-relapse", "healthy-inspection-relapse", "continuous-granted",
                       "continuous-denied", "continuous-expired", "continuous-missing", "stale-success"]
        guard allowed.contains(name) else { exit(2) }
        let mode = name.hasPrefix("continuous-") ? String(name.dropFirst("continuous-".count)) : "granted"
        let claims = RelapseClaims(mode)
        let endpoint = RelapseEndpoint()
        let visible = RelapseLocked(LoopAudioService.State())
        let service = LoopAudioService(leaseProvider: { claims.provider }) { _, _ in endpoint }
        let owner = service.register { state in visible.use { $0 = state } }
        let began = ProcessInfo.processInfo.systemUptime
        var failures = [String]()
        do {
            service.setEnabled(true, owner: owner)
            try await nextStart(endpoint)
            try check(claims.state.use { $0.requests == 1 }, "INITIAL_CLAIM_NOT_REQUESTED")
            if name.hasPrefix("continuous-") {
                if mode == "expired" {
                    claims.expire()
                    try await wait { RelapseObservation.clearedEnds.use { $0 == [1] } }
                }
                for result in [RelapseEndpoint.ResultKind.stopped, .misconfigured, .failed, .superseded] {
                    service.notify(.hint)
                    service.notify(.available)
                    try await complete(endpoint, service, result)
                    try await nextStart(endpoint)
                    observe("unhealthy retry", claims, endpoint)
                    try check(claims.state.use { $0.requests == 1 }, "CONTINUOUS_FAILURE_RENEWED_CLAIM")
                }
                try await complete(endpoint, service, .healthy)
            } else if name == "stale-success" {
                service.notify(.decoderFailed)
                try await complete(endpoint, service, .healthy)
                try await nextStart(endpoint)
                observe("stale healthy reply rejected", claims, endpoint)
                try check(claims.state.use { $0.requests == 1 && $0.ended.isEmpty },
                          "STALE_HEALTHY_REPLY_CLOSED_EPISODE")
                try await complete(endpoint, service, .healthy)
            } else {
                let episodes = name == "early-relapse" ? 3 : 2
                for episode in 1...episodes {
                    try await complete(endpoint, service, .healthy)
                    try await wait { RelapseObservation.clearedEnds.use { $0.count == episode } }
                    observe("accepted healthy start \(episode)", claims, endpoint)
                    if episode == episodes { break }
                    if name == "healthy-inspection-relapse" {
                        try await wait { endpoint.pendingName == "inspect" }
                        try await complete(endpoint, service, .healthy)
                    }
                    service.notify(.decoderFailed)
                    try await nextStart(endpoint)
                    observe("known failure after healthy \(episode)", claims, endpoint)
                    try check(claims.state.use { $0.requests == episode + 1 },
                              "ACCEPTED_HEALTHY_RELAPSE_DID_NOT_REQUEST_NEW_CLAIM")
                }
                if name == "early-relapse" {
                    try check(endpoint.state.use { $0.healthyInspectReplies == 0 }, "EARLY_RELAPSE_USED_HEALTHY_INSPECTION")
                }
            }
        } catch let error as RelapseFailure { failures.append(error.marker) }
        catch { failures.append("FIXTURE_UNEXPECTED_ERROR: \(error)") }

        // Preserve the original failure while performing bounded cleanup.
        var cleanupPassed = false
        service.setEnabled(false, owner: owner)
        endpoint.reply(.superseded)
        claims.deliverLateReceipt()
        do {
            try await wait({
                if endpoint.pendingName != nil { endpoint.reply(.superseded) }
                return visible.use { $0.text == "Off" }
            }, seconds: 5)
            try await wait({ claims.state.use { $0.live.isEmpty } }, seconds: 5)
            let value = await diagnostics(service)
            try check(value.operation == nil && !value.timerActive && value.maximumOutstanding == 1,
                      "FINAL_SINGLE_FLIGHT_OR_TIMER_NOT_DRAINED")
            let state = claims.state.use { $0 }
            try check(Set(state.ended).count == state.ended.count && state.peak <= 1,
                      "CLAIM_END_IDENTITY_OR_CONCURRENCY_BOUND")
            let expectedEnds = mode == "denied" ? 0 : state.requests
            try check(state.ended.count == expectedEnds, "FINAL_GRANTED_CLAIM_NOT_BALANCED")
            cleanupPassed = true
        } catch let error as RelapseFailure { failures.append(error.marker) }
        catch { failures.append("FIXTURE_CLEANUP_ERROR: \(error)") }
        service.unregister(owner)
        observe("final", claims, endpoint)
        let state = claims.state.use { $0 }
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "assertions": assertions, "cleanup_passed": cleanupPassed,
            "requests": state.requests, "ended_ids": state.ended, "maximum_live_claims": state.peak,
            "commands": endpoint.state.use { $0.commands }, "observations": observations,
            "elapsed_seconds": ProcessInfo.processInfo.systemUptime - began,
            "shipping_interval_seconds": 0.5, "scope": "Controlled service/lease state machine; no OS grant, AV runtime, or physical playback proof"]
        do {
            let raw = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
            print(String(decoding: raw, as: UTF8.self))
        } catch { FileHandle.standardError.write(Data("FIXTURE_RESULT_ENCODING_FAILED\n".utf8)); exit(2) }
        for failure in failures { FileHandle.standardError.write(Data((failure + "\n").utf8)) }
        exit(failures.isEmpty ? 0 : 74)
    }
}
