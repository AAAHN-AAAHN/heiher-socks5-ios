import Dispatch
import Foundation
import HevSocks5Server
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Numeric addresses only: parsing never performs a DNS request.
struct PingDestination: Sendable {
    let name: String
    let family: Int32
    var address: sockaddr_storage
    let length: socklen_t

    init(_ text: String) throws {
        guard !text.utf8.contains(0) else { throw PingInputError.address }
        var storage = sockaddr_storage()
        var v4 = in_addr()
        var v6 = in6_addr()
        var normalized = [CChar](repeating: 0, count: Int(INET6_ADDRSTRLEN))
        if inet_pton(AF_INET, text, &v4) == 1 {
            var value = sockaddr_in()
            #if canImport(Darwin)
            value.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            #endif
            value.sin_family = sa_family_t(AF_INET)
            value.sin_addr = v4
            withUnsafeMutableBytes(of: &storage) { output in
                withUnsafeBytes(of: value) { output.copyMemory(from: $0) }
            }
            inet_ntop(AF_INET, &v4, &normalized, socklen_t(normalized.count))
            family = AF_INET
            length = socklen_t(MemoryLayout<sockaddr_in>.size)
            name = String(cString: normalized)
        } else {
            let parts = text.split(separator: "%", maxSplits: 2, omittingEmptySubsequences: false)
            guard (1...2).contains(parts.count), inet_pton(AF_INET6, String(parts[0]), &v6) == 1 else {
                throw PingInputError.address
            }
            let raw = withUnsafeBytes(of: v6) { Array($0) }
            if raw.prefix(10).allSatisfy({ $0 == 0 }), raw[10] == 255, raw[11] == 255 {
                guard parts.count == 1 else { throw PingInputError.address }
                self = try PingDestination(raw.suffix(4).map(String.init).joined(separator: "."))
                return
            }
            var scope: UInt32 = 0
            if parts.count == 2 {
                guard !parts[1].isEmpty else { throw PingInputError.address }
                scope = UInt32(parts[1]) ?? if_nametoindex(String(parts[1]))
                guard scope != 0 else { throw PingInputError.address }
            }
            var value = sockaddr_in6()
            #if canImport(Darwin)
            value.sin6_len = UInt8(MemoryLayout<sockaddr_in6>.size)
            #endif
            value.sin6_family = sa_family_t(AF_INET6)
            value.sin6_addr = v6
            value.sin6_scope_id = scope
            withUnsafeMutableBytes(of: &storage) { output in
                withUnsafeBytes(of: value) { output.copyMemory(from: $0) }
            }
            inet_ntop(AF_INET6, &v6, &normalized, socklen_t(normalized.count))
            family = AF_INET6
            length = socklen_t(MemoryLayout<sockaddr_in6>.size)
            name = String(cString: normalized) + (scope == 0 ? "" : "%\(scope)")
        }
        address = storage
    }
}

enum PingInputError: String, Error, LocalizedError {
    case address = "Enter numeric IPv4 or IPv6 addresses separated by commas."
    case count = "Enter 1 to 65,536 different destination IPs."
    case period = "Period must be a positive whole number of milliseconds."
    var errorDescription: String? { rawValue }
}

struct PeriodicPingConfiguration: Sendable {
    let destinations: [PingDestination]
    let periodMilliseconds: Int

    static let maximumDestinations = 65_536

    init(destinations text: String, period: String, isCancelled: () -> Bool = { false }) throws {
        if isCancelled() { throw CancellationError() }
        // Reject an invalid period before normalizing a potentially large address list.
        let digits = period.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !digits.isEmpty, digits.utf8.allSatisfy({ (48...57).contains($0) }),
              let milliseconds = Int(digits), milliseconds > 0,
              milliseconds <= Int.max / 1_000_000 else { throw PingInputError.period }
        // Scan substrings without copying the whole input or allocating a token array.
        var remaining = text[...]
        var scanned = 0
        var seen = Set<String>()
        var addresses: [PingDestination] = []
        while true {
            if scanned > 0, scanned % 256 == 0, isCancelled() { throw CancellationError() }
            let end = remaining.firstIndex { $0 == "," || $0.isNewline } ?? remaining.endIndex
            let token = remaining[..<end].trimmingCharacters(in: .whitespacesAndNewlines)
            let address = try PingDestination(token)
            if seen.insert(address.name).inserted {
                guard addresses.count < Self.maximumDestinations else { throw PingInputError.count }
                addresses.append(address)
            }
            scanned += 1
            if end == remaining.endIndex { break }
            remaining = remaining[remaining.index(after: end)...]
        }
        guard !addresses.isEmpty else { throw PingInputError.count }
        destinations = addresses
        periodMilliseconds = milliseconds
    }
}

