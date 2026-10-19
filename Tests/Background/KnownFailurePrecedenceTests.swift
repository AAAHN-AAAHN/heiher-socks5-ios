import Foundation
import Dispatch

private final class PrecedenceValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

private struct PrecedenceFailure: Error { let marker: String }

/// The real adapter encounters an already known stop/configuration failure
/// before a held getter. Failure admission or repair must precede that read.
/// The hold is released during identical cleanup on passing and failing inputs.
@main struct KnownFailurePrecedenceTests {
    @MainActor static var assertions = 0
    @MainActor static func check(_ value: Bool, _ marker: String) throws {
        assertions += 1
        if !value { throw PrecedenceFailure(marker: marker) }
    }
    @MainActor static func wait(_ condition: () -> Bool, _ marker: String) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        while !condition() && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try check(condition(), marker)
    }
    @MainActor static func main() async {
        guard CommandLine.arguments.count == 3 else { exit(2) }
        let name = CommandLine.arguments[1]
        guard ["stopped-before-progress", "misconfigured-before-progress", "stopped-misconfigured-before-progress",
               "stopped-before-category", "misconfigured-before-mode", "mode-misconfigured-before-options",
               "healthy-progress-preserved"].contains(name) else { exit(2) }
        let blockedStep: String
        switch name {
        case "stopped-before-category": blockedStep = "category-get"
        case "misconfigured-before-mode": blockedStep = "mode-get"
        case "mode-misconfigured-before-options": blockedStep = "options-get"
        default: blockedStep = "position-get"
        }
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = CommandLine.arguments[2] }
        let visible = PrecedenceValue(LoopAudioService.State())
        let claims = PrecedenceValue((requested: 0, ended: [Int]()))
        let provider = RecoveryExecutionLease.Provider(request: { _, receipt in
            let id = claims.use { $0.requested += 1; return $0.requested }
            receipt(id)
        }, end: { id in claims.use { $0.ended.append(id) } })
        let service = LoopAudioService(leaseProvider: { provider }) { queue, event in
            queue.setSpecific(key: fixture.queueKey, value: true)
            return LoopAudioService.auditEndpoint(queue: queue, event: event)
        }
        let owner = service.register { next in visible.use { $0 = next } }
        var failures = [String]()
        var observations = [String: Int]()
        func count(_ step: String) -> Int { fixture.use { $0.calls.filter { $0 == step }.count } }
        func diagnostics() async -> LoopAudioService.Diagnostics {
            await withCheckedContinuation { continuation in service.diagnostics { continuation.resume(returning: $0) } }
        }
        do {
            service.setEnabled(true, owner: owner)
            try await wait({ visible.use { $0.text == LoopAudioService.Phase.playing.rawValue } }, "PRECEDENCE_INITIAL_PLAYBACK_MISSING")
            // Install at the actual getter boundary of the next inspection,
            // independently of timer delivery or the MainActor's exact latency.
            fixture.use {
                $0.hookName = "playing-get"
                $0.hook = {
                    fixture.use { value in
                        value.calls.append("precedence-boundary")
                        if name.hasPrefix("stopped-") { value.physicalPlaying = false }
                        if name.hasPrefix("misconfigured-") || name == "stopped-misconfigured-before-progress" {
                            value.configured = false
                        }
                        if name == "mode-misconfigured-before-options" { value.modeConfigured = false }
                        value.blocked = blockedStep
                    }
                }
            }
            service.notify(.hint)
            try await wait({ fixture.use { $0.enteredBlock } }, "PRECEDENCE_GETTER_HOLD_MISSING")
            let pending = await diagnostics()
            try check(pending.operation != nil && pending.step?.rawValue == blockedStep && pending.stepReturnedAt == nil,
                      "PRECEDENCE_GETTER_WAS_FAKE_COMPLETED")
            observations["activations_before_held_getter_return"] = count("activate")
            observations["plays_before_held_getter_return"] = count("play")
            observations["players_before_held_getter_return"] = count("player-init")
            observations["claims_requested_before_held_getter_return"] = claims.use { $0.requested }
            observations["claims_ended_before_held_getter_return"] = claims.use { $0.ended.count }
            let afterBoundary = fixture.use { Array($0.calls.drop(while: { $0 != "precedence-boundary" }).dropFirst()) }
            if name == "healthy-progress-preserved" {
                try check(count("play") == 1 && count("player-init") == 1 && count("activate") == 1,
                          "HEALTHY_PROGRESS_FORCED_RECOVERY")
                try check(afterBoundary.contains("position-get"), "HEALTHY_PROGRESS_GETTER_SKIPPED")
            } else if name == "stopped-before-category" {
                // Configuration is still needed to repair a stopped player,
                // but belongs to recovery after failure admission and a claim.
                // It must not hold that known failure inside the old inspection.
                try check(pending.phase == .configuring && claims.use { $0.requested == 2 } && pending.records.filter {
                    $0.hasPrefix("Begin ") && $0.contains("start(")
                }.count == 2, "KNOWN_FAILURE_NOT_ADMITTED_BEFORE_UNNECESSARY_GETTER")
                try check(count("play") == 1 && count("player-init") == 1,
                          "STOPPED_CONFIGURATION_CHECK_INVENTED_RECOVERY")
            } else {
                // On the old input the hold occurs before any repair. On the
                // fixed input it is the post-repair confirmation's getter.
                try check(count("play") == 2 && fixture.use { $0.physicalPlaying },
                          "KNOWN_FAILURE_NOT_ADMITTED_BEFORE_UNNECESSARY_GETTER")
                try check(count("player-init") == (name == "stopped-before-progress" ? 1 : 2),
                          "KNOWN_FAILURE_CHANGED_MINIMAL_REPAIR")
                guard let play = afterBoundary.firstIndex(of: "play"),
                      let progress = afterBoundary.firstIndex(of: blockedStep) else {
                    throw PrecedenceFailure(marker: "PRECEDENCE_REQUIRED_CALL_MISSING")
                }
                try check(play < progress, "KNOWN_FAILURE_NOT_ADMITTED_BEFORE_UNNECESSARY_GETTER")
                try check(!afterBoundary[..<play].contains(where: {
                    ["position-get", "clock-get", "duration-get", "rate-enabled-get", "rate-get", "buffer-get"].contains($0)
                }), "KNOWN_FAILURE_READ_CORROBORATION_BEFORE_REPAIR")
            }
        } catch let error as PrecedenceFailure { failures.append(error.marker) }
        catch { failures.append("PRECEDENCE_UNEXPECTED_ERROR: \(error)") }

        // Keep the true operation gate until its API returns, then complete Off.
        // Negative controls must also prove they released every held resource.
        service.setEnabled(false, owner: owner)
        fixture.use { $0.hook = nil; $0.hookName = nil; $0.blocked = nil }
        fixture.release.signal()
        fixture.deliverPending()
        var cleanupPassed = false
        do {
            try await wait({ visible.use { $0.text == "Off" } }, "PRECEDENCE_FINAL_OFF_MISSING")
            try await wait({ claims.use { $0.requested == $0.ended.count } }, "PRECEDENCE_CLAIM_END_MISSING")
            let final = await diagnostics()
            try check(final.operation == nil && !final.timerActive && final.maximumOutstanding == 1,
                      "PRECEDENCE_FINAL_WORK_BOUND")
            try check(fixture.use { !$0.physicalPlaying && $0.livePlayers == 0 && $0.peakPlayers <= 1 &&
                                    $0.peak <= 1 && $0.onWrongQueue == 0 }, "PRECEDENCE_FINAL_PLAYER_BOUND")
            try check(claims.use { Set($0.ended).count == $0.ended.count }, "PRECEDENCE_DUPLICATE_CLAIM_END")
            cleanupPassed = true
        } catch let error as PrecedenceFailure { failures.append(error.marker) }
        catch { failures.append("PRECEDENCE_CLEANUP_ERROR: \(error)") }
        service.unregister(owner)
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "assertions": assertions, "cleanup_passed": cleanupPassed,
            "observations": observations, "shipping_interval_seconds": 0.5,
            "scope": "Actual adapter/service with controlled AV outcomes; a held getter is not a physical-device hang claim"]
        do {
            let bytes = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
            print(String(decoding: bytes, as: UTF8.self))
        } catch { exit(2) }
        for failure in failures { FileHandle.standardError.write(Data((failure + "\n").utf8)) }
        exit(failures.isEmpty ? 0 : 74)
    }
}
