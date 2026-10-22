import Foundation
import Dispatch

final class RetrySignalValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

enum RetrySignalObservation {
    struct State {
        var holdBegin = false
        var began = false
        var holdIngress = false
        var accepted = false
        var returned = false
        var watchDrain = false
        var priorDeadline: Double?
        var drainedDeadline: Double?
    }
    static let state = RetrySignalValue(State())
    static let releaseBegin = DispatchSemaphore(value: 0)
    static let releaseIngress = DispatchSemaphore(value: 0)
    static func beforeBegin() {
        let hold = state.use { value -> Bool in
            guard value.holdBegin else { return false }
            value.holdBegin = false; value.began = true
            return true
        }
        if hold { precondition(releaseBegin.wait(timeout: .now() + 10) == .success, "FIXTURE_BEGIN_NOT_RELEASED") }
    }
    static func afterIngressAccepted() {
        let hold = state.use { value -> Bool in
            guard value.holdIngress else { return false }
            value.holdIngress = false; value.accepted = true
            return true
        }
        if hold { precondition(releaseIngress.wait(timeout: .now() + 10) == .success, "FIXTURE_INGRESS_NOT_RELEASED") }
    }
    static func beforeDrain(_ deadline: Double) {
        state.use { value in
            if value.watchDrain && value.priorDeadline == nil { value.priorDeadline = deadline }
        }
    }
    static func afterDrain(_ deadline: Double) {
        state.use { value in
            if value.priorDeadline != nil && value.drainedDeadline == nil { value.drainedDeadline = deadline }
        }
    }
}

struct RetrySignalFailure: Error { let marker: String }