private struct PingBatchResult: Sendable {
    var processed = 0
    var waiting = false
    var failed = 0
    var failures: [(Int, Int32)] = []
}

/// One bounded batch, with one completion instead of one queued Swift job per
/// native event. Reply/timeout events after SENT do not change send status.
private final class PingNativeInbox: @unchecked Sendable {
    private final class Batch {
        let first: UInt64
        var pending: [Bool]
        var remaining: Int
        var result: PingBatchResult
        let completion: @Sendable (PingBatchResult) -> Void

        init(first: UInt64, count: Int, completion: @escaping @Sendable (PingBatchResult) -> Void) {
            self.first = first
            pending = Array(repeating: true, count: count)
            remaining = count
            result = PingBatchResult(processed: count)
            self.completion = completion
        }
    }
    private let lock = NSLock()
    private var batch: Batch?

    func begin(first: UInt64, count: Int, completion: @escaping @Sendable (PingBatchResult) -> Void) {
        let next = Batch(first: first, count: count, completion: completion)
        lock.lock(); defer { lock.unlock() }
        precondition(batch == nil && (1...256).contains(count))
        batch = next
    }

    func complete(_ id: UInt64, error: Int32) {
        lock.lock()
        guard let current = batch, id >= current.first,
              id - current.first < UInt64(current.pending.count) else {
            lock.unlock()
            return
        }
        let index = Int(id - current.first)
        guard current.pending[index] else { lock.unlock(); return }
        current.pending[index] = false
        current.remaining -= 1
        if error != 0 {
            current.result.failed += 1
            if current.result.failures.count < 3 { current.result.failures.append((index, error)) }
        }
        if current.remaining == 0 {
            batch = nil
            lock.unlock()
            current.completion(current.result)
        } else {
            lock.unlock()
        }
    }

    func cancel() {
        lock.lock(); batch = nil; lock.unlock()
    }

    func pause(at id: UInt64) {
        lock.lock()
        guard let current = batch, id >= current.first,
              id - current.first < UInt64(current.pending.count) else { lock.unlock(); return }
        let index = Int(id - current.first)
        current.result.processed = index
        current.result.waiting = true
        for slot in index..<current.pending.count where current.pending[slot] {
            current.pending[slot] = false
            current.remaining -= 1
        }
        if current.remaining == 0 {
            batch = nil
            lock.unlock()
            current.completion(current.result)
        } else {
            lock.unlock()
        }
    }
}

private func receivePingResult(_ result: UnsafePointer<HevSocks5IcmpResult>?,
                               _ context: UnsafeMutableRawPointer?) {
    guard let result, let context else { return }
    let event = result.pointee.event
    guard event == HEV_SOCKS5_ICMP_SENT || event == HEV_SOCKS5_ICMP_ERROR else { return }
    Unmanaged<PingNativeInbox>.fromOpaque(context).takeUnretainedValue().complete(
        result.pointee.request_id, error: event == HEV_SOCKS5_ICMP_SENT ? 0 : result.pointee.error)
}

/// The native handle owns no Swift queue. Native free quiesces callbacks before
/// releasing their retained inbox; cancel may run at the public Off boundary.
private final class PingNativeClient: @unchecked Sendable {
    let generation: UInt64
    private let handle: OpaquePointer
    private let inbox: PingNativeInbox
    private let context: UnsafeMutableRawPointer
    private let admission = NSLock()
    private var cancelled = false
    private var nextID: UInt64 = 1 // Accessed only by the periodic-ping queue.

    init?(generation: UInt64) {
        let inbox = PingNativeInbox()
        let context = Unmanaged.passRetained(inbox).toOpaque()
        guard let handle = hev_socks5_server_icmp_client_new(generation, receivePingResult, context) else {
            let error = errno
            Unmanaged<PingNativeInbox>.fromOpaque(context).release()
            errno = error
            return nil
        }
        self.generation = generation
        self.inbox = inbox
        self.context = context
        self.handle = handle
    }

