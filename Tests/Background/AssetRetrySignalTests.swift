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

enum AssetReadObservation {
    static let reads = RetrySignalValue(0)
    static let released = DispatchSemaphore(value: 0)
    static func didRead() {
        let first = reads.use { $0 += 1; return $0 == 1 }
        if first {
            precondition(released.wait(timeout: .now() + 10) == .success,
                         "FIXTURE_READ_BARRIER_NOT_RELEASED")
        }
    }
}

struct RetrySignalFailure: Error { let marker: String }

@main struct AssetRetrySignalTests {
    @MainActor static func check(_ okay: Bool, _ marker: String) throws {
        if !okay { throw RetrySignalFailure(marker: marker) }
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
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 4 else { exit(2) }
        let name = CommandLine.arguments[1]
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = CommandLine.arguments[3] }
        let state = RetrySignalValue(LoopAudioService.State())
        let claims = RetrySignalValue((requests: 0, ends: [Int](), live: Set<Int>(), peak: 0))
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
        let owner = service.register { next in state.use { $0 = next } }
        var failures: [String] = []
        var cleanup = false
        var consumedSignalWhileOldReadPending = false
        let shouldRetry = name == "available" || name == "explicit" || name == "off-on"
        do {
            service.setEnabled(true, owner: owner)
            try await wait({ AssetReadObservation.reads.use { $0 == 1 } },
                           "FIXTURE_OLD_INVALID_BYTES_NOT_CAPTURED")
            // The old operation already owns immutable invalid bytes. Only a new
            // resource lookup can observe this newly available valid WAV.
            fixture.use { $0.resource = CommandLine.arguments[2] }
            switch name {
            case "available": service.notify(.available)
            case "explicit": service.setEnabled(true, owner: owner)
            case "hint": service.notify(.hint)
            case "echo": service.setEnabled(true, owner: owner, explicit: false)
            case "off-on":
                service.setEnabled(false, owner: owner, explicit: false)
                service.setEnabled(true, owner: owner, explicit: false)
            default: throw RetrySignalFailure(marker: "UNKNOWN_CASE")
            }
            // notify/setEnabled enqueues drain before this control-only fence.
            let held = await diagnostics(service)
            try check(held.operation != nil && held.step == .assetRead &&
                      held.stepReturnedAt != nil && held.resultAvailableAt == nil &&
                      fixture.use { $0.assetReads == 1 && $0.created == 0 },
                      "FIXTURE_SIGNAL_NOT_CONSUMED_BEFORE_OLD_RESULT")
            consumedSignalWhileOldReadPending = true
            AssetReadObservation.released.signal()
            if shouldRetry {
                try await wait({ state.use { $0.text == LoopAudioService.Phase.playing.rawValue } &&
                    fixture.use { $0.physicalPlaying } },
                    "NEW_ASSET_RETRY_SIGNAL_LOST_TO_OLD_INVALID_RESULT")
                try check(fixture.use { $0.assetReads == 2 && $0.created == 1 },
                          "ASSET_RETRY_NOT_EXACTLY_ONCE")
            } else {
                try await wait({ state.use { $0.text.hasPrefix("Waiting to resume:") } },
                               "FIXTURE_ASSET_FAILURE_NOT_RETURNED")
                let blocked = await diagnostics(service)
                try check(blocked.operation == nil && !blocked.timerActive &&
                          fixture.use { $0.assetReads == 1 && $0.created == 0 },
                          "UNREQUESTED_ASSET_RETRY")
            }
            if name != "off-on" {
                try check(claims.use { $0.requests == 1 }, "CONTINUOUS_FAILURE_RENEWED_CLAIM")
            }
        } catch let failure as RetrySignalFailure { failures.append(failure.marker) }
        catch { failures.append("UNEXPECTED: \(error)") }

        let beforeCleanup = fixture.use { (reads: $0.assetReads, created: $0.created, plays: $0.calls.filter { $0 == "play" }.count) }
        AssetReadObservation.released.signal()
        service.setEnabled(false, owner: owner)
        do {
            try await wait({ state.use { $0.text == "Off" } && claims.use { $0.live.isEmpty } },
                           "OFF_CLEANUP_NOT_COMPLETED")
            let final = await diagnostics(service)
            try check(final.operation == nil && !final.timerActive && final.maximumOutstanding == 1 &&
                      fixture.use { !$0.physicalPlaying && $0.livePlayers == 0 && $0.peakPlayers <= 1 && $0.onWrongQueue == 0 } &&
                      claims.use { $0.peak <= 1 && $0.ends.count == $0.requests && Set($0.ends).count == $0.ends.count },
                      "FINAL_RESOURCE_OR_CLAIM_BOUND_BROKEN")
            cleanup = true
        } catch let failure as RetrySignalFailure { failures.append(failure.marker) }
        catch { failures.append("CLEANUP_UNEXPECTED: \(error)") }
        service.unregister(owner)
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "cleanup_passed": cleanup,
            "new_signal_consumed_while_old_read_pending": consumedSignalWhileOldReadPending,
            "asset_reads_before_cleanup": beforeCleanup.reads,
            "players_created_before_cleanup": beforeCleanup.created,
            "play_calls_before_cleanup": beforeCleanup.plays,
            "claims_requested": claims.use { $0.requests }, "claims_ended": claims.use { $0.ends },
            "scope": "Actual service/adapter with controlled AV doubles and identical post-read barrier; no physical Apple proof"]
        print(String(decoding: try! JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]), as: UTF8.self))
        exit(failures.isEmpty ? 0 : 74)
    }
}
