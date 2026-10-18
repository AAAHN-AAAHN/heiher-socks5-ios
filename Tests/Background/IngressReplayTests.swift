import Foundation

// Controlled scheduling fixture. No AVFAudio/UIKit objects or OS grants occur.
final class IngressLocked<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

enum IngressObservation {
    static let armed = IngressLocked(false)
    static let entered = IngressLocked(false)
    static let returned = IngressLocked(false)
    static let timedOut = IngressLocked(false)
    static let release = DispatchSemaphore(value: 0)
    static let clearedEnds = IngressLocked([Int]())
    static let admissionArmed = IngressLocked(Optional<String>.none)
    static let admissionEntered = IngressLocked(false)
    static let admissionReturned = IngressLocked(false)
    static let admissionTimedOut = IngressLocked(false)
    static let admissionRelease = DispatchSemaphore(value: 0)

    // Added to every copied service input at the same existing unlock/dispatch
    // boundary. Only the posting thread pauses; control, I/O and timer are real.
    static func beforeDrainEnqueue(_ event: LoopAudioService.Event, scheduled: Bool) {
        guard scheduled else { return }
        switch event {
        case .interrupted, .decoderFailed, .mediaLost, .mediaReset: break
        default: return
        }
        let hold = armed.use { value -> Bool in
            guard value else { return false }
            value = false
            return true
        }
        guard hold else { return }
        entered.use { $0 = true }
        if release.wait(timeout: .now() + 10) != .success { timedOut.use { $0 = true } }
    }

    // Observation only, outside the original EndGate lock, for both inputs.
    static func endGateDidClear(_ id: Int) { clearedEnds.use { $0.append(id) } }

    // A caller chose inspect or reuse before begin reads the latest ticket.
    // Pause exactly that control-lane boundary, then accept a real invalidation.
    static func beforeAdmission(_ command: LoopAudioService.Command) {
        let name: String
        switch command {
        case .inspect: name = "inspect"
        case .start(false): name = "reuse"
        default: return
        }
        let hold = admissionArmed.use { value -> Bool in
            guard value == name else { return false }
            value = nil
            return true
        }
        guard hold else { return }
        admissionEntered.use { $0 = true }
        if admissionRelease.wait(timeout: .now() + 10) != .success { admissionTimedOut.use { $0 = true } }
        admissionReturned.use { $0 = true }
    }
}

struct IngressSnapshot: Sendable {
    let on: Bool
    let epoch: UInt64
    let latestEpoch: UInt64
    let playing: Bool
    let rebuild: Bool
    let episode: Bool
    let operation: UInt64?
    let command: String?
    let invalidationPending: Bool
    let completed: UInt64
    let timerActive: Bool
    let maximumOutstanding: Int
}

final class IngressClaims: Sendable {
    struct State {
        var requests = 0
        var live = Set<Int>()
        var ended = [Int]()
        var peak = 0
    }
    let state = IngressLocked(State())
    var provider: RecoveryExecutionLease.Provider {
        .init(request: { [self] _, receipt in
            let id = state.use { value -> Int in
                value.requests += 1
                value.live.insert(value.requests)
                value.peak = max(value.peak, value.live.count)
                return value.requests
            }
            receipt(id)
        }, end: { [self] id in
            state.use { value in value.live.remove(id); value.ended.append(id) }
        })
    }
}

final class IngressEndpoint: LoopAudioEndpoint, Sendable {
    struct Pending {
        let name: String
        let context: LoopAudioService.Context
        let generation: UInt64
        let completion: @Sendable (LoopAudioService.Reply) -> Void
    }
    struct State {
        var pending: Pending?
        var generation: UInt64 = 0
        var commands = [String]()
        var startEpochs = [UInt64]()
        var startRebuilds = [Bool]()
    }
    let state = IngressLocked(State())
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        let name: String
        let requestedRebuild: Bool
        switch command {
        case .start(let rebuild): name = "start"; requestedRebuild = rebuild
        case .inspect: name = "inspect"; requestedRebuild = false
        case .stop: name = "stop"; requestedRebuild = false
        }
        state.use { value in
            precondition(value.pending == nil, "FIXTURE_OVERLAPPING_OPERATIONS")
            value.commands.append(name)
            if name == "start" {
                value.generation = context.id
                value.startEpochs.append(context.epoch)
                value.startRebuilds.append(requestedRebuild)
            }
            if name != "stop" {
                value.pending = Pending(name: name, context: context,
                    generation: value.generation, completion: completion)
            }
        }
        if name == "stop" { completion(.init()) }
    }
    var pendingName: String? { state.use { $0.pending?.name } }
    @discardableResult func reply(healthy: Bool, stopped: Bool = false) -> UInt64? {
        let pending = state.use { value -> Pending? in
            let pending = value.pending
            value.pending = nil
            return pending
        }
        guard let pending else { return nil }
        if healthy {
            let now = ProcessInfo.processInfo.systemUptime
            pending.completion(.init(sample: .init(generation: pending.generation,
                epoch: pending.context.epoch, playing: !stopped, configured: true,
                position: now.truncatingRemainder(dividingBy: 0.05), deviceTime: now,
                duration: 0.05, rate: 1, startedAt: now, finishedAt: now, bufferDuration: 0.001)))
        } else {
            pending.completion(.init(superseded: true))
        }
        return pending.context.id
    }
}

