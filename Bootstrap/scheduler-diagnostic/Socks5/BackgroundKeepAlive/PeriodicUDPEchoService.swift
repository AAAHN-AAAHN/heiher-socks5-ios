import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Owns scheduling and target policy; all network I/O belongs to Socks5UDPClient.
final class PeriodicUDPEchoService: @unchecked Sendable {
    typealias IOObserver = @Sendable (Socks5UDPClient.Address, Int, Bool) -> Void
    typealias ServerResolver = @Sendable () -> Socks5UDPClient.Configuration?

    struct State: Sendable, Equatable {
        let generation: UInt64
        let text: String
    }

    struct Plan {
        let targets: [[Socks5UDPClient.Address]]
        let interval: UInt64
    }

    enum InputError: LocalizedError {
        case invalid(String), cancelled
        var errorDescription: String? {
            switch self {
            case .invalid(let text): return text
            case .cancelled: return nil
            }
        }
    }

    private struct Request {
        let settings: PeriodicUDPEchoSettings
        let resolver: ServerResolver?
        let runID: UUID?
        let generation: UInt64
    }

    private final class Slot {
        var client: Socks5UDPClient?
        var identity = UUID()
        var cursor: Int?
        var blocked = false
        var retries = 0
        var retryAt: UInt64?
        var nextRound: UInt64?
        var sent = false
        var error: String?
    }

    private let queue = DispatchQueue(label: "background.udp-echo.network", qos: .utility)
    private let admission = Socks5UDPClient.Admission()
    private let ingress = NSLock()
    private var latest = PeriodicUDPEchoSettings()
    private var resolver: ServerResolver?
    private var runID: UUID?
    private var constantServer: Socks5UDPClient.Configuration?
    private var pending: Request?
    private var queued = false
    private var closed = false

    private var timer: DispatchSourceTimer!
    private var current: Request?
    private var plan: Plan?
    private var server: Socks5UDPClient.Configuration?
    private var slots = [Slot(), Slot()]
    private var prepareAt: UInt64?
    private var observer: IOObserver?
    private let prepareObserver: (@Sendable () -> IOObserver?)?
    private let onState: @Sendable (State) -> Void
    private var shown: State?
    private var pumpQueued = false
    private var driving = false
    private var nextSlot = 0
    private static let payload: [UInt8] = [0]
    private static let second: UInt64 = 1_000_000_000

    init(prepareObserver: (@Sendable () -> IOObserver?)? = nil,
         onState: @escaping @Sendable (State) -> Void) {
        self.prepareObserver = prepareObserver
        self.onState = onState
        timer = DispatchSource.makeTimerSource(flags: .strict, queue: queue)
        timer.setEventHandler { [weak self] in self?.drive() }
        timer.schedule(deadline: .distantFuture)
        timer.resume()
    }

    deinit {
        _ = admission.begin(enabled: false)
        timer.cancel()
        let clients = slots.compactMap(\.client)
        queue.async { clients.forEach { $0.stop() } }
    }

    func isCurrent(_ generation: UInt64) -> Bool { admission.isCurrent(generation) }

    /// The admission generation changes synchronously, before any queued parsing.
    func update(_ settings: PeriodicUDPEchoSettings) {
        enqueue {
            latest = settings
            return true
        }
    }

    func setServer(_ configuration: Socks5UDPClient.Configuration?, runID: UUID?) {
        enqueue {
            guard self.runID != runID || constantServer != configuration ||
                (resolver == nil) != (configuration == nil) else { return false }
            constantServer = configuration
            self.runID = configuration == nil ? nil : runID
            if let configuration { resolver = { configuration } }
            else { resolver = nil }
            return true
        }
    }

    func setServer(resolve: ServerResolver?, runID: UUID?) {
        enqueue {
            guard self.runID != runID || (resolver == nil) != (resolve == nil) else { return false }
            constantServer = nil
            self.runID = resolve == nil ? nil : runID
            resolver = resolve
            return true
        }
    }

    func shutdown() {
        ingress.lock()
        guard !closed else { ingress.unlock(); return }
        closed = true
        pending = nil
        _ = admission.begin(enabled: false)
        ingress.unlock()
        queue.async {
            self.timer.cancel()
            self.closeClients()
            self.current = nil
            self.plan = nil
            self.observer = nil
        }
    }

    private func enqueue(_ change: () -> Bool) {
        ingress.lock()
        guard !closed else { ingress.unlock(); return }
        guard change() else { ingress.unlock(); return }
        let generation = admission.begin(enabled: latest.enabled)
        pending = Request(settings: latest, resolver: resolver, runID: runID, generation: generation)
        let start = !queued
        queued = true
        ingress.unlock()
        if start { queue.async { self.acceptLatest() } }
    }

