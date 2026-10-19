import Foundation

private final class ProviderValue<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func use<Result>(_ body: (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }; return body(&value)
    }
}

private final class ProviderTrace: Sendable {
    struct State {
        var callbacks = [@MainActor @Sendable () -> Void]()
        var events = [String]()
        var begins = 0
        var ends = 0
        var inEnd = 0
        var maximumEnds = 0
        var duringBegin: (@Sendable () -> Void)?
        var duringEnd: (@MainActor @Sendable () -> Void)?
    }
    let state = ProviderValue(State())
    func begin(_ expire: @escaping @MainActor @Sendable () -> Void) -> Int? {
        let hook = state.use { value -> (@Sendable () -> Void)? in
            value.begins += 1
            value.events.append("begin")
            value.callbacks.append(expire)
            return value.duringBegin
        }
        hook?()
        state.use { $0.events.append("begin-return") }
        return 71 // Deliberately reused by every later logical request.
    }
    @MainActor func end(_ id: Int) {
        dispatchPrecondition(condition: .onQueue(.main))
        ApplicationProviderBoundaryTests.check(id == 71, "APPLICATION_END_CHANGED_RAW_ID")
        let hook = state.use { value -> (@MainActor @Sendable () -> Void)? in
            value.inEnd += 1
            value.maximumEnds = max(value.maximumEnds, value.inEnd)
            value.events.append("end-enter")
            return value.duringEnd
        }
        hook?()
        state.use {
            $0.ends += 1
            $0.inEnd -= 1
            $0.events.append("end-return")
        }
    }
    @MainActor func provider() -> RecoveryExecutionLease.Provider {
        .application(begin: { self.begin($0) }, end: { self.end($0) })
    }
}

