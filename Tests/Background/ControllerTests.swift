import Foundation

@main struct ControllerTests {
    @MainActor static func main() {
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ name: String) {
            precondition(condition(), name)
            checks += 1
            print("PASS: \(name)")
        }
        let name = "BackgroundTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defer { defaults.removePersistentDomain(forName: name) }
        let app = BackgroundKeepAlive(defaults: defaults)
        app.restore()
        check(!app.locationEnabled && !app.audioEnabled && Timer.live.isEmpty, "Fresh installation is opt-in with no timer")

        UIApplication.shared.applicationState = .inactive
        CLLocationManager.initialAuthorization = .notDetermined
        app.setLocation(true)
        let location = CLLocationManager.instances.last!
        check(location.requests == 0, "Permission is not requested while inactive")
        UIApplication.shared.applicationState = .active
        app.restore()
        app.locationManagerDidChangeAuthorization(location)
        check(location.requests == 1, "Only one pending permission request")
        location.authorizationStatus = .authorizedWhenInUse
        app.locationManagerDidChangeAuthorization(location)
        app.restore()
        check(location.starts == 1, "Authorized continuous service starts once; restore is idempotent")
        check(location.desiredAccuracy == 3000 && location.distanceFilter == -1, "Low accuracy and no movement filter")
        check(location.allowsBackgroundLocationUpdates && location.showsBackgroundLocationIndicator && !location.pausesLocationUpdatesAutomatically, "Background mode, indicator and no automatic pause")
        check(Timer.live.isEmpty, "Location uses no timer or polling")
        app.locationManager(location, didUpdateLocations: [])
        check(app.readCount == 0, "Empty location callback ignored")
        app.locationManager(location, didUpdateLocations: [CLLocation()])
        check(app.readCount == 1 && app.lastRead != nil, "Location state retains count and reception time")
        app.locationManager(location, didFailWithError: CLError(code: .locationUnknown))
        check(app.locationEnabled && location.starts == 1, "Temporary location failure does not recreate or disable service")
        location.authorizationStatus = .denied
        app.locationManagerDidChangeAuthorization(location)
        check(app.locationEnabled && defaults.bool(forKey: "background.continuousLocation"), "Denied permission retains the saved intent")
        let before = location.starts
        location.authorizationStatus = .authorizedAlways
        app.locationManagerDidChangeAuthorization(location)
        check(location.starts == before + 1, "Permission restoration restarts the same manager")
        app.setLocation(false)
        app.locationManager(location, didUpdateLocations: [CLLocation()])
        check(app.readCount == 1 && location.delegate == nil, "Disabled location ignores stale callbacks and releases delegate")
        check(!defaults.bool(forKey: "background.continuousLocation"), "Location Off is saved")
        CLLocationManager.initialAuthorization = .authorizedAlways
        app.setLocation(true)

        let audio = AVAudioSession.shared
        app.setAudio(true)
        var player = AVAudioPlayer.instances.last!
        check(app.audioEnabled && player.isPlaying && player.numberOfLoops == -1, "Native player starts an infinite loop")
        check(audio.category == .playback && audio.categoryOptions == [.mixWithOthers], "Playback mixes without microphone or ducking")
        check(audio.prefersNoInterruptionsFromSystemAlerts, "Nonessential alert interruptions are minimized")
        check(Timer.live.count == 1 && Timer.live[0].interval == 5 && Timer.live[0].tolerance == 1, "One low-frequency health timer with tolerance")
        let count = audio.activations
        app.restore()
        Timer.live[0].fire()
        check(audio.activations == count && AVAudioPlayer.instances.last === player, "Healthy polling and restore do not reactivate or rebuild player")

