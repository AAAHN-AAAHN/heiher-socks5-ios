import Foundation
import Dispatch

// Actual adapter with controlled assets/API outcomes; no physical Apple claim.
final class AssetEpisodeValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

private struct AssetEpisodeFailure: Error { let marker: String }

@main struct AssetEpisodeTests {
    @MainActor static func check(_ value: Bool, _ marker: String) throws {
        if !value { throw AssetEpisodeFailure(marker: marker) }
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
        guard CommandLine.arguments.count == 4 else { exit(2) }
        let name = CommandLine.arguments[1]
        let valid = CommandLine.arguments[2]
        let invalid = CommandLine.arguments[3]
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = name == "import-missing" ? nil : invalid }
        let visible = AssetEpisodeValue(LoopAudioService.State())
        let claims = AssetEpisodeValue((requested: 0, ended: [Int](), live: Set<Int>(), peak: 0))
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
        var owners = [owner]
        var failures = [String]()
        var observations = [String: Int]()
        var cleanup = false
        let releaseControl = DispatchSemaphore(value: 0)
        func count(_ call: String) -> Int { fixture.use { $0.calls.filter { $0 == call }.count } }
        func playing() -> Bool {
            visible.use { $0.text == LoopAudioService.Phase.playing.rawValue } &&
                fixture.use { $0.physicalPlaying }
        }
        func fence() async -> FinalizationControl {
            await withCheckedContinuation { continuation in
                service.auditFinalizationFence { continuation.resume(returning: $0) }
            }
        }
        func settle() async throws -> FinalizationControl {
            let end = ProcessInfo.processInfo.systemUptime + 3
            var value = await fence()
            while (value.operation != nil || !claims.use({ $0.live.isEmpty })) &&
                  ProcessInfo.processInfo.systemUptime < end {
                try await Task.sleep(nanoseconds: 1_000_000)
                value = await fence()
            }
            try check(value.operation == nil && claims.use { $0.live.isEmpty },
                      "FIXTURE_OPERATION_OR_CLAIM_DID_NOT_SETTLE")
            return value
        }
        func holdControl() async throws {
            let held = AssetEpisodeValue(false)
            service.auditHoldControl(entered: { held.use { $0 = true } }, release: releaseControl)
            try await wait({ held.use { $0 } }, "FIXTURE_CONTROL_HOLD_NOT_ENTERED")
        }
        func expectBlocked() async throws {
            try await wait({ visible.use { $0.text.hasPrefix("Waiting to resume:") } },
                           "FIXTURE_INVALID_ASSET_NOT_OBSERVED")
            let value = try await settle()
            try check(value.on && value.assetBlocked && !value.timerActive &&
                      fixture.use { $0.assetReads == 1 && $0.created == 0 } &&
                      claims.use { $0.requested == 1 && $0.ended == [1] },
                      "FIXTURE_ASSET_EPISODE_NOT_BLOCKED")
        }

