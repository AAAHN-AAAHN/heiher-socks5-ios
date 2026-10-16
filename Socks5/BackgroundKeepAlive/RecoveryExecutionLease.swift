import Foundation
#if canImport(UIKit)
import UIKit
#endif

/// A finite claim, not a cancellation handle. The lock protects only bookkeeping;
/// no platform callback, system call or wait executes while holding it.
final class RecoveryExecutionLease: @unchecked Sendable {
    struct Provider: Sendable {
        let request: @Sendable (@escaping @Sendable () -> Void,
                                @escaping @Sendable (Int?) -> Void) -> Void
        let end: @Sendable (Int) -> Void

        static let unavailable = Provider(request: { _, receipt in receipt(nil) }, end: { _ in })

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
        /// Only inject for a verified extension context. The holder exits on end or
        /// expiration, including expiration-before-acquisition. Never cancel AV I/O.
        static func extensionActivity() -> Provider {
            let finished = DispatchSemaphore(value: 0)
            return Provider(request: { expire, receipt in
                ProcessInfo.processInfo.performExpiringActivity(withReason: "Loop sound recovery") { expired in
                    if expired {
                        expire()
                        finished.signal()
                    } else {
                        receipt(1)
                        if finished.wait(timeout: .now() + 25) == .timedOut { expire() }
                    }
                }
            }, end: { _ in finished.signal() })
        }
        #endif
    }

    private let lock = NSLock()
    private let provider: Provider
    private let expired: @Sendable () -> Void
    private var started = false
    private var received = false
    private var ended = false
    private var identifier: Int?

    init(provider: Provider, expired: @escaping @Sendable () -> Void = {}) {
        self.provider = provider
        self.expired = expired
    }

    func start() {
        lock.lock()
        let begin = !started && !ended
        started = true
        lock.unlock()
        guard begin else { return }
        provider.request({ [weak self] in self?.expire() }, { [self] in receive($0) })
    }

    private func receive(_ id: Int?) {
        lock.lock()
        guard !received else { lock.unlock(); return }
        received = true
        if !ended { identifier = id }
        let close = ended ? id : nil
        lock.unlock()
        if let close { provider.end(close) }
    }

    private func expire() {
        let first = finish()
        if first { expired() }
    }

    @discardableResult
    func finish() -> Bool {
        lock.lock()
        let first = !ended
        ended = true
        let id = identifier
        identifier = nil
        lock.unlock()
        if let id { provider.end(id) }
        return first
    }

    deinit { finish() }
}
