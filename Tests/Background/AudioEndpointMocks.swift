import Foundation
import Dispatch

/// Controlled API outcomes for the actual AudioEndpoint body. These types are
/// never linked into the application, and do not claim Apple runtime behavior.
final class AudioEndpointFixture: @unchecked Sendable {
    typealias Completion = @Sendable (Bool, Error?) -> Void
    struct Trace {
        var calls: [String] = []
        var onWrongQueue = 0
        var concurrent = 0
        var peak = 0
        var blocked: String?
        var enteredBlock = false
        var hookName: String?
        var hook: (@Sendable () -> Void)?
        var rejections: [String: Int] = [:]
        var holdCompletion: String?
        var pending: [(Bool, Completion)] = []
        var duplicateCompletion = false
        var rateEnabled = false
        var active = false
        var configured = false
        var physicalPlaying = false
        var created = 0
        var discarded = 0
        var livePlayers = 0
        var peakPlayers = 0
        var resource: String?
        var assetReads = 0
        var callbacks: [@Sendable (Bool) -> Void] = []
    }
    static let shared = AudioEndpointFixture()
    let queueKey = DispatchSpecificKey<Bool>()
    let release = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    // Environment configuration is fixed for a fixture process. Reading the
    // whole environment on every simulated AV call adds unrelated host work.
    private let traceEnabled = ProcessInfo.processInfo.environment["LOOP_ENDPOINT_TRACE"] == "1"
    private var trace = Trace()

    func use<T>(_ body: (inout Trace) -> T) -> T {
        lock.lock(); defer { lock.unlock() }
        return body(&trace)
    }
    @discardableResult func enter(_ name: String) -> Bool {
        if traceEnabled {
            FileHandle.standardError.write(Data(("API: " + name + "\n").utf8))
        }
        let step = use { value -> (Bool, (@Sendable () -> Void)?, Bool) in
            value.calls.append(name)
            value.concurrent += 1
            value.peak = max(value.peak, value.concurrent)
            if DispatchQueue.getSpecific(key: queueKey) != true { value.onWrongQueue += 1 }
            let hold = value.blocked == name
            if hold { value.blocked = nil; value.enteredBlock = true }
            let action = value.hookName == name ? value.hook : nil
            if action != nil { value.hook = nil; value.hookName = nil }
            let remaining = value.rejections[name, default: 0]
            if remaining > 0 { value.rejections[name] = remaining - 1 }
            return (hold, action, remaining > 0)
        }
        step.1?()
        if step.0 {
            precondition(release.wait(timeout: .now() + 10) == .success, "FIXTURE_BLOCK_NOT_RELEASED")
        }
        use { $0.concurrent -= 1 }
        return step.2
    }
    func complete(_ active: Bool, _ accepted: Bool, _ callback: @escaping Completion) {
        let held = use { value -> Bool in
            let name = active ? "activate" : "deactivate"
            if value.holdCompletion == name {
                value.holdCompletion = nil
                value.pending.append((active, callback))
                return true
            }
            // Even a rejected deactivation can have made the session inactive.
            value.active = accepted && active
            return false
        }
        guard !held else { return }
        let error: Error? = accepted ? nil : Self.failure
        callback(accepted, error)
        if use({ value -> Bool in let old = value.duplicateCompletion; value.duplicateCompletion = false; return old }) {
            callback(accepted, error)
        }
    }
    func deliverPending() {
        let callbacks = use { value -> [(Bool, Completion)] in
            let old = value.pending; value.pending.removeAll(); return old
        }
        for (active, callback) in callbacks {
            use { $0.active = active }
            callback(true, nil)
        }
    }
    static var failure: NSError { NSError(domain: "ControlledAudioBoundary", code: 1) }
}

struct Bundle {
    static let main = Bundle()
    func url(forResource name: String, withExtension suffix: String) -> URL? {
        let fixture = AudioEndpointFixture.shared
        fixture.enter("asset")
        return fixture.use {
            $0.assetReads += 1
            return $0.resource.map { URL(fileURLWithPath: $0) }
        }
    }
}