        let began = Notification(name: AVAudioSession.interruptionNotification,
                                 userInfo: [AVAudioSessionInterruptionTypeKey: UInt(1)])
        let ended = Notification(name: AVAudioSession.interruptionNotification,
                                 userInfo: [AVAudioSessionInterruptionTypeKey: UInt(0)])
        app.audioEvent(began)
        check(player.delegate == nil && AVAudioPlayer.instances.last!.isPlaying && audio.activations == count + 1, "Interruption begin immediately attempts recovery")
        app.audioEvent(ended)
        check(audio.activations == count + 1, "Already recovered audio is not restarted at interruption end")
        audio.rejectActivation = true
        app.audioEvent(began)
        check(app.audioEnabled && defaults.bool(forKey: "background.silentAudio"), "Activation denial never clears persisted audio preference")
        check(app.audioState.hasPrefix("Waiting to resume") && Timer.live[0].interval == 1, "Rejected activation reports waiting and schedules first retry")
        for delay in [2.0, 4.0, 8.0, 8.0] {
            Timer.live[0].fire()
            check(Timer.live.count == 1 && Timer.live[0].interval == delay, "Retry delay is bounded: \(delay) seconds")
        }
        audio.rejectActivation = false
        app.audioEvent(ended)
        check(AVAudioPlayer.instances.last!.isPlaying && Timer.live[0].interval == 5, "End notification resumes even without shouldResume")
        player = AVAudioPlayer.instances.last!
        player.isPlaying = false
        Timer.live[0].fire()
        check(player.isPlaying, "Health check recovers an unnotified playback stop")
        player.isPlaying = false
        app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                    userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(2)]))
        check(player.isPlaying, "Route removal resumes digital silence")
        let configurations = audio.configurations
        app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                    userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(3)]))
        check(audio.configurations == configurations, "Own category-change notification does not create a recovery loop")
        app.audioEvent(Notification(name: AVAudioSession.mediaServicesWereLostNotification))
        check(AVAudioPlayer.instances.last !== player, "Media-service loss discards the old player")
        audio.category = .ambient
        audio.categoryOptions = []
        app.audioEvent(Notification(name: AVAudioSession.mediaServicesWereResetNotification))
        check(AVAudioPlayer.instances.last!.isPlaying && audio.category == .playback, "Media reset reconfigures and rebuilds playback")
        player = AVAudioPlayer.instances.last!
        app.audioPlayerDidFinishPlaying(player, successfully: false)
        check(AVAudioPlayer.instances.last !== player && AVAudioPlayer.instances.last!.isPlaying, "Unexpected player completion restarts playback")
        player = AVAudioPlayer.instances.last!
        app.audioPlayerDecodeErrorDidOccur(player, error: NSError(domain: "Test", code: 1))
        check(!player.isPlaying && Timer.live.count == 1, "Decoder callback schedules bounded recovery instead of recursion")
        Timer.live[0].fire()
        check(AVAudioPlayer.instances.last !== player && AVAudioPlayer.instances.last!.isPlaying, "Decoder retry rebuilds and restarts playback")

        AVAudioPlayer.rejectPlay = true
        app.audioEvent(began)
        check(app.audioEnabled && Timer.live[0].interval == 1, "play() failure preserves intent and retries")
        AVAudioPlayer.rejectPlay = false
        Timer.live[0].fire()
        check(AVAudioPlayer.instances.last!.isPlaying, "Retry recovers play() failure")
        AVAudioPlayer.rejectInit = true
        app.audioEvent(began)
        check(app.audioEnabled && Timer.live.count == 1, "Decoder construction failure preserves intent")
        AVAudioPlayer.rejectInit = false
        Timer.live[0].fire()
        Bundle.main.resourceAvailable = false
        app.audioEvent(began)
        check(app.audioEnabled && app.audioState.contains("Silence.wav"), "Missing asset reports failure without silently disabling option")
        Bundle.main.resourceAvailable = true
        Timer.live[0].fire()
        audio.prefersNoInterruptionsFromSystemAlerts = false
        audio.rejectPreference = true
        app.audioEvent(began)
        check(AVAudioPlayer.instances.last!.isPlaying, "Optional alert preference failure does not block playback")
        audio.rejectPreference = false
        audio.rejectCategory = true
        audio.category = .ambient
        app.audioEvent(began)
        check(app.audioEnabled && Timer.live.count == 1, "Category setup failure preserves intent")
        audio.rejectCategory = false
        Timer.live[0].fire()
        check(AVAudioPlayer.instances.last!.isPlaying, "Category retry succeeds")

        let reopened = BackgroundKeepAlive(defaults: defaults)
        check(reopened.audioEnabled && reopened.locationEnabled, "Both preferences survive controller recreation")
        let oldTimer = Timer.live[0]
        player = AVAudioPlayer.instances.last!
        app.setAudio(false)
        check(!player.isPlaying && player.delegate == nil && Timer.live.isEmpty, "User Off stops player, clears delegate and cancels checks")
        let disabledCount = audio.activations
        oldTimer.fire()
        app.audioEvent(began)
        app.audioEvent(ended)
        app.audioPlayerDidFinishPlaying(player, successfully: true)
        app.restore()
        check(audio.activations == disabledCount && Timer.live.isEmpty, "Delayed events cannot restart explicitly disabled audio")
        check(!defaults.bool(forKey: "background.silentAudio"), "Audio Off persists")
        reopened.restore()
        check(AVAudioPlayer.instances.last!.isPlaying && CLLocationManager.instances.last!.starts == 1, "Saved On choices automatically activate on launch restore")
        reopened.setAudio(false)
        reopened.setLocation(false)
        app.setLocation(false)
        check(!BackgroundKeepAlive(defaults: defaults).audioEnabled && !BackgroundKeepAlive(defaults: defaults).locationEnabled, "Saved Off remains off on next launch")
        check(Timer.live.isEmpty, "No recovery timer remains when audio is disabled")
        var temporary: BackgroundKeepAlive? = BackgroundKeepAlive(defaults: defaults)
        weak var released = temporary
        temporary?.setAudio(true)
        temporary = nil
        check(released == nil && Timer.live.isEmpty, "Timer closure does not retain the controller; deinit invalidates it")
        app.setAudio(false)
        for _ in 0..<100 {
            app.setAudio(true)
            app.audioEvent(began)
            app.setAudio(false)
            app.audioEvent(ended)
        }
        check(Timer.live.isEmpty && !defaults.bool(forKey: "background.silentAudio"), "100 enable/interruption/disable cycles leave no active timer or enabled preference")
        print("SUMMARY: \(checks) controller checks passed (scripted platform doubles, not real call or suspension tests)")
    }
}
