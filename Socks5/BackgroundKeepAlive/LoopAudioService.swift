import Foundation
#if canImport(AVFAudio) && canImport(UIKit)
@preconcurrency import AVFAudio
import UIKit
#endif

/// Implementations are exclusively entered on the supplied I/O queue. Async
/// completions keep the single-flight gate closed until they actually arrive.
protocol LoopAudioEndpoint: AnyObject {
    func bind(_ relay: LoopAudioService.EndpointRelay)
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void)
    func receiveSession(_ receipt: LoopAudioService.SessionReceipt)
    func receiveDelegate(_ receipt: LoopAudioService.DelegateReceipt)
}

// Injected endpoints without system callbacks need only implement perform.
// The actual adapter binds its owner mailbox once before its first operation.
extension LoopAudioEndpoint {
    func bind(_ relay: LoopAudioService.EndpointRelay) {}
    func receiveSession(_ receipt: LoopAudioService.SessionReceipt) {}
    func receiveDelegate(_ receipt: LoopAudioService.DelegateReceipt) {}
}

/// Checked immutable API. The private queue owner confines all mutable service
/// state and the non-Sendable adapter; no AV object crosses this surface.
final class LoopAudioService: Sendable {
    enum Event: Sendable { case hint, available, interrupted, mediaLost, mediaReset, routeChanged, decoderFailed }
    enum Command: Sendable { case inspect, start(rebuild: Bool), stop }
    enum Phase: String, Sendable {
        case off = "Off"
        case queued = "Waiting for the audio worker"
        case protecting = "Requesting finite recovery execution time"
        case loading = "Loading silent WAV"
        case configuring = "Configuring audio session"
        case activating = "Activating audio session"
        case preparing = "Preparing silent WAV"
        case starting = "Starting silent WAV"
        case inspecting = "Checking playback"
        case playing = "Playing silent WAV continuously"
        case retry = "Waiting to resume audio"
        case stopping = "Stopping silent WAV"
        case deactivating = "Releasing audio session"
    }
    /// A fixed current boundary, not a per-call log. Grouped UI phases remain
    /// independent from the exact API whose invocation has not returned.
    enum Step: String, Sendable {
        case executionClaim = "execution-claim"
        case assetLookup = "asset"
        case assetRead = "asset-read"
        case session = "session"
        case categoryGet = "category-get"
        case modeGet = "mode-get"
        case optionsGet = "options-get"
        case categorySet = "category-set"
        case alerts = "alerts"
        case disconnect = "disconnect"
        case activate = "activate"
        case deactivate = "deactivate"
        case playerCreate = "player-init"
        case loops = "loops"
        case delegate = "delegate"
        case prepare = "prepare"
        case play = "play"
        case stop = "stop"
        case playingGet = "playing-get"
        case positionGet = "position-get"
        case clockGet = "clock-get"
        case durationGet = "duration-get"
        case rateEnabledGet = "rate-enabled-get"
        case rateGet = "rate-get"
        case bufferGet = "buffer-get"
    }

    struct State: Sendable, Equatable {
        var text = "Off"
        var detail = ""
        var health = PlaybackProgressMonitor.Health.inconclusive
    }
    struct Reply: Sendable {
        enum KnownFailure: Sendable { case stopped, configurationMismatch }
        var sample: PlaybackProgressMonitor.Sample?
        var knownFailure: KnownFailure?
        var error: String?
        var superseded = false
        var invalidAsset = false
    }
    struct Context: Sendable {
        let id: UInt64
        let epoch: UInt64
        let mayStart: @Sendable () -> Bool
        let phase: @Sendable (Phase) -> Void
        let step: @Sendable (Step, Bool) -> Void

        init(id: UInt64, epoch: UInt64, mayStart: @escaping @Sendable () -> Bool,
             phase: @escaping @Sendable (Phase) -> Void,
             step: @escaping @Sendable (Step, Bool) -> Void = { _, _ in }) {
            self.id = id
            self.epoch = epoch
            self.mayStart = mayStart
            self.phase = phase
            self.step = step
        }
    }
    struct Policy: Sendable {
        var interval = 0.5
        var warning = 2.0
        var stalled = 10.0
        /// Requires a device-specific quantization/false-positive acceptance run.
        var speculativeRecoveryCertified = false
    }
    struct Diagnostics: Sendable {
        let phase: Phase
        let operation: UInt64?
        let queuedAt: Double?
        let enteredAt: Double?
        let phaseAt: Double?
        let resultAvailableAt: Double?
        let resultConsumedAt: Double?
        let step: Step?
        let stepEnteredAt: Double?
        let stepReturnedAt: Double?
        let sessionResultAvailableAt: Double?
        let sessionResultConsumedAt: Double?
        let completedOperations: UInt64
        let maximumOutstanding: Int
        let scheduledIngress: Int
        let timerActive: Bool
        let records: [String]
    }
    typealias Observer = @MainActor @Sendable (State) -> Void
    typealias Factory = @Sendable (DispatchQueue, @escaping @Sendable (Event) -> Void) -> any LoopAudioEndpoint

    /// System callbacks carry immutable receipts, never player/session objects.
    struct SessionReceipt: Sendable {
        let operation: UInt64
        let success: Bool
        let error: Error?
    }
    struct DelegateReceipt: Sendable {
        let generation: UInt64
        let decoder: Bool
    }
    struct EndpointRelay: Sendable {
        let session: @Sendable (SessionReceipt) -> Void
        let delegate: @Sendable (DelegateReceipt) -> Void
        let generation: @Sendable (UInt64?) -> Void
    }

    private let queueOwner: LoopAudioQueueOwner