final class AVAudioSession: @unchecked Sendable {
    enum Category: Sendable { case playback, ambient }
    enum Mode: Sendable { case `default`, other }
    struct CategoryOptions: OptionSet, Sendable {
        let rawValue: Int
        static let mixWithOthers = CategoryOptions(rawValue: 1)
    }
    struct SetActiveOptions: OptionSet, Sendable {
        let rawValue: Int
        static let notifyOthersOnDeactivation = SetActiveOptions(rawValue: 1)
    }
    static let shared = AVAudioSession()
    static func sharedInstance() -> AVAudioSession {
        AudioEndpointFixture.shared.enter("session")
        return shared
    }
    var category: Category {
        AudioEndpointFixture.shared.enter("category-get")
        return AudioEndpointFixture.shared.use { $0.configured ? .playback : .ambient }
    }
    var mode: Mode {
        AudioEndpointFixture.shared.enter("mode-get")
        return .default
    }
    var categoryOptions: CategoryOptions {
        AudioEndpointFixture.shared.enter("options-get")
        return [.mixWithOthers]
    }
    var ioBufferDuration: Double { AudioEndpointFixture.shared.enter("buffer-get"); return 0.001 }
    func setCategory(_ category: Category, mode: Mode, options: CategoryOptions) throws {
        precondition(category == .playback && mode == .default && options == [.mixWithOthers])
        if AudioEndpointFixture.shared.enter("category-set") { throw AudioEndpointFixture.failure }
        AudioEndpointFixture.shared.use { $0.configured = true }
    }
    func setPrefersNoInterruptionsFromSystemAlerts(_ value: Bool) throws {
        precondition(value)
        if AudioEndpointFixture.shared.enter("alerts") { throw AudioEndpointFixture.failure }
    }
    func setPrefersInterruptionOnRouteDisconnect(_ value: Bool) throws {
        precondition(!value)
        if AudioEndpointFixture.shared.enter("disconnect") { throw AudioEndpointFixture.failure }
    }
    func activate(options: SetActiveOptions, completionHandler: @escaping AudioEndpointFixture.Completion) {
        let accepted = !AudioEndpointFixture.shared.enter("activate")
        AudioEndpointFixture.shared.complete(true, accepted, completionHandler)
    }
    func deactivate(options: SetActiveOptions, completionHandler: @escaping AudioEndpointFixture.Completion) {
        precondition(options == [.notifyOthersOnDeactivation])
        let accepted = !AudioEndpointFixture.shared.enter("deactivate")
        AudioEndpointFixture.shared.complete(false, accepted, completionHandler)
    }
    func setActive(_ active: Bool, options: SetActiveOptions) throws {
        precondition(options == (active ? [] : [.notifyOthersOnDeactivation]))
        let accepted = !AudioEndpointFixture.shared.enter(active ? "activate" : "deactivate")
        AudioEndpointFixture.shared.use { $0.active = accepted && active }
        if !accepted { throw AudioEndpointFixture.failure }
    }
}

protocol AVAudioPlayerDelegate: AnyObject {
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool)
    func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?)
}
final class AVAudioPlayer: @unchecked Sendable {
    private final class CallbackTarget: @unchecked Sendable {
        let value: any AVAudioPlayerDelegate
        init(_ value: any AVAudioPlayerDelegate) { self.value = value }
    }
    private var discarded = false
    private weak var delegateValue: (any AVAudioPlayerDelegate)?
    init(data: Data, fileTypeHint: String?) throws {
        precondition(data.count == 844 && data.dropFirst(44).allSatisfy { $0 == 0 } && fileTypeHint == "wav")
        if AudioEndpointFixture.shared.enter("player-init") { throw AudioEndpointFixture.failure }
        AudioEndpointFixture.shared.use {
            $0.created += 1; $0.livePlayers += 1
            $0.peakPlayers = max($0.peakPlayers, $0.livePlayers)
        }
    }
    var numberOfLoops: Int = 0 {
        didSet { AudioEndpointFixture.shared.enter("loops"); precondition(numberOfLoops == -1) }
    }
    var delegate: (any AVAudioPlayerDelegate)? {
        get { delegateValue }
        set {
            AudioEndpointFixture.shared.enter("delegate")
            delegateValue = newValue
            guard let newValue else { return }
            let target = CallbackTarget(newValue)
            AudioEndpointFixture.shared.use { trace in
                trace.callbacks.append { [self, target] decoder in
                    // Emulate an already-delivered delegate callback retaining
                    // its old sender even after replacement; no property reads.
                    if decoder { target.value.audioPlayerDecodeErrorDidOccur(self, error: AudioEndpointFixture.failure) }
                    else { target.value.audioPlayerDidFinishPlaying(self, successfully: false) }
                }
            }
        }
    }
    var isPlaying: Bool {
        AudioEndpointFixture.shared.enter("playing-get")
        return AudioEndpointFixture.shared.use { $0.physicalPlaying }
    }
    var currentTime: Double {
        AudioEndpointFixture.shared.enter("position-get")
        return ProcessInfo.processInfo.systemUptime.truncatingRemainder(dividingBy: 0.05)
    }
    var deviceCurrentTime: Double { AudioEndpointFixture.shared.enter("clock-get"); return ProcessInfo.processInfo.systemUptime }
    var duration: Double { AudioEndpointFixture.shared.enter("duration-get"); return 0.05 }
    var enableRate: Bool {
        AudioEndpointFixture.shared.enter("rate-enabled-get")
        return AudioEndpointFixture.shared.use { $0.rateEnabled }
    }
    var rate: Float { AudioEndpointFixture.shared.enter("rate-get"); return 1 }
    func prepareToPlay() -> Bool { !AudioEndpointFixture.shared.enter("prepare") }
    func play() -> Bool {
        let accepted = !AudioEndpointFixture.shared.enter("play")
        AudioEndpointFixture.shared.use { $0.physicalPlaying = accepted }
        return accepted
    }
    func stop() {
        AudioEndpointFixture.shared.enter("stop")
        AudioEndpointFixture.shared.use {
            $0.physicalPlaying = false
            if !discarded { discarded = true; $0.discarded += 1; $0.livePlayers -= 1 }
        }
    }
}
