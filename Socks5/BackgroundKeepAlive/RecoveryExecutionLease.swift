import Foundation
#if canImport(UIKit)
import UIKit
#endif

#if os(Linux)
import Synchronization
#else
import os
#endif

/// Checked platform lock and Sendable metadata only. No AV object, provider
/// callback, system call or wait runs in this accessor. The Darwin API is
/// available from iOS 16; no iOS 18 Mutex or deployment-target change is needed.
private final class LeaseStorage<Value: Sendable>: Sendable {
    #if os(Linux)
    private let value: Mutex<Value>
    init(_ value: Value) { self.value = Mutex(value) }
    #else
    private let value: OSAllocatedUnfairLock<Value>
    init(_ value: Value) { self.value = OSAllocatedUnfairLock(initialState: value) }
    #endif
    func withValue<Result: Sendable>(_ body: @Sendable (inout Value) -> Result) -> Result {
        value.withLock { body(&$0) }
    }
}

/// A finite claim, not a cancellation handle. All mutable metadata is confined
/// by LeaseStorage; callbacks and platform operations always run outside it.
final class RecoveryExecutionLease: Sendable {
    struct Provider: Sendable {
        fileprivate let issue: @Sendable (@escaping @Sendable () -> Bool,
                                      @escaping @Sendable () -> Void,
                                      @escaping @Sendable (Int?) -> Void,
                                      @escaping @Sendable () -> Void) -> Void
        let end: @Sendable (Int) -> Void

        init(request: @escaping @Sendable (@escaping @Sendable () -> Void,
                                           @escaping @Sendable (Int?) -> Void) -> Void,
             end: @escaping @Sendable (Int) -> Void) {
            issue = { allowed, expire, receipt, returned in
                if allowed() { request(expire, receipt) } else { receipt(nil) }
                // A provider may return before its receipt, or never deliver a
                // receipt. This boundary does not wait for a grant.
                returned()
            }
            self.end = end
        }

        private init(issue: @escaping @Sendable (@escaping @Sendable () -> Bool,
                                                  @escaping @Sendable () -> Void,
                                                  @escaping @Sendable (Int?) -> Void,
                                                  @escaping @Sendable () -> Void) -> Void,
                     end: @escaping @Sendable (Int) -> Void) {
            self.issue = issue
            self.end = end
        }

        func request(_ expire: @escaping @Sendable () -> Void,
                     _ receipt: @escaping @Sendable (Int?) -> Void) {
            issue({ true }, expire, receipt, {})
        }

        static let unavailable = Provider(request: { _, receipt in receipt(nil) }, end: { _ in })

        /// One end gate is shared for the service lifetime. A pending platform
        /// end refuses new claims instead of accumulating tokens or cleanup jobs.
        func serializingEnds() -> Provider {
            let gate = EndGate(provider: self)
            return Provider(issue: { gate.request(allowed: $0, expire: $1, receipt: $2, returned: $3) },
                            end: { gate.end($0) })
        }

        #if canImport(UIKit)
        /// Supplied by an actual UIApplication root, not inferred from a bundle ID.
        @MainActor static func application(_ app: UIApplication) -> Provider {
            application(begin: { expire in
                let id = app.beginBackgroundTask(withName: "Loop sound recovery", expirationHandler: {
                    // UIKit delivers expiration on main. Do not enqueue the
                    // actual end behind the handler's return.
                    MainActor.assumeIsolated { expire() }
                })
                return id == .invalid ? nil : id.rawValue
            }, end: { app.endBackgroundTask(UIBackgroundTaskIdentifier(rawValue: $0)) })
        }
        #endif

        /// The portable application policy owns begin/end/expiration on main.
        /// Only application(_:) supplies UIKit operations. No audio, file or
        /// worker wait is performed by this holder or its platform callbacks.
        @MainActor static func application(
            begin: @escaping @MainActor @Sendable (@escaping @MainActor @Sendable () -> Void) -> Int?,
            end: @escaping @MainActor @Sendable (Int) -> Void
        ) -> Provider {
            let holder = ApplicationHolder(begin: begin, end: end)
            return Provider(issue: { allowed, expire, receipt, returned in
                DispatchQueue.main.async {
                    holder.request(allowed: allowed, expire: expire, receipt: receipt)
                    returned()
                }
            }, end: { id in
                DispatchQueue.main.async { holder.end(id) }
            })
        }

