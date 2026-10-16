import Foundation
#if canImport(AVFAudio)
@preconcurrency import AVFAudio
import UIKit
#endif

/// Implementations are exclusively entered on the supplied I/O queue. Async
/// completions keep the single-flight gate closed until they actually arrive.
protocol LoopAudioEndpoint: AnyObject {
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void)
}

/// Queue confinement: control owns policy; io owns the endpoint. The short lock
/// protects only ingress, cancellation and published values. It never encloses AV
/// calls, file I/O, client callbacks, or dispatch sync. No queue waits on another.
final class LoopAudioService: @unchecked Sendable {
    enum Event: Sendable { case hint, available, interrupted, mediaLost, mediaReset, routeChanged, decoderFailed }
    enum Command: Sendable { case inspect, start(rebuild: Bool), stop }
    enum Phase: String, Sendable {
        case off = "Off"
        case queued = "Waiting for the audio worker"
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

    struct State: Sendable, Equatable {
        var text = "Off"
        var detail = ""
        var health = PlaybackProgressMonitor.Health.inconclusive
    }
    struct Reply: Sendable {
        var sample: PlaybackProgressMonitor.Sample?
        var error: String?
        var superseded = false
        var invalidAsset = false
    }
    struct Context: Sendable {
        let id: UInt64
        let epoch: UInt64
        let mayStart: @Sendable () -> Bool
        let phase: @Sendable (Phase) -> Void
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
        let completedOperations: UInt64
        let maximumOutstanding: Int
        let scheduledIngress: Int
        let timerActive: Bool
        let records: [String]
    }
    typealias Observer = @MainActor @Sendable (State) -> Void
    typealias Factory = (DispatchQueue, @escaping @Sendable (Event) -> Void) -> any LoopAudioEndpoint

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
        var lost = false
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
    private let factory: Factory
    private let leaseProvider: @Sendable () -> RecoveryExecutionLease.Provider
    private let policy: Policy
    // I/O queue only; the mutable endpoint never leaves that queue.
    private var endpoint: (any LoopAudioEndpoint)?
    // Control queue only.
    private var current = Ticket()
    private var work: Work?
    private var sequence: UInt64 = 0
    private var completed: UInt64 = 0
    private var timerSequence: UInt64 = 0
    private var timer: DispatchSourceTimer?
    private var lastState = State()
    private var lastPublishedRevision: UInt64?
    private var playing = false
    private var rebuild = false
    private var releaseBarrier = false
    private var releaseFailed = false
    private var assetBlocked = false
    private var retryAt = 0.0
    private var episode = false
    private var expedited = false
    private var lease: RecoveryExecutionLease?
    private var monitor = PlaybackProgressMonitor()
    private var records: [String] = []
    private var notificationTokens: [NSObjectProtocol] = []

    init(policy: Policy = Policy(),
         leaseProvider: @escaping @Sendable () -> RecoveryExecutionLease.Provider = { .unavailable },
         endpointFactory: @escaping Factory) {
        precondition(policy.interval > 0 && policy.warning > 0 && policy.stalled >= policy.warning)
        self.policy = policy
        self.leaseProvider = leaseProvider
        factory = endpointFactory
    }

