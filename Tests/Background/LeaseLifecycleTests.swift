import Foundation

private final class LeaseValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T
    init(_ value: T) { self.value = value }
    func use<R>(_ body: (inout T) -> R) -> R {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}
@main struct LeaseLifecycleTests {
    static func check(_ value: Bool, _ message: String) {
        if !value {
            FileHandle.standardError.write(Data(("FAIL: " + message + "\n").utf8))
            fatalError(message)
        }
    }
    @MainActor static func until(_ condition: () -> Bool) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        while !condition() && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        check(condition(), "LEASE_ASYNC_BOUNDARY_NOT_REACHED")
    }
    @MainActor static func main() async throws {
        let trace = LeaseValue((requests: 0, endEntered: 0, ended: [Int](), noGrant: 0))
        let release = DispatchSemaphore(value: 0)
        let provider = RecoveryExecutionLease.Provider(request: { _, receipt in
            receipt(trace.use { $0.requests += 1; return $0.requests })
        }, end: { id in
            trace.use { $0.endEntered += 1 }
            if id == 1 { _ = release.wait(timeout: .now() + 5) }
            trace.use { $0.ended.append(id) }
        }).serializingEnds()
        let first = RecoveryExecutionLease(provider: provider)
        first.start()
        let began = ProcessInfo.processInfo.systemUptime
        first.finish()
        check(ProcessInfo.processInfo.systemUptime - began < 0.15, "LEASE_END_BLOCKED_CALLER")
        try await until { trace.use { $0.endEntered == 1 } }
        for _ in 0..<1000 {
            let refused = RecoveryExecutionLease(provider: provider, granted: { granted in
                if !granted { trace.use { $0.noGrant += 1 } }
            })
            refused.start(); refused.finish()
        }
        check(trace.use { $0.requests == 1 && $0.noGrant == 1000 && $0.ended.isEmpty }, "BLOCKED_END_ACCUMULATED_TOKENS")
        release.signal()
        try await until { trace.use { $0.ended == [1] } }
        // Wait for the gate's bookkeeping, not merely the test provider's body.
        var second: RecoveryExecutionLease?
        for _ in 0..<100 {
            let granted = LeaseValue(false)
            let candidate = RecoveryExecutionLease(provider: provider, granted: { value in granted.use { $0 = value } })
            candidate.start()
            if granted.use({ $0 }) { second = candidate; break }
            candidate.finish(); try await Task.sleep(nanoseconds: 1_000_000)
        }
        check(second != nil, "RETURNED_END_RETAINED_GRANT_GATE")
        provider.end(1) // Old token identity cannot end a newer episode.
        try await Task.sleep(nanoseconds: 10_000_000)
        check(trace.use { $0.ended == [1] }, "STALE_LEASE_END_CLOSED_NEW_TOKEN")
        second?.finish()
        try await until { trace.use { $0.ended == [1, 2] } }

        let callbacks = LeaseValue([@Sendable (Bool) -> Void]())
        let holderProvider = RecoveryExecutionLease.Provider.expiringActivity { callback in
            callbacks.use { $0.append(callback) }
        }
        for order in 0..<4 {
            let finished = LeaseValue(false)
            let accepted = LeaseValue(Optional<Int>.none)
            let expirations = LeaseValue(0)
            // Observe the same provider via a receipt passthrough without changing
            // its holder, identity or callback body.
            let observed = RecoveryExecutionLease.Provider(request: { expire, receipt in
                holderProvider.request(expire, { id in accepted.use { $0 = id }; receipt(id) })
            }, end: holderProvider.end)
            let active = RecoveryExecutionLease(provider: observed, expired: { expirations.use { $0 += 1 } })
            active.start()
            let callback = callbacks.use { $0.last! }
            if order == 0 { callback(true) }
            DispatchQueue.global().async { callback(false); finished.use { $0 = true } }
            try await until { accepted.use { $0 != nil } }
            if order == 1 { callback(true) }
            if order == 2 { active.finish() }
            if order == 3 {
                DispatchQueue.concurrentPerform(iterations: 1000) { index in
                    if index % 2 == 0 { callback(true) } else { active.finish() }
                }
            }
            try await until { finished.use { $0 } }
            active.finish()
            check(expirations.use { $0 <= 1 }, "EXTENSION_DUPLICATE_EXPIRATION")
            // A late callback from this request must not signal the next holder.
            if order == 2 {
                let nextAccepted = LeaseValue(Optional<Int>.none)
                let nextFinished = LeaseValue(false)
                holderProvider.request({}, { id in nextAccepted.use { $0 = id } })
                let next = callbacks.use { $0.last! }
                DispatchQueue.global().async { next(false); nextFinished.use { $0 = true } }
                try await until { nextAccepted.use { $0 != nil } }
                callback(true)
                try await Task.sleep(nanoseconds: 10_000_000)
                check(!nextFinished.use { $0 }, "EXTENSION_OLD_SIGNAL_RELEASED_NEW_HOLDER")
                holderProvider.end(nextAccepted.use { $0! })
                try await until { nextFinished.use { $0 } }
            }
        }
        print("PASS: blocked token end, no-grant cap, stale identity, extension acquisition/expiration/reuse order")
    }
}
