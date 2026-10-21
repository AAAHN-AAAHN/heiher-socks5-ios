import Foundation
import Dispatch

// Actual adapter with controlled return values. No physical Apple outcome is claimed.
final class StoppedStartValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

struct StoppedStartResult: Sendable, Codable {
    let operation: UInt64
    let command: String
    let stopped: Bool
    let retryDelay: Double
    let rebuild: Bool
}

enum StoppedStartObservation {
    static let results = StoppedStartValue<[StoppedStartResult]>([])
    static let mode = StoppedStartValue("")

    static func failed(_ operation: UInt64, _ command: LoopAudioService.Command,
                       _ failure: LoopAudioService.Reply.KnownFailure?,
                       _ returnedAt: Double, _ retryAt: Double, _ rebuild: Bool) {
        let name: String
        switch command {
        case .start: name = "start"
        case .inspect: name = "inspect"
        case .stop: name = "stop"
        }
        let stopped: Bool
        if case .stopped = failure { stopped = true } else { stopped = false }
        results.use { $0.append(.init(operation: operation, command: name,
            stopped: stopped, retryDelay: retryAt - returnedAt, rebuild: rebuild)) }
    }

    // Existing mock's one-shot hook is rearmed at each getter. A controlled
    // unreported stop happens after play() returns true. In bad-resume mode it
    // affects only the first player; a replacement can play normally.
    static func armStoppedGetter() {
        AudioEndpointFixture.shared.use { trace in
            trace.hookName = "playing-get"
            trace.hook = {
                let name = mode.use { $0 }
                AudioEndpointFixture.shared.use { value in
                    if name == "persistent-stopped" || value.created == 1 {
                        value.physicalPlaying = false
                    }
                }
                armStoppedGetter()
            }
        }
    }
}

private struct StoppedStartFailure: Error { let marker: String }