        #if os(iOS)
        /// Inject only after verifying this deployment's actual extension context.
        /// The current application root does not select or advertise this adapter.
        static func extensionActivity() -> Provider {
            expiringActivity { activity in
                ProcessInfo.processInfo.performExpiringActivity(withReason: "Loop sound recovery", using: activity)
            }
        }
        #endif

        /// Portable holder policy; extensionActivity alone supplies the platform
        /// operation. Acquisition and expiration may arrive in either order.
        static func expiringActivity(_ begin: @escaping @Sendable (@escaping @Sendable (Bool) -> Void) -> Void) -> Provider {
            let holders = ExtensionHolders()
            return Provider(request: { expire, receipt in
                guard let holder = holders.make() else { receipt(nil); return }
                begin { expired in
                    if expired {
                        expire()
                        holders.end(holder.id)
                    } else {
                        receipt(holder.id)
                        if holder.finished.wait(timeout: .now() + 25) == .timedOut {
                            expire()
                            holders.end(holder.id)
                        }
                    }
                }
            }, end: { holders.end($0) })
        }
    }

    /// One platform identifier is owned on main. A monotonically increasing
    /// logical identity prevents old callbacks/ends from closing a reused raw
    /// UIKit identifier. Refuse new claims instead of wrapping that identity.
    @MainActor private final class ApplicationHolder {
        private final class Request {
            let id: Int
            let expire: @Sendable () -> Void
            var received = false
            var ended = false
            var platformID: Int?
            init(id: Int, expire: @escaping @Sendable () -> Void) {
                self.id = id
                self.expire = expire
            }
        }
        private let begin: @MainActor @Sendable (@escaping @MainActor @Sendable () -> Void) -> Int?
        private let platformEnd: @MainActor @Sendable (Int) -> Void
        private var sequence = 0
        private var current: Request?

        init(begin: @escaping @MainActor @Sendable (@escaping @MainActor @Sendable () -> Void) -> Int?,
             end: @escaping @MainActor @Sendable (Int) -> Void) {
            self.begin = begin
            platformEnd = end
        }

        func request(allowed: @Sendable () -> Bool, expire: @escaping @Sendable () -> Void,
                     receipt: @escaping @Sendable (Int?) -> Void) {
            guard allowed(), current == nil, sequence < Int.max else { receipt(nil); return }
            sequence += 1
            let request = Request(id: sequence, expire: expire)
            current = request
            let id = begin { [weak self, request] in self?.expire(request) }
            request.received = true
            request.platformID = id
            if request.ended {
                // If expiration reentered begin before it returned an ID, end
                // that ID at the first safe point, before receipt/AV continuation.
                finish(request)
            } else if id == nil {
                current = nil
            }
            receipt(id == nil ? nil : request.id)
        }

        func end(_ id: Int) {
            guard let request = current, request.id == id else { return }
            finish(request)
        }

        private func expire(_ request: Request) {
            guard current === request, !request.ended else { return }
            finish(request)
            request.expire()
        }

        private func finish(_ request: Request) {
            guard current === request else { return }
            request.ended = true
            guard request.received else { return }
            if let id = request.platformID {
                request.platformID = nil
                platformEnd(id)
            }
            // Keep ownership through the platform call, including reentrancy.
            if current === request { current = nil }
        }
    }

    /// Immutable handles plus locked value state. A never-returning platform end
    /// occupies one serial job and prevents replacement grants, not audio policy.
    private final class EndGate: Sendable {
        private final class Request: Sendable {}
        private struct State: Sendable {
            var current: Request?
            var received = false
            var closing = false
            var identifier: Int?
        }
        private let state = LeaseStorage(State())
        private let provider: Provider
        private let queue = DispatchQueue(label: "Socks5.loop-audio.claim-end", qos: .utility)

        init(provider: Provider) { self.provider = provider }

