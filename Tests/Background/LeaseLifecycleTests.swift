import Foundation

private final class LeaseValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T
    init(_ value: T) { self.value = value }
    func use<R>(_ body: (inout T) -> R) -> R {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

@MainActor private final class ApplicationClaimTrace {
    var callbacks = [@MainActor @Sendable () -> Void]()
    var rawID: Int? = 71
    var begins = 0
    var ends = [Int]()
    var duringBegin: (@MainActor () -> Void)?
    let observedEnds = LeaseValue(0)

    func begin(_ expire: @escaping @MainActor @Sendable () -> Void) -> Int? {
        dispatchPrecondition(condition: .onQueue(.main))
        begins += 1
        callbacks.append(expire)
        duringBegin?()
        return rawID
    }
    func end(_ id: Int) {
        dispatchPrecondition(condition: .onQueue(.main))
        ends.append(id)
        observedEnds.use { $0 += 1 }
    }
    func provider() -> RecoveryExecutionLease.Provider {
        .application(begin: { self.begin($0) }, end: { self.end($0) }).serializingEnds()
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

    @MainActor static func acquire(_ provider: RecoveryExecutionLease.Provider) async throws -> RecoveryExecutionLease {
        // A previous generic end job may have returned to its gate only just
        // after the platform trace. Do not infer that bookkeeping from a sleep.
        for _ in 0..<100 {
            let observed = LeaseValue((grant: false, issued: false))
            let lease = RecoveryExecutionLease(provider: provider, granted: { value in observed.use { $0.grant = value } })
            check(lease.start { observed.use { $0.issued = true } }, "APPLICATION_START_NOT_ADMITTED")
            try await until { observed.use { $0.issued } }
            if observed.use({ $0.grant }) { return lease }
            lease.finish()
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        fatalError("APPLICATION_END_GATE_NOT_RELEASED")
    }

    @MainActor static func applicationAndIssueBoundaries() async throws {
        let trace = ApplicationClaimTrace()
        let provider = trace.provider()
        let issued = LeaseValue(0)
        let expired = LeaseValue((count: 0, actualEndObserved: false))
        let observedEnds = trace.observedEnds
        trace.duringBegin = { check(issued.use { $0 == 0 }, "APPLICATION_CONTINUATION_BEFORE_BEGIN_RETURN") }
        let first = RecoveryExecutionLease(provider: provider, expired: {
            expired.use { $0.count += 1; $0.actualEndObserved = observedEnds.use { $0 == 1 } }
        })
        check(first.start { issued.use { $0 += 1 } }, "APPLICATION_INITIAL_START_REFUSED")
        check(trace.begins == 0 && issued.use { $0 == 0 }, "APPLICATION_BEGIN_NOT_MAIN_QUEUED")
        for _ in 0..<1000 {
            check(!first.start { issued.use { $0 += 1000 } }, "PENDING_START_ACCUMULATED_CONTINUATIONS")
        }
        try await until { issued.use { $0 == 1 } }
        check(trace.begins == 1, "APPLICATION_DUPLICATE_BEGIN")
        trace.duringBegin = nil
        let oldExpiry = trace.callbacks[0]
        oldExpiry()
        check(trace.ends == [71], "APPLICATION_EXPIRY_RETURNED_BEFORE_ACTUAL_END")
        check(expired.use { $0.count == 1 && $0.actualEndObserved }, "APPLICATION_LOGICAL_EXPIRY_BEFORE_ACTUAL_END")
        for _ in 0..<1000 { oldExpiry(); first.finish() }
        check(first.start { issued.use { $0 += 1 } }, "SETTLED_START_NOT_COMPLETED")
        check(issued.use { $0 == 2 }, "SETTLED_START_COMPLETION_NOT_EXACTLY_ONCE")

        // UIKit may reuse the same raw value. An old logical end or expiration
        // must not close the new request carrying that raw value.
        let second = try await acquire(provider)
        check(trace.begins == 2, "APPLICATION_REPLACEMENT_NOT_BEGUN")
        provider.end(1)
        oldExpiry()
        try await Task.sleep(nanoseconds: 10_000_000)
        check(trace.ends == [71], "APPLICATION_STALE_CALLBACK_ENDED_REUSED_RAW_ID")
        second.finish() // Its queued normal end races the main expiration below.
        trace.callbacks[1]()
        check(trace.ends == [71, 71], "APPLICATION_OFF_EXPIRY_RACE_DELAYED_ACTUAL_END")
        let third = try await acquire(provider)
        third.finish()
        try await until { trace.ends.count == 3 }
        trace.callbacks[2]() // Normal end already completed; expiration is stale.
        check(trace.ends == [71, 71, 71], "APPLICATION_END_EXPIRY_DUPLICATE")

        let early = ApplicationClaimTrace()
        let earlyIssued = LeaseValue(false)
        let earlyExpired = LeaseValue(0)
        early.duringBegin = {
            early.callbacks.last!()
            check(early.ends.isEmpty, "APPLICATION_EARLY_EXPIRY_INVENTED_PLATFORM_ID")
            check(!earlyIssued.use { $0 }, "APPLICATION_EARLY_EXPIRY_COMPLETED_UNRETURNED_BEGIN")
        }
        let earlyEnds = early.observedEnds
        let earlyLease = RecoveryExecutionLease(provider: early.provider(), expired: { earlyExpired.use { $0 += 1 } })
        earlyLease.start {
            check(earlyEnds.use { $0 == 1 }, "APPLICATION_EARLY_EXPIRY_LEAKED_RETURNED_ID")
            earlyIssued.use { $0 = true }
        }
        try await until { earlyIssued.use { $0 } }
        check(earlyExpired.use { $0 == 1 } && early.ends == [71], "APPLICATION_EARLY_EXPIRY_UNBALANCED")
        earlyLease.finish(); early.callbacks[0]()

        let denied = ApplicationClaimTrace()
        denied.rawID = nil
        let denial = LeaseValue((issued: false, noGrant: 0))
        let deniedLease = RecoveryExecutionLease(provider: denied.provider(), granted: { value in
            if !value { denial.use { $0.noGrant += 1 } }
        })
        deniedLease.start { denial.use { $0.issued = true } }
        try await until { denial.use { $0.issued } }
        deniedLease.finish(); denied.callbacks[0]()
        check(denied.begins == 1 && denied.ends.isEmpty && denial.use { $0.noGrant == 1 }, "APPLICATION_DENIAL_CHANGED_ISSUE_BOUNDARY")

        let cancelled = ApplicationClaimTrace()
        let cancelState = LeaseValue((issued: 0, noGrant: 0))
        let cancelledLease = RecoveryExecutionLease(provider: cancelled.provider(), granted: { value in
            if !value { cancelState.use { $0.noGrant += 1 } }
        })
        cancelledLease.start { cancelState.use { $0.issued += 1 } }
        cancelledLease.finish() // Main's queued begin has not entered yet.
        try await until { cancelState.use { $0.issued == 1 } }
        check(cancelled.begins == 0 && cancelled.ends.isEmpty, "APPLICATION_QUEUED_OFF_ISSUED_PLATFORM_BEGIN")
        check(cancelState.use { $0.noGrant == 1 }, "APPLICATION_CANCELLED_ISSUE_NOT_SETTLED")
        let neverStarted = RecoveryExecutionLease(provider: cancelled.provider())
        neverStarted.finish()
        check(neverStarted.start { cancelState.use { $0.issued += 1 } }, "OFF_BEFORE_FIRST_START_NOT_COMPLETED")
        check(cancelState.use { $0.issued == 2 } && cancelled.begins == 0, "OFF_BEFORE_FIRST_START_ISSUED_BEGIN")

        // Synchronous service intent can precede its control-lane lease.finish.
        // Main must consult that intent when its queued begin actually enters.
        let intentOnly = ApplicationClaimTrace()
        let intent = LeaseValue(true)
        let intentIssued = LeaseValue(false)
        let intentLease = RecoveryExecutionLease(provider: intentOnly.provider())
        intentLease.start(mayIssue: { intent.use { $0 } }) { intentIssued.use { $0 = true } }
        intent.use { $0 = false } // Deliberately do not call lease.finish yet.
        try await until { intentIssued.use { $0 } }
        check(intentOnly.begins == 0 && intentOnly.ends.isEmpty, "APPLICATION_LATEST_OFF_BEFORE_CONTROL_DRAIN_ISSUED_BEGIN")
        intentLease.finish()

        // General providers retain the old request-return meaning even when
        // their grant callback arrives later, or does not arrive at all.
        let late = LeaseValue((request: 0, issued: 0, ends: [Int](), receipt: Optional<@Sendable (Int?) -> Void>.none))
        let lateProvider = RecoveryExecutionLease.Provider(request: { _, receipt in
            late.use { $0.request += 1; $0.receipt = receipt }
        }, end: { id in late.use { $0.ends.append(id) } }).serializingEnds()
        let lateLease = RecoveryExecutionLease(provider: lateProvider)
        lateLease.start { late.use { $0.issued += 1 } }
        check(late.use { $0.request == 1 && $0.issued == 1 }, "GENERIC_REQUEST_RETURN_WAITED_FOR_RECEIPT")
        lateLease.finish()
        late.use { $0.receipt }?(42)
        late.use { $0.receipt }?(42)
        try await until { late.use { $0.ends == [42] } }
        let missing = LeaseValue((request: 0, issued: 0, noGrant: 0))
        let missingProvider = RecoveryExecutionLease.Provider(request: { _, _ in
            missing.use { $0.request += 1 }
        }, end: { _ in fatalError("MISSING_RECEIPT_INVENTED_PLATFORM_END") }).serializingEnds()
        let missingLease = RecoveryExecutionLease(provider: missingProvider)
        missingLease.start { missing.use { $0.issued += 1 } }
        missingLease.finish()
        let refused = RecoveryExecutionLease(provider: missingProvider, granted: { value in
            if !value { missing.use { $0.noGrant += 1 } }
        })
        refused.start { missing.use { $0.issued += 1 } }; refused.finish()
        check(missing.use { $0.request == 1 && $0.issued == 2 && $0.noGrant == 1 }, "MISSING_RECEIPT_CHANGED_REQUEST_RETURN_OR_CAP")

        let blocking = LeaseValue((entered: false, issued: false, ended: [Int]()))
        let unblock = DispatchSemaphore(value: 0)
        let blockingLease = RecoveryExecutionLease(provider: .init(request: { _, receipt in
            blocking.use { $0.entered = true }
            _ = unblock.wait(timeout: .now() + 3)
            receipt(91)
        }, end: { id in blocking.use { $0.ended.append(id) } }))
        DispatchQueue.global().async {
            blockingLease.start { blocking.use { $0.issued = true } }
        }
        try await until { blocking.use { $0.entered } }
        blockingLease.finish()
        for _ in 0..<1000 {
            check(!blockingLease.start { blocking.use { $0.issued = true } }, "BLOCKED_REQUEST_ADMITTED_DUPLICATE_AFTER_OFF")
        }
        check(!blocking.use { $0.issued }, "OFF_FABRICATED_UNRETURNED_REQUEST_COMPLETION")
        unblock.signal()
        try await until { blocking.use { $0.issued } }
        check(blocking.use { $0.ended == [91] }, "BLOCKED_REQUEST_LATE_RECEIPT_LEAKED_AFTER_OFF")
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
        try await applicationAndIssueBoundaries()
        print("PASS: blocked token end, no-grant cap, stale identity, extension acquisition/expiration/reuse order; application main ownership, synchronous expiry end, issue/receipt separation and cancellation")
    }
}
