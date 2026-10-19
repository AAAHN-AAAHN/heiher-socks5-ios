import Foundation
import Dispatch

// Controlled outcomes and exact queue boundaries; no Apple runtime/device claim.
final class FinalizationValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

struct FinalizationResult: Sendable {
    let operation: UInt64
    let returnedAt: Double
    let retryAt: Double
    let episode: Bool
}

enum FinalizationObservation {
    static let result = FinalizationValue<FinalizationResult?>(nil)
    // Identical copies observe the assigned deadline before reconcile can enter
    // another command. This does not infer a deadline from host wake-up latency.
    static func completed(_ operation: UInt64, _ returnedAt: Double, _ retryAt: Double, _ episode: Bool) {
        result.use { $0 = FinalizationResult(operation: operation,
            returnedAt: returnedAt, retryAt: retryAt, episode: episode) }
    }
}

private final class FinalizationEndpoint: LoopAudioEndpoint, @unchecked Sendable {
    struct Pending {
        let name: String
        let context: LoopAudioService.Context
        let completion: @Sendable (LoopAudioService.Reply) -> Void
    }
    enum ResultKind: Equatable { case healthy, stopped, misconfigured, failed, empty, superseded, invalidAsset, wrongEpoch }
    let pending = FinalizationValue<Pending?>(nil)

    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        let name: String
        switch command {
        case .start: name = "start"
        case .inspect: name = "inspect"
        case .stop: completion(.init()); return
        }
        pending.use { value in
            precondition(value == nil, "FIXTURE_OVERLAPPING_PENDING_COMMAND")
            value = Pending(name: name, context: context, completion: completion)
        }
    }
    var name: String? { pending.use { $0?.name } }
    @discardableResult func reply(_ result: ResultKind) -> UInt64? {
        guard let value = pending.use({ current -> Pending? in
            let value = current; current = nil; return value
        }) else { return nil }
        switch result {
        case .failed: value.completion(.init(error: "Controlled start or inspection failure"))
        case .empty: value.completion(.init())
        case .superseded: value.completion(.init(superseded: true))
        default:
            let now = ProcessInfo.processInfo.systemUptime
            let playing = result == .healthy || result == .misconfigured
            let configured = result != .misconfigured
            let epoch = result == .wrongEpoch ? value.context.epoch &+ 1 : value.context.epoch
            value.completion(.init(sample: .init(generation: 1, epoch: epoch,
                playing: playing, configured: configured,
                position: now.truncatingRemainder(dividingBy: 0.05), deviceTime: now,
                duration: 0.05, rate: 1, startedAt: now, finishedAt: now, bufferDuration: 0.001),
                invalidAsset: result == .invalidAsset))
        }
        return value.context.id
    }
}

private struct FinalizationFailure: Error { let marker: String }

@main struct RecoveryFinalizationTests {
    @MainActor static var assertions = 0
    @MainActor static func check(_ value: Bool, _ marker: String) throws {
        assertions += 1
        if !value { throw FinalizationFailure(marker: marker) }
    }
    @MainActor static func wait(_ condition: () -> Bool, _ marker: String, seconds: Double = 3) async throws {
        let end = ProcessInfo.processInfo.systemUptime + seconds
        while !condition() && ProcessInfo.processInfo.systemUptime < end {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        try check(condition(), marker)
    }

    @MainActor static func main() async {
        guard CommandLine.arguments.count == 4 else { exit(2) }
        let name = CommandLine.arguments[1]
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = CommandLine.arguments[2] }
        let scripted = name.hasPrefix("inspect-") || name.hasPrefix("start-") || name.hasSuffix("-paced")
        let controlled = FinalizationEndpoint()
        let visible = FinalizationValue(LoopAudioService.State())
        let claims = FinalizationValue((requested: 0, ended: [Int](), live: Set<Int>(), peak: 0))
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
            if scripted { return controlled }
            queue.setSpecific(key: fixture.queueKey, value: true)
            return LoopAudioService.auditEndpoint(queue: queue, event: event)
        }
        let owner = service.register { state in visible.use { $0 = state } }
        var owners = [owner]
        var failures = [String]()
        var observations = [String: String]()
        let began = ProcessInfo.processInfo.systemUptime
        let releaseControl = DispatchSemaphore(value: 0)

