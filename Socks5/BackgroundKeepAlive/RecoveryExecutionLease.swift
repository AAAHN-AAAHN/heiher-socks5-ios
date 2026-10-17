import Foundation
#if canImport(UIKit)
import UIKit
#endif

/// The only unchecked type in this file. It contains value-only lease metadata;
/// no AV object, provider callback, system call or wait runs under this lock.
private final class LeaseStorage<Value: Sendable>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value
    init(_ value: Value) { self.value = value }
    func withValue<Result: Sendable>(_ body: @Sendable (inout Value) -> Result) -> Result {
        lock.lock(); defer { lock.unlock() }
        return body(&value)
    }
}

/// A finite claim, not a cancellation handle. All mutable metadata is confined
/// by LeaseStorage; callbacks and platform operations always run outside it.
final class RecoveryExecutionLease: Sendable {
    struct Provider: Sendable {
        let request: @Sendable (@escaping @Sendable () -> Void,
                                @escaping @Sendable (Int?) -> Void) -> Void
        let end: @Sendable (Int) -> Void

        static let unavailable = Provider(request: { _, receipt in receipt(nil) }, end: { _ in })

        /// One end gate is shared for the service lifetime. A pending platform
        /// end refuses new claims instead of accumulating tokens or cleanup jobs.
        func serializingEnds() -> Provider {
            let gate = EndGate(provider: self)
            return Provider(request: { gate.request(expire: $0, receipt: $1) }, end: { gate.end($0) })
        }

        #if canImport(UIKit)
        /// Supplied by an actual UIApplication root, not inferred from a bundle ID.
        @MainActor static func application(_ app: UIApplication) -> Provider {
            Provider(request: { expire, receipt in
                let id = app.beginBackgroundTask(withName: "Loop sound recovery", expirationHandler: expire)
                receipt(id == .invalid ? nil : id.rawValue)
            }, end: { app.endBackgroundTask(UIBackgroundTaskIdentifier(rawValue: $0)) })
        }
        #endif

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

        func request(expire: @escaping @Sendable () -> Void,
                     receipt: @escaping @Sendable (Int?) -> Void) {
            let request = Request()
            let admitted = state.withValue { value -> Bool in
                guard value.current == nil else { return false }
                value.current = request
                value.received = false
                return true
            }
            guard admitted else { receipt(nil); return }
            provider.request(expire, { [self, request] id in
                let accepted = state.withValue { value -> Bool in
                    guard value.current === request, !value.received else { return false }
                    value.received = true
                    value.identifier = id
                    if id == nil { value.current = nil }
                    return true
                }
                if accepted { receipt(id) }
            })
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

    func start() {
        let begin = state.withValue { value -> Bool in
            let first = !value.started && !value.ended
            value.started = true
            return first
        }
        guard begin else { return }
        provider.request({ [weak self] in self?.expire() }, { [self] in receive($0) })
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