    private func acceptLatest() {
        ingress.lock()
        let request = pending
        pending = nil
        queued = false
        ingress.unlock()
        guard let request, admission.isCurrent(request.generation) else { return }
        let changed = current?.settings != request.settings
        current = request
        closeClients()
        server = nil
        prepareAt = nil
        if changed {
            slots.forEach { $0.nextRound = nil }
        }
        guard request.settings.enabled else {
            plan = nil
            slots.forEach { $0.nextRound = nil }
            show("Off")
            armTimer()
            return
        }
        do {
            if changed || plan == nil {
                plan = try Self.parse(request.settings) { self.admission.isCurrent(request.generation) }
            }
        } catch InputError.cancelled {
            return
        } catch {
            plan = nil
            show(error.localizedDescription)
            armTimer()
            return
        }
        drive()
    }

    static func parse(_ settings: PeriodicUDPEchoSettings,
                      isCurrent: () -> Bool = { true }) throws -> Plan {
        let periodError = InputError.invalid("Period must be a positive integer number of milliseconds within the timer range.")
        let maximum = UInt64(Int64.max) / 1_000_000
        var milliseconds: UInt64 = 0
        var digitSeen = false
        var trailingSpace = false
        var scanned = 0
        for scalar in settings.period.unicodeScalars {
            if scanned & 1023 == 0, !isCurrent() { throw InputError.cancelled }
            scanned &+= 1
            if CharacterSet.whitespacesAndNewlines.contains(scalar) {
                if digitSeen { trailingSpace = true }
                continue
            }
            guard !trailingSpace, (48...57).contains(scalar.value) else { throw periodError }
            let digit = UInt64(scalar.value - 48)
            guard milliseconds <= (maximum - digit) / 10 else { throw periodError }
            milliseconds = milliseconds * 10 + digit
            digitSeen = true
        }
        guard digitSeen, milliseconds > 0 else { throw periodError }
        let raw = settings.destinations
        let scalars = raw.unicodeScalars
        var first: String.Index?
        var end: String.Index?
        var targets = [[Socks5UDPClient.Address](), [Socks5UDPClient.Address]()]
        var seen = Set<Socks5UDPClient.Address>()
        func finish() throws {
            guard let first, let end else { return }
            // Numeric IP grammar is at most 45 bytes; the input/file itself has no byte cap.
            guard raw.utf8.distance(from: first, to: end) <= 45,
                  let address = Socks5UDPClient.Address(host: String(raw[first..<end]), port: 7),
                  !address.requiresScope else {
                throw InputError.invalid("Enter numeric IPv4 or IPv6 addresses without interface scopes or link-local scopes.")
            }
            if seen.insert(address).inserted {
                guard seen.count <= 65_536 else {
                    throw InputError.invalid("At most 65,536 unique destination IP addresses are supported.")
                }
                targets[address.family == AF_INET ? 0 : 1].append(address)
            }
        }
        scanned = 0
        for index in scalars.indices {
            if scanned & 1023 == 0, !isCurrent() { throw InputError.cancelled }
            scanned &+= 1
            let scalar = scalars[index]
            if scalar == "," || CharacterSet.newlines.contains(scalar) {
                try finish()
                first = nil
                end = nil
            } else if !CharacterSet.whitespaces.contains(scalar) {
                if first == nil { first = index }
                end = scalars.index(after: index)
            }
        }
        try finish()
        guard isCurrent() else { throw InputError.cancelled }
        guard !seen.isEmpty else { throw InputError.invalid("Enter at least one destination IP address.") }
        return Plan(targets: targets, interval: milliseconds * 1_000_000)
    }

    private func closeClients() {
        for slot in slots {
            slot.identity = UUID()
            let client = slot.client
            slot.client = nil
            slot.cursor = nil
            slot.blocked = false
            slot.retries = 0
            slot.retryAt = nil
            slot.sent = false
            slot.error = nil
            client?.stop()
        }
    }

    private func drive() {
        guard !driving else { return }
        driving = true
        defer { driving = false; armTimer() }
        guard let current, admission.permits(current.generation), let plan else { return }
        let now = DispatchTime.now().uptimeNanoseconds
        if server == nil {
            guard current.runID != nil, let resolve = current.resolver else {
                show("Waiting for SOCKS5 server")
                return
            }
            if let prepareAt, now < prepareAt { return }
            guard let value = resolve() else {
                prepareAt = Self.after(now, Self.second)
                show("Waiting for SOCKS5 listener")
                return
            }
            guard admission.permits(current.generation) else { return }
            server = value
        }
        if observer == nil {
            if let prepareAt, now < prepareAt { return }
            if let prepareObserver {
                guard let value = prepareObserver() else {
                    prepareAt = Self.after(now, Self.second)
                    show("Waiting for traffic statistics")
                    return
                }
                observer = value
            } else {
                observer = { _, _, _ in }
            }
        }
        prepareAt = nil
        guard admission.permits(current.generation), let server, let observer else { return }
        for index in slots.indices where !plan.targets[index].isEmpty {
            let slot = slots[index]
            if let client = slot.client {
                client.advance(now: now)
            } else if slot.retryAt == nil || now >= slot.retryAt! {
                let identity = UUID()
                slot.identity = identity
                slot.retryAt = nil
                let client = Socks5UDPClient(queue: queue, admission: admission,
                                            generation: current.generation, onEvent: { [weak self] event in
                    self?.event(event, index: index, identity: identity, generation: current.generation)
                }, observe: observer)
                slot.client = client
                client.start(configuration: server, now: now)
            }
        }
        for slot in slots where slot.client?.isReady == true && slot.cursor == nil {
            if let deadline = slot.nextRound, now >= deadline {
                slot.cursor = 0
                requestPump()
            }
        }
        showProgress()
    }