        func count(_ call: String) -> Int { fixture.use { $0.calls.filter { $0 == call }.count } }
        func playing() -> Bool { visible.use { $0.text == LoopAudioService.Phase.playing.rawValue } }
        func fence() async -> FinalizationControl {
            await withCheckedContinuation { continuation in
                service.auditFinalizationFence { continuation.resume(returning: $0) }
            }
        }
        func settle() async throws -> FinalizationControl {
            let end = ProcessInfo.processInfo.systemUptime + 3
            var value = await fence()
            while value.operation != nil && ProcessInfo.processInfo.systemUptime < end {
                try await Task.sleep(nanoseconds: 1_000_000)
                value = await fence()
            }
            try check(value.operation == nil, "FIXTURE_OPERATION_DID_NOT_SETTLE")
            return value
        }
        func start() async throws {
            service.setEnabled(true, owner: owner)
            try await wait(playing, "FIXTURE_INITIAL_PLAYBACK_NOT_REACHED")
            _ = try await settle()
        }
        func reuse() async throws -> @MainActor @Sendable (Bool) -> Void {
            try await start()
            guard let old = fixture.use({ $0.callbacks.last }) else {
                throw FinalizationFailure(marker: "FIXTURE_INITIAL_DELEGATE_MISSING")
            }
            fixture.use { $0.physicalPlaying = false }
            try await wait({ count("play") == 2 && fixture.use { $0.physicalPlaying } },
                           "FIXTURE_STOPPED_PLAYER_DID_NOT_RESUME")
            _ = try await settle()
            try check(count("player-init") == 1 && playing(), "VALID_STOPPED_PLAYER_NOT_REUSED")
            return old
        }
        func observed(_ kind: FinalizationEndpoint.ResultKind) async throws -> FinalizationResult {
            guard let id = controlled.reply(kind) else {
                throw FinalizationFailure(marker: "FIXTURE_NO_PENDING_RESULT")
            }
            try await wait({ FinalizationObservation.result.use { $0?.operation == id } },
                           "FIXTURE_RESULT_BOUNDARY_NOT_OBSERVED")
            return FinalizationObservation.result.use { $0! }
        }