    init(policy: Policy = Policy(),
         leaseProvider: @escaping @Sendable () -> RecoveryExecutionLease.Provider = { .unavailable },
         endpointFactory: @escaping Factory) {
        queueOwner = LoopAudioQueueOwner(policy: policy, leaseProvider: leaseProvider,
                                         endpointFactory: endpointFactory)
    }

    #if canImport(AVFAudio) && canImport(UIKit)
    @MainActor static let shared: LoopAudioService = {
        let provider = RecoveryExecutionLease.Provider.application(UIApplication.shared)
        let service = LoopAudioService(leaseProvider: { provider }) { queue, event in
            AudioEndpoint(queue: queue, event: event)
        }
        // Observe on the posting thread and coalesce immediately. A blocked main
        // run loop must not accumulate an unbounded receive(on:) audio backlog.
        service.observeAudioNotifications(BackgroundKeepAlive.audioNotifications,
                                          normalize: { BackgroundKeepAlive.audioEventValue($0) })
        return service
    }()
    #endif

    @MainActor func observeAudioNotifications(_ names: [Notification.Name],
                                             normalize: @escaping @Sendable (Notification) -> Event) {
        queueOwner.observeAudioNotifications(names, normalize: normalize)
    }
    @discardableResult func register(_ observer: @escaping Observer) -> UInt64 {
        queueOwner.register(observer)
    }
    func setEnabled(_ enabled: Bool, owner: UInt64, explicit: Bool = true) {
        queueOwner.setEnabled(enabled, owner: owner, explicit: explicit)
    }
    func unregister(_ owner: UInt64) { queueOwner.unregister(owner) }
    func notify(_ event: Event) { queueOwner.notify(event) }
    func diagnostics(_ completion: @escaping @Sendable (Diagnostics) -> Void) {
        queueOwner.diagnostics(completion)
    }
}

/// The module's single private unchecked boundary. It owns both queues and
/// enforces control-only policy, I/O-only endpoint access, and short lock-only
/// ingress/publication/receipt metadata. No external call runs under that lock.
private final class LoopAudioQueueOwner: @unchecked Sendable {
    typealias Event = LoopAudioService.Event
    typealias Command = LoopAudioService.Command
    typealias Phase = LoopAudioService.Phase
    typealias Step = LoopAudioService.Step
    typealias State = LoopAudioService.State
    typealias Reply = LoopAudioService.Reply
    typealias Context = LoopAudioService.Context
    typealias Policy = LoopAudioService.Policy
    typealias Diagnostics = LoopAudioService.Diagnostics
    typealias Observer = LoopAudioService.Observer
    typealias Factory = LoopAudioService.Factory
    typealias SessionReceipt = LoopAudioService.SessionReceipt
    typealias DelegateReceipt = LoopAudioService.DelegateReceipt
    typealias EndpointRelay = LoopAudioService.EndpointRelay

    private struct Owner { var enabled: Bool; let observer: Observer }
    private struct Ticket: Sendable {
        var on = false
        var revision: UInt64 = 0
        var stop: UInt64 = 0
        var epoch: UInt64 = 0
    }
    private struct Inbox {
        var queued = false
        var explicit = false
        var hint = false
        var available = false
        var invalidated = false
        var route = false
    }
    private struct Work: Sendable {
        let id: UInt64
        let command: Command
        let ticket: Ticket
        let queuedAt: Double
    }
    private struct Timing {
        var id: UInt64 = 0
        var phase: Phase = .off
        var enteredAt: Double?
        var phaseAt: Double?
        var resultAvailableAt: Double?
        var resultConsumedAt: Double?
        var step: Step?
        var stepEnteredAt: Double?
        var stepReturnedAt: Double?
        var sessionResultAvailableAt: Double?
        var sessionResultConsumedAt: Double?
    }

    private let lock = NSLock()
    private var owners: [UInt64: Owner] = [:]
    private var ownerSequence: UInt64 = 0
    private var ticket = Ticket()
    private var inbox = Inbox()
    private var exhausted = false
    private var timing = Timing()
    private var published = State()
    private var publishedTicket = Ticket()
    private var deliveryQueued = false
    private let control = DispatchQueue(label: "Socks5.loop-audio.control")
    private let io = DispatchQueue(label: "Socks5.loop-audio.io", qos: .userInitiated)
    private let ioIdentity = DispatchSpecificKey<Bool>()
    private let factory: Factory
    private let leaseProvider: RecoveryExecutionLease.Provider
    private let policy: Policy
    // I/O queue only; the mutable endpoint never leaves that queue.
    private var endpoint: (any LoopAudioEndpoint)?
    // Control queue only.
    private var current = Ticket()
    private var work: Work?
    private var sequence: UInt64 = 0
    private var completed: UInt64 = 0
    private var outstanding = 0
    private var peakOutstanding = 0
    private var timerSequence: UInt64 = 0
    private var timer: DispatchSourceTimer?
    private var timerDeadline: Double?
    private var timerOperation: UInt64?
    private var timerRecovery = false
    private var lastState = State()
    private var lastPublishedRevision: UInt64?
    private var playing = false
    private var rebuild = false
    private var releaseBarrier = false
    private var releaseFailed = false
    private var assetBlocked = false
    private var retryAt = 0.0
    private var inspectAt = 0.0
    private var episode = false
    private var expedited = false
    private var lease: RecoveryExecutionLease?
    private var monitor = PlaybackProgressMonitor()
    private var records: [String] = []
    private var notificationTokens: [NSObjectProtocol] = []
    // Callback ingress: a fixed session slot, fixed delegate slot and one drain.
    // Only immutable receipts cross into I/O; the adapter is never captured.
    private var ioSessionReceipt: SessionReceipt?
    private var ioReceiptOperation: UInt64?
    private var ioDelegateGeneration: UInt64?
    private var ioDelegateReceipt: DelegateReceipt?
    private var ioDeliveryQueued = false

