import Foundation
import Dispatch

final class AdmissionValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

enum AssetRetryAdmissionObservation {
    struct State {
        var holdBegin = false
        var began = false
        var holdIngress = false
        var accepted = false
        var returned = false
    }
    static let state = AdmissionValue(State())
    static let releaseBegin = DispatchSemaphore(value: 0)
    static let releaseIngress = DispatchSemaphore(value: 0)
    static func beforeBegin() {
        let hold = state.use { value -> Bool in
            guard value.holdBegin else { return false }
            value.holdBegin = false
            value.began = true
            return true
        }
        if hold { precondition(releaseBegin.wait(timeout: .now() + 10) == .success, "FIXTURE_BEGIN_NOT_RELEASED") }
    }
    static func afterIngressAccepted() {
        let hold = state.use { value -> Bool in
            guard value.holdIngress else { return false }
            value.holdIngress = false
            value.accepted = true
            return true
        }
        if hold { precondition(releaseIngress.wait(timeout: .now() + 10) == .success, "FIXTURE_INGRESS_NOT_RELEASED") }
    }
}

struct AdmissionFailure: Error { let marker: String }

@main struct AssetRetryAdmissionTests {
    @MainActor static func check(_ okay: Bool, _ marker: String) throws {
        if !okay { throw AdmissionFailure(marker: marker) }
    }
    @MainActor static func wait(_ condition: () -> Bool, _ marker: String) async throws {
        let limit = ProcessInfo.processInfo.systemUptime + 3
        while !condition() && ProcessInfo.processInfo.systemUptime < limit {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try check(condition(), marker)
    }
    @MainActor static func diagnostics(_ service: LoopAudioService) async -> LoopAudioService.Diagnostics {
        await withCheckedContinuation { continuation in
            service.diagnostics { continuation.resume(returning: $0) }
        }
    }
    @MainActor static func settled(_ service: LoopAudioService, operations: UInt64) async throws -> LoopAudioService.Diagnostics {
        let limit = ProcessInfo.processInfo.systemUptime + 3
        while ProcessInfo.processInfo.systemUptime < limit {
            let value = await diagnostics(service)
            if value.completedOperations >= operations && value.operation == nil { return value }
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        throw AdmissionFailure(marker: "FIXTURE_OPERATION_DID_NOT_SETTLE")
    }
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 4 else { exit(2) }
        let name = CommandLine.arguments[1]
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = CommandLine.arguments[3] }
        let visible = AdmissionValue(LoopAudioService.State())
        let claims = AdmissionValue((requests: 0, ends: [Int](), live: Set<Int>(), peak: 0))
        let service = LoopAudioService(leaseProvider: {
            RecoveryExecutionLease.Provider(request: { _, receipt in
                let id = claims.use { value -> Int in
                    value.requests += 1
                    value.live.insert(value.requests)
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
        var admissionProven = false
        do {
            service.setEnabled(true, owner: owner)
            let initial = try await settled(service, operations: 1)
            try await wait({ claims.use { $0.ends == [1] && $0.live.isEmpty } }, "FIXTURE_INITIAL_CLAIM_NOT_ENDED")
            try check(!initial.timerActive && fixture.use { $0.assetReads == 1 && $0.created == 0 }, "FIXTURE_INITIAL_ASSET_NOT_BLOCKED")
            if name == "media-reset-parked" {
                fixture.use { $0.resource = CommandLine.arguments[2] }
                service.notify(.mediaReset)
                try await wait({ visible.use { $0.text == LoopAudioService.Phase.playing.rawValue } && fixture.use { $0.physicalPlaying } },
                               "MEDIA_RESET_DID_NOT_RETRY_PARKED_ASSET")
                try check(fixture.use { $0.assetReads == 2 && $0.created == 1 }, "MEDIA_RESET_ASSET_RETRY_COUNT_CHANGED")
            } else {
                try check(name == "pre-admission-available" || name == "pre-admission-explicit", "UNKNOWN_CASE")
                AssetRetryAdmissionObservation.state.use { $0.holdBegin = true }
                service.setEnabled(true, owner: owner)
                try await wait({ AssetRetryAdmissionObservation.state.use { $0.began } }, "FIXTURE_ADMISSION_NOT_HELD")
                AssetRetryAdmissionObservation.state.use { $0.holdIngress = true }
                DispatchQueue.global().async {
                    if name == "pre-admission-available" { service.notify(.available) }
                    else { service.setEnabled(true, owner: owner) }
                    AssetRetryAdmissionObservation.state.use { $0.returned = true }
                }
                try await wait({ AssetRetryAdmissionObservation.state.use { $0.accepted } }, "FIXTURE_RETRY_SIGNAL_NOT_ACCEPTED")
                AssetRetryAdmissionObservation.releaseBegin.signal()
                let retried = try await settled(service, operations: 2)
                try check(!retried.timerActive && fixture.use { $0.assetReads == 2 && $0.created == 0 }, "FIXTURE_PRE_ADMISSION_ATTEMPT_NOT_COMPLETED")
                admissionProven = true
                fixture.use { $0.resource = CommandLine.arguments[2] }
                AssetRetryAdmissionObservation.releaseIngress.signal()
                try await wait({ AssetRetryAdmissionObservation.state.use { $0.returned } }, "FIXTURE_INGRESS_DISPATCH_NOT_RETURNED")
                // Accepted-before-admission advice already contributed to attempt 2.
                // Its deliberately late control delivery cannot create attempt 3.
                let late = await diagnostics(service)
                try check(late.operation == nil && !late.timerActive && fixture.use { $0.assetReads == 2 && $0.created == 0 },
                          "PRE_ADMISSION_ASSET_SIGNAL_REPLAYED")
            }
            try check(claims.use { $0.requests == 1 }, "CONTINUOUS_FAILURE_RENEWED_CLAIM")
        } catch let failure as AdmissionFailure { failures.append(failure.marker) }
        catch { failures.append("UNEXPECTED: \(error)") }
        let reads = fixture.use { $0.assetReads }
        AssetRetryAdmissionObservation.state.use { $0.holdBegin = false; $0.holdIngress = false }
        AssetRetryAdmissionObservation.releaseBegin.signal()
        AssetRetryAdmissionObservation.releaseIngress.signal()
        service.setEnabled(false, owner: owner)
        do {
            try await wait({ visible.use { $0.text == "Off" } && claims.use { $0.live.isEmpty } }, "OFF_CLEANUP_NOT_COMPLETED")
            let final = await diagnostics(service)
            try check(final.operation == nil && !final.timerActive && final.maximumOutstanding == 1 &&
                      fixture.use { !$0.physicalPlaying && $0.livePlayers == 0 && $0.peakPlayers <= 1 && $0.onWrongQueue == 0 } &&
                      claims.use { $0.peak <= 1 && $0.ends.count == $0.requests && Set($0.ends).count == $0.ends.count },
                      "FINAL_RESOURCE_OR_CLAIM_BOUND_BROKEN")
            cleanup = true
        } catch let failure as AdmissionFailure { failures.append(failure.marker) }
        catch { failures.append("CLEANUP_UNEXPECTED: \(error)") }
        service.unregister(owner)
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL", "failures": failures,
            "cleanup_passed": cleanup, "pre_admission_signal_incorporation_proven": admissionProven,
            "asset_reads_before_cleanup": reads, "claims_requested": claims.use { $0.requests },
            "claims_ended": claims.use { $0.ends },
            "scope": "Actual service/adapter with identical controlled ingress/admission barriers; no physical Apple proof"]
        print(String(decoding: try! JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), as: UTF8.self))
        exit(failures.isEmpty ? 0 : 74)
    }
}