        do {
            if name == "reused-queued-delegate" {
                try await start()
                guard let old = fixture.use({ $0.callbacks.last }) else {
                    throw FinalizationFailure(marker: "FIXTURE_INITIAL_DELEGATE_MISSING")
                }
                let before = await fence()
                fixture.use { $0.physicalPlaying = false; $0.blocked = "activate" }
                try await wait({ fixture.use { $0.enteredBlock } }, "FIXTURE_REUSE_ACTIVATION_NOT_HELD")
                // This receipt enters before rotation and drains after the new
                // activation returns. Async receipt delivery handles session
                // completion before its already copied old delegate receipt.
                old(true)
                fixture.release.signal()
                try await wait({ count("play") >= 2 }, "FIXTURE_HELD_REUSE_DID_NOT_FINISH")
                let after = await fence()
                observations["epoch_before_queued_callback"] = String(before.epoch)
                observations["epoch_after_queued_callback"] = String(after.epoch)
                try check(after.epoch == before.epoch, "REUSED_PLAYBACK_ACCEPTED_STALE_DELEGATE")
                try check(count("player-init") == 1 && fixture.use { $0.physicalPlaying },
                          "QUEUED_OLD_DELEGATE_STOPPED_REUSED_PLAYBACK")
            } else if name == "reused-finish" || name == "reused-decoder" || name == "reused-current-mixed" {
                let old = try await reuse()
                let before = await fence()
                if name == "reused-current-mixed" {
                    guard let current = fixture.use({ $0.callbacks.last }) else {
                        throw FinalizationFailure(marker: "FIXTURE_REUSED_DELEGATE_MISSING")
                    }
                    fixture.use { $0.blocked = "position-get" }
                    service.notify(.hint)
                    try await wait({ fixture.use { $0.enteredBlock } }, "FIXTURE_REUSED_DELEGATE_HOLD_NOT_ENTERED")
                    current(true)
                    for _ in 0..<1000 { old(false) }
                    fixture.release.signal()
                    try await wait({ count("player-init") == 2 && playing() }, "REUSED_CURRENT_DECODER_LOST")
                    _ = try await settle()
                    try check(count("player-init") == 2, "REUSED_CURRENT_DECODER_REBUILT_TWICE")
                } else {
                    old(name == "reused-decoder")
                    let after = await fence()
                    observations["epoch_before_old_callback"] = String(before.epoch)
                    observations["epoch_after_old_callback"] = String(after.epoch)
                    try check(after.epoch == before.epoch, "REUSED_PLAYBACK_ACCEPTED_STALE_DELEGATE")
                    try check(count("player-init") == 1 && fixture.use { $0.physicalPlaying },
                              "STALE_REUSED_DELEGATE_STOPPED_PLAYBACK")
                }
            } else if name == "reused-generation-limit" {
                try await start()
                await withCheckedContinuation { continuation in
                    service.auditSetPlayerGeneration(UInt64.max) { continuation.resume() }
                }
                fixture.use { $0.physicalPlaying = false }
                try await wait({ count("activate") >= 2 }, "FIXTURE_SATURATED_REUSE_NOT_ATTEMPTED")
                _ = try await settle()
                try check(count("play") == 1 && count("player-init") == 1,
                          "SATURATED_REUSE_STARTED_WITH_OLD_CALLBACK_IDENTITY")
                try await wait({ visible.use { $0.text.contains("Player generation limit reached") } },
                               "GENERATION_LIMIT_ERROR_NOT_VISIBLE")
            } else if name == "failed-allocation-generation" {
                fixture.use {
                    $0.rejections["player-init"] = 1
                    $0.hookName = "player-init"
                    $0.hook = { service.setEnabled(false, owner: owner) }
                }
                service.setEnabled(true, owner: owner)
                try await wait({ count("player-init") == 1 }, "FIXTURE_ALLOCATION_FAILURE_NOT_ENTERED")
                _ = try await settle()
                let generation: UInt64? = await withCheckedContinuation { continuation in
                    service.auditPlayerGeneration { continuation.resume(returning: $0) }
                }
                try check(generation == 0 && count("play") == 0 && fixture.use { $0.created == 0 },
                          "FAILED_ALLOCATION_CONSUMED_CALLBACK_GENERATION")
            } else if name == "owner-unregister-blocked" || name == "owner-off-blocked" || name == "owner-on-preserved" {
                fixture.use { $0.resource = name == "owner-off-blocked" ? CommandLine.arguments[3] : nil }
                service.setEnabled(true, owner: owner)
                try await wait({ visible.use { $0.text.hasPrefix("Waiting to resume:") } },
                               "FIXTURE_INVALID_ASSET_NOT_OBSERVED")
                let before = try await settle()
                try check(before.assetBlocked && !before.timerActive, "FIXTURE_ASSET_NOT_BLOCKED")
                let reads = fixture.use { $0.assetReads }
                let unused = service.register { _ in }
                owners.append(unused)
                if name == "owner-on-preserved" {
                    let held = FinalizationValue(false)
                    service.auditHoldControl(entered: { held.use { $0 = true } }, release: releaseControl)
                    try await wait({ held.use { $0 } }, "FIXTURE_CONTROL_HOLD_NOT_ENTERED")
                    fixture.use { $0.resource = CommandLine.arguments[2] }
                    service.setEnabled(true, owner: owner)
                    service.setEnabled(false, owner: unused)
                    service.unregister(unused)
                    releaseControl.signal()
                    try await wait(playing, "OWNER_CLEANUP_ERASED_PENDING_EXPLICIT_ON")
                } else {
                    if name == "owner-unregister-blocked" { service.unregister(unused) }
                    else { service.setEnabled(false, owner: unused) }
                    let after = await fence()
                    observations["asset_lookups_before_cleanup"] = String(reads)
                    observations["asset_lookups_after_cleanup"] = String(fixture.use { $0.assetReads })
                    try check(fixture.use { $0.assetReads } == reads && after.assetBlocked,
                              "OWNER_CLEANUP_REOPENED_BLOCKED_ASSET")
                }
            } else if name == "owner-unregister-paced" || name == "owner-off-paced" {
                service.setEnabled(true, owner: owner)
                try await wait({ controlled.name == "start" }, "FIXTURE_START_NOT_ENTERED")
                let result = try await observed(.failed)
                let unused = service.register { _ in }
                owners.append(unused)
                if name == "owner-unregister-paced" { service.unregister(unused) }
                else { service.setEnabled(false, owner: unused) }
                let after = await fence()
                observations["retry_deadline_before_cleanup"] = String(result.retryAt)
                observations["retry_deadline_after_cleanup"] = String(after.retryAt)
                try check(after.retryAt == result.retryAt, "OWNER_CLEANUP_ERASED_RETRY_DEADLINE")
            } else if name == "owner-release-failure" || name == "owner-last-off" {
                try await start()
                if name == "owner-release-failure" {
                    fixture.use { $0.rejections["deactivate"] = 1 }
                    service.setEnabled(false, owner: owner)
                    try await wait({ visible.use { $0.text.hasPrefix("Off; session release failed:") } },
                                   "FIXTURE_RELEASE_FAILURE_NOT_RECORDED")
                    service.setEnabled(false, owner: owner)
                    try await wait({ count("deactivate") == 2 && visible.use { $0.text == "Off" } },
                                   "REPEATED_OFF_DID_NOT_RETRY_OWNED_RELEASE")
                } else {
                    service.unregister(owner)
                    let after = try await settle()
                    try check(!after.on && count("deactivate") == 1 && !fixture.use { $0.physicalPlaying },
                              "LAST_OWNER_REMOVAL_DID_NOT_RELEASE_AUDIO")
                }
            } else if name.hasPrefix("inspect-") || name.hasPrefix("start-") {
                service.setEnabled(true, owner: owner)
                try await wait({ controlled.name == "start" }, "FIXTURE_START_NOT_ENTERED")
                if name.hasPrefix("inspect-") {
                    try check(controlled.reply(.healthy) != nil, "FIXTURE_HEALTHY_START_NOT_PENDING")
                    try await wait(playing, "FIXTURE_HEALTHY_START_NOT_ACCEPTED")
                    try await wait({ controlled.name == "inspect" }, "FIXTURE_INSPECTION_NOT_ENTERED")
                }
                let kind: FinalizationEndpoint.ResultKind
                switch name {
                case "inspect-stopped", "start-stopped-paced", "inspect-epoch-changed-paced": kind = .stopped
                case "inspect-misconfigured": kind = .misconfigured
                case "inspect-error-paced", "start-error-paced": kind = .failed
                case "inspect-empty-paced": kind = .empty
                case "inspect-superseded-paced": kind = .superseded
                case "inspect-invalid-asset-paced": kind = .invalidAsset
                case "inspect-wrong-sample-epoch-paced": kind = .wrongEpoch
                default: throw FinalizationFailure(marker: "FIXTURE_UNKNOWN_CASE")
                }
                if name == "inspect-epoch-changed-paced" { service.notify(.mediaLost) }
                let result = try await observed(kind)
                let delay = result.retryAt - result.returnedAt
                observations["assigned_delay_seconds"] = String(delay)
                observations["episode_before_first_recovery"] = String(result.episode)
                if name == "inspect-stopped" || name == "inspect-misconfigured" {
                    try check(!result.episode && delay == 0, "FIRST_OBSERVED_STOP_ADDED_RETRY_COOLDOWN")
                    try await wait({ controlled.name == "start" }, "FIRST_OBSERVED_STOP_DID_NOT_START_RECOVERY")
                } else {
                    try check(abs(delay - 0.5) < 0.000000001, "COMPLETED_FAILURE_LOST_ORIGINAL_RETRY_PACING")
                    if name == "inspect-invalid-asset-paced" {
                        let after = await fence()
                        try check(after.assetBlocked && !after.timerActive && after.operation == nil,
                                  "INVALID_ASSET_BYPASSED_AUTOMATIC_RETRY_BLOCK")
                    }
                }
            } else { throw FinalizationFailure(marker: "FIXTURE_UNKNOWN_CASE") }
        } catch let error as FinalizationFailure { failures.append(error.marker) }
        catch { failures.append("FIXTURE_UNEXPECTED_ERROR: \(error)") }

