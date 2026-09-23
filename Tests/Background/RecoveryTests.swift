import Foundation

@main struct RecoveryTests {
    @MainActor static func main() {
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ name: String) {
            precondition(condition(), name)
            checks += 1
            print("PASS: \(name)")
        }
        let session = AVAudioSession.shared
        let app = BackgroundKeepAlive()
        let invalidations = [AVAudioSession.interruptionNotification,
                             AVAudioSession.mediaServicesWereLostNotification,
                             AVAudioSession.mediaServicesWereResetNotification,
                             AVAudioSession.didBecomeInactiveNotification,
                             AVAudioSession.resumptionRecommendationNotification]
        let checkpoints = [AVAudioSession.routeChangeNotification,
                           AVAudioSession.silenceSecondaryAudioHintNotification,
                           AVAudioSession.spatialPlaybackCapabilitiesChangedNotification,
                           AVAudioSession.renderingModeChangeNotification,
                           AVAudioSession.renderingCapabilitiesChangeNotification,
                           AVAudioSession.outputMuteStateChangeNotification,
                           AVAudioSession.userIntentToUnmuteOutputNotification,
                           AVAudioSession.didBecomeActiveNotification,
                           UIApplication.willResignActiveNotification,
                           UIApplication.didEnterBackgroundNotification,
                           UIApplication.willEnterForegroundNotification,
                           UIApplication.protectedDataDidBecomeAvailableNotification]
        check(Set(BackgroundKeepAlive.audioNotifications) == Set(invalidations + checkpoints),
              "All 13 playback-session names and four lifecycle checkpoints are registered")
        check(BackgroundKeepAlive.audioNotifications.count == 17, "No duplicate notification registration")
        for event in invalidations + checkpoints { app.audioEvent(Notification(name: event)) }
        check(session.activations == 0 && Timer.live.isEmpty, "Every registered event is inert while Off")
        app.setAudio(true)
        for event in invalidations {
            for payload: [AnyHashable: Any]? in [nil, [:], ["context": "unknown"], ["shouldResume": false]] {
                let old = AVAudioPlayer.instances.last!
                let before = session.activations
                app.audioEvent(Notification(name: event, userInfo: payload))
                check(session.activations == before + 1 && AVAudioPlayer.instances.last !== old
                      && AVAudioPlayer.instances.last!.isPlaying,
                      "Immediate invalidation recovery: \(event.rawValue), including absent/unknown metadata")
                check(Timer.live.count == 1 && Timer.live[0].interval == 1, "Invalidation preserves a single one-second timer")
            }
        }
        for event in checkpoints {
            let healthy = AVAudioPlayer.instances.last!
            let before = session.activations
            app.audioEvent(Notification(name: event))
            check(session.activations == before && AVAudioPlayer.instances.last === healthy,
                  "Healthy checkpoint does not reactivate or rebuild: \(event.rawValue)")
            healthy.isPlaying = false
            app.audioEvent(Notification(name: event))
            check(session.activations == before + 1 && healthy.isPlaying,
                  "Stopped checkpoint retries immediately: \(event.rawValue)")
        }
        for reason in [0, 1, 2, 3, 4, 6, 7, 8, 999] {
            let player = AVAudioPlayer.instances.last!
            player.isPlaying = false
            let before = session.activations
            app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                        userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(reason)]))
            check(player.isPlaying && session.activations == before + 1,
                  "Route reason \(reason) cannot leave a stopped player waiting for polling")
        }
        let unexpected = session.activations
        app.audioEvent(Notification(name: Notification.Name("UnrelatedInputOnlySignal")))
        check(session.activations == unexpected, "Unrelated notifications do not trigger recovery")
        session.rejectActivation = true
        for event in invalidations {
            let before = session.activations
            app.audioEvent(Notification(name: event))
            check(session.activations == before + 1 && app.audioEnabled && Timer.live.count == 1,
                  "Failed immediate activation remains enabled: \(event.rawValue)")
            Timer.live[0].fire()
            check(session.activations == before + 2 && Timer.live[0].interval == 1,
                  "Activation failure retries on the next one-second callback")
        }
        let echoTimer = Timer.live[0]
        let beforeEcho = session.activations
        for _ in 0..<100 {
            app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                        userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(3)]))
            app.audioEvent(Notification(name: AVAudioSession.didBecomeActiveNotification))
        }
        check(session.activations == beforeEcho && Timer.live[0] === echoTimer,
              "Own category/active echoes cannot spin or postpone an existing retry")
        session.rejectActivation = false
        Timer.live[0].fire()
        Timer.live[0].fire()
        let firstFailed = AVAudioPlayer.instances.last!
        let beforeFailure = session.activations
        app.audioPlayerDecodeErrorDidOccur(firstFailed, error: NSError(domain: "Decoder", code: 7))
        check(session.activations == beforeFailure + 1 && AVAudioPlayer.instances.last !== firstFailed,
              "First decoder failure has no initial one-second delay")
        let replacement = AVAudioPlayer.instances.last!
        let retryDeadline = Timer.live[0]
        app.audioPlayerDecodeErrorDidOccur(replacement, error: nil)
        check(session.activations == beforeFailure + 1 && Timer.live[0] === retryDeadline,
              "Immediate repeat decoder failure is paced without extending the retry deadline")
        Timer.live[0].fire()
        check(session.activations == beforeFailure + 2, "Repeated decoder failure next attempt runs after one timer callback")
        Timer.live[0].fire()
        let recovered = AVAudioPlayer.instances.last!
        app.audioPlayerDidFinishPlaying(recovered, successfully: false)
        check(session.activations == beforeFailure + 3 && AVAudioPlayer.instances.last !== recovered,
              "A healthy sample resets pacing: the next independent stop is immediate")
        let replaced = AVAudioPlayer.instances.last!
        let oldTimer = Timer.live[0]
        app.audioPlayerDidFinishPlaying(recovered, successfully: true)
        check(AVAudioPlayer.instances.last === replaced && Timer.live[0] === oldTimer,
              "Stale completion cannot discard the current player")
        app.setAudio(false)

        // Realistic synchronous callbacks, not a double that always accepts work.
        session.onCategory = {
            app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                        userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(3)]))
        }
        session.onActivation = { app.audioEvent(Notification(name: AVAudioSession.didBecomeActiveNotification)) }
        let beforeReentrant = session.activations
        app.setAudio(true)
        check(session.activations == beforeReentrant + 1 && AVAudioPlayer.instances.last!.isPlaying && Timer.live.count == 1,
              "Synchronous category and activation notifications do not recurse")
        AVAudioPlayer.onPlay = { player in app.audioPlayerDecodeErrorDidOccur(player, error: nil) }
        app.audioEvent(Notification(name: AVAudioSession.didBecomeInactiveNotification))
        let afterFirstNestedError = session.activations
        check(app.audioState.hasPrefix("Waiting to resume") && Timer.live.count == 1,
              "Decoder failure raised inside play invalidates success and is paced")
        for _ in 0..<1000 { Timer.live[0].fire() }
        check(session.activations == afterFirstNestedError + 1000 && Timer.live.count == 1,
              "1000 synchronous decoder failures produce exactly one attempt per timer, no recursion")
        AVAudioPlayer.onPlay = { player in app.audioPlayerDidFinishPlaying(player, successfully: true) }
        let beforeNestedFinish = session.activations
        for _ in 0..<100 { Timer.live[0].fire() }
        check(session.activations == beforeNestedFinish + 100 && Timer.live.count == 1,
              "Repeated completion raised by play has the same bounded recovery policy")
        AVAudioPlayer.onPlay = { _ in app.audioEvent(Notification(name: AVAudioSession.didBecomeInactiveNotification)) }
        Timer.live[0].fire()
        check(app.audioState.hasPrefix("Waiting to resume") && Timer.live.count == 1,
              "Session invalidation during play is not lost and cannot be reported as healthy")
        AVAudioPlayer.onPlay = nil
        AVAudioPlayer.onStop = { app.audioEvent(Notification(name: AVAudioSession.didBecomeInactiveNotification)) }
        Timer.live[0].fire()
        let beforeStopEcho = session.activations
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        check(session.activations == beforeStopEcho + 1 && Timer.live.count == 1,
              "Synchronous stop/deactivation echoes cannot recursively recreate players")
        AVAudioPlayer.onStop = nil
        Timer.live[0].fire()
        Timer.live[0].fire()
        session.onActivation = { app.setAudio(false) }
        app.audioEvent(Notification(name: AVAudioSession.didBecomeInactiveNotification))
        check(!app.audioEnabled && app.audioState == "Off" && Timer.live.isEmpty,
              "Off during activation wins over outer success/retry logic")
        session.onCategory = nil
        session.onActivation = nil
        let beforeOff = session.activations
        for event in invalidations + checkpoints { app.audioEvent(Notification(name: event)) }
        check(session.activations == beforeOff && Timer.live.isEmpty, "All delayed signals remain inert after Off")
        app.setAudio(true)
        let stale = Timer.live[0]
        app.audioEvent(Notification(name: AVAudioSession.didBecomeInactiveNotification))
        let fresh = Timer.live[0]
        stale.fireStale()
        check(Timer.live[0] === fresh, "Stale timer cannot replace the recovery timer")
        let healthyBefore = session.activations
        for _ in 0..<100 { Timer.live[0].fire() }
        check(session.activations == healthyBefore && Timer.live.count == 1,
              "100 healthy samples do not reactivate the session")
        app.setAudio(false)
        print("SUMMARY: \(checks) recovery assertions passed; includes 1000 decoder/100 completion loops; not OS-delivered iPhone events")
    }
}