@main struct StoppedStartTests {
    @MainActor static func check(_ value: Bool, _ marker: String) throws {
        if !value { throw StoppedStartFailure(marker: marker) }
    }
    @MainActor static func wait(_ condition: () -> Bool, _ marker: String,
                                seconds: Double = 3) async throws {
        let end = ProcessInfo.processInfo.systemUptime + seconds
        while !condition() && ProcessInfo.processInfo.systemUptime < end {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try check(condition(), marker)
    }

    @MainActor static func main() async {
        guard CommandLine.arguments.count == 3 else { exit(2) }
        let name = CommandLine.arguments[1]
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = CommandLine.arguments[2] }
        StoppedStartObservation.mode.use { $0 = name }
        let visible = StoppedStartValue(LoopAudioService.State())
        let claims = StoppedStartValue((requested: 0, ended: [Int](), live: Set<Int>(), peak: 0))
        let provider = RecoveryExecutionLease.Provider(request: { _, receipt in
            let id = claims.use { value -> Int in
                value.requested += 1
                value.live.insert(value.requested)
                value.peak = max(value.peak, value.live.count)
                return value.requested
            }
            receipt(id)
        }, end: { id in claims.use { $0.ended.append(id); $0.live.remove(id) } })
        let service = LoopAudioService(leaseProvider: { provider }) { queue, event in
            queue.setSpecific(key: fixture.queueKey, value: true)
            return LoopAudioService.auditEndpoint(queue: queue, event: event)
        }
        let owner = service.register { state in visible.use { $0 = state } }
        var failures = [String]()
        var observations = [String: Int]()
        var cleanup = false
        func count(_ call: String) -> Int { fixture.use { $0.calls.filter { $0 == call }.count } }
        func playing() -> Bool { visible.use { $0.text == LoopAudioService.Phase.playing.rawValue } }
        func startsFailed() -> Int {
            StoppedStartObservation.results.use { $0.filter { $0.command == "start" && $0.stopped }.count }
        }
        func fence() async -> FinalizationControl {
            await withCheckedContinuation { continuation in
                service.auditFinalizationFence { continuation.resume(returning: $0) }
            }
        }
        func settleOff() async throws -> FinalizationControl {
            let end = ProcessInfo.processInfo.systemUptime + 3
            var value = await fence()
            while (value.operation != nil || value.on || value.timerActive || !claims.use({ $0.live.isEmpty })) &&
                  ProcessInfo.processInfo.systemUptime < end {
                try await Task.sleep(nanoseconds: 1_000_000)
                value = await fence()
            }
            try check(!value.on && value.operation == nil && !value.timerActive &&
                      claims.use { $0.live.isEmpty }, "OFF_CLEANUP_DID_NOT_SETTLE")
            return value
        }

        do {
            let initialFailure = name == "initial-stopped"
            if initialFailure { StoppedStartObservation.armStoppedGetter() }
            service.setEnabled(true, owner: owner)
            if initialFailure {
                try await wait({ startsFailed() >= 1 }, "FAILED_INITIAL_START_NOT_OBSERVED")
                try await wait({ fixture.use { $0.created == 2 && $0.physicalPlaying } && playing() },
                               "MISSING_L2_AFTER_FAILED_INITIAL_START")
                _ = await fence()
                try check(count("play") == 2 && startsFailed() == 1, "INITIAL_RECOVERY_ATTEMPT_COUNT_CHANGED")
            } else {
                try await wait({ playing() && fixture.use { $0.physicalPlaying } }, "INITIAL_PLAYBACK_NOT_REACHED")
                _ = await fence()
                try check(count("play") == 1 && fixture.use { $0.created == 1 }, "INITIAL_PLAYER_COUNT_CHANGED")
            }

            switch name {
            case "initial-stopped": break
            case "healthy":
                try await wait({ count("playing-get") >= 4 }, "HEALTHY_INSPECTIONS_NOT_REACHED")
                try check(count("play") == 1 && fixture.use { $0.created == 1 }, "HEALTHY_PLAYER_REBUILT")
                try check(StoppedStartObservation.results.use { $0.isEmpty }, "HEALTHY_RESULT_BECAME_FAILURE")
            case "ordinary-stopped":
                fixture.use { $0.physicalPlaying = false }
                try await wait({ count("play") >= 2 && fixture.use { $0.physicalPlaying } }, "VALID_STOPPED_PLAYER_DID_NOT_RESUME")
                _ = await fence()
                try check(fixture.use { $0.created == 1 }, "ORDINARY_STOP_SKIPPED_L1_REUSE")
                try check(startsFailed() == 0, "ORDINARY_STOP_RECORDED_FAILED_START")
            case "bad-resume":
                StoppedStartObservation.armStoppedGetter()
                try await wait({ startsFailed() >= 1 }, "FAILED_START_NOT_OBSERVED")
                try await wait({ fixture.use { $0.created == 2 && $0.physicalPlaying } && playing() },
                               "MISSING_L2_AFTER_FAILED_RESUME")
                _ = await fence()
                try check(count("play") == 3 && startsFailed() == 1, "RECOVERY_ATTEMPT_COUNT_CHANGED")
            case "persistent-stopped":
                StoppedStartObservation.armStoppedGetter()
                try await wait({ startsFailed() >= 3 }, "THREE_FAILED_STARTS_NOT_OBSERVED")
                try check(fixture.use { $0.created >= 3 }, "FAILED_STARTS_NEVER_RECREATE_PLAYER")
                try check(claims.use { $0.requested <= 2 }, "FAILED_EPISODE_REISSUED_CLAIMS")
            case "off-after-failed-start":
                StoppedStartObservation.armStoppedGetter()
                try await wait({ startsFailed() >= 1 }, "FAILED_START_NOT_OBSERVED")
                let before = count("play")
                service.setEnabled(false, owner: owner)
                _ = try await settleOff()
                try await Task.sleep(nanoseconds: 600_000_000)
                try check(count("play") == before && fixture.use { $0.created == 1 }, "OFF_ALLOWED_QUEUED_REBUILD")
            default: throw StoppedStartFailure(marker: "UNKNOWN_CASE")
            }

            let values = StoppedStartObservation.results.use { $0 }
            for value in values {
                if value.command == "start" {
                    try check(abs(value.retryDelay - 0.5) < 0.000000001, "FAILED_START_CHANGED_ORIGINAL_PACING")
                } else if value.command == "inspect" && value.stopped {
                    try check(value.retryDelay == 0, "KNOWN_STOP_DELAYED_FIRST_L1")
                }
            }
            try check(fixture.use { $0.peakPlayers == 1 && $0.peak <= 1 && $0.onWrongQueue == 0 },
                      "PLAYER_OR_API_SINGLE_FLIGHT_BROKEN")
        } catch let failure as StoppedStartFailure { failures.append(failure.marker) }
        catch { failures.append("UNEXPECTED: \(error)") }

        observations["play_calls_before_cleanup"] = count("play")
        observations["players_created_before_cleanup"] = fixture.use { $0.created }
        fixture.use { $0.hookName = nil; $0.hook = nil }
        service.setEnabled(false, owner: owner)
        do {
            let final = try await settleOff()
            try check(final.maximumOutstanding == 1, "OUTSTANDING_OPERATION_LIMIT_BROKEN")
            try check(fixture.use { !$0.physicalPlaying && $0.livePlayers == 0 && $0.peakPlayers <= 1 },
                      "PLAYER_CLEANUP_FAILED")
            try check(claims.use { $0.live.isEmpty && Set($0.ended).count == $0.ended.count && $0.ended.count == $0.requested },
                      "CLAIM_CLEANUP_FAILED")
            cleanup = true
        } catch let failure as StoppedStartFailure { failures.append(failure.marker) }
        catch { failures.append("CLEANUP_UNEXPECTED: \(error)") }
        service.unregister(owner)
        let encoded = try! JSONEncoder().encode(StoppedStartObservation.results.use { $0 })
        let value: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "cleanup_passed": cleanup, "observations": observations,
            "failed_results": try! JSONSerialization.jsonObject(with: encoded),
            "calls": fixture.use { $0.calls },
            "peak_players": fixture.use { $0.peakPlayers },
            "claims_requested": claims.use { $0.requested },
            "claims_ended": claims.use { $0.ended },
            "scope": "Exact service and adapter with existing controlled AV doubles; no physical Apple execution"]
        let bytes = try! JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
        print(String(decoding: bytes, as: UTF8.self))
        exit(failures.isEmpty ? 0 : 74)
    }
}
