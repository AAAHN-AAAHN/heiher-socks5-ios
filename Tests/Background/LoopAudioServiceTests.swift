import Foundation
import Dispatch

private final class Box<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T
    init(_ value: T) { self.value = value }
    func withValue<R>(_ action: (inout T) -> R) -> R {
        lock.lock(); defer { lock.unlock() }; return action(&value)
    }
}

private final class Endpoint: LoopAudioEndpoint, @unchecked Sendable {
    struct Trace {
        var calls: [String] = []
        var failures = 0
        var hold: String?
        var physicalPlaying = false
        var generation: UInt64 = 0
        var executing = 0
        var peak = 0
        var starts = 0
        var stops = 0
        var hasPlayer = false
        var configurations = 0
        var configured = true
        var duplicate = false
    }
    let trace = Box(Trace())
    let block = DispatchSemaphore(value: 0)
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        let name: String
        switch command { case .start: name = "start"; case .inspect: name = "inspect"; case .stop: name = "stop" }
        let pause = trace.withValue { t -> Bool in
            t.executing += 1; t.peak = max(t.peak, t.executing)
            t.calls.append(name)
            let pause = t.hold == name
            if pause { t.hold = nil }
            return pause
        }
        context.phase(name == "start" ? .preparing : name == "stop" ? .deactivating : .inspecting)
        if pause { precondition(block.wait(timeout: .now() + 15) == .success, "Fixture barrier timed out") }
        var reply = LoopAudioService.Reply()
        let duplicate = trace.withValue { t -> Bool in
            switch command {
            case .stop:
                t.physicalPlaying = false; t.hasPlayer = false; t.stops += 1
            case .start(let recreate):
                if !context.mayStart() { reply.superseded = true; break }
                t.starts += 1
                if t.failures > 0 {
                    t.failures -= 1; reply.error = "Controlled rejection"; break
                }
                if recreate { t.hasPlayer = false }
                if !t.hasPlayer { t.generation += 1; t.hasPlayer = true; t.configurations += 1 }
                t.physicalPlaying = true; t.configured = true
                fallthrough
            case .inspect:
                let now = ProcessInfo.processInfo.systemUptime
                reply.sample = .init(generation: t.generation, epoch: context.epoch,
                    playing: t.physicalPlaying, configured: t.configured,
                    position: now.truncatingRemainder(dividingBy: 0.05), deviceTime: now,
                    duration: 0.05, rate: 1, startedAt: now, finishedAt: now, bufferDuration: 0.002)
            }
            t.executing -= 1
            let value = t.duplicate; t.duplicate = false
            return value
        }
        completion(reply)
        if duplicate { completion(reply) }
    }
}