struct IngressFailure: Error { let marker: String }

@main struct IngressReplayTests {
    @MainActor static var assertions = 0
    @MainActor static var observations = [[String: String]]()
    @MainActor static func check(_ condition: Bool, _ marker: String) throws {
        assertions += 1
        if !condition { throw IngressFailure(marker: marker) }
    }
    @MainActor static func wait(_ marker: String, _ condition: () -> Bool, seconds: Double = 3) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + seconds
        while !condition() && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try check(condition(), marker)
    }
    @MainActor static func snapshot(_ service: LoopAudioService) async -> IngressSnapshot {
        await withCheckedContinuation { continuation in
            service.auditIngressSnapshot { continuation.resume(returning: $0) }
        }
    }
    @MainActor static func observe(_ label: String, _ service: LoopAudioService,
                                   _ endpoint: IngressEndpoint, _ claims: IngressClaims) async -> IngressSnapshot {
        let value = await snapshot(service)
        observations.append(["boundary": label, "on": String(value.on), "epoch": String(value.epoch),
            "latest_epoch": String(value.latestEpoch),
            "playing": String(value.playing), "rebuild": String(value.rebuild), "episode": String(value.episode),
            "operation": value.operation.map(String.init) ?? "nil", "command": value.command ?? "nil",
            "invalidation_pending": String(value.invalidationPending),
            "starts": String(endpoint.state.use { $0.startEpochs.count }),
            "claims": String(claims.state.use { $0.requests }),
            "end_gate_clears": String(describing: IngressObservation.clearedEnds.use { $0 })])
        return value
    }
    @MainActor static func nextStart(_ endpoint: IngressEndpoint) async throws {
        try await wait("FIXTURE_REPLACEMENT_START_NOT_OBSERVED") {
            // If inspection had entered just before ingress accepted the new
            // epoch, release its obsolete result; no replacement healthy evidence.
            if endpoint.pendingName == "inspect" { endpoint.reply(healthy: false) }
            return endpoint.pendingName == "start"
        }
    }
    @MainActor static func complete(_ endpoint: IngressEndpoint, _ service: LoopAudioService, stopped: Bool = false) async throws {
        guard let id = endpoint.reply(healthy: true, stopped: stopped) else { throw IngressFailure(marker: "FIXTURE_NO_PENDING_REPLY") }
        // finish was enqueued before reply returned. This is a control-queue
        // barrier proving actual consumption, rather than an elapsed-time guess.
        let value = await snapshot(service)
        try check(value.completed >= id, "FIXTURE_HEALTHY_REPLY_NOT_CONSUMED")
    }
    @MainActor static func waitForAdoption(_ service: LoopAudioService) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        var value = await snapshot(service)
        while value.epoch != 1 && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 1_000_000)
            value = await snapshot(service)
        }
        try check(value.epoch == 1 && value.invalidationPending, "FIXTURE_TIMER_ADOPTION_NOT_OBSERVED")
    }
    @MainActor static func releaseIngress(_ service: LoopAudioService) async throws {
        IngressObservation.release.signal()
        try await wait("FIXTURE_POSTING_THREAD_NOT_RELEASED") { IngressObservation.returned.use { $0 } }
        // notify dispatched its drain before returning. This read is queued after
        // that drain on the same control queue, including when a timer consumed it.
        _ = await snapshot(service)
        try check(!IngressObservation.timedOut.use { $0 }, "FIXTURE_INGRESS_HOLD_TIMED_OUT")
    }
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 2 else { exit(2) }
        let name = CommandLine.arguments[1]
        let cases = ["recovered-interrupted", "recovered-media-reset", "pending-interrupted",
                     "pending-media-reset", "pending-inspection", "off-before-drain", "off-on-before-drain",
                     "second-during-replacement", "second-after-recovery", "admit-inspect-invalidated", "admit-reuse-invalidated"]
        guard cases.contains(name) else { exit(2) }
        let endpoint = IngressEndpoint()
        let claims = IngressClaims()
        let visible = IngressLocked(LoopAudioService.State())
        let service = LoopAudioService(leaseProvider: { claims.provider }) { _, _ in endpoint }
        let owner = service.register { state in visible.use { $0 = state } }
        let began = ProcessInfo.processInfo.systemUptime
        var failures = [String]()
        do {
            service.setEnabled(true, owner: owner)
            try await nextStart(endpoint)
            try await complete(endpoint, service)
            try await wait("FIXTURE_INITIAL_CLAIM_END_NOT_OBSERVED") {
                IngressObservation.clearedEnds.use { $0 == [1] }
            }
            if name.hasPrefix("admit-") {
                if name == "admit-reuse-invalidated" {
                    try await wait("FIXTURE_INSPECTION_NOT_ENTERED") { endpoint.pendingName == "inspect" }
                    IngressObservation.admissionArmed.use { $0 = "reuse" }
                    // Do not queue an awaited control read behind the upcoming
                    // admission hold; the entered flag proves finish progressed.
                    try check(endpoint.reply(healthy: true, stopped: true) != nil, "FIXTURE_NO_PENDING_REPLY")
                } else {
                    IngressObservation.admissionArmed.use { $0 = "inspect" }
                    // A healthy inspection might already be outstanding on a
                    // slow host. Release it and hold the next actual admission.
                    if endpoint.pendingName == "inspect" { endpoint.reply(healthy: true) }
                }
                try await wait("FIXTURE_ADMISSION_NOT_HELD") { IngressObservation.admissionEntered.use { $0 } }
                service.notify(.interrupted)
                IngressObservation.admissionRelease.signal()
                try await wait("FIXTURE_ADMISSION_NOT_RELEASED") { IngressObservation.admissionReturned.use { $0 } }
                try await wait("FIXTURE_ADMITTED_OPERATION_NOT_ENTERED") { endpoint.pendingName != nil }
                let admitted = await observe("operation admitted after invalidation accepted", service, endpoint, claims)
                try check(admitted.command == "start" && endpoint.state.use { $0.startRebuilds.last == true },
                          "INVALIDATED_RESOURCE_ADMITTED_WITHOUT_REBUILD")
                try await complete(endpoint, service)
                let recovered = await observe("latest admitted generation recovered", service, endpoint, claims)
                try check(recovered.playing && !recovered.rebuild && endpoint.state.use { $0.startEpochs == [0, 1] },
                          "ADMISSION_REPLACEMENT_NOT_RECOVERED")
                try check(!IngressObservation.admissionTimedOut.use { $0 }, "FIXTURE_ADMISSION_HOLD_TIMED_OUT")
            } else {
                if name == "pending-inspection" {
                    try await wait("FIXTURE_INSPECTION_NOT_ENTERED") { endpoint.pendingName == "inspect" }
                }
                _ = await observe("initial healthy", service, endpoint, claims)
                IngressObservation.armed.use { $0 = true }
                let event: LoopAudioService.Event = name.hasSuffix("media-reset") ? .mediaReset : .interrupted
                DispatchQueue.global().async {
                    service.notify(event)
                    IngressObservation.returned.use { $0 = true }
                }
                try await wait("FIXTURE_INVALIDATION_NOT_ACCEPTED") { IngressObservation.entered.use { $0 } }
                _ = await observe("accepted ingress before posting-thread dispatch", service, endpoint, claims)

                if name == "off-before-drain" {
                    service.setEnabled(false, owner: owner)
                    try await wait("FIXTURE_OFF_NOT_DRAINED") {
                        if endpoint.pendingName != nil { endpoint.reply(healthy: false) }
                        return visible.use { $0.text == "Off" }
                    }
                    let startsBeforeDrain = endpoint.state.use { $0.startEpochs.count }
                    let claimsBeforeDrain = claims.state.use { $0.requests }
                    try await releaseIngress(service)
                    let value = await observe("delayed invalidation after Off", service, endpoint, claims)
                    try check(!value.on && !value.playing && value.operation == nil && !value.timerActive,
                              "DELAYED_INVALIDATION_RESTARTED_AFTER_OFF")
                    try check(endpoint.state.use { $0.startEpochs.count == startsBeforeDrain }
                        && claims.state.use { $0.requests == claimsBeforeDrain }, "OFF_ADMITTED_REPLACEMENT_START")
                } else if name == "pending-inspection" {
                    // Keep the old inspection physically outstanding until the
                    // actual timer has adopted the new epoch. It cannot overlap AV.
                    try await waitForAdoption(service)
                    try await releaseIngress(service)
                    let old = await observe("invalidation with old inspection outstanding", service, endpoint, claims)
                    try check(old.command == "inspect" && old.rebuild && !old.playing,
                              "PENDING_INSPECTION_INVALIDATION_LOST")
                    try await complete(endpoint, service) // Its epoch is stale, despite a healthy payload.
                    try await nextStart(endpoint)
                    try await complete(endpoint, service)
                    let value = await observe("new epoch recovered after old inspection returned", service, endpoint, claims)
                    try check(value.playing && !value.rebuild && endpoint.state.use { $0.startEpochs == [0, 1] },
                              "PENDING_INSPECTION_REPLACEMENT_LOST")
                } else {
                    if name == "off-on-before-drain" {
                        service.setEnabled(false, owner: owner)
                        service.setEnabled(true, owner: owner)
                    }
                    try await nextStart(endpoint)
                    let pending = await observe("new epoch replacement admitted before drain", service, endpoint, claims)
                    try check(pending.epoch == 1 && pending.command == "start" && pending.rebuild && !pending.playing,
                              "FIXTURE_NEW_EPOCH_REPLACEMENT_NOT_ADMITTED")
                    if name == "second-during-replacement" {
                        service.notify(.decoderFailed)
                        let revoked = endpoint.state.use { $0.pending?.context.mayStart() == false }
                        _ = await observe("new invalidation while prior replacement outstanding", service, endpoint, claims)
                        try check(revoked, "SECOND_INVALIDATION_DID_NOT_REVOKE_REPLACEMENT")
                        try await complete(endpoint, service) // Deliberately late healthy payload from A.
                        let stale = await snapshot(service)
                        try check(!stale.playing && stale.rebuild, "SECOND_INVALIDATION_ACCEPTED_STALE_HEALTHY")
                        try await nextStart(endpoint)
                        try await complete(endpoint, service)
                        try await wait("FIXTURE_REPLACEMENT_CLAIM_END_NOT_OBSERVED") {
                            IngressObservation.clearedEnds.use { $0 == [1, 2] }
                        }
                        try await releaseIngress(service)
                        let value = await observe("new invalidation recovered within same failed episode", service, endpoint, claims)
                        try check(value.playing && !value.rebuild && !value.episode
                            && endpoint.state.use { $0.startEpochs == [0, 1, 2] } && claims.state.use { $0.requests == 2 },
                            "SECOND_INVALIDATION_RECOVERY_OR_EPISODE_BOUND")
                    } else if name.hasPrefix("pending-") {
                        try await releaseIngress(service)
                        let value = await observe("delayed invalidation while replacement outstanding", service, endpoint, claims)
                        try check(value.operation == pending.operation && value.command == "start" && value.rebuild,
                                  "PENDING_REPLACEMENT_INVALIDATION_LOST_OR_DUPLICATED")
                        try await complete(endpoint, service)
                    } else {
                        try await complete(endpoint, service)
                        try await wait("FIXTURE_REPLACEMENT_CLAIM_END_NOT_OBSERVED") {
                            IngressObservation.clearedEnds.use { $0 == [1, 2] }
                        }
                        let healthy = await observe("accepted healthy replacement before delayed drain", service, endpoint, claims)
                        try check(healthy.playing && !healthy.rebuild && !healthy.episode && !IngressObservation.returned.use { $0 },
                                  "FIXTURE_HEALTHY_REPLACEMENT_NOT_ACCEPTED")
                        if name == "second-after-recovery" {
                            service.notify(.mediaReset)
                            let second = await observe("new invalidation after accepted replacement", service, endpoint, claims)
                            try check(second.latestEpoch == 2, "SECOND_INVALIDATION_COALESCED_WITH_RECOVERED_EPOCH")
                            try await nextStart(endpoint)
                            try await complete(endpoint, service)
                            try await wait("FIXTURE_SECOND_REPLACEMENT_CLAIM_END_NOT_OBSERVED") {
                                IngressObservation.clearedEnds.use { $0 == [1, 2, 3] }
                            }
                            _ = await observe("second accepted replacement before old dispatch", service, endpoint, claims)
                        }
                        try await releaseIngress(service)
                        let after = await observe("after delayed invalidation drain", service, endpoint, claims)
                        if after.command == "start" {
                            // Preserve actual endpoint/claim evidence for the invalid
                            // input before throwing and performing bounded Off cleanup.
                            try await nextStart(endpoint)
                            _ = await observe("extra replacement actually entered", service, endpoint, claims)
                        }
                        try check(after.playing && !after.rebuild && !after.episode && after.command != "start",
                                  "ACCEPTED_HEALTHY_REPLACEMENT_INVALIDATION_REPLAYED")
                        let expectedEpochs: [UInt64] = name == "second-after-recovery" ? [0, 1, 2] : [0, 1]
                        try check(endpoint.state.use { $0.startEpochs == expectedEpochs }
                            && claims.state.use { $0.requests == expectedEpochs.count },
                                  "RECOVERED_EPOCH_REQUESTED_DUPLICATE_WORK_OR_CLAIM")
                        if name == "off-on-before-drain" {
                            try check(endpoint.state.use { Array($0.commands.filter { $0 != "inspect" }.prefix(3)) }
                                == ["start", "stop", "start"], "OFF_ON_RELEASE_BARRIER_LOST")
                        }
                    }
                }
            }
        } catch let error as IngressFailure { failures.append(error.marker) }
        catch { failures.append("FIXTURE_UNEXPECTED_ERROR: \(error)") }

        // All normal and negative inputs use identical cleanup. Do not hide the
        // original regression behind a crashed process, timeout, or leaked claim.
        var cleanupPassed = false
        IngressObservation.release.signal()
        IngressObservation.admissionRelease.signal()
        service.setEnabled(false, owner: owner)
        endpoint.reply(healthy: false)
        do {
            try await wait("FIXTURE_FINAL_OFF_NOT_DRAINED", {
                if endpoint.pendingName != nil { endpoint.reply(healthy: false) }
                return visible.use { $0.text == "Off" }
            }, seconds: 5)
            try await wait("FIXTURE_FINAL_CLAIMS_NOT_ENDED", { claims.state.use { $0.live.isEmpty } }, seconds: 5)
            let value = await snapshot(service)
            try check(value.operation == nil && !value.timerActive && value.maximumOutstanding == 1,
                      "FINAL_SINGLE_FLIGHT_OR_TIMER_NOT_DRAINED")
            let state = claims.state.use { $0 }
            try check(state.ended.count == state.requests && Set(state.ended).count == state.ended.count && state.peak <= 1,
                      "FINAL_CLAIM_BALANCE_OR_CONCURRENCY_BOUND")
            try check(!IngressObservation.timedOut.use { $0 }, "FIXTURE_INGRESS_HOLD_TIMED_OUT")
            try check(!IngressObservation.admissionTimedOut.use { $0 }, "FIXTURE_ADMISSION_HOLD_TIMED_OUT")
            cleanupPassed = true
        } catch let error as IngressFailure { failures.append(error.marker) }
        catch { failures.append("FIXTURE_CLEANUP_ERROR: \(error)") }
        service.unregister(owner)
        _ = await observe("final cleanup", service, endpoint, claims)
        let claimState = claims.state.use { $0 }
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "assertions": assertions, "cleanup_passed": cleanupPassed,
            "requests": claimState.requests, "ended_ids": claimState.ended, "maximum_live_claims": claimState.peak,
            "commands": endpoint.state.use { $0.commands }, "start_epochs": endpoint.state.use { $0.startEpochs },
            "start_rebuilds": endpoint.state.use { $0.startRebuilds },
            "observations": observations, "elapsed_seconds": ProcessInfo.processInfo.systemUptime - began,
            "shipping_interval_seconds": 0.5, "scope": "Controlled service/lease scheduling only; no OS, device, or AV playback proof"]
        do {
            let raw = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
            print(String(decoding: raw, as: UTF8.self))
        } catch { FileHandle.standardError.write(Data("FIXTURE_RESULT_ENCODING_FAILED\n".utf8)); exit(2) }
        for failure in failures { FileHandle.standardError.write(Data((failure + "\n").utf8)) }
        exit(failures.isEmpty ? 0 : 74)
    }
}