    private func event(_ event: Socks5UDPClient.Event, index: Int, identity: UUID, generation: UInt64) {
        guard admission.permits(generation), slots[index].identity == identity else { return }
        let slot = slots[index]
        switch event {
        case .ready:
            slot.retries = 0
            slot.error = nil
            if slot.nextRound == nil {
                slot.cursor = 0
            }
            requestPump()
        case .writable:
            slot.blocked = false
            requestPump()
        case .failed(let message):
            let client = slot.client
            slot.client = nil
            slot.identity = UUID()
            slot.cursor = nil
            slot.blocked = false
            slot.sent = false
            slot.error = message
            let seconds = min(30, 1 << min(slot.retries, 5))
            slot.retries = min(slot.retries + 1, 5)
            slot.retryAt = Self.after(DispatchTime.now().uptimeNanoseconds, UInt64(seconds) * Self.second)
            client?.stop()
        }
        showProgress()
        armTimer()
    }

    private func requestPump() {
        guard !pumpQueued else { return }
        pumpQueued = true
        queue.async {
            self.pumpQueued = false
            self.pump()
        }
    }

    private func pump() {
        guard let current, admission.permits(current.generation), let plan else { return }
        var remaining = 256
        var idle = 0
        while remaining > 0 && idle < slots.count {
            let index = nextSlot
            nextSlot = (nextSlot + 1) % slots.count
            let slot = slots[index]
            guard !slot.blocked, let cursor = slot.cursor, let client = slot.client, client.isReady else {
                idle += 1
                continue
            }
            guard cursor < plan.targets[index].count else {
                slot.cursor = nil
                let now = DispatchTime.now().uptimeNanoseconds
                if let deadline = slot.nextRound, now >= deadline {
                    slot.nextRound = Self.after(now, plan.interval)
                }
                idle += 1
                continue
            }
            idle = 0
            remaining -= 1
            switch client.send(to: plan.targets[index][cursor], payload: Self.payload) {
            case .sent:
                slot.sent = true
                slot.cursor = cursor + 1
                if cursor == 0 { slot.nextRound = Self.after(DispatchTime.now().uptimeNanoseconds, plan.interval) }
            case .dropped(let code):
                slot.error = "UDP send error \(code); continuing at the configured period"
                slot.cursor = cursor + 1
                if cursor == 0 { slot.nextRound = Self.after(DispatchTime.now().uptimeNanoseconds, plan.interval) }
            case .blocked:
                slot.blocked = true
            case .closed:
                slot.cursor = nil
            }
            if !admission.permits(current.generation) { return }
        }
        showProgress()
        armTimer()
        if slots.contains(where: { $0.cursor != nil && !$0.blocked && $0.client?.isReady == true }) {
            requestPump()
        }
    }

    private func showProgress() {
        guard server != nil, observer != nil else { return }
        if slots.contains(where: { $0.sent && $0.client?.isReady == true }) {
            show("Sending UDP Echo")
        } else if let error = slots.compactMap(\.error).first {
            show(error)
        } else if slots.contains(where: { $0.client?.isReady == true }) {
            show("UDP Echo ready")
        } else {
            show("Connecting to SOCKS5 server")
        }
    }

    private func show(_ text: String) {
        guard let current, admission.isCurrent(current.generation) else { return }
        let value = State(generation: current.generation, text: text)
        guard shown != value else { return }
        shown = value
        onState(value)
    }

    private func armTimer() {
        guard let current, admission.permits(current.generation), plan != nil else {
            timer.schedule(deadline: .distantFuture)
            return
        }
        var deadline = prepareAt
        func include(_ value: UInt64?) {
            if let value { deadline = min(deadline ?? value, value) }
        }
        // A blocked/in-progress round is driven by readiness or one continuation,
        // not by repeatedly waking at the user's period while no new round can run.
        for slot in slots {
            if slot.client?.isReady == true && slot.cursor == nil { include(slot.nextRound) }
            include(slot.retryAt)
            include(slot.client?.setupDeadline)
        }
        if let deadline {
            timer.schedule(deadline: DispatchTime(uptimeNanoseconds: deadline), leeway: .milliseconds(1))
        } else {
            timer.schedule(deadline: .distantFuture)
        }
    }

    private static func after(_ now: UInt64, _ duration: UInt64) -> UInt64 {
        let (value, overflow) = now.addingReportingOverflow(duration)
        return overflow ? UInt64.max : value
    }
}