        func request(allowed: @escaping @Sendable () -> Bool,
                     expire: @escaping @Sendable () -> Void,
                     receipt: @escaping @Sendable (Int?) -> Void,
                     returned: @escaping @Sendable () -> Void) {
            let request = Request()
            let admitted = state.withValue { value -> Bool in
                guard value.current == nil else { return false }
                value.current = request
                value.received = false
                return true
            }
            guard admitted else { receipt(nil); returned(); return }
            provider.issue(allowed, expire, { [self, request] id in
                let accepted = state.withValue { value -> Bool in
                    guard value.current === request, !value.received else { return false }
                    value.received = true
                    value.identifier = id
                    if id == nil { value.current = nil }
                    return true
                }
                if accepted { receipt(id) }
            }, returned)
        }

        func end(_ id: Int) {
            let admitted = state.withValue { value -> Bool in
                guard value.current != nil, value.received, value.identifier == id, !value.closing else { return false }
                value.closing = true
                return true
            }
            guard admitted else { return }
            queue.async { [self] in
                provider.end(id)
                state.withValue { $0 = State() }
            }
        }
    }

    /// Each request has an immutable identity and its own semaphore. An old
    /// expiration/end cannot release a later request. Saturation returns no grant.
    private final class ExtensionHolders: Sendable {
        final class Holder: Sendable {
            let id: Int
            let finished = DispatchSemaphore(value: 0)
            init(id: Int) { self.id = id }
        }
        private struct State: Sendable {
            var sequence = 0
            var current: Holder?
        }
        private let state = LeaseStorage(State())

        func make() -> Holder? {
            state.withValue { value in
                guard value.current == nil, value.sequence < Int.max else { return nil }
                value.sequence += 1
                let holder = Holder(id: value.sequence)
                value.current = holder
                return holder
            }
        }

        func end(_ id: Int) {
            let holder = state.withValue { value -> Holder? in
                guard let holder = value.current, holder.id == id else { return nil }
                value.current = nil
                return holder
            }
            holder?.finished.signal()
        }
    }

    private struct State: Sendable {
        var started = false
        var issued = false
        var received = false
        var ended = false
        var identifier: Int?
    }
    private let state = LeaseStorage(State())
    private let provider: Provider
    private let expired: @Sendable () -> Void
    private let granted: @Sendable (Bool) -> Void

    init(provider: Provider, granted: @escaping @Sendable (Bool) -> Void = { _ in },
         expired: @escaping @Sendable () -> Void = {}) {
        self.provider = provider
        self.granted = granted
        self.expired = expired
    }

    /// Completion means the request call returned (not that a grant arrived),
    /// or that it was cancelled before issue. A duplicate start while the first
    /// issue is pending returns false and stores no second continuation.
    @discardableResult
    func start(completion: @escaping @Sendable () -> Void = {}) -> Bool {
        start(mayIssue: { true }, completion: completion)
    }

    @discardableResult
    func start(mayIssue: @escaping @Sendable () -> Bool,
               completion: @escaping @Sendable () -> Void) -> Bool {
        let action = state.withValue { value -> Int in
            if value.started { return value.issued ? 1 : 0 }
            value.started = true
            if value.ended { value.issued = true; return 1 }
            return 2
        }
        guard action != 0 else { return false }
        if action == 1 { completion(); return true }
        provider.issue({ [self] in
            guard state.withValue({ !$0.ended }) else { return false }
            // The service accepts Off before its control drain can finish this
            // lease. Read that latest ticket here, outside the lease lock.
            return mayIssue()
        },
                       { [weak self] in self?.expire() }, { [self] in receive($0) }, { [self] in
            state.withValue { $0.issued = true }
            completion()
        })
        return true
    }

    private func receive(_ id: Int?) {
        let result = state.withValue { value -> (Bool, Int?) in
            guard !value.received else { return (false, nil) }
            value.received = true
            if !value.ended { value.identifier = id }
            return (true, value.ended ? id : nil)
        }
        guard result.0 else { return }
        granted(id != nil)
        if let close = result.1 { provider.end(close) }
    }

    private func expire() {
        let first = finish()
        if first { expired() }
    }

    @discardableResult
    func finish() -> Bool {
        let result = state.withValue { value -> (Bool, Int?) in
            let first = !value.ended
            value.ended = true
            let id = value.identifier
            value.identifier = nil
            return (first, id)
        }
        let id = result.1
        if let id { provider.end(id) }
        return result.0
    }

    deinit { finish() }
}