@main struct ApplicationProviderBoundaryTests {
    @MainActor static var mainEndJobs = 0
    @MainActor static var mainEndJobLimit = Int.max
    @MainActor static func mainEndJobDequeued() {
        mainEndJobs += 1
        check(mainEndJobs <= mainEndJobLimit, "APPLICATION_DUPLICATE_END_JOB_QUEUED")
    }
    static func check(_ value: Bool, _ marker: String) {
        if !value {
            FileHandle.standardError.write(Data(("FAIL: " + marker + "\n").utf8))
            fatalError(marker)
        }
    }
    @MainActor static func until(_ condition: () -> Bool) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        while !condition() && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        check(condition(), "APPLICATION_PROVIDER_BOUNDARY_NOT_REACHED")
    }
    @MainActor static func main() async throws {
        let name = CommandLine.arguments[1]
        let trace = ProviderTrace()
        let rawProvider = trace.provider()
        let observed = ProviderValue((issued: 0, expired: 0, lateGrant: false))
        switch name {
        case "worker-expiry-before-return":
            let entered = ProviderValue(false)
            let release = DispatchSemaphore(value: 0)
            let workerReturned = DispatchSemaphore(value: 0)
            trace.state.use { $0.duringBegin = {
                entered.use { $0 = true }
                check(release.wait(timeout: .now() + 3) == .success, "APPLICATION_BEGIN_HOLD_NOT_RELEASED")
            } }
            let lease = RecoveryExecutionLease(provider: rawProvider.serializingEnds(), expired: {
                check(trace.state.use { $0.ends == 0 } && observed.use { $0.issued == 0 },
                      "APPLICATION_UNKNOWN_ID_EXPIRY_WAITED_FOR_BEGIN")
                observed.use { $0.expired += 1 }
            })
            DispatchQueue.global().async {
                lease.start {
                    check(trace.state.use { $0.ends == 1 }, "APPLICATION_EARLY_EXPIRY_CONTINUATION_PRECEDED_END")
                    observed.use { $0.issued += 1 }
                }
                workerReturned.signal()
            }
            try await until { entered.use { $0 } }
            trace.state.use { $0.callbacks[0] }()
            check(trace.state.use { $0.ends == 0 } && observed.use { $0.issued == 0 },
                  "APPLICATION_EARLY_EXPIRY_INVENTED_RETURNED_ID")
            check(observed.use { $0.expired == 1 }, "APPLICATION_UNKNOWN_ID_EXPIRY_WAITED_FOR_BEGIN")
            trace.state.use { $0.callbacks[0] }()
            check(observed.use { $0.expired == 1 }, "APPLICATION_UNKNOWN_ID_EXPIRY_REPEATED")
            release.signal()
            // Keep main occupied while the worker publishes the returned ID.
            // Its asynchronous cleanup must not block the worker or signal AV.
            check(workerReturned.wait(timeout: .now() + 3) == .success, "APPLICATION_EARLY_END_BLOCKED_WORKER")
            check(observed.use { $0.issued == 0 } && trace.state.use { $0.ends == 0 },
                  "APPLICATION_EARLY_EXPIRY_CONTINUATION_PRECEDED_END")
            try await until { observed.use { $0.issued == 1 } }
            check(observed.use { $0.expired == 1 } && trace.state.use { $0.ends == 1 },
                  "APPLICATION_EARLY_EXPIRY_UNBALANCED")
            lease.finish()

        case "expiry-before-receipt":
            let entered = ProviderValue(false)
            let release = DispatchSemaphore(value: 0)
            let heldReceipt = rawProvider.auditBeforeReceipt {
                entered.use { $0 = true }
                check(release.wait(timeout: .now() + 3) == .success, "APPLICATION_RECEIPT_HOLD_NOT_RELEASED")
            }
            let first = RecoveryExecutionLease(provider: heldReceipt, expired: { observed.use { $0.expired += 1 } })
            DispatchQueue.global().async { first.start { observed.use { $0.issued += 1 } } }
            try await until { entered.use { $0 } }
            let staleExpiry = trace.state.use { $0.callbacks[0] }
            staleExpiry()
            check(trace.state.use { $0.ends == 1 } && observed.use { $0.expired == 1 },
                  "APPLICATION_KNOWN_ID_EXPIRY_DID_NOT_END_INLINE")
            let second = RecoveryExecutionLease(provider: rawProvider, granted: { grant in
                observed.use { $0.lateGrant = grant }
            })
            second.start()
            check(observed.use { $0.lateGrant } && trace.state.use { $0.begins == 2 },
                  "APPLICATION_RETURNED_END_DID_NOT_RELEASE_HOLDER")
            release.signal()
            try await until { observed.use { $0.issued == 1 } }
            // The late first receipt schedules logical end(1). Drain it while
            // request(2) owns the same raw UIKit ID, then replay old expiration.
            await withCheckedContinuation { continuation in
                DispatchQueue.main.async { continuation.resume() }
            }
            staleExpiry()
            check(trace.state.use { $0.ends == 1 }, "APPLICATION_LATE_RECEIPT_ENDED_REUSED_RAW_ID")
            first.finish(); second.finish()
            try await until { trace.state.use { $0.ends == 2 } }

        case "reentrant-end":
            // Exercise the holder's end/expiry boundary directly. A lease that
            // already finished deliberately suppresses later logical expiry.
            let firstID = ProviderValue<Int?>(nil)
            rawProvider.request({
                check(trace.state.use { $0.ends == 1 }, "APPLICATION_EXPIRY_FABRICATED_END_RETURN")
                observed.use { $0.expired += 1 }
            }, { id in firstID.use { $0 = id } })
            check(firstID.use { $0 == 1 }, "APPLICATION_INITIAL_HOLDER_CLAIM_MISSING")
            let staleExpiry = trace.state.use { $0.callbacks[0] }
            trace.state.use { $0.duringEnd = {
                check(trace.state.use { $0.maximumEnds == 1 }, "APPLICATION_DUPLICATE_END_IN_FLIGHT")
                staleExpiry()
                check(observed.use { $0.expired == 0 }, "APPLICATION_EXPIRY_FABRICATED_END_RETURN")
                let result = ProviderValue((received: false, granted: false))
                let attempted = DispatchSemaphore(value: 0)
                DispatchQueue.global().async {
                    rawProvider.request({}, { id in result.use { $0.received = true; $0.granted = id != nil } })
                    attempted.signal()
                }
                check(attempted.wait(timeout: .now() + 3) == .success, "APPLICATION_END_HELD_METADATA_LOCK")
                check(result.use { $0.received && !$0.granted } && trace.state.use { $0.begins == 1 },
                      "APPLICATION_END_RELEASED_CLAIM_EARLY")
            } }
            rawProvider.end(firstID.use { $0! })
            try await until { trace.state.use { $0.ends == 1 } }
            check(observed.use { $0.expired == 1 }, "APPLICATION_REENTRANT_EXPIRY_WAS_LOST")
            trace.state.use { $0.duringEnd = nil }
            let second = RecoveryExecutionLease(provider: rawProvider)
            second.start()
            staleExpiry(); rawProvider.end(1)
            await withCheckedContinuation { continuation in
                DispatchQueue.main.async { continuation.resume() }
            }
            check(trace.state.use { $0.begins == 2 && $0.ends == 1 }, "APPLICATION_STALE_END_CLOSED_REUSED_ID")
            second.finish()
            try await until { trace.state.use { $0.ends == 2 } }

        case "queued-end-bound":
            mainEndJobLimit = 1
            let firstID = ProviderValue<Int?>(nil)
            rawProvider.request({
                check(trace.state.use { $0.ends == 1 }, "APPLICATION_QUEUED_EXPIRY_PRECEDED_END")
                observed.use { $0.expired += 1 }
            }, { id in firstID.use { $0 = id } })
            check(firstID.use { $0 == 1 }, "APPLICATION_INITIAL_HOLDER_CLAIM_MISSING")
            let queued = DispatchSemaphore(value: 0)
            DispatchQueue.global().async {
                for _ in 0..<1000 { rawProvider.end(firstID.use { $0! }) }
                queued.signal()
            }
            // Keep main occupied: all duplicate requests must return promptly,
            // reserve one job, and leave actual end for main/expiry.
            check(queued.wait(timeout: .now() + 3) == .success, "APPLICATION_QUEUED_END_BLOCKED_CALLER")
            check(trace.state.use { $0.ends == 0 }, "APPLICATION_NORMAL_END_LEFT_MAIN")
            trace.state.use { $0.callbacks[0] }()
            check(trace.state.use { $0.ends == 1 } && observed.use { $0.expired == 1 },
                  "APPLICATION_QUEUED_EXPIRY_DID_NOT_END_INLINE")
            let result = ProviderValue((received: false, granted: false))
            let attempted = DispatchSemaphore(value: 0)
            DispatchQueue.global().async {
                rawProvider.request({}, { id in result.use { $0.received = true; $0.granted = id != nil } })
                attempted.signal()
            }
            check(attempted.wait(timeout: .now() + 3) == .success, "APPLICATION_QUEUED_END_BLOCKED_ADMISSION")
            check(result.use { $0.received && !$0.granted } && trace.state.use { $0.begins == 1 },
                  "APPLICATION_QUEUED_END_ADMITTED_ANOTHER_CLAIM")
            await withCheckedContinuation { continuation in
                DispatchQueue.main.async { continuation.resume() }
            }
            check(mainEndJobs == 1, "APPLICATION_MAIN_END_RESERVATION_NOT_CONSUMED")
            mainEndJobLimit = 2
            let secondID = ProviderValue<Int?>(nil)
            rawProvider.request({}, { id in secondID.use { $0 = id } })
            check(secondID.use { $0 == 2 } && trace.state.use { $0.begins == 2 && $0.ends == 1 },
                  "APPLICATION_CONSUMED_END_RESERVATION_BLOCKED_CLAIM")
            rawProvider.end(secondID.use { $0! })
            try await until { trace.state.use { $0.ends == 2 } }

        case "settled-lifetime":
            var lease: RecoveryExecutionLease? = RecoveryExecutionLease(provider: rawProvider.serializingEnds())
            lease!.start()
            let released = { [weak current = lease] in current == nil }
            lease = nil // Deinit must still own and balance the one active ID.
            check(released(), "APPLICATION_SETTLED_CALLBACK_RETAINED_LEASE")
            try await until { trace.state.use { $0.ends == 1 } }
            // A platform is allowed to retain an old callback after end. That
            // callback carries identity and a weak expiry, not AV continuations.
            trace.state.use { $0.callbacks[0] }()
            check(released(), "APPLICATION_OLD_EXPIRY_REVIVED_LEASE")

        default: fatalError("Unknown application provider boundary")
        }
        check(trace.state.use { $0.begins == $0.ends && $0.inEnd == 0 && $0.maximumEnds == 1 },
              "APPLICATION_PROVIDER_FINAL_RESOURCE_BOUND")
        print("PASS: application provider \(name); actual request/receipt/end ordering with platform doubles")
    }
}
