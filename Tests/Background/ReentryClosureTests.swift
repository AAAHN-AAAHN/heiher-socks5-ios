import Foundation

// Reentrant platform-call boundaries; no actual Apple audio or permission tests.
@main struct ReentryClosureTests {
    @MainActor static func main() {
        let s = AVAudioSession.shared
        var checks = 0
        var histories = 0
        var context = ""
        func check(_ value: @autoclosure () -> Bool, _ label: String) {
            checks += 1
            if !value() { print("FAIL: \(context): \(label)"); exit(1) }
        }
        func resetFailures() {
            s.rejectCategory = false; s.rejectActivation = false; s.rejectPreference = false; s.rejectDeactivation = false
            AVAudioPlayer.rejectInit = false; AVAudioPlayer.rejectPreparation = false; AVAudioPlayer.rejectPlay = false
            Bundle.main.resourceAvailable = true
        }
        func clearHooks() {
            s.onCategory = nil; s.onPreference = nil; s.onActivation = nil; s.onDeactivation = nil
            AVAudioPlayer.onPrepare = nil; AVAudioPlayer.onPlay = nil; AVAudioPlayer.onStop = nil
        }
        func invariant(_ app: BackgroundKeepAlive) {
            check(s.pending.count + DispatchQueue.pendingUtility.count <= 1, "one operation")
            check(Timer.live.count <= 1 && Timer.live.allSatisfy { $0.interval == 0.5 }, "one half-second deadline")
            check(AVAudioPlayer.instances.filter(\.isPlaying).count <= 1, "one playing object")
            check(AVAudioPlayer.implicitPreparations == 0, "no implicit preparation")
            if healthy(app) { check(Timer.live.count == 1, "healthy output retains its health deadline") }
            if !app.audioEnabled {
                check(Timer.live.isEmpty && !AVAudioPlayer.instances.contains(where: \.isPlaying), "Off has no local output/work")
            }
        }
        func healthy(_ app: BackgroundKeepAlive) -> Bool {
            app.audioEnabled && app.audioState == "Playing silent WAV continuously"
            && AVAudioPlayer.instances.contains { $0.isPlaying && $0.numberOfLoops == -1 }
            && s.category == .playback && s.mode == .default && s.categoryOptions == [.mixWithOthers]
        }
        func drain(_ app: BackgroundKeepAlive) {
            for _ in 0..<32 {
                invariant(app)
                if !s.pending.isEmpty { s.completeNext(success: true) }
                else if !DispatchQueue.pendingUtility.isEmpty { DispatchQueue.completeUtility() }
                else if !app.audioEnabled || healthy(app) { break }
                else if let t = Timer.live.first { t.fire() }
                else { break }
            }
            invariant(app)
        }
        func action(_ app: BackgroundKeepAlive, _ id: Int) {
            func event(_ name: Notification.Name, _ info: [AnyHashable: Any]? = nil) {
                app.audioEvent(Notification(name: name, userInfo: info))
            }
            switch id {
            case 0: app.setAudio(false)
            case 1: app.setAudio(true)
            case 2: app.setAudio(false); app.setAudio(true)
            case 3: event(AVAudioSession.interruptionNotification, [AVAudioSessionInterruptionTypeKey: UInt(1)])
            case 4: event(AVAudioSession.interruptionNotification, [AVAudioSessionInterruptionTypeKey: UInt(0)])
            case 5: event(AVAudioSession.mediaServicesWereLostNotification)
            case 6: event(AVAudioSession.mediaServicesWereResetNotification)
            case 7: event(AVAudioSession.resumptionRecommendationNotification,
                          [AVAudioSession.resumptionContextKey: AVAudioSession.ResumptionContext(.shouldResume)])
            case 8: event(AVAudioSession.resumptionRecommendationNotification,
                          [AVAudioSession.resumptionContextKey: AVAudioSession.ResumptionContext(.shouldNotResume)])
            case 9: app.restore()
            case 10: s.category = .ambient; event(AVAudioSession.routeChangeNotification, [AVAudioSessionRouteChangeReasonKey: UInt(3)])
            default: event(AVAudioSession.didBecomeInactiveNotification)
            }
        }
        for boundary in 0..<7 {
            for delayed in [false, true] {
                for failure in 0..<6 {
                    for a in 0..<12 {
                        for b in 0..<12 {
                            context = "boundary=\(boundary) delayed=\(delayed) failure=\(failure) events=\(a),\(b)"
                            resetFailures(); clearHooks()
                            s.deferTransitions = false; DispatchQueue.deferUtility = false
                            s.isActive = false; s.category = .ambient; s.mode = .default; s.categoryOptions = []
                            s.prefersNoInterruptionsFromSystemAlerts = false
                            s.activations = 0; s.deactivations = 0
                            AVAudioPlayer.instances.removeAll(); Timer.scheduled.removeAll()
                            let app = BackgroundKeepAlive()
                            // stop/deactivation callbacks need an already active owner.
                            if boundary >= 5 { app.setAudio(true) }
                            s.deferTransitions = delayed; DispatchQueue.deferUtility = delayed
                            var entered = 0
                            var expectedOn = boundary < 5
                            let callback = {
                                clearHooks(); entered += 1
                                switch failure {
                                case 1: s.rejectActivation = true
                                case 2: AVAudioPlayer.rejectPreparation = true
                                case 3: AVAudioPlayer.rejectPlay = true
                                case 4: s.rejectCategory = true
                                case 5: s.rejectDeactivation = true
                                default: break
                                }
                                for input in [a, b] {
                                    if input == 0 { expectedOn = false }
                                    else if input == 1 || input == 2 { expectedOn = true }
                                    action(app, input)
                                }
                            }
                            switch boundary {
                            case 0: s.onCategory = callback
                            case 1: s.onPreference = callback
                            case 2: s.onActivation = callback
                            case 3: AVAudioPlayer.onPrepare = callback
                            case 4: AVAudioPlayer.onPlay = { _ in callback() }
                            case 5: AVAudioPlayer.onStop = callback
                            default: s.onDeactivation = callback
                            }
                            if boundary >= 5 { app.setAudio(false) } else { app.setAudio(true) }
                            // Deliver only already queued work to reach a delayed hook.
                            for _ in 0..<4 where entered == 0 {
                                if !s.pending.isEmpty { s.completeNext() }
                                else if !DispatchQueue.pendingUtility.isEmpty { DispatchQueue.completeUtility() }
                            }
                            check(entered == 1, "one-shot callback really executed")
                            check(app.audioEnabled == expectedOn, "latest explicit intent is preserved")
                            invariant(app)
                            clearHooks(); resetFailures()
                            drain(app)
                            check(app.audioEnabled == expectedOn, "completion cannot replace latest intent")
                            check(!expectedOn || healthy(app), "saved On recovers from existing work without a new On")
                            app.setAudio(false); drain(app)
                            check(s.pending.isEmpty && DispatchQueue.pendingUtility.isEmpty && Timer.live.isEmpty, "Off drains pending work")
                            check(!s.isActive && app.audioState == "Off", "owned release completes")
                            histories += 1
                        }
                    }
                }
            }
        }
        print("PASS: \(histories) platform-reentry histories; \(checks) assertions; platform doubles only")
    }
}
