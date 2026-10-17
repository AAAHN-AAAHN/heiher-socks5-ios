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
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        switch command {
        case .stop: commands.use { $0.append("stop") }; playing = false
        case .start:
            commands.use { $0.append("start") }
            guard context.mayStart() else { completion(.init(superseded: true)); return }
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
        precondition(value, name)
    }
    @MainActor static func wait(_ condition: () -> Bool, seconds: Double = 3) async throws -> Bool {
        let limit = ProcessInfo.processInfo.systemUptime + seconds
        while !condition() && ProcessInfo.processInfo.systemUptime < limit {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        return condition()
    }
    @MainActor static func main() async throws {
        let name = CommandLine.arguments[1]
        if name == "lease-matrix" {
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