    #if canImport(AVFAudio)
    @MainActor static let shared: LoopAudioService = {
        let provider = RecoveryExecutionLease.Provider.application(UIApplication.shared)
        let service = LoopAudioService(leaseProvider: { provider }) { queue, event in
            AudioEndpoint(queue: queue, event: event)
        }
        // Observe on the posting thread and coalesce immediately. A blocked main
        // run loop must not accumulate an unbounded receive(on:) audio backlog.
        service.notificationTokens = BackgroundKeepAlive.audioNotifications.map { name in
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: nil) { [weak service] note in
                service?.notify(BackgroundKeepAlive.audioEventValue(note))
            }
        }
        return service
    }()
    #endif

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
        ticket.on = owners.values.contains(where: \.enabled)
        if old && !ticket.on { bumpStop() }
        bumpRevision()
        inbox.explicit = inbox.explicit || explicit
        let schedule = enqueueLocked()
        lock.unlock()
        if schedule { control.async { self.drain() } }
    }

    func unregister(_ owner: UInt64) {
        lock.lock()
        guard owners.removeValue(forKey: owner) != nil else { lock.unlock(); return }
        let old = ticket.on
        ticket.on = owners.values.contains(where: \.enabled)
        if old && !ticket.on { bumpStop() }
        bumpRevision()
        inbox.explicit = true
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
            if case .mediaLost = event { inbox.lost = true }
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
    private static var now: Double { ProcessInfo.processInfo.systemUptime }

    private func drain() {
        dispatchPrecondition(condition: .onQueue(control))
        lock.lock()
        let events = inbox
        inbox = Inbox()
        let next = ticket
        let overflow = exhausted
        lock.unlock()
        if next.stop != current.stop { releaseBarrier = true }
        current = next
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
            if events.explicit || !expedited {
                retryAt = 0
                expedited = true
            }
        }
        if !current.on || overflow {
            cancelTimer()
            finishLease()
            if work != nil {
                publish(State(text: "Off — waiting for system completion"))
            } else if releaseBarrier || playing || releaseFailed {
                begin(.stop)
            } else {
                publish(State(text: overflow ? "Off — audio identifier limit reached" : "Off"))
            }
            return
        }
        if work != nil { return }
        reconcile(inspect: (events.hint || events.explicit || events.available) && playing && !rebuild)
    }

    private func reconcile(inspect: Bool = false) {
        guard work == nil else { return }
        current = latest()
        if !current.on {
            cancelTimer(); finishLease()
            if releaseBarrier || playing || releaseFailed { begin(.stop) }
            return
        }
        if releaseBarrier { begin(.stop); return }
        if assetBlocked { return }
        let remaining = retryAt - Self.now
        if remaining > 0 { schedule(after: remaining); return }
        if playing && !rebuild {
            if inspect { begin(.inspect) }
            else { schedule(after: policy.interval) }
        } else {
            begin(.start(rebuild: rebuild))
        }
    }

    private func begin(_ command: Command) {
        guard work == nil else { return }
        guard sequence < UInt64.max else {
            cancelTimer(); finishLease()
            publish(State(text: "Waiting — audio operation identifier limit reached"))
            return
        }
        let input = latest()
        if case .start = command, !input.on { drain(); return }
        sequence += 1
        let job = Work(id: sequence, command: command, ticket: input, queuedAt: Self.now)
        work = job
        lock.lock()
        timing = Timing(id: job.id, phase: .queued)
        lock.unlock()
        switch command {
        case .start:
            if !episode {
                episode = true
                let claim = RecoveryExecutionLease(provider: leaseProvider()) { [weak self] in
                    self?.control.async { [weak self] in self?.record("Execution claim expired") }
                }
                lease = claim
                claim.start()
            }
            publish(State(text: Phase.activating.rawValue))
        case .stop:
            publish(State(text: "Off — stopping"))
        case .inspect: break
        }
        record("Begin \(job.id): \(String(describing: command))")
        if input.on { schedule(after: policy.interval) }
        io.async {
            self.mark(job.id, .queued, entered: true)
            if self.endpoint == nil {
                self.endpoint = self.factory(self.io) { [weak self] in self?.notify($0) }
            }
            let context = Context(id: job.id, epoch: input.epoch,
                                  mayStart: { [weak self] in self?.valid(input) == true },
                                  phase: { [weak self] in self?.mark(job.id, $0) })
            self.endpoint?.perform(command, context: context) { [self] reply in
                control.async { self.finish(job, reply) }
            }
        }
    }

    private func mark(_ id: UInt64, _ phase: Phase, entered: Bool = false) {
        lock.lock(); defer { lock.unlock() }
        guard timing.id == id else { return }
        timing.phase = phase
        timing.phaseAt = Self.now
        if entered { timing.enteredAt = timing.phaseAt }
    }

    private func finish(_ job: Work, _ reply: Reply) {
        guard work?.id == job.id else { return } // Duplicate/stale completion.
        work = nil
        if completed < UInt64.max { completed += 1 }
        lock.lock(); timing.phase = .off; lock.unlock()
        current = latest()
        if current.stop != job.ticket.stop { releaseBarrier = true }
        if current.epoch != job.ticket.epoch { rebuild = true }
        record("End \(job.id): \(reply.error ?? (reply.superseded ? "superseded" : "accepted"))")
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
                retryAt = Self.now + policy.interval
                publish(State(text: Phase.retry.rawValue, detail: "Audio resources changed during recovery"))
            } else if let sample = reply.sample, sample.playing && sample.configured {
                let wasInspect: Bool
                if case .inspect = job.command { wasInspect = true } else { wasInspect = false }
                playing = true
                rebuild = false
                releaseFailed = false
                assetBlocked = false
                retryAt = 0
                finishLease()
                // Only a subsequent healthy observation closes a failed episode.
                if wasInspect { episode = false; expedited = false }
                let result = monitor.inspect(sample, speculativeRecoveryCertified: policy.speculativeRecoveryCertified)
                if result.mayRebuild {
                    playing = false; rebuild = true
                    reconcile()
                    return
                }
                publish(State(text: Phase.playing.rawValue, detail: result.health.rawValue, health: result.health))
                schedule(after: result.nextDelay)
                return
            } else {
                playing = false
                rebuild = reply.error != nil || reply.sample?.configured != true
                assetBlocked = reply.invalidAsset
                retryAt = Self.now + policy.interval
                monitor.knownFailure(now: Self.now)
                publish(State(text: "Waiting to resume: \(String((reply.error ?? "Audio playback stopped").prefix(256)))"))
                if assetBlocked { cancelTimer(); finishLease(); return }
            }
        }
        reconcile()
    }

    private func schedule(after delay: Double) {
        guard latest().on else { cancelTimer(); return }
        if timer == nil {
            guard timerSequence < UInt64.max else {
                publish(State(text: "Waiting — audio timer identifier limit reached"))
                finishLease()
                return
            }
            timerSequence += 1
            let epoch = timerSequence
            let source = DispatchSource.makeTimerSource(queue: control)
            source.setEventHandler { [weak self] in
                guard let self, timer != nil, timerSequence == epoch else { return }
                tick()
            }
            timer = source
            source.resume()
        }
        timer?.schedule(deadline: .now() + max(0.001, delay), leeway: .milliseconds(1))
    }
    private func tick() {
        current = latest()
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
    private func cancelTimer() { timer?.cancel(); timer = nil }
    private func finishLease() { lease?.finish(); lease = nil }
    private func record(_ message: String) {
        if records.count == 64 { records.removeFirst() }
        records.append(String(message.prefix(384)))
    }
    private func publish(_ state: State) {
        let revision = latest().revision
        guard state != lastState || lastPublishedRevision != revision else { return }
        lastState = state
        lastPublishedRevision = revision
        lock.lock()
        published = state
        publishedTicket = ticket
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
                        State(text: state.text.hasPrefix("Off") ? state.text : "Off — stopping")
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
                completedOperations: self.completed, maximumOutstanding: 1,
                scheduledIngress: queued, timerActive: self.timer != nil, records: self.records))
        }
    }
}

