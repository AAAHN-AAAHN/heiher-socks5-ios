import Foundation

/// Delayed system completions, not simulated telephone or physical host behavior.
@main struct AsyncSessionTests {
    @MainActor static func main() {
        let session = AVAudioSession.shared
        session.deferTransitions = true
        let app = BackgroundKeepAlive()
        var checks = 0
        func check(_ value: @autoclosure () -> Bool, _ label: String) {
            precondition(value(), label)
            checks += 1
            print("PASS: \(label)")
        }
        func pump() {
            Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        }
        func off() {
            app.setAudio(false)
            for _ in 0..<4 {
                if session.pending.isEmpty { break }
                session.completeNext()
            }
            precondition(session.pending.isEmpty && Timer.live.isEmpty && !app.audioEnabled)
            precondition(!AVAudioPlayer.instances.contains(where: \.isPlaying))
        }
        session.isActive = true
        app.setAudio(false)
        check(session.pending.isEmpty && session.isActive, "Initial Off leaves host audio untouched")
        session.isActive = false
        app.setAudio(true)
        check(session.pending.count == 1 && session.pending[0].active, "On starts one asynchronous activation")
        check(AVAudioPlayer.instances.isEmpty && Timer.live.isEmpty, "No playback or premature retry before activation completion")
        for _ in 0..<100 { app.restore(); app.setAudio(true) }
        check(session.pending.count == 1 && session.activations == 1, "Repeated On and restore coalesce while activation is pending")
        app.setLocation(true)
        check(app.locationEnabled && CLLocationManager.instances.last!.starts == 1, "Location can progress while audio activation is pending")
        app.setLocation(false)
        app.setAudio(false)
        check(app.audioState == "Off" && Timer.live.isEmpty, "Off takes effect locally before system activation completes")
        check(session.deactivations == 0 && session.pending.count == 1, "Off never overlaps activation with deactivation")
        session.completeNext()
        check(session.pending.count == 1 && !session.pending[0].active && AVAudioPlayer.instances.isEmpty,
              "Late successful activation is released without creating a player")
        session.completeNext()
        check(!session.isActive && session.pending.isEmpty, "Late activation compensation actually completes")
        let releases = session.deactivations
        for _ in 0..<100 { app.setAudio(false); app.restore() }
        check(session.deactivations == releases, "Repeated completed Off does not touch shared session again")

        app.setAudio(true)
        app.setAudio(false)
        app.setAudio(true)
        session.completeNext()
        check(session.pending.count == 1 && !session.pending[0].active && AVAudioPlayer.instances.isEmpty,
              "Off-On during activation drains the earlier release before new activation")
        session.completeNext()
        check(session.pending.count == 1 && session.pending[0].active, "Latest On starts only after deactivation completion")
        session.completeNext()
        check(AVAudioPlayer.instances.last!.isPlaying && Timer.live.count == 1, "Latest On reaches playback and one health timer")
        let healthy = session.activations
        for _ in 0..<100 { Timer.live[0].fire(); app.restore() }
        check(session.activations == healthy && session.pending.isEmpty, "Healthy fast path still has no session transition work")
        let staleTimer = Timer.live[0]
        app.setAudio(false)
        app.setAudio(true)
        staleTimer.fireStale()
        app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                    userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(3)]))
        check(session.pending.count == 1 && !session.pending[0].active && Timer.live.isEmpty,
              "On and stale timer cannot overtake pending deactivation")
        session.completeNext()
        session.completeNext()
        check(AVAudioPlayer.instances.last!.isPlaying, "Serialized On after deactivation remains running")
        off()

        app.setAudio(true)
        app.audioEvent(Notification(name: AVAudioSession.mediaServicesWereResetNotification))
        session.completeNext()
        check(!AVAudioPlayer.instances.last!.isPlaying && Timer.live.count == 1 && Timer.live[0].interval == 1,
              "Reset during activation rejects stale success and preserves one-second recovery pacing")
        Timer.live[0].fire()
        session.completeNext()
        check(AVAudioPlayer.instances.last!.isPlaying, "Fresh request after invalidation restores playback")
        off()
        app.setAudio(true)
        session.completeNext(success: false)
        check(app.audioState.hasPrefix("Waiting to resume") && Timer.live.count == 1,
              "False-without-error completion is a failure, not playback success")
        let retry = Timer.live[0]
        for _ in 0..<100 {
            app.audioEvent(Notification(name: AVAudioSession.didBecomeActiveNotification))
            app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                        userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(3)]))
        }
        check(Timer.live[0] === retry && session.pending.isEmpty, "Own echoes preserve an existing retry deadline")
        Timer.live[0].fire()
        check(Timer.live.isEmpty && session.pending.count == 1, "Retry waits for completion rather than starting overlapping work")
        session.completeNext(success: true, error: NSError(domain: "CompletionError", code: 9))
        check(app.audioState.hasPrefix("Waiting to resume") && Timer.live.count == 1,
              "A completion error is not discarded even with a success flag")
        Timer.live[0].fire()
        session.completeNext()
        off()

        app.setAudio(true)
        // The worker delivered its result, but the MainActor completion is queued.
        let request = session.pending.removeFirst()
        session.isActive = true
        let done = DispatchSemaphore(value: 0)
        DispatchQueue.global().async { request.completion(true, nil); done.signal() }
        precondition(done.wait(timeout: .now() + 2) == .success)
        app.setAudio(false)
        check(session.pending.isEmpty, "Queued actor delivery still owns the in-flight gate")
        pump()
        check(session.pending.count == 1 && !session.pending[0].active,
              "Off before worker completion delivery compensates without stale playback")
        session.completeNext()
        check(!session.isActive, "Worker completion compensation releases the actual mock session")

        app.setAudio(true)
        session.completeNext()
        app.setAudio(false)
        session.completeNext(success: false, error: NSError(domain: "Deactivation", code: 8))
        check(app.audioState.hasPrefix("Off; session release failed") && Timer.live.isEmpty,
              "Failed release is visible and does not create an Off retry loop")
        app.setAudio(false)
        check(session.pending.count == 1 && !session.pending[0].active, "Explicit Off can retry this controller's failed release")
        session.completeNext()
        check(app.audioState == "Off" && !session.isActive, "Successful release retry clears its pending state")
        app.setAudio(true)
        session.completeNext()
        app.setAudio(false)
        app.setAudio(true)
        session.completeNext(success: false)
        check(session.pending.count == 1 && session.pending[0].active,
              "Latest On can proceed after a completed unsuccessful release without overlap")
        session.completeNext()
        off()

        app.setAudio(true)
        session.completeNext()
        app.audioPlayerDecodeErrorDidOccur(AVAudioPlayer.instances.last!, error: nil)
        session.completeNext()
        AVAudioPlayer.onStop = {
            AVAudioPlayer.onStop = nil
            app.setAudio(false)
        }
        app.audioPlayerDecodeErrorDidOccur(AVAudioPlayer.instances.last!, error: nil)
        check(!app.audioEnabled && session.pending.count == 1 && !session.pending[0].active,
              "Off inside retry disposal drains release after the outer re-entry guard unwinds")
        session.completeNext()
        check(!session.isActive && Timer.live.isEmpty, "Retry-disposal Off leaves no system session or retry")

        let beforeCanceledConfiguration = session.activations
        session.onCategory = {
            session.onCategory = nil
            app.setAudio(false)
            app.setAudio(true)
        }
        app.setAudio(true)
        check(session.activations == beforeCanceledConfiguration && session.pending.count == 1 && !session.pending[0].active,
              "Off-On inside configuration drains release without launching the canceled activation")
        session.completeNext()
        session.completeNext()
        check(AVAudioPlayer.instances.last!.isPlaying, "The latest On restarts after configuration cancellation cleanup")
        off()

        var seed: UInt64 = 0xC013BEEF
        for _ in 0..<3000 {
            seed = seed &* 6364136223846793005 &+ 1
            switch (seed >> 32) % 7 {
            case 0: app.setAudio(false)
            case 1: app.setAudio(true)
            case 2:
                if !session.pending.isEmpty { session.completeNext(success: (seed & 15) != 0) }
            case 3: Timer.live.first?.fire()
            case 4: app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
            case 5: app.restore()
            default:
                if let player = AVAudioPlayer.instances.last, player.isPlaying {
                    app.audioPlayerDecodeErrorDidOccur(player, error: nil)
                }
            }
            precondition(session.pending.count <= 1 && Timer.live.count <= 1)
            precondition(AVAudioPlayer.instances.filter(\.isPlaying).count <= 1)
            if !app.audioEnabled {
                precondition(Timer.live.isEmpty && !AVAudioPlayer.instances.contains(where: \.isPlaying))
            }
        }
        off()
        check(session.maxPending == 1, "3000 mixed delayed transitions keep one request, one player, one timer and Off priority")
        check(session.synchronousCalls == 0, "The iOS27 path never calls synchronous setActive")

        var temporary: BackgroundKeepAlive? = BackgroundKeepAlive()
        weak var released = temporary
        temporary!.setAudio(true)
        temporary = nil
        check(released == nil, "Pending system completion does not retain a discarded controller")
        session.completeNext()
        check(session.pending.count == 1 && !session.pending[0].active,
              "An orphaned successful activation is asynchronously released")
        session.completeNext()
        check(!session.isActive && Timer.live.isEmpty, "Orphan cleanup leaves no session or timer")
        print("SUMMARY: \(checks) asynchronous session assertions; 3000 mixed transitions; not physical-device tests")
    }
}
