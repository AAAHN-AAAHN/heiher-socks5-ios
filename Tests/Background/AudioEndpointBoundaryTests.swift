import Foundation
import Dispatch

private final class BoundaryValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T
    init(_ value: T) { self.value = value }
    func use<R>(_ body: (inout T) -> R) -> R {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

@main struct AudioEndpointBoundaryTests {
    @MainActor static var assertions = 0
    @MainActor static func check(_ value: Bool, _ message: String) {
        assertions += 1
        if !value {
            FileHandle.standardError.write(Data(("FAIL: " + message + "\n").utf8))
            fatalError(message)
        }
    }
    @MainActor static func until(_ condition: () -> Bool, _ message: String,
                                 timeout: Double = 3, diagnostic: (() async -> String)? = nil) async throws {
        let end = ProcessInfo.processInfo.systemUptime + timeout
        while !condition() && ProcessInfo.processInfo.systemUptime < end {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        let reached = condition()
        if !reached, let diagnostic {
            FileHandle.standardError.write(Data((await diagnostic() + "\n").utf8))
        }
        check(reached, message)
    }
    @MainActor static func pendingFinalOwner(_ fixture: AudioEndpointFixture) async throws {
        let claims = BoundaryValue((requested: 0, ended: [Int]()))
        let provider = RecoveryExecutionLease.Provider(request: { _, receipt in
            let id = claims.use { value -> Int in value.requested += 1; return value.requested }
            receipt(id)
        }, end: { id in claims.use { $0.ended.append(id) } })
        var policy = LoopAudioService.Policy()
        policy.interval = 0.005
        policy.warning = 0.025
        policy.stalled = 0.06
        var service: LoopAudioService? = LoopAudioService(policy: policy, leaseProvider: { provider }) { queue, event in
            queue.setSpecific(key: fixture.queueKey, value: true)
            return LoopAudioService.auditEndpoint(queue: queue, event: event)
        }
        let facadeReleased = { [weak value = service] in value == nil }
        let ownerAlive = service!.auditOwnerLifetime()
        let owner = service!.register { _ in }
        fixture.use { $0.holdCompletion = "activate" }
        service!.setEnabled(true, owner: owner)
        try await until({ fixture.use { !$0.pending.isEmpty } }, "ACTIVATION_COMPLETION_NOT_HELD")
        service!.setEnabled(false, owner: owner)
        service!.unregister(owner)
        let stopped = await withCheckedContinuation { continuation in
            service!.diagnostics { continuation.resume(returning: $0) }
        }
        check(stopped.operation != nil && !stopped.timerActive, "FINAL_OWNER_OFF_DID_NOT_REACH_CONTROL")
        let drained = BoundaryValue(false)
        service!.auditAfterQueueDrain { drained.use { $0 = true } }
        service = nil
        check(facadeReleased(), "TEST_RETAINED_EXTERNAL_FACADE")
        try await until({ drained.use { $0 } }, "OWNER_RELEASE_BARRIER_DID_NOT_DRAIN")
        check(ownerAlive(), "PENDING_RECEIPT_LOST_OWNER")
        fixture.deliverPending()
        try await until({ fixture.use { $0.calls.filter { $0 == "deactivate" }.count == 1 && !$0.active } },
                        "RELEASED_OWNER_DID_NOT_DEACTIVATE")
        try await until({ claims.use { $0.requested == $0.ended.count } }, "TOKEN_END_NOT_RETURNED")
        try await until({ !ownerAlive() }, "COMPLETED_RECEIPT_RETAINED_OWNER")
        check(fixture.use { $0.created == 0 && $0.livePlayers == 0 && $0.peakPlayers == 0 }, "RELEASED_OWNER_CREATED_PLAYER")
        check(fixture.use { $0.peak <= 1 && $0.onWrongQueue == 0 }, "AV_API_OUTSIDE_EXCLUSIVE_IO_LANE")
        check(claims.use { $0.requested == 1 && $0.ended == [1] }, "TOKEN_END_IDENTITY_OR_LEAK")
        print("PASS actual-adapter pending-final-owner: \(assertions) assertions; real receipt outlives external facade")
    }
    @MainActor static func main() async throws {
        let name = CommandLine.arguments[1]
        let fixture = AudioEndpointFixture.shared
        fixture.use { $0.resource = CommandLine.arguments[2] }
        if name == "pending-final-owner" { try await pendingFinalOwner(fixture); return }
        if name.hasSuffix("rate-get") { fixture.use { $0.rateEnabled = true } }
        let state = BoundaryValue(LoopAudioService.State())
        let publications = BoundaryValue([String]())
        let claims = BoundaryValue((requested: 0, ended: [Int]()))
        let provider = RecoveryExecutionLease.Provider(request: { _, receipt in
            let id = claims.use { value -> Int in value.requested += 1; return value.requested }
            receipt(id)
        }, end: { id in claims.use { $0.ended.append(id) } })
        var policy = LoopAudioService.Policy()
        policy.interval = 0.005
        policy.warning = 0.025
        policy.stalled = 0.06
        let service = LoopAudioService(policy: policy, leaseProvider: { provider }) { queue, event in
            queue.setSpecific(key: fixture.queueKey, value: true)
            return LoopAudioService.auditEndpoint(queue: queue, event: event)
        }
        let owner = service.register { next in
            state.use { $0 = next }
            publications.use { $0.append(next.text) }
        }
        func playing() -> Bool { state.use { $0.text == "Playing silent WAV continuously" } }
        func off() -> Bool { state.use { $0.text == "Off" } }
        func count(_ call: String) -> Int { fixture.use { $0.calls.filter { $0 == call }.count } }
        func snapshot() async -> LoopAudioService.Diagnostics {
            await withCheckedContinuation { continuation in
                service.diagnostics { continuation.resume(returning: $0) }
            }
        }
        func start() async throws {
            service.setEnabled(true, owner: owner)
            try await until(playing, "ACTUAL_ADAPTER_START_FAILED")
        }
        func stop() async throws {
            service.setEnabled(false, owner: owner)
            try await until(off, "ACTUAL_ADAPTER_OFF_FAILED")
        }

        if name.hasPrefix("off-at-") {
            let boundary = String(name.dropFirst(7))
            fixture.use {
                $0.hookName = boundary
                $0.hook = {
                    service.setEnabled(false, owner: owner)
                    fixture.use { $0.calls.append("intent-off") }
                }
            }
            service.setEnabled(true, owner: owner)
            try await until({ fixture.use { $0.hook == nil } && off() }, "OFF_BOUNDARY_NOT_REACHED")
            check(!publications.use { $0.contains("Playing silent WAV continuously") }, "LATE_PLAYING_AFTER_OFF")
            check(!fixture.use { $0.physicalPlaying }, "PLAYER_RUNNING_AFTER_OFF")
            check(fixture.use { $0.livePlayers } == 0, "PLAYER_RETAINED_AFTER_OFF")
            let later = fixture.use { Array($0.calls.drop(while: { $0 != "intent-off" }).dropFirst()) }
            check(!later.contains("activate") && !later.contains("prepare") && !later.contains("play"),
                  "NEW_PLAYBACK_API_AFTER_OFF")
            check(later.allSatisfy { ["delegate", "stop", "session", "deactivate"].contains($0) },
                  "READ_OR_CONFIGURATION_AFTER_OFF")
            // A pre-activation failure/Off must not deactivate an unrelated session.
            if count("activate") == 0 { check(count("deactivate") == 0, "UNOWNED_SESSION_RELEASE") }
        } else if name.hasPrefix("blocked-") {
            let boundary = String(name.dropFirst(8))
            if boundary == "stop" || boundary == "deactivate" {
                try await start()
                fixture.use { $0.blocked = boundary }
                service.setEnabled(false, owner: owner)
            } else {
                fixture.use { $0.blocked = boundary }
                service.setEnabled(true, owner: owner)
            }
            try await until({ fixture.use { $0.enteredBlock } }, "API_BARRIER_NOT_ENTERED")
            let completed = (await snapshot()).completedOperations
            for _ in 0..<100 {
                service.notify(.hint)
                try await Task.sleep(nanoseconds: 1_000_000)
            }
            let before = await snapshot()
            check(before.operation != nil && before.maximumOutstanding == 1, "PENDING_GATE_WAS_RELEASED")
            check(before.completedOperations == completed, "INFLIGHT_API_WAS_FAKE_COMPLETED")
            if boundary != "stop" && boundary != "deactivate" {
                check(state.use { $0.text == "Waiting for system audio completion" }, "CONTROL_DID_NOT_OBSERVE_DELAY")
            }
            service.setEnabled(false, owner: owner)
            let stoppedControl = await snapshot()
            check(!stoppedControl.timerActive, "OFF_LEFT_AUTOMATIC_TIMER")
            check(fixture.use { $0.concurrent } == 1, "API_RETURN_WAS_INVENTED")
            fixture.release.signal()
            try await until(off, "OFF_DID_NOT_DRAIN_REAL_COMPLETION")
            check(!fixture.use { $0.physicalPlaying }, "OFF_DRAIN_LEFT_PLAYBACK")
        } else if name.hasPrefix("failure-") {
            let failures = Int(name.dropFirst(8))!
            fixture.use { $0.rejections["activate"] = failures }
            let began = ProcessInfo.processInfo.systemUptime
            service.setEnabled(true, owner: owner)
            try await until(playing, "FINITE_FAILURE_DID_NOT_RECOVER", timeout: 10, diagnostic: {
                let observed = await snapshot()
                let remaining = fixture.use { $0.rejections["activate", default: 0] }
                let visible = state.use { $0 }
                return "FINITE_FAILURE_DIAGNOSTIC elapsed=\(ProcessInfo.processInfo.systemUptime - began) " +
                    "attempts=\(count("activate")) remaining=\(remaining) state=\(visible) control=\(observed)"
            })
            print("FINITE_FAILURE_ELAPSED rejections=\(failures) seconds=\(ProcessInfo.processInfo.systemUptime - began)")
            check(count("activate") == failures + 1, "FAILURE_ATTEMPT_COUNT")
            check(claims.use { $0.requested } == 1, "FAILED_EPISODE_REISSUED_TOKEN")
            try await stop()
        } else {
            switch name {
            case "healthy":
                try await start()
                for i in 0..<10_000 { service.notify(i % 2 == 0 ? .hint : .available) }
                try await Task.sleep(nanoseconds: 30_000_000)
                check(count("activate") == 1 && count("player-init") == 1, "HEALTHY_RECREATION")
                check(fixture.use { $0.assetReads } == 1, "HEALTHY_DISK_READ")
                try await stop()
            case "preferences":
                fixture.use { $0.rejections = ["alerts": 1, "disconnect": 1] }
                try await start()
                check(count("alerts") == 1 && count("disconnect") == 1, "PREFERENCE_NOT_EXERCISED")
                check(count("activate") == 1, "BEST_EFFORT_PREFERENCE_ABORTED_PLAYBACK")
                try await stop()
            case "category-failure":
                fixture.use {
                    $0.rejections["category-set"] = 1
                    $0.hookName = "category-set"
                    $0.hook = { service.setEnabled(false, owner: owner) }
                }
                service.setEnabled(true, owner: owner)
                try await until({ count("category-set") == 1 && off() }, "CATEGORY_FAILURE_NOT_DRAINED")
                check(count("activate") == 0 && count("deactivate") == 0, "SETUP_FAILURE_RELEASED_UNOWNED_SESSION")
            case "prepare-failure", "play-failure", "player-failure":
                let key = name == "prepare-failure" ? "prepare" : name == "play-failure" ? "play" : "player-init"
                fixture.use { $0.rejections[key] = 1 }
                try await start()
                check(count(key) == 2, "PLAYER_FAILURE_DID_NOT_RETRY")
                try await stop()
            case "silent-stop":
                try await start()
                fixture.use { $0.physicalPlaying = false }
                try await until({ count("play") >= 2 && fixture.use { $0.physicalPlaying } }, "STOP_NOT_RECOVERED")
                check(count("player-init") == 1, "VALID_STOPPED_PLAYER_WAS_RECREATED")
                try await stop()
            case "configuration-drift":
                try await start()
                fixture.use { $0.configured = false }
                try await until({ count("player-init") == 2 && playing() }, "DRIFT_NOT_RECOVERED")
                check(count("category-set") == 2, "DRIFT_NOT_RECONFIGURED")
                try await stop()
            case "compatible-route":
                try await start()
                for _ in 0..<128 { service.notify(.routeChanged) }
                try await Task.sleep(nanoseconds: 30_000_000)
                check(count("player-init") == 1 && count("activate") == 1, "COMPATIBLE_ROUTE_RESTARTED_PLAYER")
                try await stop()
            case "decoder":
                try await start()
                fixture.use { $0.callbacks.last }?(true)
                try await until({ count("player-init") == 2 && playing() }, "DECODER_FAILURE_NOT_RECOVERED")
                try await stop()
            case "stale-delegate":
                try await start()
                let old = fixture.use { $0.callbacks.first! }
                service.notify(.mediaReset)
                try await until({ count("player-init") == 2 && playing() }, "RESET_DID_NOT_REPLACE_PLAYER")
                for _ in 0..<1000 { old(true) }
                try await Task.sleep(nanoseconds: 50_000_000)
                check(count("player-init") == 2, "STALE_DELEGATE_REBUILT_NEW_PLAYER")
                try await stop()
            case "mixed-delegate":
                try await start()
                let old = fixture.use { $0.callbacks.first! }
                service.notify(.mediaReset)
                try await until({ count("player-init") == 2 && playing() }, "RESET_DID_NOT_REPLACE_PLAYER")
                let current = fixture.use { $0.callbacks.last! }
                fixture.use { $0.blocked = "position-get" }
                service.notify(.hint)
                try await until({ fixture.use { $0.enteredBlock } }, "DELEGATE_IO_BARRIER_NOT_ENTERED")
                current(true)
                for _ in 0..<1000 { old(false) }
                check(service.auditEndpointQueueDepth() == 1, "DELEGATE_DELIVERY_QUEUE_BOUND")
                fixture.release.signal()
                try await until({ count("player-init") == 3 && playing() }, "CURRENT_DELEGATE_RECEIPT_LOST")
                try await Task.sleep(nanoseconds: 50_000_000)
                check(count("player-init") == 3, "MIXED_DELEGATE_REBUILT_TWICE")
                try await stop()
            case "asset-missing", "asset-invalid":
                fixture.use { $0.resource = name == "asset-missing" ? nil : CommandLine.arguments[3] }
                service.setEnabled(true, owner: owner)
                try await until({ state.use { $0.text.hasPrefix("Waiting to resume:") } }, "BAD_ASSET_NOT_REPORTED")
                let reads = fixture.use { $0.assetReads }
                try await Task.sleep(nanoseconds: 40_000_000)
                check(fixture.use { $0.assetReads } == reads && count("player-init") == 0, "BAD_ASSET_BUSY_LOOP")
                fixture.use { $0.resource = CommandLine.arguments[2] }
                service.notify(.available)
                try await until(playing, "AVAILABLE_ASSET_NOT_RETRIED")
                try await stop()
            case "cache":
                try await start(); try await stop()
                fixture.use { $0.resource = nil }
                try await start()
                check(fixture.use { $0.assetReads } == 1 && count("player-init") == 2, "ORIGINAL_DATA_CACHE_NOT_REUSED")
                try await stop()
            case "release-failure":
                try await start()
                fixture.use { $0.rejections["deactivate"] = 1 }
                service.setEnabled(false, owner: owner)
                try await until({ state.use { $0.text.hasPrefix("Off; session release failed:") } }, "RELEASE_ERROR_HIDDEN")
                try await Task.sleep(nanoseconds: 40_000_000)
                check(count("deactivate") == 1, "AUTOMATIC_OFF_RELEASE_RETRY")
                try await stop()
                check(count("deactivate") == 2, "EXPLICIT_RELEASE_RETRY_LOST")
            case "pending-owner", "pending-reset", "pending-off-on":
                fixture.use { $0.holdCompletion = "activate" }
                service.setEnabled(true, owner: owner)
                try await until({ fixture.use { !$0.pending.isEmpty } }, "ACTIVATION_COMPLETION_NOT_HELD")
                if name == "pending-owner" {
                    let next = service.register { value in state.use { $0 = value } }
                    service.setEnabled(true, owner: next)
                    service.unregister(owner)
                    fixture.deliverPending()
                    try await until(playing, "NEW_OWNER_DID_NOT_REUSE_PENDING_ACTIVATION")
                    check(count("deactivate") == 0, "ORPHAN_RELEASED_NEW_OWNER")
                    service.setEnabled(false, owner: next)
                    try await until(off, "FINAL_OWNER_DID_NOT_STOP")
                    service.unregister(next)
                } else {
                    if name == "pending-reset" { service.notify(.mediaReset) }
                    else { service.setEnabled(false, owner: owner); service.setEnabled(true, owner: owner) }
                    fixture.deliverPending()
                    try await until(playing, "LATEST_INTENT_NOT_RECOVERED")
                    check(count("activate") == 2, "STALE_ACTIVATION_WAS_ACCEPTED")
                    if name == "pending-off-on" { check(count("deactivate") == 1, "OFF_ON_RELEASE_BARRIER_LOST") }
                    try await stop()
                }
            case "pending-deactivation":
                try await start()
                fixture.use { $0.holdCompletion = "deactivate" }
                service.setEnabled(false, owner: owner)
                try await until({ fixture.use { !$0.pending.isEmpty } }, "DEACTIVATION_COMPLETION_NOT_HELD")
                service.setEnabled(true, owner: owner)
                try await Task.sleep(nanoseconds: 40_000_000)
                check(count("activate") == 1, "ACTIVATED_BEFORE_OLD_RELEASE")
                fixture.deliverPending()
                try await until({ count("activate") == 2 && playing() }, "ACTIVATION_AFTER_RELEASE_MISSING")
                try await stop()
            case "duplicate-completion":
                fixture.use { $0.duplicateCompletion = true }
                try await start()
                check(count("player-init") == 1 && count("play") == 1, "DUPLICATE_ACTIVATION_STARTED_TWICE")
                try await stop()
            default: preconditionFailure("Unknown actual-adapter case: \(name)")
            }
        }
        service.unregister(owner)
        let final = await snapshot()
        check(final.operation == nil && !final.timerActive, "FINAL_OFF_RETAINED_WORK")
        check(final.maximumOutstanding <= 1, "MORE_THAN_ONE_SERVICE_OPERATION")
        check(fixture.use { $0.peak <= 1 && $0.onWrongQueue == 0 }, "AV_API_OUTSIDE_EXCLUSIVE_IO_LANE")
        check(fixture.use { $0.peakPlayers <= 1 && $0.livePlayers == 0 }, "PLAYER_RESOURCE_CAP")
        try await until({ claims.use { $0.requested == $0.ended.count } }, "TOKEN_END_NOT_RETURNED")
        check(claims.use { $0.requested == $0.ended.count && Set($0.ended).count == $0.ended.count }, "TOKEN_END_IDENTITY_OR_LEAK")
        print("PASS actual-adapter \(name): \(assertions) assertions; API outcomes are controlled doubles")
    }
}
