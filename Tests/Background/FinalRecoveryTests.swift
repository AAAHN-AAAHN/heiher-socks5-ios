import Foundation

/// Additional exact-controller state-order tests. Platform responses and timer
/// delivery are scripted; these are not physical audio-interruption measurements.
@main struct FinalRecoveryTests {
    @MainActor static func main() {
        let session = AVAudioSession.shared
        var checks = 0
        var histories = 0
        var context = ""
        func check(_ value: @autoclosure () -> Bool, _ message: String) {
            checks += 1
            if !value() {
                print("FAIL:", context, message)
                exit(1)
            }
        }
        func event(_ app: BackgroundKeepAlive, _ name: Notification.Name,
                   _ info: [AnyHashable: Any]? = nil) {
            app.audioEvent(Notification(name: name, userInfo: info))
        }
        func invariant(_ app: BackgroundKeepAlive) {
            check(session.pending.count + DispatchQueue.pendingUtility.count <= 1,
                  "exclusive activation/preparation/release")
            check(Timer.live.count <= 1 && Timer.live.allSatisfy { $0.interval == 0.5 },
                  "one half-second timer")
            check(AVAudioPlayer.instances.filter(\.isPlaying).count <= 1, "single player")
            check(AVAudioPlayer.implicitPreparations == 0, "no implicit preparation")
            if !app.audioEnabled {
                check(Timer.live.isEmpty && !AVAudioPlayer.instances.contains(where: \.isPlaying),
                      "local Off immediately stops output and checks")
            }
        }
        func healthy(_ app: BackgroundKeepAlive) -> Bool {
            app.audioEnabled && app.audioState == "Playing silent WAV continuously"
                && AVAudioPlayer.instances.contains { $0.isPlaying && $0.numberOfLoops == -1 }
                && session.category == .playback && session.mode == .default
                && session.categoryOptions == [.mixWithOthers]
        }
        func clearFailures() {
            session.rejectActivation = false
            session.rejectDeactivation = false
            session.rejectCategory = false
            session.rejectPreference = false
            AVAudioPlayer.rejectInit = false
            AVAudioPlayer.rejectPreparation = false
            AVAudioPlayer.rejectPlay = false
            Bundle.main.resourceAvailable = true
        }
        func settle(_ app: BackgroundKeepAlive) {
            clearFailures()
            // No new On/foreground/advice is supplied: only the existing scheduled
            // work may recover saved On once platform responses become successful.
            for _ in 0..<24 {
                invariant(app)
                if !session.pending.isEmpty { session.completeNext() }
                else if !DispatchQueue.pendingUtility.isEmpty { DispatchQueue.completeUtility() }
                else if !app.audioEnabled || healthy(app) { break }
                else if let timer = Timer.live.first { timer.fire() }
                else { break }
            }
            invariant(app)
            check(!app.audioEnabled || healthy(app), "automatic recovery without fresh user intent")
        }
        func cleanup(_ app: BackgroundKeepAlive) {
            clearFailures()
            app.setAudio(false)
            settle(app)
            check(session.pending.isEmpty && DispatchQueue.pendingUtility.isEmpty && Timer.live.isEmpty,
                  "Off drains every pending operation")
            check(!session.isActive && app.audioState == "Off", "release completed")
            AVAudioPlayer.instances.removeAll()
            Timer.scheduled.removeAll()
        }
        func start(_ phase: Int) -> BackgroundKeepAlive {
            clearFailures()
            session.deferTransitions = false
            DispatchQueue.deferUtility = false
            let app = BackgroundKeepAlive()
            if phase == 1 { session.deferTransitions = true }
            if phase == 2 { DispatchQueue.deferUtility = true }
            if phase == 4 { session.rejectActivation = true }
            app.setAudio(true)
            if phase == 3 {
                session.deferTransitions = true
                app.setAudio(false)
                app.setAudio(true)
            }
            if phase == 5 { event(app, AVAudioSession.mediaServicesWereLostNotification) }
            // Later requests may also be held independently of the initial phase.
            session.deferTransitions = true
            DispatchQueue.deferUtility = true
            return app
        }
        func signal(_ app: BackgroundKeepAlive, _ index: Int, reject: Bool) {
            switch index {
            case 0: event(app, AVAudioSession.mediaServicesWereLostNotification)
            case 1: event(app, AVAudioSession.mediaServicesWereResetNotification)
            case 2: event(app, AVAudioSession.interruptionNotification,
                          [AVAudioSessionInterruptionTypeKey: UInt(1)])
            case 3: event(app, AVAudioSession.interruptionNotification,
                          [AVAudioSessionInterruptionTypeKey: UInt(0)])
            case 4, 5:
                event(app, AVAudioSession.resumptionRecommendationNotification,
                      [AVAudioSession.resumptionContextKey: AVAudioSession.ResumptionContext(
                        index == 4 ? .shouldResume : .shouldNotResume)])
            case 6: event(app, AVAudioSession.resumptionRecommendationNotification)
            case 7: event(app, AVAudioSession.didBecomeInactiveNotification)
            case 8: event(app, AVAudioSession.renderingModeChangeNotification)
            case 9:
                session.category = .ambient
                event(app, AVAudioSession.routeChangeNotification,
                      [AVAudioSessionRouteChangeReasonKey: UInt(3)])
            case 10: app.setAudio(false)
            case 11: app.setAudio(true)
            case 12: AVAudioPlayer.instances.last?.isPlaying = false
            case 13:
                if let player = AVAudioPlayer.instances.last {
                    app.audioPlayerDidFinishPlaying(player, successfully: true)
                }
            case 14:
                if let player = AVAudioPlayer.instances.last {
                    app.audioPlayerDecodeErrorDidOccur(player, error: nil)
                }
            case 15: Timer.live.first?.fire()
            case 16:
                if !session.pending.isEmpty {
                    session.completeNext(success: !reject,
                        error: reject ? NSError(domain: "FinalRecovery", code: 1) : nil)
                } else if !DispatchQueue.pendingUtility.isEmpty { DispatchQueue.completeUtility() }
            default:
                // Invalid metadata must not silently remove all recovery paths.
                event(app, AVAudioSession.interruptionNotification,
                      [AVAudioSessionInterruptionTypeKey: "invalid", AVAudioSessionInterruptionOptionKey: -1])
            }
        }
        for phase in 0..<6 {
            for reject in [false, true] {
                for first in 0..<18 {
                    for second in 0..<18 {
                        for third in 0..<18 {
                            context = "\(phase)/\(reject)/\(first),\(second),\(third)"
                            let app = start(phase)
                            session.rejectActivation = reject
                            session.rejectDeactivation = reject
                            AVAudioPlayer.rejectPreparation = reject
                            for input in [first, second, third] {
                                signal(app, input, reject: reject)
                                invariant(app)
                            }
                            settle(app)
                            cleanup(app)
                            histories += 1
                        }
                    }
                }
            }
        }
        check(histories == 69984, "all ordered triples, phases and response classes")
        print("PASS:", histories, "ordered histories;", checks, "assertions; scripted platform only")
        let tripleChecks = checks
        var longEvents = 0
        var episodes = 0
        // Extend beyond pairs/triples. Failures at every API stage, silent config
        // drift, stale callbacks and timer delivery are interleaved reproducibly.
        for initialSeed in 1...16 {
            var seed = UInt64(initialSeed)
            let app = start(0)
            for episode in 0..<64 {
                for index in 0..<64 {
                    seed = seed &* 6364136223846793005 &+ 1442695040888963407
                    context = "seed=\(initialSeed)/episode=\(episode)/event=\(index)"
                    let action = Int((seed >> 32) % 27)
                    if action < 18 {
                        signal(app, action, reject: seed & 1 == 0)
                    } else {
                        switch action {
                        case 18: session.rejectCategory = seed & 1 == 0
                        case 19: AVAudioPlayer.rejectInit = seed & 1 == 0
                        case 20: AVAudioPlayer.rejectPlay = seed & 1 == 0
                        case 21: Bundle.main.resourceAvailable = seed & 1 != 0
                        case 22: session.mode = .voiceChat
                        case 23: session.categoryOptions = []
                        case 24:
                            if let old = AVAudioPlayer.instances.first {
                                app.audioPlayerDidFinishPlaying(old, successfully: false)
                            }
                        case 25:
                            // A delivered but obsolete timer must not touch state.
                            if let old = Timer.live.first {
                                app.setAudio(false)
                                app.setAudio(true)
                                old.fireStale()
                            }
                        default:
                            if !session.pending.isEmpty {
                                session.completeNext(success: true,
                                    error: NSError(domain: "ContradictoryCompletion", code: 1))
                            }
                        }
                    }
                    invariant(app)
                    longEvents += 1
                }
                settle(app)
                episodes += 1
            }
            cleanup(app)
        }
        check(longEvents == 65536 && episodes == 1024, "all long-history checkpoints")
        print("PASS:", longEvents, "events across", episodes, "automatic-recovery checkpoints and 16 seeds;",
              checks - tripleChecks, "assertions; scripted platform only")
    }
}