#if canImport(AVFAudio)
/// Only the service I/O queue touches player/session. Delegate callbacks carry a
/// weak object identity back to this queue; they never inspect the player elsewhere.
private final class AudioEndpoint: NSObject, LoopAudioEndpoint, AVAudioPlayerDelegate, @unchecked Sendable {
    private let queue: DispatchQueue
    private let event: @Sendable (LoopAudioService.Event) -> Void
    private var player: AVAudioPlayer?
    private var data: Data?
    private var generation: UInt64 = 0
    private var activationPending: UInt64?
    private var sessionUsed = false
    private let delegateLock = NSLock()
    private weak var delegateSource: AVAudioPlayer?
    private var delegateQueued = false
    private var decodePending = false

    init(queue: DispatchQueue, event: @escaping @Sendable (LoopAudioService.Event) -> Void) {
        self.queue = queue
        self.event = event
    }
    private func error(_ message: String) -> NSError {
        NSError(domain: "LoopAudio", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
    private func matches(_ session: AVAudioSession) -> Bool {
        session.category == .playback && session.mode == .default && session.categoryOptions == [.mixWithOthers]
    }
    private func discard(_ context: LoopAudioService.Context) {
        context.phase(.stopping)
        delegateLock.lock()
        delegateSource = nil
        decodePending = false
        delegateLock.unlock()
        player?.delegate = nil
        player?.stop()
        player = nil
    }
    private func snapshot(_ context: LoopAudioService.Context) -> PlaybackProgressMonitor.Sample? {
        guard let player else { return nil }
        context.phase(.inspecting)
        let begin = ProcessInfo.processInfo.systemUptime
        let session = AVAudioSession.sharedInstance()
        let playing = player.isPlaying, configured = matches(session)
        let position = player.currentTime, clock = player.deviceCurrentTime
        let duration = player.duration, rate = player.enableRate ? Double(player.rate) : 1
        let buffer = session.ioBufferDuration
        return .init(generation: generation, epoch: context.epoch, playing: playing, configured: configured,
                     position: position, deviceTime: clock, duration: duration, rate: rate,
                     startedAt: begin, finishedAt: ProcessInfo.processInfo.systemUptime, bufferDuration: buffer)
    }

    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        dispatchPrecondition(condition: .onQueue(queue))
        switch command {
        case .inspect:
            guard context.mayStart() else { completion(.init(superseded: true)); return }
            completion(.init(sample: snapshot(context)))
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
                    guard let url = Bundle.main.url(forResource: "Silence", withExtension: "wav") else {
                        completion(.init(error: "Silence.wav is missing", invalidAsset: true)); return
                    }
                    let bytes = try Data(contentsOf: url)
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
                let session = AVAudioSession.sharedInstance()
                if !matches(session) { try session.setCategory(.playback, mode: .default, options: [.mixWithOthers]) }
                guard context.mayStart() else { completion(.init(superseded: true)); return }
                if player == nil {
                    try? session.setPrefersNoInterruptionsFromSystemAlerts(true)
                    try? session.setPrefersInterruptionOnRouteDisconnect(false)
                }
                guard context.mayStart() else { completion(.init(superseded: true)); return }
                context.phase(.activating)
                sessionUsed = true // Even an error need not mean absence of external effects.
                changeSession(true, context: context) { [self] success, message in
                    guard success else { completion(.init(error: message ?? "Audio activation failed")); return }
                    guard context.mayStart() else { completion(.init(superseded: true)); return }
                    do {
                        if player == nil {
                            guard generation < UInt64.max else { throw error("Player generation limit reached") }
                            player = try AVAudioPlayer(data: data!, fileTypeHint: "wav")
                            generation += 1
                            player?.numberOfLoops = -1
                            delegateLock.lock(); delegateSource = player; delegateLock.unlock()
                            player?.delegate = self
                        }
                        guard let active = player else { throw error("Audio player unavailable") }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        context.phase(.preparing)
                        guard active.prepareToPlay() else { throw error("Audio preparation failed") }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        context.phase(.starting)
                        guard active.play() else { throw error("Audio playback could not start") }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        completion(.init(sample: snapshot(context)))
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
                               completion: @escaping @Sendable (Bool, String?) -> Void) {
        activationPending = context.id
        if #available(iOS 27.0, *) {
            let session = AVAudioSession.sharedInstance()
            let receive: @Sendable (Bool, Error?) -> Void = { [self] success, error in
                let message = error?.localizedDescription
                queue.async { [self] in
                    guard activationPending == context.id else { return }
                    activationPending = nil
                    completion(success && error == nil, message ?? (success ? nil : "Session request was not accepted"))
                }
            }
            if active { session.activate(options: [], completionHandler: receive) }
            else { session.deactivate(options: [.notifyOthersOnDeactivation], completionHandler: receive) }
        } else {
            do {
                try AVAudioSession.sharedInstance().setActive(active, options: active ? [] : [.notifyOthersOnDeactivation])
                activationPending = nil
                completion(true, nil)
            } catch {
                activationPending = nil
                completion(false, error.localizedDescription)
            }
        }
    }
    private func delegateStopped(_ source: AVAudioPlayer, decoder: Bool) {
        delegateLock.lock()
        guard delegateSource === source else { delegateLock.unlock(); return }
        decodePending = decodePending || decoder
        let enqueue = !delegateQueued
        delegateQueued = true
        delegateLock.unlock()
        guard enqueue else { return }
        queue.async { [self] in
            delegateLock.lock()
            let source = delegateSource
            let decoder = decodePending
            decodePending = false
            delegateQueued = false
            delegateLock.unlock()
            guard let source, player === source else { return }
            event(decoder ? .decoderFailed : .interrupted)
        }
    }
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        delegateStopped(player, decoder: false)
    }
    func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        delegateStopped(player, decoder: true)
    }
}
#endif