@main struct RetrySignalPacingTests {
    @MainActor static func check(_ condition: Bool, _ marker: String) throws {
        if !condition { throw RetrySignalFailure(marker: marker) }
    }
    @MainActor static func wait(_ condition: () -> Bool, _ marker: String) async throws {
        let limit = ProcessInfo.processInfo.systemUptime + 3
        while !condition() && ProcessInfo.processInfo.systemUptime < limit {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try check(condition(), marker)
    }
    @MainActor static func diagnostics(_ service: LoopAudioService) async -> LoopAudioService.Diagnostics {
        await withCheckedContinuation { continuation in service.diagnostics { continuation.resume(returning: $0) } }
    }
    @MainActor static func settled(_ service: LoopAudioService, operations: UInt64) async throws -> LoopAudioService.Diagnostics {
        let limit = ProcessInfo.processInfo.systemUptime + 3
        while ProcessInfo.processInfo.systemUptime < limit {
            let value = await diagnostics(service)
            if value.completedOperations >= operations && value.operation == nil { return value }
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        throw RetrySignalFailure(marker: "FIXTURE_OPERATION_DID_NOT_SETTLE")
    }
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 3 else { exit(2) }
        let name = CommandLine.arguments[1]
        let preAdmission = name.hasPrefix("pre-admission-")
        let budget = name == "availability-budget-after-admission"
        let staleExplicit = name == "stale-explicit-new-available"
        let newExplicit = name == "new-explicit-old-available"
        let delayed = preAdmission || budget || staleExplicit || newExplicit
        let isExplicit = name == "pre-admission-explicit" || staleExplicit
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = CommandLine.arguments[2]; $0.rejections["activate"] = 100 }
        let visible = RetrySignalValue(LoopAudioService.State())
        let claims = RetrySignalValue((requests: 0, ends: [Int](), live: Set<Int>(), peak: 0))
        let service = LoopAudioService(leaseProvider: {
            RecoveryExecutionLease.Provider(request: { _, receipt in
                let id = claims.use { value -> Int in
                    value.requests += 1; value.live.insert(value.requests)
                    value.peak = max(value.peak, value.live.count)
                    return value.requests
                }
                receipt(id)
            }, end: { id in claims.use { $0.ends.append(id); $0.live.remove(id) } })
        }) { queue, event in
            queue.setSpecific(key: fixture.queueKey, value: true)
            return LoopAudioService.auditEndpoint(queue: queue, event: event)
        }
        let owner = service.register { value in visible.use { $0 = value } }
        var failures = [String]()
        var cleanup = false
        var before = -1.0
        var after = -1.0
        var admissionProven = false
        do {
            if staleExplicit {
                service.setEnabled(true, owner: owner)
                _ = try await settled(service, operations: 1)
                RetrySignalObservation.state.use { $0.holdBegin = true }
                // Spend this continuous episode's one availability opportunity.
                service.notify(.available)
            } else {
                if delayed { RetrySignalObservation.state.use { $0.holdBegin = true } }
                service.setEnabled(true, owner: owner)
            }
            if delayed {
                try await wait({ RetrySignalObservation.state.use { $0.began } }, "FIXTURE_ADMISSION_NOT_HELD")
                RetrySignalObservation.state.use { $0.holdIngress = true }
                DispatchQueue.global().async {
                    if isExplicit { service.setEnabled(true, owner: owner) }
                    else { service.notify(.available) }
                    RetrySignalObservation.state.use { $0.returned = true }
                }
                try await wait({ RetrySignalObservation.state.use { $0.accepted } }, "FIXTURE_RETRY_SIGNAL_NOT_ACCEPTED")
                RetrySignalObservation.releaseBegin.signal()
            }
            let first = try await settled(service, operations: staleExplicit ? 2 : 1)
            try check(first.timerActive && fixture.use { $0.calls.filter { $0 == "activate" }.count >= 1 }, "FIXTURE_FAILED_START_NOT_PACED")
            admissionProven = delayed
            before = await withCheckedContinuation { continuation in
                service.auditRetryDeadline { continuation.resume(returning: $0) }
            }
            try check(before > 0, "FIXTURE_MISSING_FAILURE_DEADLINE")
            RetrySignalObservation.state.use { $0.watchDrain = true }
            if delayed {
                // These inputs arrive after the attempt while the earlier
                // signal's drain is still held. Its latest slot is coalesced,
                // so identity and the consumed availability budget both matter.
                if budget || staleExplicit { service.notify(.available) }
                if newExplicit { service.setEnabled(true, owner: owner) }
                RetrySignalObservation.releaseIngress.signal()
                try await wait({ RetrySignalObservation.state.use { $0.returned } }, "FIXTURE_INGRESS_DISPATCH_NOT_RETURNED")
            } else if name == "new-explicit" { service.setEnabled(true, owner: owner) }
            else if name == "new-available" { service.notify(.available) }
            else if name == "new-hint" { service.notify(.hint) }
            else { throw RetrySignalFailure(marker: "UNKNOWN_CASE") }
            try await wait({ RetrySignalObservation.state.use { $0.drainedDeadline != nil } }, "FIXTURE_DRAIN_NOT_OBSERVED")
            before = RetrySignalObservation.state.use { $0.priorDeadline! }
            after = RetrySignalObservation.state.use { $0.drainedDeadline! }
            // Both observations belong to the same serial drain. An ordinary
            // retry between the main actor's setup and this drain cannot alter
            // the comparison. The production 0.5-second interval is unchanged.
            try check(before > 0, "FIXTURE_DRAIN_DID_NOT_BEGIN_WITH_FAILURE_DEADLINE")
            if preAdmission {
                try check(after == before, "PRE_ADMISSION_RETRY_SIGNAL_REPLAYED_AFTER_FAILED_START")
            } else if budget {
                try check(after == before, "ADMITTED_AVAILABILITY_OPPORTUNITY_REUSED")
            } else if staleExplicit {
                try check(after == before, "STALE_EXPLICIT_PROMOTED_NEW_AVAILABILITY")
            } else if name == "new-hint" {
                try check(after == before, "ORDINARY_HINT_ERASED_FAILURE_DEADLINE")
            } else {
                try check(after == 0, "NEW_POST_FAILURE_RETRY_SIGNAL_DID_NOT_EXPEDITE")
            }
            try check(claims.use { $0.requests == 1 }, "CONTINUOUS_FAILURE_RENEWED_CLAIM")
        } catch let error as RetrySignalFailure { failures.append(error.marker) }
        catch { failures.append("UNEXPECTED: \(error)") }
        RetrySignalObservation.state.use { $0.holdBegin = false; $0.holdIngress = false }
        RetrySignalObservation.releaseBegin.signal(); RetrySignalObservation.releaseIngress.signal()
        service.setEnabled(false, owner: owner)
        do {
            try await wait({ visible.use { $0.text == "Off" } && claims.use { $0.live.isEmpty } }, "OFF_CLEANUP_NOT_COMPLETED")
            let final = await diagnostics(service)
            try check(final.operation == nil && !final.timerActive && final.maximumOutstanding == 1 &&
                      fixture.use { !$0.physicalPlaying && $0.livePlayers == 0 && $0.peakPlayers <= 1 && $0.onWrongQueue == 0 } &&
                      claims.use { $0.peak <= 1 && $0.ends.count == $0.requests && Set($0.ends).count == $0.ends.count },
                      "FINAL_RESOURCE_OR_CLAIM_BOUND_BROKEN")
            cleanup = true
        } catch let error as RetrySignalFailure { failures.append(error.marker) }
        catch { failures.append("CLEANUP_UNEXPECTED: \(error)") }
        service.unregister(owner)
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "cleanup_passed": cleanup, "deadline_before_drain": before,
            "deadline_after_drain": after, "claims_requested": claims.use { $0.requests },
            "pre_admission_signal_incorporation_proven": admissionProven,
            "claims_ended": claims.use { $0.ends }, "shipping_interval_seconds": 0.5,
            "scope": "Actual service/adapter with controlled ingress/admission and API outcomes; no Apple playback proof"]
        print(String(decoding: try! JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), as: UTF8.self))
        exit(failures.isEmpty ? 0 : 74)
    }
}