    func submit(_ targets: ArraySlice<PingDestination>, isCurrent: () -> Bool,
                completion: @escaping @Sendable (PingBatchResult) -> Void) {
        guard nextID <= UInt64.max - UInt64(targets.count) else {
            completion(PingBatchResult(processed: targets.count, failed: targets.count, failures: [(0, EOVERFLOW)]))
            return
        }
        let first = nextID
        nextID += UInt64(targets.count)
        admission.lock()
        guard !cancelled else { admission.unlock(); return }
        inbox.begin(first: first, count: targets.count, completion: completion)
        admission.unlock()
        for (index, value) in targets.enumerated() {
            var target = value
            let id = first + UInt64(index)
            admission.lock()
            guard !cancelled, isCurrent() else { admission.unlock(); cancel(); return }
            let status = withUnsafePointer(to: &target.address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    hev_socks5_server_icmp_ping(handle, id, $0, target.length, 1000)
                }
            }
            admission.unlock()
            if status == -EAGAIN { inbox.pause(at: id); return }
            if status != 0 { inbox.complete(id, error: -status) }
        }
    }

    func cancel() {
        admission.lock(); cancelled = true; admission.unlock()
        inbox.cancel()
        hev_socks5_server_icmp_cancel(handle)
    }

    deinit {
        hev_socks5_server_icmp_client_free(handle)
        Unmanaged<PingNativeInbox>.fromOpaque(context).release()
    }
}

/// Public handle. Requests coalesce before parsing; Off invalidates an in-flight batch.
final class PeriodicPingService: Sendable {
    private let worker = PeriodicPingWorker()

    func configure(_ configuration: PeriodicPingConfiguration?, report: @escaping @Sendable (String) -> Void) {
        submit(.parsed(configuration), report: report)
    }

    func configure(enabled: Bool, destinations: String, period: String,
                   report: @escaping @Sendable (String) -> Void) {
        submit(.text(enabled, destinations, period), report: report)
    }

    private func submit(_ input: PingRequests.Input, report: @escaping @Sendable (String) -> Void) {
        let owner = worker
        if owner.requests.post(input, report: report) { owner.queue.async { owner.consume() } }
    }

    deinit {
        let owner = worker
        if owner.requests.post(.parsed(nil), report: { _ in }) { owner.queue.async { owner.consume() } }
    }
}

/// Only the latest request is retained. The lock also cancels parsing/sending
/// without waiting behind a large batch on the worker queue.
private final class PingRequests: @unchecked Sendable {
    enum Input: Sendable {
        case parsed(PeriodicPingConfiguration?)
        case text(Bool, String, String)
    }
    struct Request: Sendable {
        let id: UUID
        let input: Input
        let report: @Sendable (String) -> Void
    }
    private let lock = NSLock()
    private var latest = UUID()
    private var pending: Request?
    private var scheduled = false
    private var client: PingNativeClient?

    func post(_ input: Input, report: @escaping @Sendable (String) -> Void) -> Bool {
        lock.lock()
        latest = UUID()
        pending = Request(id: latest, input: input, report: report)
        let old = client
        client = nil
        let enqueue = !scheduled
        scheduled = true
        lock.unlock()
        // Never hold the Swift lock while native cancel waits on its send gate.
        // The strong local reference also serializes native free after this use.
        old?.cancel()
        return enqueue
    }

    func take() -> Request? {
        lock.lock(); defer { lock.unlock() }
        let value = pending
        pending = nil
        scheduled = false
        return value
    }

    func current(_ id: UUID) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return latest == id
    }

    func install(_ next: PingNativeClient?, for id: UUID) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard latest == id else { return false }
        client = next
        return true
    }
}

