import Foundation

/// Exact controller and scripted platform boundaries, not physical OS interruptions.
@main struct MixedNotificationTests {
    @MainActor static func main() {
        let scenario = CommandLine.arguments[1]
        let session = AVAudioSession.shared
        var checks = 0
        var failures = 0
        func check(_ condition: @autoclosure () -> Bool, _ message: String) {
            checks += 1
            if !condition() { failures += 1; print("FAIL:", message) }
        }
        func event(_ app: BackgroundKeepAlive, _ name: Notification.Name,
                   _ info: [AnyHashable: Any]? = nil) {
            app.audioEvent(Notification(name: name, userInfo: info))
        }
        func advice(_ app: BackgroundKeepAlive, _ positive: Bool) {
            event(app, AVAudioSession.resumptionRecommendationNotification,
                  [AVAudioSession.resumptionContextKey: AVAudioSession.ResumptionContext(
                    positive ? .shouldResume : .shouldNotResume)])
        }
        func drain() {
            var count = 0
            while count < 16 && (!session.pending.isEmpty || !DispatchQueue.pendingUtility.isEmpty) {
                count += 1
                if !session.pending.isEmpty { session.completeNext() }
                else { DispatchQueue.completeUtility() }
            }
            check(count < 16, "finite platform work drains")
        }
        func invariant(_ app: BackgroundKeepAlive) {
            check(session.pending.count + DispatchQueue.pendingUtility.count <= 1,
                  "one uncancelable operation at a time")
            check(Timer.live.count <= 1 && Timer.live.allSatisfy { $0.interval == 0.5 },
                  "one timer with exactly the shared half-second interval")
            check(AVAudioPlayer.instances.filter(\.isPlaying).count <= 1,
                  "one continuously playing object")
            if !app.audioEnabled {
                check(Timer.live.isEmpty && !AVAudioPlayer.instances.contains(where: \.isPlaying),
                      "Off wins over every event")
            }
        }
        func cleanup(_ app: BackgroundKeepAlive) {
            session.rejectActivation = false
            session.rejectDeactivation = false
            AVAudioPlayer.rejectPreparation = false
            app.setAudio(false)
            drain()
            invariant(app)
            check(!session.isActive && app.audioState == "Off", "Off finishes release")
        }
        if scenario == "deadline" {
            let app = BackgroundKeepAlive()
            session.rejectActivation = true
            app.setAudio(true)
            let deadline = Timer.live.first!
            event(app, AVAudioSession.mediaServicesWereLostNotification)
            check(Timer.live.first === deadline, "first loss preserves an existing failed-episode deadline")
            for _ in 0..<100 {
                event(app, AVAudioSession.mediaServicesWereLostNotification)
                advice(app, false)
                event(app, AVAudioSession.renderingModeChangeNotification)
            }
            check(Timer.live.first === deadline && session.activations == 1,
                  "loss and ordinary hints cannot starve or bypass the deadline")
            session.rejectActivation = false
            deadline.fire()
            check(AVAudioPlayer.instances.last?.isPlaying == true,
                  "the original deadline still recovers when service becomes usable")
            cleanup(app)
        } else if scenario == "storm" {
            let app = BackgroundKeepAlive()
            session.rejectActivation = true
            app.setAudio(true)
            event(app, AVAudioSession.mediaServicesWereLostNotification)
            advice(app, true)
            check(session.activations == 2, "one positive opportunity may expedite a failed episode")
            let deadline = Timer.live.first!
            let count = session.activations
            for index in 0..<200 {
                event(app, AVAudioSession.mediaServicesWereLostNotification)
                if index % 2 == 0 { advice(app, true) }
                else { event(app, AVAudioSession.resumptionRecommendationNotification) }
                event(app, AVAudioSession.interruptionNotification,
                      [AVAudioSessionInterruptionTypeKey: UInt(0)])
                event(app, AVAudioSession.mediaServicesWereResetNotification)
                event(app, AVAudioSession.didBecomeInactiveNotification)
                invariant(app)
            }
            check(session.activations == count, "alternating loss/advice/reset cannot renew the immediate retry budget")
            check(Timer.live.first === deadline, "mixed signals preserve the already scheduled deadline")
            session.rejectActivation = false
            deadline.fire()
            check(AVAudioPlayer.instances.last?.isPlaying == true,
                  "a mixed storm cannot invalidate the only executable retry")
            // After a real healthy sample, a new episode gets its immediate attempt.
            Timer.live.first?.fire()
            let before = session.activations
            event(app, AVAudioSession.interruptionNotification)
            check(session.activations == before + 1 && AVAudioPlayer.instances.last?.isPlaying == true,
                  "new independent interruption still recovers immediately")
            cleanup(app)
        } else if scenario == "matrix" {
            // Every ordered pair at steady/activation/preparation/release boundaries,
            // with both accepting and failing platform operations: 4*2*13*13 = 1352.
            func signal(_ app: BackgroundKeepAlive, _ value: Int) {
                switch value {
                case 0: event(app, AVAudioSession.mediaServicesWereLostNotification)
                case 1: event(app, AVAudioSession.mediaServicesWereResetNotification)
                case 2: event(app, AVAudioSession.interruptionNotification)
                case 3: event(app, AVAudioSession.interruptionNotification,
                              [AVAudioSessionInterruptionTypeKey: UInt(0)])
                case 4: advice(app, true)
                case 5: advice(app, false)
                case 6: event(app, AVAudioSession.resumptionRecommendationNotification)
                case 7: event(app, AVAudioSession.didBecomeInactiveNotification)
                case 8: event(app, AVAudioSession.renderingModeChangeNotification)
                case 9: session.category = .ambient
                        event(app, AVAudioSession.routeChangeNotification,
                              [AVAudioSessionRouteChangeReasonKey: UInt(3)])
                case 10: app.setAudio(false)
                case 11: app.setAudio(true)
                default: AVAudioPlayer.instances.last?.isPlaying = false
                         event(app, AVAudioSession.routeChangeNotification)
                }
            }
            var combinations = 0
            for phase in 0..<4 {
                for reject in [false, true] {
                    for first in 0..<13 {
                        for second in 0..<13 {
                            session.deferTransitions = phase == 1 || phase == 3
                            DispatchQueue.deferUtility = phase == 2
                            AVAudioPlayer.instances.removeAll()
                            let app = BackgroundKeepAlive()
                            app.setAudio(true)
                            if phase == 3 {
                                session.completeNext()
                                app.setAudio(false)
                                app.setAudio(true)
                            }
                            session.rejectActivation = reject
                            session.rejectDeactivation = reject
                            AVAudioPlayer.rejectPreparation = reject
                            signal(app, first); invariant(app)
                            signal(app, second); invariant(app)
                            session.rejectActivation = false
                            session.rejectDeactivation = false
                            AVAudioPlayer.rejectPreparation = false
                            for _ in 0..<12 {
                                drain()
                                if !app.audioEnabled || AVAudioPlayer.instances.last?.isPlaying == true { break }
                                Timer.live.first?.fire()
                            }
                            invariant(app)
                            check(!app.audioEnabled || AVAudioPlayer.instances.last?.isPlaying == true,
                                  "automatic liveness at \(phase)/\(reject)/\(first)/\(second)")
                            cleanup(app)
                            combinations += 1
                        }
                    }
                }
            }
            check(combinations == 1352, "all ordered event pairs and transition boundaries were exercised")
        } else { fatalError("Unknown mixed-notification scenario") }
        print("SUMMARY:", scenario, checks, "checks;", failures, "failures; simulated event ordering only")
        if failures > 0 { exit(1) }
    }
}
