import Foundation

final class Locked<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T
    init(_ value: T) { self.value = value }
    func use<R>(_ body: (inout T) -> R) -> R { lock.lock(); defer { lock.unlock() }; return body(&value) }
}
final class ControlledEndpoint: LoopAudioEndpoint, @unchecked Sendable {
    let commands = Locked([String]())
    private var playing = false
    private let onStart: @Sendable () -> Void
    init(onStart: @escaping @Sendable () -> Void = {}) { self.onStart = onStart }
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        switch command {
        case .stop: commands.use { $0.append("stop") }; playing = false
        case .start:
            commands.use { $0.append("start") }
            guard context.mayStart() else { completion(.init(superseded: true)); return }
            onStart()
            playing = true
        case .inspect: commands.use { $0.append("inspect") }
        }
        let now = ProcessInfo.processInfo.systemUptime
        completion(.init(sample: .init(generation: 1, epoch: context.epoch, playing: playing,
            configured: true, position: now.truncatingRemainder(dividingBy: 0.05), deviceTime: now,
            duration: 0.05, rate: 1, startedAt: now, finishedAt: now, bufferDuration: 0.001)))
    }
}
@main struct RecoveryBoundaryTests {
    @MainActor static var assertions = 0
    @MainActor static func check(_ value: Bool, _ name: String) {
        assertions += 1
        if !value {
            FileHandle.standardError.write(Data(("FAIL: " + name + "\n").utf8))
            fatalError(name)
        }
    }
    @MainActor static func wait(_ condition: () -> Bool, seconds: Double = 3) async throws -> Bool {
        let limit = ProcessInfo.processInfo.systemUptime + seconds
        while !condition() && ProcessInfo.processInfo.systemUptime < limit {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        return condition()
    }
    @MainActor static func holdMainThroughWorkerTurn(_ service: LoopAudioService, owner: UInt64,
                                                    events: Locked<[String]>, cancel: Bool,
                                                    invalidate: Bool = false, restart: Bool = false,
                                                    relapse: Bool = false) -> DispatchSemaphore? {
        // Main remains synchronously occupied. An ordinary application begin
        // and its audio continuation must now finish on the real worker lane.
        if !cancel && !invalidate {
            service.setEnabled(true, owner: owner)
            let drained = DispatchSemaphore(value: 0)
            service.auditAfterWorkerTurn { drained.signal() }
            check(drained.wait(timeout: .now() + 3) == .success, "LEASE_MAIN_ISSUE_BLOCKED_AUDIO_LANES")
            check(events.use { !$0.isEmpty }, "APPLICATION_BEGIN_WAITED_FOR_MAIN")
            check(events.use { $0 == ["request", "start"] }, "AV_PREPARATION_BEFORE_MAIN_REQUEST_RETURN")
            if relapse {
                // The preceding I/O turn queued its healthy completion. Drain
                // control so its normal end is pending on still-occupied main.
                service.auditAfterWorkerTurn { drained.signal() }
                check(drained.wait(timeout: .now() + 3) == .success, "HEALTHY_CLAIM_BOUNDARY_NOT_DRAINED")
                service.notify(.interrupted)
                service.auditAfterWorkerTurn { drained.signal() }
                check(drained.wait(timeout: .now() + 3) == .success, "RELAPSE_WORKER_BOUNDARY_NOT_DRAINED")
                check(events.use { $0 == ["request", "start", "start"] }, "APPLICATION_RELAPSE_WAITED_FOR_MAIN")
            }
            return nil
        }
        // Hold I/O before claim admission, then hold control after it queued
        // that work. This fixes the event order without relying on a main hop.
        let ioEntered = DispatchSemaphore(value: 0)
        let ioRelease = DispatchSemaphore(value: 0)
        service.auditHoldIO(entered: { ioEntered.signal() }, release: ioRelease)
        check(ioEntered.wait(timeout: .now() + 3) == .success, "IO_HOLD_NOT_ENTERED")
        service.setEnabled(true, owner: owner)
        let controlEntered = DispatchSemaphore(value: 0)
        let controlRelease = DispatchSemaphore(value: 0)
        service.auditHoldControl(entered: { controlEntered.signal() }, release: controlRelease)
        check(controlEntered.wait(timeout: .now() + 3) == .success, "CONTROL_HOLD_NOT_ENTERED")
        if invalidate { service.notify(.interrupted) }
        if cancel { service.setEnabled(false, owner: owner) }
        if restart { service.setEnabled(true, owner: owner) }
        ioRelease.signal()
        let drained = DispatchSemaphore(value: 0)
        service.auditAfterIO { drained.signal() }
        check(drained.wait(timeout: .now() + 3) == .success, "CLAIM_ISSUE_DID_NOT_RETURN")
        return controlRelease
    }
    @MainActor static func main() async throws {
        let name = CommandLine.arguments[1]
        if ["lease-main-issued", "lease-main-relapse", "lease-main-cancelled", "lease-main-resource-reset", "lease-main-off-on"].contains(name) {
            let events = Locked([String]())
            let ended = Locked([Int]())
            let endpoint = ControlledEndpoint(onStart: { events.use { $0.append("start") } })
            let provider = RecoveryExecutionLease.Provider.application(begin: { _ in
                events.use { $0.append("request") }
                return 7
            }, end: { id in ended.use { $0.append(id) } })
            let state = Locked(LoopAudioService.State())
            let service = LoopAudioService(leaseProvider: { provider }) { _, _ in endpoint }
            let owner = service.register { next in state.use { $0 = next } }
            let cancel = name == "lease-main-cancelled"
            let reset = name == "lease-main-resource-reset"
            let restart = name == "lease-main-off-on"
            let relapse = name == "lease-main-relapse"
            let release = holdMainThroughWorkerTurn(service, owner: owner, events: events,
                cancel: cancel || restart, invalidate: reset, restart: restart, relapse: relapse)
            if cancel || restart || reset {
                let obsoleteRequestSkipped = events.use { $0.isEmpty }
                release?.signal()
                if restart { check(obsoleteRequestSkipped, "QUEUED_CLAIM_OFF_ON_BARRIER_LOST") }
            }
            if cancel {
                check(try await wait { state.use { $0.text == "Off" } }, "QUEUED_CLAIM_OFF_DID_NOT_DRAIN")
                check(events.use { $0.isEmpty } && ended.use { $0.isEmpty }, "QUEUED_OFF_ISSUED_AUDIO_OR_CLAIM")
            } else {
                check(try await wait { state.use { $0.text == "Playing silent WAV continuously" } },
                      "MAIN_REQUEST_RETURN_DID_NOT_RESUME_AUDIO")
                if reset {
                    check(events.use { $0 == ["request", "start"] }, "RESOURCE_RESET_DROPPED_EPISODE_CLAIM")
                    check(endpoint.commands.use { $0.filter { $0 == "start" }.count == 2 },
                          "RESOURCE_RESET_OLD_AV_WORK_NOT_SUPERSEDED")
                }
                check(events.use { $0 == (relapse ? ["request", "start", "start"] : ["request", "start"]) },
                      "MAIN_REQUEST_AUDIO_ORDER_CHANGED")
                service.setEnabled(false, owner: owner)
                check(try await wait { state.use { $0.text == "Off" } }, "MAIN_CLAIM_FINAL_OFF")
                check(try await wait { ended.use { $0 == [7] } }, "MAIN_CLAIM_ACTUAL_END_MISSING")
            }
            service.unregister(owner)
        } else if name == "lease-matrix" {
            for order in 0..<6 {
                let callbacks = Locked((expire: Optional<@Sendable () -> Void>.none,
                    receipt: Optional<@Sendable (Int?) -> Void>.none))
                let ended = Locked([Int]())
                let expired = Locked(0)
                let lease = RecoveryExecutionLease(provider: .init(request: { expire, receipt in
                    callbacks.use { $0 = (expire, receipt) }
                }, end: { id in ended.use { $0.append(id) } }), expired: { expired.use { $0 += 1 } })
                lease.start(); lease.start()
                let pair = callbacks.use { $0 }
                check(pair.expire != nil && pair.receipt != nil, "lease not requested")
                switch order {
                case 0: pair.receipt?(42); lease.finish(); pair.expire?()
                case 1: pair.expire?(); pair.receipt?(42); lease.finish()
                case 2: lease.finish(); pair.receipt?(42); pair.expire?()
                case 3: pair.receipt?(nil); pair.expire?(); lease.finish()
                case 4: pair.receipt?(42); pair.expire?(); pair.expire?(); lease.finish()
                default:
                    pair.receipt?(42)
                    DispatchQueue.concurrentPerform(iterations: 1000) { i in
                        if i % 2 == 0 { lease.finish() } else { pair.expire?() }
                    }
                }
                pair.receipt?(42) // Duplicate completion may not end a token twice.
                check(ended.use { $0 } == (order == 3 ? [] : [42]), "LEASE_TOKEN_END_COUNT")
                check(expired.use { $0 } <= 1, "LEASE_EXPIRATION_DUPLICATE")
                callbacks.use { $0 = (nil, nil) }
            }
        } else if name == "progress-clock" {
            func sample(_ time: Double, _ clock: Double, _ position: Double) -> PlaybackProgressMonitor.Sample {
                .init(generation: 1, epoch: 0, playing: true, configured: true, position: position,
                    deviceTime: clock, duration: 0.05, rate: 1, startedAt: time, finishedAt: time,
                    bufferDuration: 0.001)
            }
            var monitor = PlaybackProgressMonitor()
            _ = monitor.inspect(sample(1, 1, 0))
            let jumped = monitor.inspect(sample(1.017, 1.417, 0.017), speculativeRecoveryCertified: true)
            check(jumped.health == .inconclusive && !jumped.mayRebuild, "PROGRESS_CLOCK_DISCONTINUITY")
            _ = monitor.inspect(sample(2, 2, 0))
            let moved = monitor.inspect(sample(2.017, 2.017, 0.017))
            check(moved.health == .progressObserved, "VALID_PROGRESS_REJECTED")
            var alias = PlaybackProgressMonitor()
            for i in 0..<100 {
                let time = 10 + Double(i) * 0.5
                let result = alias.inspect(sample(time, time, 0), speculativeRecoveryCertified: true)
                check(!result.mayRebuild, "HARMONIC_ALIAS_FALSE_RECOVERY")
            }
        } else {
            let endpoint = ControlledEndpoint()
            let state = Locked(LoopAudioService.State())
            let block = DispatchSemaphore(value: 0)
            let requested = Locked(false)
            let ended = Locked([Int]())
            let provider = RecoveryExecutionLease.Provider(request: { _, receipt in
                requested.use { $0 = true }
                if name == "lease-blocked" {
                    precondition(block.wait(timeout: .now() + 5) == .success, "test unblock missing")
                }
                receipt(7)
            }, end: { id in ended.use { $0.append(id) } })
            var policy = LoopAudioService.Policy()
            policy.interval = 0.01; policy.warning = 0.03; policy.stalled = 0.07
            let service = LoopAudioService(policy: policy, leaseProvider: { provider }) { _, _ in endpoint }
            let owner = service.register { next in state.use { $0 = next } }
            service.setEnabled(true, owner: owner)
            if name == "lease-blocked" {
                check(try await wait { requested.use { $0 } }, "lease request not entered")
                let observed = Locked(false)
                service.diagnostics { _ in observed.use { $0 = true } }
                let responsive = try await wait({ observed.use { $0 } }, seconds: 0.15)
                service.setEnabled(false, owner: owner)
                block.signal()
                check(try await wait { state.use { $0.text == "Off" } }, "Off after lease return")
                check(responsive, "LEASE_BLOCKED_CONTROL")
                check(ended.use { $0 } == [7], "late execution token leaked")
                check(endpoint.commands.use { !$0.contains("start") } || !state.use { $0.text.contains("Playing") }, "late start after Off")
            } else {
                check(try await wait { state.use { $0.text == "Playing silent WAV continuously" } }, "initial start")
                let admission = Locked(Optional<Bool>.none)
                service.auditStopAdmission(owner: owner, direct: name == "race-admit") { result in
                    admission.use { $0 = result }
                }
                check(try await wait { admission.use { $0 != nil } }, "admission observation missing")
                let safe = admission.use { $0 == true }
                check(try await wait { endpoint.commands.use { $0.filter { $0 == "start" }.count >= (safe ? 2 : 1) } }, "restart after barrier")
                service.setEnabled(false, owner: owner)
                check(try await wait { state.use { $0.text == "Off" } }, "final Off")
                check(safe, "ACCEPTED_STOP_BARRIER_LOST")
            }
            service.unregister(owner)
        }
        print("PASS \(name): \(assertions) assertions")
    }
}