        do {
            if name == "off-on-release-pending" {
                fixture.use { $0.resource = valid }
                service.setEnabled(true, owner: owner)
                try await wait(playing, "FIXTURE_INITIAL_PLAYBACK_NOT_REACHED")
                _ = try await settle()
                fixture.use { $0.blocked = "deactivate" }
                service.setEnabled(false, owner: owner, explicit: false)
                try await wait({ fixture.use { $0.enteredBlock } }, "FIXTURE_DEACTIVATION_NOT_HELD")
                service.setEnabled(true, owner: owner, explicit: false)
                let pending: LoopAudioService.Diagnostics = await withCheckedContinuation { continuation in
                    service.diagnostics { continuation.resume(returning: $0) }
                }
                try check(pending.operation != nil && pending.step == .deactivate &&
                          pending.stepReturnedAt == nil && pending.maximumOutstanding == 1 &&
                          count("play") == 1 && count("activate") == 1 &&
                          fixture.use { $0.livePlayers == 0 && !$0.physicalPlaying },
                          "RESTORED_ON_BYPASSED_ACTUAL_RELEASE")
                fixture.release.signal()
                try await wait({ playing() && count("play") == 2 }, "RESTORED_ON_DID_NOT_FOLLOW_RELEASE")
                _ = try await settle()
                try check(count("deactivate") == 1 && fixture.use { $0.created == 2 },
                          "RELEASE_RECOVERY_RESOURCE_COUNT_CHANGED")
            } else if name == "pending-invalid-off-on" {
                fixture.use { $0.blocked = "asset" }
                service.setEnabled(true, owner: owner)
                try await wait({ fixture.use { $0.enteredBlock } }, "FIXTURE_ASSET_LOOKUP_NOT_HELD")
                try await holdControl()
                fixture.release.signal()
                // Keep this operation valid until it really returns invalidAsset;
                // only control consumption is held across the newer Off-On.
                try await wait({ service.auditAvailableResult() != nil }, "FIXTURE_OLD_ASSET_RESULT_NOT_AVAILABLE")
                try check(fixture.use { $0.assetReads == 1 && $0.created == 0 },
                          "FIXTURE_OLD_INVALID_ASSET_PATH_CHANGED")
                service.setEnabled(false, owner: owner, explicit: false)
                service.setEnabled(true, owner: owner, explicit: false)
                fixture.use { $0.resource = valid }
                releaseControl.signal()
                try await wait(playing, "STALE_INVALID_ASSET_BLOCKED_NEW_EPISODE")
                let value = try await settle()
                try check(!value.assetBlocked && fixture.use { $0.assetReads == 2 && $0.created == 1 },
                          "STALE_INVALID_ASSET_RELATCHED_AFTER_RELEASE")
            } else {
                service.setEnabled(true, owner: owner)
                try await expectBlocked()
                if name != "import-still-invalid" { fixture.use { $0.resource = valid } }
                switch name {
                case "import-missing", "import-invalid", "import-still-invalid":
                    service.setEnabled(false, owner: owner, explicit: false)
                    let off = try await settle()
                    try check(!off.on && !off.timerActive, "FIXTURE_IMPORTED_OFF_DID_NOT_SETTLE")
                    try await wait({ visible.use { $0.text == "Off" } }, "FIXTURE_IMPORTED_OFF_NOT_VISIBLE")
                    service.setEnabled(true, owner: owner, explicit: false)
                    if name == "import-still-invalid" {
                        try await wait({ fixture.use { $0.assetReads == 2 } &&
                            visible.use { $0.text.hasPrefix("Waiting to resume:") } },
                            "IMPORT_ON_DID_NOT_RETRY_INVALID_ASSET")
                    } else {
                        try await wait(playing, "IMPORT_ON_DID_NOT_RETRY_BLOCKED_ASSET")
                    }
                case "coalesced-off-on":
                    try await holdControl()
                    service.setEnabled(false, owner: owner, explicit: false)
                    service.setEnabled(true, owner: owner, explicit: false)
                    releaseControl.signal()
                    try await wait(playing, "COALESCED_OFF_ON_DID_NOT_RETRY_BLOCKED_ASSET")
                case "echo-preserves-block":
                    service.setEnabled(true, owner: owner, explicit: false)
                case "surviving-owner-preserves-block":
                    let other = service.register { _ in }
                    owners.append(other)
                    service.setEnabled(true, owner: other, explicit: false)
                    _ = try await settle()
                    service.setEnabled(false, owner: other, explicit: false)
                    service.unregister(other)
                default: throw AssetEpisodeFailure(marker: "UNKNOWN_CASE")
                }
                let value = try await settle()
                if name == "import-still-invalid" {
                    try check(value.on && value.assetBlocked && !value.timerActive &&
                              fixture.use { $0.assetReads == 2 && $0.created == 0 } &&
                              claims.use { $0.requested <= 2 && $0.ended.count == $0.requested },
                              "FRESH_INVALID_ASSET_EPISODE_DID_NOT_BLOCK_ONCE")
                } else if name == "echo-preserves-block" || name == "surviving-owner-preserves-block" {
                    try check(value.on && value.assetBlocked && !value.timerActive &&
                              fixture.use { $0.assetReads == 1 && $0.created == 0 } &&
                              claims.use { $0.requested == 1 }, "UNCHANGED_EPISODE_REOPENED_BLOCKED_ASSET")
                } else {
                    try check(value.on && !value.assetBlocked && fixture.use { $0.assetReads == 2 && $0.created == 1 } &&
                              count("play") == 1, "FRESH_EPISODE_RETRIED_MORE_THAN_ONCE")
                }
            }
            try check(claims.use { $0.requested <= 2 && $0.peak <= 1 } &&
                      fixture.use { $0.peakPlayers <= 1 && $0.peak <= 1 && $0.onWrongQueue == 0 },
                      "ASSET_EPISODE_RESOURCE_BOUND_BROKEN")
        } catch let failure as AssetEpisodeFailure { failures.append(failure.marker) }
        catch { failures.append("UNEXPECTED: \(error)") }

        observations["asset_lookups_before_cleanup"] = fixture.use { $0.assetReads }
        observations["play_calls_before_cleanup"] = count("play")
        observations["players_created_before_cleanup"] = fixture.use { $0.created }
        releaseControl.signal()
        fixture.release.signal()
        fixture.use { $0.blocked = nil; $0.hookName = nil; $0.hook = nil }
        for value in owners { service.setEnabled(false, owner: value) }
        do {
            let final = try await settle()
            try check(!final.on && !final.timerActive && final.operation == nil && final.maximumOutstanding == 1,
                      "OFF_CLEANUP_DID_NOT_SETTLE")
            try check(fixture.use { !$0.physicalPlaying && $0.livePlayers == 0 && $0.peakPlayers <= 1 },
                      "PLAYER_CLEANUP_FAILED")
            try check(claims.use { $0.live.isEmpty && Set($0.ended).count == $0.ended.count &&
                $0.ended.sorted() == Array(0..<$0.requested).map { $0 + 1 } && $0.peak <= 1 }, "CLAIM_CLEANUP_FAILED")
            cleanup = true
        } catch let failure as AssetEpisodeFailure { failures.append(failure.marker) }
        catch { failures.append("CLEANUP_UNEXPECTED: \(error)") }
        for value in owners { service.unregister(value) }
        let report: [String: Any] = ["case": name, "status": failures.isEmpty ? "PASS" : "FAIL",
            "failures": failures, "cleanup_passed": cleanup, "observations": observations,
            "calls": fixture.use { $0.calls }, "peak_players": fixture.use { $0.peakPlayers },
            "claims_requested": claims.use { $0.requested }, "claims_ended": claims.use { $0.ended },
            "scope": "Exact service and adapter with controlled WAV resources and AV doubles; no physical Apple execution"]
        let bytes = try! JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        print(String(decoding: bytes, as: UTF8.self))
        exit(failures.isEmpty ? 0 : 74)
    }
}