        // Failures remain failures after the same bounded cleanup on both inputs.
        releaseControl.signal()
        fixture.release.signal()
        service.setEnabled(false, owner: owner)
        controlled.reply(.superseded)
        fixture.deliverPending()
        var cleanupPassed = false
        do {
            let end = ProcessInfo.processInfo.systemUptime + 5
            var final = await fence()
            while (final.on || final.operation != nil || !claims.use({ $0.live.isEmpty })) && ProcessInfo.processInfo.systemUptime < end {
                controlled.reply(.superseded)
                fixture.deliverPending()
                try await Task.sleep(nanoseconds: 1_000_000)
                final = await fence()
            }
            try check(!final.on && final.operation == nil && !final.timerActive && final.maximumOutstanding == 1,
                      "FINAL_OFF_DID_NOT_DRAIN_SINGLE_FLIGHT")
            let value = claims.use { $0 }
            try check(value.live.isEmpty && value.peak <= 1 && value.requested == value.ended.count &&
                      Set(value.ended).count == value.ended.count, "FINAL_EXECUTION_CLAIM_NOT_BALANCED")
            try check(fixture.use { !$0.physicalPlaying && $0.livePlayers == 0 && $0.peakPlayers <= 1 &&
                      $0.peak <= 1 && $0.onWrongQueue == 0 }, "FINAL_AUDIO_RESOURCE_OR_QUEUE_BOUND")
            cleanupPassed = true
        } catch let error as FinalizationFailure { failures.append(error.marker) }
        catch { failures.append("FIXTURE_CLEANUP_ERROR: \(error)") }
        for id in owners { service.unregister(id) }
        let value = claims.use { $0 }
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "assertions": assertions, "cleanup_passed": cleanupPassed,
            "observations": observations, "requests": value.requested, "ended_ids": value.ended,
            "maximum_live_claims": value.peak, "player_creations": fixture.use { $0.created },
            "shipping_interval_seconds": 0.5, "elapsed_seconds": ProcessInfo.processInfo.systemUptime - began,
            "scope": "Controlled service and actual adapter with AV doubles; no OS grant or physical playback proof"]
        do {
            let bytes = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
            print(String(decoding: bytes, as: UTF8.self))
        } catch { FileHandle.standardError.write(Data("FIXTURE_RESULT_ENCODING_FAILED\n".utf8)); exit(2) }
        for failure in failures { FileHandle.standardError.write(Data((failure + "\n").utf8)) }
        exit(failures.isEmpty ? 0 : 74)
    }
}