/// Checked at the public boundary; mutable fields below are exclusively queue-confined.
private final class PeriodicPingWorker: @unchecked Sendable {
    let requests = PingRequests()
    let queue = DispatchQueue(label: "hev.Socks5.periodic-ping", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var configuration: PeriodicPingConfiguration?
    private var client: PingNativeClient?
    private var report: (@Sendable (String) -> Void)?
    private var lastStatus: String?
    private var requestID = UUID()
    private var cursor: Int?
    private var waitingCapacity = false
    private var failureCount = 0
    private var failures: [String] = []
    private var generation = UUID()

    func consume() {
        guard let request = requests.take() else { return }
        stop()
        requestID = request.id
        let next: PeriodicPingConfiguration?
        do {
            switch request.input {
            case .parsed(let value): next = value
            case .text(let enabled, let destinations, let period):
                if enabled {
                    next = try PeriodicPingConfiguration(destinations: destinations, period: period) {
                        !self.requests.current(request.id)
                    }
                } else { next = nil }
            }
        } catch {
            if requests.current(request.id) { request.report(error.localizedDescription) }
            return
        }
        guard requests.current(request.id) else { return }
        configure(next, report: request.report)
    }

    func configure(_ next: PeriodicPingConfiguration?, report: @escaping @Sendable (String) -> Void) {
        self.report = report
        configuration = next
        lastStatus = nil
        guard let next else { publish("Off"); return }
        let source = DispatchSource.makeTimerSource(queue: queue)
        timer = source
        let period = next.periodMilliseconds
        source.schedule(deadline: .now(), repeating: .milliseconds(period),
                        leeway: .milliseconds(min(10, period / 20)))
        let generation = self.generation
        source.setEventHandler { [weak self] in
            guard let self, self.generation == generation else { return }
            self.tick()
        }
        source.resume()
    }

    func stop() {
        generation = UUID()
        timer?.setEventHandler {}
        timer?.cancel()
        timer = nil
        configuration = nil
        cursor = nil
        waitingCapacity = false
        failures.removeAll(keepingCapacity: true)
        releaseClient()
        report = nil
    }

    private func publish(_ status: String) {
        guard lastStatus != status else { return }
        lastStatus = status
        report?(status)
    }

    private func releaseClient() {
        _ = requests.install(nil, for: requestID)
        client?.cancel()
        client = nil
    }

    private func tick() {
        guard configuration != nil, cursor == nil || waitingCapacity, requests.current(requestID) else { return }
        let active = hev_socks5_server_icmp_generation()
        if client?.generation != active {
            releaseClient()
            cursor = nil
            waitingCapacity = false
        }
        guard active != 0 else { publish("Waiting for native ICMP server"); return }
        if client == nil {
            guard let opened = PingNativeClient(generation: active) else {
                let error = errno
                publish(hev_socks5_server_icmp_generation() == active ?
                    "Send error: " + String(cString: strerror(error)) : "Waiting for native ICMP server")
                return
            }
            guard requests.install(opened, for: requestID) else { opened.cancel(); return }
            client = opened
        }
        if cursor != nil {
            waitingCapacity = false
            sendBatch()
            return
        }
        failures.removeAll(keepingCapacity: true)
        failureCount = 0
        cursor = 0
        sendBatch()
    }

    private func sendBatch() {
        guard let configuration, let client, let start = cursor, requests.current(requestID) else { return }
        let end = min(start + 256, configuration.destinations.count)
        let generation = self.generation
        client.submit(configuration.destinations[start..<end], isCurrent: { self.requests.current(self.requestID) }) { [weak self] result in
            guard let self else { return }
            self.queue.async {
                guard self.generation == generation, self.requests.current(self.requestID) else { return }
                self.completeBatch(result, start: start)
            }
        }
    }

    private func completeBatch(_ result: PingBatchResult, start: Int) {
        guard let configuration else { return }
        guard client?.generation == hev_socks5_server_icmp_generation() else {
            releaseClient()
            cursor = nil
            waitingCapacity = false
            publish("Waiting for native ICMP server")
            return
        }
        failureCount += result.failed
        for (index, error) in result.failures where failures.count < 3 {
            failures.append("\(configuration.destinations[start + index].name): \(String(cString: strerror(error)))")
        }
        let end = start + result.processed
        if result.waiting {
            cursor = end
            waitingCapacity = true
            publish("Waiting for native ICMP capacity; \(end)/\(configuration.destinations.count) destinations processed" +
                    (failureCount == 0 ? "" : "; \(failureCount) send failure(s)"))
            return
        }
        if end < configuration.destinations.count {
            cursor = end
            let generation = self.generation
            queue.async { [weak self] in
                guard let self, self.generation == generation else { return }
                self.sendBatch()
            }
            return
        }
        cursor = nil
        if failureCount == 0 {
            publish("Sending ICMP to \(configuration.destinations.count) destination(s)")
        } else {
            publish("Send error: " + failures.joined(separator: "; ") +
                    (failureCount > failures.count ? "; \(failureCount) destination(s) failed" : ""))
        }
    }
}
