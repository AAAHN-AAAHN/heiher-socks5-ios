import Foundation

/// Exact controller with platform doubles. Success means the specified invariant,
/// not a physical call, audio render, or permission to execute while suspended.
@main struct InterruptionPolicyTests {
    @MainActor static func main() {
        let name = CommandLine.arguments[1]
        // Historical defect controls retain their own timing contract, so an
        // interval change cannot masquerade as detection of a recovery defect.
        let historical = CommandLine.arguments.contains("--historical-intervals")
        let expectedInterval: TimeInterval = historical ? 1 : 0.5
        let expectedServiceInterval: TimeInterval = historical ? 5 : 0.5
        let session = AVAudioSession.shared
        let app = BackgroundKeepAlive()
        var checks = 0
        var failures = 0
        func check(_ condition: @autoclosure () -> Bool, _ message: String) {
            checks += 1
            if !condition() { failures += 1; print("FAIL:", message) }
        }
        func event(_ name: Notification.Name, _ info: [AnyHashable: Any]? = nil) {
            app.audioEvent(Notification(name: name, userInfo: info))
        }
        func advice(_ positive: Bool = true) {
            event(AVAudioSession.resumptionRecommendationNotification,
                  [AVAudioSession.resumptionContextKey: AVAudioSession.ResumptionContext(
                    positive ? .shouldResume : .shouldNotResume)])
        }
        func healthy() -> Bool { AVAudioPlayer.instances.last?.isPlaying == true }
        func drain() {
            var n = 0
            while n < 12 && (!session.pending.isEmpty || !DispatchQueue.pendingUtility.isEmpty) {
                n += 1
                if !session.pending.isEmpty { session.completeNext() }
                else { DispatchQueue.completeUtility() }
            }
            check(n < 12, "uncancelable work drains without recursive requests")
        }
        func invariant() {
            check(session.pending.count + DispatchQueue.pendingUtility.count <= 1,
                  "at most one exclusive platform operation")
            check(Timer.live.count <= 1, "at most one management timer")
            if !historical {
                check(Timer.live.allSatisfy { $0.interval == 0.5 },
                      "every state uses the same independently expected 0.5-second interval")
            }
            check(AVAudioPlayer.instances.filter(\.isPlaying).count <= 1, "at most one playing object")
            if !app.audioEnabled {
                check(Timer.live.isEmpty && !AVAudioPlayer.instances.contains(where: \.isPlaying),
                      "Off never has playback or a retry")
            }
        }
        switch name {
        case "uniform-intervals":
            app.setAudio(true)
            let original = AVAudioPlayer.instances.last!
            check(Timer.live.count == 1 && Timer.live[0].interval == 0.5,
                  "normal playback is checked every 0.5 seconds")
            Timer.live.first?.fire()
            check(AVAudioPlayer.instances.last === original && session.activations == 1,
                  "shorter health interval does not recreate healthy playback")
            session.rejectActivation = true
            app.audioPlayerDecodeErrorDidOccur(original, error: nil)
            check(Timer.live.count == 1 && Timer.live[0].interval == 0.5,
                  "ordinary recovery failure retries after 0.5 seconds")
            let retry = Timer.live.first
            for _ in 0..<100 { event(AVAudioSession.renderingModeChangeNotification) }
            check(Timer.live.first === retry, "hints preserve the half-second deadline")
            event(AVAudioSession.mediaServicesWereLostNotification)
            check(Timer.live.count == 1 && Timer.live[0].interval == 0.5,
                  "known media loss also uses 0.5 seconds, not five seconds")
            Timer.live.first?.fire()
            check(Timer.live.count == 1 && Timer.live[0].interval == 0.5,
                  "failed service availability probe keeps the half-second interval")
            session.rejectActivation = false
            Timer.live.first?.fire()
            check(healthy() && Timer.live.first?.interval == 0.5,
                  "service recovery returns to the same half-second health interval")
            app.setAudio(false)
            check(Timer.live.isEmpty, "Off does not gain an automatic retry loop")
        case "healthy-advice":
            app.setAudio(true)
            let first = AVAudioPlayer.instances.last!
            let timer = Timer.live.first!
            for _ in 0..<100 { advice(); advice(false); event(AVAudioSession.resumptionRecommendationNotification) }
            check(session.activations == 1 && AVAudioPlayer.instances.last === first && first.stops == 0,
                  "all recommendations preserve a healthy player")
            check(Timer.live.first === timer, "healthy recommendations preserve deadline")
        case "activation-advice", "preparation-advice":
            session.deferTransitions = name == "activation-advice"
            DispatchQueue.deferUtility = name == "preparation-advice"
            app.setAudio(true)
            for _ in 0..<100 { advice(); event(AVAudioSession.resumptionRecommendationNotification) }
            check(session.activations == 1, "recommendation cannot duplicate in-flight activation")
            drain()
            check(healthy() && session.activations == 1 && AVAudioPlayer.instances.count == 1,
                  "valid in-flight result survives recommendation")
        case "generic-storm", "inactive-storm", "negative-advice-storm":
            session.rejectActivation = true
            app.setAudio(true)
            let deadline = Timer.live.first!
            for _ in 0..<100 {
                if name == "generic-storm" { event(AVAudioSession.renderingModeChangeNotification) }
                if name == "inactive-storm" { event(AVAudioSession.didBecomeInactiveNotification) }
                if name == "negative-advice-storm" { advice(false) }
            }
            check(session.activations == 1, "duplicate events cannot bypass retry")
            check(Timer.live.first === deadline, "duplicate events cannot postpone retry")
            session.rejectActivation = false
            Timer.live.first?.fire()
            check(healthy() && session.activations == 2, "scheduled retry remains live")
        case "positive-advice-storm":
            session.rejectActivation = true; app.setAudio(true)
            advice()
            let attempts = session.activations
            let deadline = Timer.live.first
            for _ in 0..<100 { advice(); event(AVAudioSession.resumptionRecommendationNotification) }
            check(attempts == 2 && session.activations == 2, "one immediate availability opportunity per episode")
            check(Timer.live.first === deadline, "repeated positive advice preserves the failure deadline")
            session.rejectActivation = false; Timer.live.first?.fire()
            check(healthy(), "bounded advice handling still recovers")
        case "end-preserves-healthy":
            app.setAudio(true); let first = AVAudioPlayer.instances.last!
            for _ in 0..<100 { event(AVAudioSession.interruptionNotification, [AVAudioSessionInterruptionTypeKey: UInt(0)]) }
            check(session.activations == 1 && AVAudioPlayer.instances.last === first && first.stops == 0,
                  "interruption end alone does not invalidate healthy output")
        case "end-after-invalidated-activation", "end-after-invalidated-preparation":
            session.deferTransitions = name.hasSuffix("activation")
            DispatchQueue.deferUtility = name.hasSuffix("preparation")
            app.setAudio(true)
            event(AVAudioSession.interruptionNotification, [AVAudioSessionInterruptionTypeKey: UInt(1)])
            advice()
            invariant()
            drain()
            check(healthy() && session.activations == 2, "end during stale work requests one fresh recovery at completion")
        case "explicit-after-invalidated-activation", "explicit-after-invalidated-preparation":
            session.deferTransitions = name.hasSuffix("activation")
            DispatchQueue.deferUtility = name.hasSuffix("preparation")
            app.setAudio(true)
            event(AVAudioSession.interruptionNotification)
            app.setAudio(true)
            invariant()
            drain()
            check(healthy() && session.activations == 2,
                  "latest explicit On follows invalidated completion without an extra retry delay")
            check(Timer.live.count == 1 && Timer.live[0].interval == expectedInterval,
                  "explicit recovery returns to one normal health timer")
        case "explicit-during-valid-activation", "explicit-during-valid-preparation":
            session.deferTransitions = name.hasSuffix("activation")
            DispatchQueue.deferUtility = name.hasSuffix("preparation")
            app.setAudio(true)
            for _ in 0..<100 { app.setAudio(true) }
            invariant(); drain()
            check(healthy() && session.activations == 1,
                  "repeated explicit On preserves a valid pending result without duplicate work")
        case "lost-no-probes":
            app.setAudio(true); let before = session.activations
            session.rejectActivation = true
            event(AVAudioSession.mediaServicesWereLostNotification)
            for _ in 0..<100 {
                event(AVAudioSession.mediaServicesWereLostNotification)
                event(AVAudioSession.didBecomeInactiveNotification)
                event(AVAudioSession.interruptionNotification)
                event(AVAudioSession.renderingModeChangeNotification)
                advice(false)
            }
            check(session.activations == before && Timer.live.count == 1
                  && Timer.live[0].interval == expectedServiceInterval && !healthy() && app.audioEnabled,
                  "known service absence keeps one 0.5-second probe rather than retrying on hints")
            let deadline = Timer.live.first!
            for _ in 0..<100 { event(AVAudioSession.mediaServicesWereLostNotification) }
            check(Timer.live.first === deadline, "duplicate loss does not starve availability probe")
            session.rejectActivation = false
            event(AVAudioSession.mediaServicesWereResetNotification)
            check(healthy() && session.activations == before + 1, "reset performs one immediate fresh restore")
        case "lost-missing-reset":
            app.setAudio(true)
            session.rejectActivation = true
            event(AVAudioSession.mediaServicesWereLostNotification)
            check(session.activations == 1 && Timer.live.first?.interval == expectedServiceInterval,
                  "loss does not attempt immediate use of known-unavailable service")
            for _ in 0..<3 {
                Timer.live.first?.fire()
                check(Timer.live.count == 1 && Timer.live[0].interval == expectedServiceInterval,
                      "failed service probe remains paced and bounded")
            }
            check(session.activations == 4, "one attempt per availability probe")
            session.rejectActivation = false
            Timer.live.first?.fire()
            check(healthy() && session.activations == 5 && Timer.live.first?.interval == expectedInterval,
                  "missing reset notification does not permanently latch service loss")
        case "lost-probe-interruption":
            app.setAudio(true)
            event(AVAudioSession.mediaServicesWereLostNotification)
            session.deferTransitions = true
            Timer.live.first?.fire()
            check(session.pending.count == 1, "service probe is an exclusive real request")
            event(AVAudioSession.didBecomeInactiveNotification)
            session.completeNext()
            check(!healthy() && Timer.live.first?.interval == expectedServiceInterval,
                  "new interruption during probe rejects its obsolete success")
            event(AVAudioSession.mediaServicesWereResetNotification)
            drain()
            check(healthy(), "explicit reset recovers after invalidated service probe")
        case "lost-activation-reset", "lost-preparation-reset":
            session.deferTransitions = name.contains("activation")
            DispatchQueue.deferUtility = name.contains("preparation")
            app.setAudio(true)
            event(AVAudioSession.mediaServicesWereLostNotification)
            event(AVAudioSession.mediaServicesWereResetNotification)
            invariant(); drain()
            check(healthy() && session.activations == 2, "loss/reset cannot accept old operation or overlap fresh work")
        case "lost-foreground", "lost-explicit-on", "lost-positive-advice":
            app.setAudio(true); event(AVAudioSession.mediaServicesWereLostNotification)
            if name == "lost-foreground" { app.restore() }
            if name == "lost-explicit-on" { app.setAudio(true) }
            if name == "lost-positive-advice" { advice() }
            check(healthy() && session.activations == 2, "missing service reset can recover at meaningful availability checkpoint")
        case "configuration-drift":
            app.setAudio(true); let before = session.activations
            session.category = .ambient
            Timer.live.first?.fire()
            check(session.category == .playback && healthy() && session.activations == before + 1,
                  "health timer repairs configuration drift even with true isPlaying and no category event")
        case "silent-stop", "first-decoder-stop":
            app.setAudio(true); let first = AVAudioPlayer.instances.last!
            if name == "silent-stop" { first.isPlaying = false; Timer.live.first?.fire() }
            else { app.audioPlayerDecodeErrorDidOccur(first, error: nil) }
            check(healthy() && session.activations == 2, "first unexpected stop gets an immediate attempt")
            let again = AVAudioPlayer.instances.last!
            again.isPlaying = false
            event(AVAudioSession.renderingModeChangeNotification)
            check(session.activations == 2 && Timer.live.count == 1, "repeat silent stop uses the same failure budget")
            Timer.live.first?.fire()
            check(healthy() && session.activations == 3, "repeat silent stop recovers at its deadline")
        case "reset-storm":
            session.rejectActivation = true; app.setAudio(true)
            event(AVAudioSession.mediaServicesWereResetNotification)
            let attempts = session.activations; let deadline = Timer.live.first
            for _ in 0..<100 { event(AVAudioSession.mediaServicesWereResetNotification) }
            check(attempts <= 2 && session.activations == attempts && Timer.live.first === deadline,
                  "duplicate reset does not bypass availability budget or replace timer")
            session.rejectActivation = false; Timer.live.first?.fire()
            check(healthy(), "reset storm ends in an executable retry")
        case "own-echo":
            session.onCategory = { event(AVAudioSession.routeChangeNotification, [AVAudioSessionRouteChangeReasonKey: UInt(3)]) }
            session.onActivation = { event(AVAudioSession.didBecomeActiveNotification) }
            app.setAudio(true)
            check(healthy() && session.activations == 1, "inline own configuration/active echoes do not recurse")
        case "lost-off-reentry":
            app.setAudio(true)
            AVAudioPlayer.onStop = { AVAudioPlayer.onStop = nil; app.setAudio(false) }
            event(AVAudioSession.mediaServicesWereLostNotification)
            check(!app.audioEnabled && app.audioState == "Off" && !session.isActive,
                  "Off during loss disposal cannot be overwritten by waiting-services state")
        case "no-completion":
            session.deferTransitions = true; app.setAudio(true)
            for _ in 0..<100 {
                app.restore(); advice()
                event(AVAudioSession.mediaServicesWereResetNotification)
                invariant()
            }
            check(session.pending.count == 1 && Timer.live.isEmpty && session.activations == 1,
                  "a missing system completion is not assumed canceled")
            drain(); check(healthy(), "work can progress once the real completion arrives")
        case "owner-release":
            var owner: BackgroundKeepAlive? = BackgroundKeepAlive()
            let released = { [weak owner] in owner == nil }
            owner!.setAudio(true); let first = AVAudioPlayer.instances.last!
            owner = nil
            check(released() && Timer.live.isEmpty && first.stops == 1 && !session.isActive,
                  "steady owner teardown explicitly stops and best-effort releases")
        case "initial-off":
            session.isActive = true
            app.setAudio(false)
            check(session.deactivations == 0 && session.isActive, "initial Off leaves unused host session alone")
        case "reentry-matrix":
            for boundary in 0..<7 {
                for action in 0..<7 {
                    for delayed in [false, true] {
                        app.setAudio(false); drain()
                        session.deferTransitions = delayed
                        DispatchQueue.deferUtility = delayed
                        var invoked = false
                        let hook: () -> Void = {
                            guard !invoked else { return }
                            invoked = true
                            switch action {
                            case 0: app.setAudio(false)
                            case 1: app.setAudio(false); app.setAudio(true)
                            case 2: event(AVAudioSession.mediaServicesWereLostNotification)
                            case 3: event(AVAudioSession.mediaServicesWereResetNotification)
                            case 4: event(AVAudioSession.interruptionNotification)
                            case 5: advice()
                            default: app.restore()
                            }
                        }
                        switch boundary {
                        case 0: session.onCategory = hook
                        case 1: session.onPreference = hook
                        case 2: session.onActivation = hook
                        case 3: AVAudioPlayer.onPrepare = hook
                        case 4: AVAudioPlayer.onPlay = { _ in hook() }
                        case 5: AVAudioPlayer.onStop = hook
                        default: session.onDeactivation = hook
                        }
                        app.setAudio(true); drain()
                        if boundary >= 5 { app.setAudio(false); drain() }
                        check(invoked, "reentry reaches boundary/action/delivery \(boundary)/\(action)/\(delayed)")
                        invariant()
                        session.onCategory = nil; session.onPreference = nil
                        session.onActivation = nil; session.onDeactivation = nil
                        AVAudioPlayer.onPrepare = nil; AVAudioPlayer.onPlay = nil; AVAudioPlayer.onStop = nil
                        app.setAudio(false); drain(); invariant()
                        check(app.audioState == "Off", "reentrant cancellation settles at Off")
                        app.setAudio(true); drain()
                        check(healthy(), "reentry never permanently loses the ability to restore")
                    }
                }
            }
        case "automatic-liveness":
            session.deferTransitions = true
            DispatchQueue.deferUtility = true
            app.setAudio(true)
            var seed: UInt64 = 0x9B_28_F001
            for _ in 0..<300 {
                for _ in 0..<40 {
                    seed = seed &* 6364136223846793005 &+ 1
                    switch (seed >> 32) % 14 {
                    case 0: app.setAudio(true)
                    case 1: app.setAudio(false)
                    case 2: if !session.pending.isEmpty { session.completeNext(success: seed & 7 != 0) }
                    case 3: if !DispatchQueue.pendingUtility.isEmpty {
                        AVAudioPlayer.rejectPreparation = seed & 7 == 0
                        DispatchQueue.completeUtility(); AVAudioPlayer.rejectPreparation = false
                    }
                    case 4: Timer.live.first?.fire()
                    case 5: advice()
                    case 6: advice(false)
                    case 7: event(AVAudioSession.mediaServicesWereLostNotification)
                    case 8: event(AVAudioSession.mediaServicesWereResetNotification)
                    case 9: event(AVAudioSession.interruptionNotification,
                                  [AVAudioSessionInterruptionTypeKey: UInt(seed & 1)])
                    case 10: event(AVAudioSession.didBecomeInactiveNotification)
                    case 11: event(AVAudioSession.renderingModeChangeNotification)
                    case 12: if let current = AVAudioPlayer.instances.last {
                        app.audioPlayerDecodeErrorDidOccur(current, error: nil)
                    }
                    default: if let current = AVAudioPlayer.instances.last { current.isPlaying = false }
                    }
                    invariant()
                }
                // Once the platform accepts work, saved On must recover using only
                // completions and its existing timer, without a new user request.
                session.rejectActivation = false
                session.rejectDeactivation = false
                AVAudioPlayer.rejectPreparation = false
                for _ in 0..<8 {
                    drain()
                    if !app.audioEnabled || healthy() { break }
                    Timer.live.first?.fire()
                }
                drain(); invariant()
                check(!app.audioEnabled || healthy(),
                      "saved On recovers automatically after arbitrary finite event history")
            }
        case "mixed-transitions":
            session.deferTransitions = true
            DispatchQueue.deferUtility = true
            var seed: UInt64 = 0x9B_28_A0D1
            for step in 0..<12000 {
                seed = seed &* 6364136223846793005 &+ 1
                switch (seed >> 32) % 15 {
                case 0: app.setAudio(true)
                case 1: app.setAudio(false)
                case 2: if !session.pending.isEmpty { session.completeNext(success: seed & 7 != 0) }
                case 3: if !DispatchQueue.pendingUtility.isEmpty {
                    AVAudioPlayer.rejectPreparation = seed & 15 == 0
                    DispatchQueue.completeUtility(); AVAudioPlayer.rejectPreparation = false
                }
                case 4: Timer.live.first?.fire()
                case 5: advice()
                case 6: advice(false)
                case 7: event(AVAudioSession.mediaServicesWereLostNotification)
                case 8: event(AVAudioSession.mediaServicesWereResetNotification)
                case 9: event(AVAudioSession.interruptionNotification, [AVAudioSessionInterruptionTypeKey: UInt(seed & 1)])
                case 10: event(AVAudioSession.didBecomeInactiveNotification)
                case 11: event(AVAudioSession.renderingModeChangeNotification)
                case 12: app.restore()
                case 13: if let player = AVAudioPlayer.instances.last { app.audioPlayerDecodeErrorDidOccur(player, error: nil) }
                default: if let player = AVAudioPlayer.instances.last { player.isPlaying = false }
                }
                invariant()
                if step % 100 == 0 {
                    session.rejectActivation = false; session.rejectDeactivation = false
                    app.setAudio(false); drain()
                    app.setAudio(true); drain()
                    check(healthy(), "explicit recovery still possible after arbitrary event sequence")
                }
            }
        default: fatalError("Unknown policy scenario")
        }
        AVAudioPlayer.onStop = nil
        session.onActivation = nil; session.onCategory = nil
        session.rejectActivation = false; session.rejectDeactivation = false
        app.setAudio(false); drain()
        invariant()
        check(!app.audioEnabled && Timer.live.isEmpty && session.pending.isEmpty && DispatchQueue.pendingUtility.isEmpty,
              "scenario teardown drains all work")
        print("SUMMARY:", name, checks, "checks;", failures, "failures; scripted platform, not device playback")
        if failures > 0 { exit(1) }
    }
}