@main struct LoopAudioServiceTests {
    @MainActor static func main() async throws {
        let name = CommandLine.arguments.dropFirst().first ?? "normal"
        let endpoint = Endpoint()
        let state = Box(LoopAudioService.State())
        let claims = Box((began: 0, ended: [Int]()))
        let provider = RecoveryExecutionLease.Provider(request: { _, receipt in
            let id = claims.withValue { x -> Int in x.began += 1; return x.began }
            receipt(id)
        }, end: { id in claims.withValue { $0.ended.append(id) } })
        var policy = LoopAudioService.Policy()
        policy.interval = 0.005; policy.warning = 0.015; policy.stalled = 0.04
        let service = LoopAudioService(policy: policy, leaseProvider: { provider }) { _, _ in endpoint }
        let owner = service.register { next in state.withValue { $0 = next } }
        var assertions = 0
        func check(_ x: Bool, _ message: String) {
            assertions += 1; precondition(x, "\(name): \(message)")
        }
        func wait(_ condition: () -> Bool) async throws {
            let end = ProcessInfo.processInfo.systemUptime + 10
            while !condition() && ProcessInfo.processInfo.systemUptime < end {
                try await Task.sleep(nanoseconds: 1_000_000)
            }
            check(condition(), "Bounded condition was not reached")
        }
        func diagnostics() async -> LoopAudioService.Diagnostics {
            await withCheckedContinuation { continuation in service.diagnostics { continuation.resume(returning: $0) } }
        }
        func playing() -> Bool { state.withValue { $0.text == "Playing silent WAV continuously" } }
        func stopped() -> Bool { state.withValue { $0.text == "Off" } }
        switch name {
        case "normal":
            service.setEnabled(true, owner: owner)
            try await wait(playing)
            let gen = endpoint.trace.withValue { $0.generation }
            for _ in 0..<1000 { service.notify(.hint) }
            try await Task.sleep(nanoseconds: 40_000_000)
            check(endpoint.trace.withValue { $0.generation } == gen, "Healthy object was recreated")
            service.setEnabled(false, owner: owner)
            try await wait(stopped)
        case "finite-failure":
            endpoint.trace.withValue { $0.failures = 130 }
            service.setEnabled(true, owner: owner)
            try await wait(playing)
            check(endpoint.trace.withValue { $0.starts } == 131, "No automatic recovery without a new On")
            check(claims.withValue { $0.began } == 1, "Retry reissued finite execution claims")
            service.setEnabled(false, owner: owner); try await wait(stopped)
        case "pending-off-on", "pending-reset", "pending-owner":
            endpoint.trace.withValue { $0.hold = "start" }
            service.setEnabled(true, owner: owner)
            try await wait { endpoint.trace.withValue { $0.executing == 1 } }
            var heartbeats = 0
            for _ in 0..<100 {
                service.notify(.hint)
                try await Task.sleep(nanoseconds: 1_000_000); heartbeats += 1
            }
            check(heartbeats == 100, "UI heartbeat blocked")
            check(endpoint.trace.withValue { $0.calls.count } == 1, "Overlapping AV operations")
            check(state.withValue { $0.text.contains("Waiting for system") }, "No delayed-operation status")
            if name == "pending-off-on" {
                service.setEnabled(false, owner: owner)
                service.setEnabled(true, owner: owner)
            } else if name == "pending-reset" {
                for _ in 0..<128 { service.notify(.mediaReset) }
            } else {
                let second = service.register { value in state.withValue { $0 = value } }
                service.setEnabled(true, owner: second)
                service.unregister(owner)
                endpoint.block.signal()
                try await wait(playing)
                check(endpoint.trace.withValue { $0.stops } == 0, "Old owner stopped the current owner's activation")
                service.setEnabled(false, owner: second); try await wait(stopped)
                service.unregister(second)
            }
            if name != "pending-owner" {
                endpoint.block.signal()
                try await wait(playing)
                if name == "pending-off-on" {
                    check(endpoint.trace.withValue { Array($0.calls.prefix(3)) } == ["start", "stop", "start"], "Release barrier lost")
                }
                service.setEnabled(false, owner: owner); try await wait(stopped)
            }
        case "pending-deactivation":
            service.setEnabled(true, owner: owner); try await wait(playing)
            endpoint.trace.withValue { $0.hold = "stop" }
            service.setEnabled(false, owner: owner)
            try await wait { endpoint.trace.withValue { $0.calls.last == "stop" && $0.executing == 1 } }
            service.setEnabled(true, owner: owner)
            try await Task.sleep(nanoseconds: 25_000_000)
            check(endpoint.trace.withValue { $0.starts } == 1, "Activated before actual deactivation completed")
            endpoint.block.signal()
            try await wait { playing() && endpoint.trace.withValue { $0.starts == 2 } }
            service.setEnabled(false, owner: owner); try await wait(stopped)
        case "pending-inspection":
            service.setEnabled(true, owner: owner); try await wait(playing)
            endpoint.trace.withValue { $0.hold = "inspect" }
            service.notify(.hint)
            try await wait { endpoint.trace.withValue { $0.executing == 1 } }
            service.setEnabled(false, owner: owner)
            try await Task.sleep(nanoseconds: 20_000_000)
            check(!playing(), "Stale Playing publication after Off")
            let snapshot = await diagnostics()
            check(!snapshot.timerActive, "Automatic timer continued while Off")
            endpoint.block.signal(); try await wait(stopped)
        case "storm":
            endpoint.trace.withValue { $0.hold = "start" }
            service.setEnabled(true, owner: owner)
            try await wait { endpoint.trace.withValue { $0.executing == 1 } }
            for index in 0..<100_000 {
                service.notify(index % 17 == 0 ? .interrupted : .available)
            }
            let snap = await diagnostics()
            check(snap.scheduledIngress <= 1, "Unbounded ingress queue")
            check(endpoint.trace.withValue { $0.calls.count } == 1, "Storm started duplicate work")
            service.setEnabled(false, owner: owner)
            endpoint.block.signal(); try await wait(stopped)
        case "stopped-player":
            service.setEnabled(true, owner: owner); try await wait(playing)
            let gen = endpoint.trace.withValue { $0.generation }
            endpoint.trace.withValue { $0.physicalPlaying = false }
            try await wait { endpoint.trace.withValue { $0.starts >= 2 && $0.physicalPlaying } }
            check(endpoint.trace.withValue { $0.generation } == gen, "L1 did not reuse a valid stopped player")
            service.setEnabled(false, owner: owner); try await wait(stopped)
        case "duplicate-completion":
            endpoint.trace.withValue { $0.duplicate = true }
            service.setEnabled(true, owner: owner); try await wait(playing)
            check(endpoint.trace.withValue { $0.starts } == 1, "Duplicate completion restarted playback")
            service.setEnabled(false, owner: owner); try await wait(stopped)
        default: preconditionFailure("Unknown case")
        }
        service.unregister(owner)
        try await Task.sleep(nanoseconds: 15_000_000)
        let final = await diagnostics()
        check(final.operation == nil && !final.timerActive, "Outstanding work after complete Off")
        check(endpoint.trace.withValue { $0.peak } <= 1, "I/O single-flight violated")
        check(endpoint.trace.withValue { !$0.physicalPlaying && !$0.hasPlayer }, "Player retained after Off")
        check(claims.withValue { $0.began == $0.ended.count && Set($0.ended).count == $0.ended.count }, "Claim leak/double end")
        check(final.records.count <= 64, "Unbounded diagnostics")
        print("PASS: \(name); \(assertions) assertions; completed operations=\(final.completedOperations)")
    }
}