    init(policy: Policy = Policy(),
         leaseProvider: @escaping @Sendable () -> RecoveryExecutionLease.Provider = { .unavailable },
         endpointFactory: @escaping Factory) {
        precondition(policy.interval > 0 && policy.warning > 0 && policy.stalled >= policy.warning)
        self.policy = policy
        self.leaseProvider = leaseProvider().serializingEnds()
        factory = endpointFactory
        io.setSpecific(key: ioIdentity, value: true)
    }

    /// Root setup only. Repeated view restoration does not add subscriptions.
    /// NotificationCenter invokes this mailbox on the posting thread.
    @MainActor func observeAudioNotifications(_ names: [Notification.Name],
                                             normalize: @escaping @Sendable (Notification) -> Event) {
        guard notificationTokens.isEmpty else { return }
        notificationTokens = names.map { name in
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: nil) { [weak self] note in
                self?.notify(normalize(note))
            }
        }
    }

    deinit {
        for token in notificationTokens { NotificationCenter.default.removeObserver(token) }
    }

    @discardableResult
    func register(_ observer: @escaping Observer) -> UInt64 {
        lock.lock()
        guard ownerSequence < UInt64.max, !exhausted else { lock.unlock(); return 0 }
        ownerSequence += 1
        let id = ownerSequence
        owners[id] = Owner(enabled: false, observer: observer)
        lock.unlock()
        return id
    }

    /// Synchronous intent acceptance; no main-to-worker wait and no disk access.
    func setEnabled(_ enabled: Bool, owner: UInt64, explicit: Bool = true) {
        lock.lock()
        guard var entry = owners[owner] else { lock.unlock(); return }
        let old = ticket.on
        entry.enabled = enabled
        owners[owner] = entry
        ticket.on = !exhausted && owners.values.contains(where: \.enabled)
        if old && !ticket.on { bumpStop() }
        bumpRevision()
        inbox.explicit = inbox.explicit || (explicit && enabled)
        let schedule = enqueueLocked()
        lock.unlock()
        if schedule { control.async { self.drain() } }
    }

    func unregister(_ owner: UInt64) {
        lock.lock()
        guard owners.removeValue(forKey: owner) != nil else { lock.unlock(); return }
        let old = ticket.on
        ticket.on = !exhausted && owners.values.contains(where: \.enabled)
        if old && !ticket.on { bumpStop() }
        bumpRevision()
        // Owner cleanup preserves any already accepted explicit On signal.
        let schedule = enqueueLocked()
        lock.unlock()
        if schedule { control.async { self.drain() } }
    }

    func notify(_ event: Event) {
        lock.lock()
        guard ticket.on, !exhausted else { lock.unlock(); return }
        switch event {
        case .hint: inbox.hint = true
        case .available: inbox.available = true
        case .routeChanged: inbox.hint = true; inbox.route = true
        case .interrupted, .decoderFailed, .mediaLost, .mediaReset:
            if !inbox.invalidated { bumpEpoch() }
            inbox.invalidated = true
            if case .mediaReset = event { inbox.available = true }
        }
        let schedule = enqueueLocked()
        lock.unlock()
        if schedule { control.async { self.drain() } }
    }

    // Called only with lock held. Saturation is fail-closed, never ID reuse.
    private func bumpStop() {
        if ticket.stop == UInt64.max { exhausted = true; ticket.on = false }
        else { ticket.stop += 1 }
    }
    private func bumpRevision() {
        if ticket.revision == UInt64.max { exhausted = true; ticket.on = false }
        else { ticket.revision += 1 }
    }
    private func bumpEpoch() {
        if ticket.epoch == UInt64.max { exhausted = true; ticket.on = false }
        else { ticket.epoch += 1 }
    }
    private func enqueueLocked() -> Bool {
        guard !inbox.queued else { return false }
        inbox.queued = true
        return true
    }
    private func latest() -> Ticket {
        lock.lock(); defer { lock.unlock() }
        return ticket
    }
    private func valid(_ input: Ticket) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return !exhausted && ticket.on && ticket.stop == input.stop && ticket.epoch == input.epoch
    }
    private func mayRequestClaim(_ input: Ticket) -> Bool {
        lock.lock(); defer { lock.unlock() }
        // A resource reset cancels this AV generation, not the surviving
        // On/Stop recovery episode. Do not consume its sole protection request
        // merely because a newer resource generation is awaiting recovery.
        return !exhausted && ticket.on && ticket.stop == input.stop
    }
    private static var now: Double { ProcessInfo.processInfo.systemUptime }

    /// Every control-lane observation preserves stop/resource transitions. A
    /// timer or admission check must not consume a pending Off-On barrier.
    private func adopt(_ next: Ticket) {
        if next.stop != current.stop { releaseBarrier = true }
        if next.epoch != current.epoch {
            rebuild = true
            playing = false
            monitor.knownFailure(now: Self.now)
        }
        current = next
    }

    private func drain() {
        dispatchPrecondition(condition: .onQueue(control))
        lock.lock()
        let events = inbox
        inbox = Inbox()
        let next = ticket
        let overflow = exhausted
        lock.unlock()
        adopt(next)
        let now = Self.now
        if events.route { monitor.reset(now: now) }
        if events.invalidated {
            rebuild = true
            playing = false
            monitor.knownFailure(now: now)
            if !episode { retryAt = now } // First invalidation may recover immediately.
        }
        if events.explicit || events.available {
            assetBlocked = false
            if events.explicit {
                retryAt = 0
            } else if !expedited {
                retryAt = 0
                expedited = true
            }
        }
        if !current.on || overflow {
            cancelTimer()
            finishLease()
            if work != nil {
                publish(State(text: "Off \u{2014} waiting for system completion"))
            } else if releaseBarrier || playing || releaseFailed {
                begin(.stop)
            } else {
                publish(State(text: overflow ? "Off \u{2014} audio identifier limit reached" : "Off"))
            }
            return
        }
        if work != nil { return }
        reconcile(inspect: (events.hint || events.explicit || events.available) && playing && !rebuild)
    }

    private func reconcile(inspect: Bool = false) {
        guard work == nil else { return }
        adopt(latest())
        if !current.on {
            cancelTimer(); finishLease()
            if releaseBarrier || playing || releaseFailed { begin(.stop) }
            return
        }
        if releaseBarrier { begin(.stop); return }
        if assetBlocked { return }
        let remaining = retryAt - Self.now
        if remaining > 0 { schedule(at: retryAt); return }
        if playing && !rebuild {
            let remaining = inspectAt - Self.now
            if inspect && remaining <= 0 { begin(.inspect) }
            else { schedule(at: max(Self.now + 0.001, inspectAt)) }
        } else {
            begin(.start(rebuild: rebuild))
        }
    }

    private func begin(_ requested: Command) {
        guard work == nil else { return }
        guard sequence < UInt64.max else {
            cancelTimer(); finishLease()
            publish(State(text: "Waiting \u{2014} audio operation identifier limit reached"))
            return
        }
        adopt(latest())
        let command: Command
        switch requested {
        case .inspect where rebuild: command = .start(rebuild: true)
        case .start(let recreate): command = .start(rebuild: recreate || rebuild)
        default: command = requested
        }
        if releaseBarrier {
            if case .stop = command {} else { begin(.stop); return }
        }
        let input = current
        if case .stop = command {} else if !input.on { drain(); return }
        sequence += 1
        let job = Work(id: sequence, command: command, ticket: input, queuedAt: Self.now)
        work = job
        outstanding += 1
        peakOutstanding = max(peakOutstanding, outstanding)
        precondition(outstanding == 1)
        lock.lock()
        // This start incorporates the pending invalidation into its resources.
        // A later event must revoke it even if an earlier drain is still queued.
        if case .start = command, ticket.on, ticket.stop == input.stop, ticket.epoch == input.epoch {
            inbox.invalidated = false
        }
        timing = Timing(id: job.id, phase: .queued)
        lock.unlock()
        switch command {
        case .start:
            if !episode {
                episode = true
                let claim = makeLease()
                lease = claim
                // Request on I/O: a slow provider cannot occupy control.
            }
            publish(State(text: Phase.activating.rawValue))
        case .stop:
            publish(State(text: "Off \u{2014} stopping"))
        case .inspect: break
        }
        if case .inspect = command {} else { record("Begin \(job.id): \(String(describing: command))") }
        if input.on { schedule(after: policy.interval) }
        let executionClaim = lease
        io.async { [self] in
            self.mark(job.id, .queued, entered: true)
            if let executionClaim {
                self.mark(job.id, .protecting)
                self.markStep(job.id, .executionClaim, returned: false)
                let admitted = executionClaim.start(mayIssue: { [weak self] in self?.mayRequestClaim(job.ticket) == true }) { [self] in
                    // This means the actual provider request returned (or was
                    // skipped before entry), not that an execution grant arrived.
                    self.markStep(job.id, .executionClaim, returned: true)
                    if DispatchQueue.getSpecific(key: self.ioIdentity) == true {
                        self.perform(job)
                    } else {
                        self.io.async { self.perform(job) }
                    }
                }
                if !admitted {
                    // Single flight cannot normally encounter a second pending
                    // start. Preserve the outstanding gate instead of inventing
                    // a request return or entering unprotected preparation.
                    self.control.async { self.record("Finite execution request is already pending") }
                }
            } else {
                self.perform(job)
            }
        }
    }

    private func perform(_ job: Work) {
        dispatchPrecondition(condition: .onQueue(io))
        let input = job.ticket
        let command = job.command
        if self.endpoint == nil {
            self.endpoint = self.factory(self.io) { [weak self] in self?.notify($0) }
            self.endpoint?.bind(EndpointRelay(
                session: { [weak self] in self?.acceptSession($0) },
                delegate: { [weak self] in self?.acceptDelegate($0) },
                generation: { [weak self] in self?.setDelegateGeneration($0) }))
        }
        let context = Context(id: job.id, epoch: input.epoch,
                              mayStart: { [weak self] in self?.valid(input) == true },
                              phase: { [weak self] in self?.mark(job.id, $0) },
                              step: { [weak self] in self?.markStep(job.id, $0, returned: $1) })
        self.endpoint?.perform(command, context: context) { [self] reply in
            lock.lock()
            guard timing.id == job.id, timing.resultAvailableAt == nil else { lock.unlock(); return }
            timing.resultAvailableAt = Self.now
            lock.unlock()
            control.async { self.finish(job, reply) }
        }
    }

    private func acceptSession(_ receipt: SessionReceipt) {
        lock.lock()
        guard timing.id == receipt.operation, timing.resultAvailableAt == nil,
              ioReceiptOperation != receipt.operation else { lock.unlock(); return }
        ioReceiptOperation = receipt.operation
        timing.sessionResultAvailableAt = Self.now
        ioSessionReceipt = receipt
        let enqueue = enqueueIOLocked()
        lock.unlock()
        if enqueue { io.async { self.drainIOReceipts() } }
    }
    private func acceptDelegate(_ receipt: DelegateReceipt) {
        lock.lock()
        guard ioDelegateGeneration == receipt.generation else { lock.unlock(); return }
        ioDelegateReceipt = DelegateReceipt(generation: receipt.generation,
            decoder: receipt.decoder || (ioDelegateReceipt?.decoder ?? false))
        let enqueue = enqueueIOLocked()
        lock.unlock()
        if enqueue { io.async { self.drainIOReceipts() } }
    }
    private func setDelegateGeneration(_ generation: UInt64?) {
        dispatchPrecondition(condition: .onQueue(io))
        lock.lock()
        ioDelegateGeneration = generation
        ioDelegateReceipt = nil
        // An already queued drain still owns its queued bit until it starts.
        lock.unlock()
    }
    private func enqueueIOLocked() -> Bool {
        guard !ioDeliveryQueued else { return false }
        ioDeliveryQueued = true
        return true
    }
    private func drainIOReceipts() {
        dispatchPrecondition(condition: .onQueue(io))
        lock.lock()
        let session = ioSessionReceipt
        let delegate = ioDelegateReceipt
        ioSessionReceipt = nil
        ioDelegateReceipt = nil
        ioDeliveryQueued = false
        lock.unlock()
        if let session {
            lock.lock()
            if timing.id == session.operation { timing.sessionResultConsumedAt = Self.now }
            lock.unlock()
            endpoint?.receiveSession(session)
        }
        if let delegate { endpoint?.receiveDelegate(delegate) }
    }

    private func mark(_ id: UInt64, _ phase: Phase, entered: Bool = false) {
        lock.lock(); defer { lock.unlock() }
        guard timing.id == id else { return }
        timing.phase = phase
        timing.phaseAt = Self.now
        if entered { timing.enteredAt = timing.phaseAt }
    }

    private func markStep(_ id: UInt64, _ step: Step, returned: Bool) {
        lock.lock(); defer { lock.unlock() }
        guard timing.id == id else { return }
        if returned {
            guard timing.step == step, timing.stepReturnedAt == nil else { return }
            timing.stepReturnedAt = Self.now
        } else {
            timing.step = step
            timing.stepEnteredAt = Self.now
            timing.stepReturnedAt = nil
        }
    }

    private func finish(_ job: Work, _ reply: Reply) {
        guard work?.id == job.id else { return } // Duplicate/stale completion.
        work = nil
        outstanding -= 1
        precondition(outstanding == 0)
        if completed < UInt64.max { completed += 1 }
        lock.lock()
        timing.phase = .off
        timing.resultConsumedAt = Self.now
        let returnedAt = timing.resultAvailableAt ?? timing.resultConsumedAt!
        lock.unlock()
        adopt(latest())
        if current.stop != job.ticket.stop { releaseBarrier = true }
        if current.epoch != job.ticket.epoch { rebuild = true }
        if case .inspect = job.command, reply.error == nil {}
        else { record("End \(job.id): \(reply.error ?? (reply.superseded ? "superseded" : "accepted"))") }
        switch job.command {
        case .stop:
            playing = false
            releaseBarrier = false // The actual release returned, even on isBusy/error.
            releaseFailed = reply.error != nil
            rebuild = true
            finishLease()
            if !current.on {
                cancelTimer()
                episode = false
                expedited = false
                publish(State(text: reply.error.map { "Off; session release failed: \($0)" } ?? "Off"))
                return
            }
            retryAt = 0
            episode = false
            expedited = false
        case .start, .inspect:
            if !current.on || releaseBarrier {
                playing = reply.sample?.playing == true
                releaseBarrier = true
                reconcile()
                return
            }
            if reply.superseded || current.epoch != job.ticket.epoch {
                playing = false
                rebuild = true
                retryAt = returnedAt + policy.interval
                publish(State(text: Phase.retry.rawValue, detail: "Audio resources changed during recovery"))
            } else if let sample = reply.sample, sample.playing && sample.configured {
                playing = true
                rebuild = false
                releaseFailed = false
                assetBlocked = false
                retryAt = 0
                finishLease()
                // The same accepted healthy result ends protection and its episode.
                // A real relapse before the next inspection needs a new recovery claim.
                episode = false
                expedited = false
                let result = monitor.inspect(sample, speculativeRecoveryCertified: policy.speculativeRecoveryCertified)
                if result.mayRebuild {
                    playing = false; rebuild = true
                    reconcile()
                    return
                }
                publish(State(text: Phase.playing.rawValue, detail: result.health.rawValue, health: result.health))
                inspectAt = Self.now + result.nextDelay
                schedule(after: result.nextDelay)
                return
            } else {
                playing = false
                switch reply.knownFailure {
                case .stopped: rebuild = reply.error != nil
                case .configurationMismatch: rebuild = true
                case nil: rebuild = reply.error != nil || reply.sample?.configured != true
                }
                assetBlocked = reply.invalidAsset
                // Keep the actual completed-failure deadline. A delayed control
                // consumer must not add another full cooldown after it elapsed.
                retryAt = returnedAt + policy.interval
                // A first observed stop is not a failed recovery attempt.
                // Start that new episode now; actual failed starts keep pacing.
                if case .inspect = job.command, !episode, reply.error == nil, !reply.invalidAsset,
                   reply.knownFailure != nil || (reply.sample.map {
                       $0.epoch == job.ticket.epoch && (!$0.playing || !$0.configured)
                   } ?? false) {
                    retryAt = returnedAt
                }
                monitor.knownFailure(now: Self.now)
                publish(State(text: "Waiting to resume: \(String((reply.error ?? "Audio playback stopped").prefix(256)))"))
                if assetBlocked { cancelTimer(); finishLease(); return }
            }
        }
        reconcile()
    }

    private func schedule(after delay: Double) {
        schedule(at: Self.now + max(0.001, delay))
    }
    private func schedule(at requestedDeadline: Double) {
        guard latest().on else { cancelTimer(); return }
        let recovery = !playing
        var deadline = requestedDeadline
        // Within the same work/wait context, preserve an earlier deadline even
        // when recovery changes the source flags. Completed/replaced work may
        // legitimately use a new watchdog target.
        if let armed = timerDeadline, timerOperation == work?.id, armed <= deadline {
            if timerRecovery == recovery { return }
            deadline = armed
        }
        if timer != nil && timerRecovery != recovery { cancelTimer() }
        if timer == nil {
            guard timerSequence < UInt64.max else {
                publish(State(text: "Waiting \u{2014} audio timer identifier limit reached"))
                finishLease()
                return
            }
            timerSequence += 1
            let epoch = timerSequence
            let source = DispatchSource.makeTimerSource(flags: recovery ? .strict : [], queue: control)
            source.setEventHandler { [weak self] in
                guard let self, timer != nil, timerSequence == epoch else { return }
                timerDeadline = nil
                timerOperation = nil
                tick()
            }
            timer = source
            timerRecovery = recovery
            source.resume()
        }
        timerDeadline = deadline
        timerOperation = work?.id
        timer?.schedule(deadline: .now() + max(0.001, deadline - Self.now), leeway: .milliseconds(1))
    }
    private func tick() {
        adopt(latest())
        guard current.on else { drain(); return }
        if let job = work {
            lock.lock(); let observed = timing; lock.unlock()
            let elapsed = Self.now - (observed.phaseAt ?? job.queuedAt)
            if elapsed >= policy.warning {
                let waiting = elapsed >= policy.stalled ? "Waiting for system audio completion" : "Audio transition delayed"
                publish(State(text: waiting, detail: observed.phase.rawValue))
            }
            schedule(after: policy.interval)
        } else {
            reconcile(inspect: true)
        }
    }
    private func cancelTimer() {
        timer?.cancel()
        timer = nil
        timerDeadline = nil
        timerOperation = nil
        timerRecovery = false
    }
    private func makeLease() -> RecoveryExecutionLease {
        RecoveryExecutionLease(provider: leaseProvider, granted: { [weak self] granted in
            self?.control.async { [weak self] in
                self?.record(granted ? "Finite execution claim granted" : "Finite execution claim unavailable")
            }
        }, expired: { [weak self] in
            self?.control.async { [weak self] in self?.record("Execution claim expired") }
        })
    }
    private func finishLease() { lease?.finish(); lease = nil }
    private func record(_ message: String) {
        if records.count == 64 { records.removeFirst() }
        records.append(String(message.prefix(384)))
    }
    private func publish(_ state: State) {
        let revision = current.revision
        guard state != lastState || lastPublishedRevision != revision else { return }
        lastState = state
        lastPublishedRevision = revision
        lock.lock()
        published = state
        publishedTicket = current
        let enqueue = !deliveryQueued
        deliveryQueued = true
        lock.unlock()
        guard enqueue else { return }
        DispatchQueue.main.async { [self] in
            MainActor.assumeIsolated {
                lock.lock()
                let state = published
                let stateTicket = publishedTicket
                let ids = Array(owners.keys)
                deliveryQueued = false
                lock.unlock()
                for id in ids {
                    lock.lock()
                    let candidate = owners[id]
                    let on = ticket.on
                    let stale = stateTicket.stop != ticket.stop || stateTicket.epoch != ticket.epoch
                    lock.unlock()
                    guard let entry = candidate else { continue }
                    // An Off accepted after publication must never display late Playing.
                    let onState = stale && state.text == Phase.playing.rawValue ? State(text: Phase.queued.rawValue) : state
                    let visible = entry.enabled && on ? onState :
                        (on ? State(text: "Off", detail: "Shared playback is requested by another owner") :
                        State(text: state.text.hasPrefix("Off") ? state.text : "Off \u{2014} stopping"))
                    entry.observer(visible)
                }
            }
        }
    }

    /// Asynchronous inspection only; never block UI or AV I/O to obtain diagnostics.
    func diagnostics(_ completion: @escaping @Sendable (Diagnostics) -> Void) {
        control.async {
            self.lock.lock()
            let timing = self.timing
            let queued = self.inbox.queued ? 1 : 0
            self.lock.unlock()
            completion(Diagnostics(phase: timing.phase, operation: self.work?.id,
                queuedAt: self.work?.queuedAt, enteredAt: timing.enteredAt, phaseAt: timing.phaseAt,
                resultAvailableAt: timing.resultAvailableAt, resultConsumedAt: timing.resultConsumedAt,
                step: timing.step, stepEnteredAt: timing.stepEnteredAt, stepReturnedAt: timing.stepReturnedAt,
                sessionResultAvailableAt: timing.sessionResultAvailableAt,
                sessionResultConsumedAt: timing.sessionResultConsumedAt,
                completedOperations: self.completed, maximumOutstanding: self.peakOutstanding,
                scheduledIngress: queued, timerActive: self.timer != nil, records: self.records))
        }
    }
}

#if canImport(AVFAudio) && canImport(UIKit)
/// Only the service I/O queue touches player/session. Delegate callbacks carry
/// an immutable generation back to that queue without retaining any AV object.
private nonisolated final class AudioEndpoint: NSObject, LoopAudioEndpoint {
    private let queue: DispatchQueue
    private let event: @Sendable (LoopAudioService.Event) -> Void
    private var player: AVAudioPlayer?
    private var data: Data?
    private var generation: UInt64 = 0
    private var activationPending: UInt64?
    private var sessionUsed = false
    private var relay: LoopAudioService.EndpointRelay?
    private var delegate: DelegateProxy?
    // I/O-only plain closure. It retains the operation's service completion
    // until the actual receipt, then is cleared before any callback/reentry.
    private var activationCompletion: ((Bool, String?) -> Void)?

    private nonisolated final class DelegateProxy: NSObject, AVAudioPlayerDelegate, Sendable {
        let generation: UInt64
        let event: @Sendable (LoopAudioService.DelegateReceipt) -> Void
        init(generation: UInt64, event: @escaping @Sendable (LoopAudioService.DelegateReceipt) -> Void) {
            self.generation = generation
            self.event = event
            super.init()
        }
        nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
            event(.init(generation: generation, decoder: false))
        }
        nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
            event(.init(generation: generation, decoder: true))
        }
    }

    init(queue: DispatchQueue, event: @escaping @Sendable (LoopAudioService.Event) -> Void) {
        self.queue = queue
        self.event = event
    }
    func bind(_ relay: LoopAudioService.EndpointRelay) {
        dispatchPrecondition(condition: .onQueue(queue))
        precondition(self.relay == nil, "Audio endpoint relay can bind only once")
        self.relay = relay
    }
    private func error(_ message: String) -> NSError {
        NSError(domain: "LoopAudio", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
    @discardableResult
    private func atStep<Value>(_ step: LoopAudioService.Step, context: LoopAudioService.Context,
                               _ body: () throws -> Value) rethrows -> Value {
        context.step(step, false)
        defer { context.step(step, true) }
        return try body()
    }
    private func matches(_ session: AVAudioSession, context: LoopAudioService.Context) -> Bool? {
        guard context.mayStart() else { return nil }
        let category = atStep(.categoryGet, context: context) { session.category }
        guard context.mayStart() else { return nil }
        guard category == .playback else { return false }
        let mode = atStep(.modeGet, context: context) { session.mode }
        guard context.mayStart() else { return nil }
        guard mode == .default else { return false }
        let options = atStep(.optionsGet, context: context) { session.categoryOptions }
        guard context.mayStart() else { return nil }
        return options == [.mixWithOthers]
    }
    private func discard(_ context: LoopAudioService.Context) {
        context.phase(.stopping)
        relay?.generation(nil)
        delegate = nil
        if player != nil {
            atStep(.delegate, context: context) { player?.delegate = nil }
            atStep(.stop, context: context) { player?.stop() }
        }
        player = nil
    }
    private func snapshot(_ context: LoopAudioService.Context) -> LoopAudioService.Reply {
        guard let player, context.mayStart() else { return .init() }
        context.phase(.inspecting)
        let begin = ProcessInfo.processInfo.systemUptime
        let playing = atStep(.playingGet, context: context) { player.isPlaying }
        guard context.mayStart() else { return .init() }
        // A known stop starts recovery before any session or progress getter.
        // Configuration remains unobserved; start checks it under the recovery
        // claim and promotes a valid-player resume to a rebuild when required.
        if !playing { return .init(knownFailure: .stopped) }
        let session = atStep(.session, context: context) { AVAudioSession.sharedInstance() }
        guard context.mayStart() else { return .init() }
        guard let configured = matches(session, context: context) else { return .init() }
        if !configured { return .init(knownFailure: .configurationMismatch) }
        let position = atStep(.positionGet, context: context) { player.currentTime }
        guard context.mayStart() else { return .init() }
        let clock = atStep(.clockGet, context: context) { player.deviceCurrentTime }
        guard context.mayStart() else { return .init() }
        let duration = atStep(.durationGet, context: context) { player.duration }
        guard context.mayStart() else { return .init() }
        let enableRate = atStep(.rateEnabledGet, context: context) { player.enableRate }
        guard context.mayStart() else { return .init() }
        let rate = enableRate ? atStep(.rateGet, context: context) { Double(player.rate) } : 1
        guard context.mayStart() else { return .init() }
        let buffer = atStep(.bufferGet, context: context) { session.ioBufferDuration }
        guard context.mayStart() else { return .init() }
        return .init(sample: .init(generation: generation, epoch: context.epoch, playing: playing, configured: configured,
                     position: position, deviceTime: clock, duration: duration, rate: rate,
                     startedAt: begin, finishedAt: ProcessInfo.processInfo.systemUptime, bufferDuration: buffer))
    }

    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        dispatchPrecondition(condition: .onQueue(queue))
        switch command {
        case .inspect:
            guard context.mayStart() else { completion(.init(superseded: true)); return }
            completion(snapshot(context))
        case .stop:
            discard(context)
            guard sessionUsed else { completion(.init()); return }
            context.phase(.deactivating)
            changeSession(false, context: context) { [self] success, message in
                if success { sessionUsed = false }
                completion(.init(error: message))
            }
        case .start(let rebuild):
            if rebuild { discard(context) }
            guard context.mayStart() else { completion(.init(superseded: true)); return }
            do {
                if data == nil {
                    context.phase(.loading)
                    guard let url = atStep(.assetLookup, context: context, {
                        Bundle.main.url(forResource: "Silence", withExtension: "wav")
                    }) else {
                        completion(.init(error: "Silence.wav is missing", invalidAsset: true)); return
                    }
                    guard context.mayStart() else { completion(.init(superseded: true)); return }
                    let bytes = try atStep(.assetRead, context: context) { try Data(contentsOf: url) }
                    // The original canonical 44-byte PCM header and all-zero frames.
                    let header: [UInt8] = [82,73,70,70,68,3,0,0,87,65,86,69,102,109,116,32,
                        16,0,0,0,1,0,1,0,64,31,0,0,128,62,0,0,2,0,16,0,100,97,116,97,32,3,0,0]
                    guard bytes.count == 844, Array(bytes.prefix(44)) == header,
                          bytes.dropFirst(44).allSatisfy({ $0 == 0 }) else {
                        completion(.init(error: "Silence.wav failed integrity validation", invalidAsset: true)); return
                    }
                    data = bytes
                }
                guard context.mayStart() else { completion(.init(superseded: true)); return }
                context.phase(.configuring)
                let session = atStep(.session, context: context) { AVAudioSession.sharedInstance() }
                guard let configured = matches(session, context: context) else {
                    completion(.init(superseded: true)); return
                }
                if !configured {
                    // A stopped player's configuration was intentionally not
                    // read during failure detection. Preserve L3 when this
                    // recovery check discovers that its resources are invalid.
                    if player != nil { discard(context) }
                    guard context.mayStart() else { completion(.init(superseded: true)); return }
                    try atStep(.categorySet, context: context) {
                        try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
                    }
                }
                guard context.mayStart() else { completion(.init(superseded: true)); return }
                if player == nil {
                    try? atStep(.alerts, context: context) { try session.setPrefersNoInterruptionsFromSystemAlerts(true) }
                    guard context.mayStart() else { completion(.init(superseded: true)); return }
                    try? atStep(.disconnect, context: context) { try session.setPrefersInterruptionOnRouteDisconnect(false) }
                }
                guard context.mayStart() else { completion(.init(superseded: true)); return }
                context.phase(.activating)
                changeSession(true, context: context) { [self] success, message in
                    guard success else { completion(.init(error: message ?? "Audio activation failed")); return }
                    guard context.mayStart() else { completion(.init(superseded: true)); return }
                    do {
                        guard generation < UInt64.max else { throw error("Player generation limit reached") }
                        if player == nil {
                            player = try atStep(.playerCreate, context: context) {
                                try AVAudioPlayer(data: data!, fileTypeHint: "wav")
                            }
                            guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                            atStep(.loops, context: context) { player?.numberOfLoops = -1 }
                        }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        // Reusing a stopped player begins a new callback lifetime.
                        generation += 1
                        guard let relay else { preconditionFailure("Audio endpoint relay is missing") }
                        relay.generation(generation)
                        let proxy = DelegateProxy(generation: generation, event: relay.delegate)
                        delegate = proxy
                        atStep(.delegate, context: context) { player?.delegate = proxy }
                        guard let active = player else { throw error("Audio player unavailable") }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        context.phase(.preparing)
                        guard atStep(.prepare, context: context, { active.prepareToPlay() }) else {
                            throw error("Audio preparation failed")
                        }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        context.phase(.starting)
                        guard atStep(.play, context: context, { active.play() }) else {
                            throw error("Audio playback could not start")
                        }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        completion(snapshot(context))
                    } catch {
                        discard(context)
                        completion(.init(error: error.localizedDescription))
                    }
                }
            } catch {
                completion(.init(error: error.localizedDescription))
            }
        }
    }

    private func changeSession(_ active: Bool, context: LoopAudioService.Context,
                               completion: @escaping (Bool, String?) -> Void) {
        let session = atStep(.session, context: context) { AVAudioSession.sharedInstance() }
        guard !active || context.mayStart() else { completion(false, "Session activation superseded"); return }
        if active { sessionUsed = true } // A returned error can still have external effects.
        activationPending = context.id
        if #available(iOS 27.0, *) {
            guard let relay else { preconditionFailure("Audio endpoint relay is missing") }
            activationCompletion = completion
            let receive: @Sendable (Bool, Error?) -> Void = { [relay, operation = context.id] success, error in
                relay.session(.init(operation: operation, success: success, error: error))
            }
            if active {
                atStep(.activate, context: context) { session.activate(options: [], completionHandler: receive) }
            } else {
                atStep(.deactivate, context: context) {
                    session.deactivate(options: [.notifyOthersOnDeactivation], completionHandler: receive)
                }
            }
        } else {
            do {
                try atStep(active ? .activate : .deactivate, context: context) {
                    try session.setActive(active, options: active ? [] : [.notifyOthersOnDeactivation])
                }
                activationPending = nil
                completion(true, nil)
            } catch {
                activationPending = nil
                completion(false, error.localizedDescription)
            }
        }
    }
    func receiveSession(_ receipt: LoopAudioService.SessionReceipt) {
        dispatchPrecondition(condition: .onQueue(queue))
        guard activationPending == receipt.operation else { return }
        let completion = activationCompletion
        activationPending = nil
        activationCompletion = nil
        let message = receipt.error?.localizedDescription
        completion?(receipt.success && receipt.error == nil,
                    message ?? (receipt.success ? nil : "Session request was not accepted"))
    }
    func receiveDelegate(_ receipt: LoopAudioService.DelegateReceipt) {
        dispatchPrecondition(condition: .onQueue(queue))
        guard receipt.generation == generation, player != nil else { return }
        event(receipt.decoder ? .decoderFailed : .interrupted)
    }
}
#endif
