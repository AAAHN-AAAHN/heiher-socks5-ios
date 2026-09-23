import Foundation

@main struct ControllerTests {
    @MainActor static func main() {
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ name: String) {
            precondition(condition(), name)
            checks += 1
            print("PASS: \(name)")
        }
        let app = BackgroundKeepAlive()
        app.restore()
        check(!app.locationEnabled && !app.audioEnabled && Timer.live.isEmpty, "Runtime waits for central saved preferences")
        UIApplication.shared.applicationState = .inactive
        CLLocationManager.initialAuthorization = .notDetermined
        app.setLocation(true)
        let location = CLLocationManager.instances.last!
        check(location.requests == 0, "No permission request while inactive")
        UIApplication.shared.applicationState = .active
        app.restore()
        app.locationManagerDidChangeAuthorization(location)
        check(location.requests == 1, "One permission request")
        location.authorizationStatus = .authorizedWhenInUse
        app.locationManagerDidChangeAuthorization(location)
        app.restore()
        check(location.starts == 1 && Timer.live.isEmpty, "One continuous manager without polling")
        check(location.desiredAccuracy == 3000 && !location.pausesLocationUpdatesAutomatically, "Coarse continuous location preserved")
        app.locationManager(location, didUpdateLocations: [CLLocation()])
        check(app.readCount == 1 && app.lastRead != nil, "Location state retained")
        app.locationManager(location, didFailWithError: CLError(code: .locationUnknown))
        check(app.locationEnabled, "Temporary error retains intent")
        location.authorizationStatus = .denied
        app.locationManagerDidChangeAuthorization(location)
        check(app.locationEnabled, "Denial does not change user intent")
        location.authorizationStatus = .authorizedAlways
        app.locationManagerDidChangeAuthorization(location)
        check(location.starts == 2, "Permission restoration restarts the same manager")
        app.setLocation(false)
        app.locationManager(location, didUpdateLocations: [CLLocation()])
        check(app.readCount == 1 && location.delegate == nil, "Off ignores stale location callbacks")

        let audio = AVAudioSession.shared
        app.setAudio(true)
        var player = AVAudioPlayer.instances.last!
        check(player.isPlaying && player.numberOfLoops == -1, "Native infinite WAV playback")
        check(audio.category == .playback && audio.categoryOptions == [.mixWithOthers], "Mixing playback category")
        check(Timer.live.count == 1 && Timer.live[0].interval == 1, "One-second health check")
        let healthyActivations = audio.activations
        for _ in 0..<100 { Timer.live[0].fire(); app.restore() }
        check(audio.activations == healthyActivations && AVAudioPlayer.instances.last === player
              && Timer.live.count == 1 && Timer.live[0].interval == 1,
              "100 healthy checks retain one-second monitoring without player reactivation")
        for info: [AnyHashable: Any]? in [
            [AVAudioSessionInterruptionTypeKey: UInt(1)],
            [AVAudioSessionInterruptionTypeKey: UInt(0)],
            [AVAudioSessionInterruptionTypeKey: UInt(999)], nil
        ] {
            let previous = AVAudioPlayer.instances.last!
            app.audioEvent(Notification(name: AVAudioSession.interruptionNotification, userInfo: info))
            check(AVAudioPlayer.instances.last !== previous && AVAudioPlayer.instances.last!.isPlaying,
                  "Interruption is handled even with absent/unknown metadata and stale isPlaying")
        }
        audio.rejectActivation = true
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        for _ in 0..<1000 {
            check(Timer.live.count == 1 && Timer.live[0].interval == 1 && app.audioEnabled,
                  "Failure retains one fixed one-second retry")
            Timer.live[0].fire()
        }
        let beforeCategoryEvent = audio.activations
        app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                    userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(3)]))
        check(audio.activations == beforeCategoryEvent && Timer.live.count == 1, "Own category event cannot create a recursive retry loop")
        audio.rejectActivation = false
        Timer.live[0].fire()
        check(AVAudioPlayer.instances.last!.isPlaying && Timer.live[0].interval == 1, "Recovery retains one-second monitoring")
        player = AVAudioPlayer.instances.last!
        player.isPlaying = false
        Timer.live[0].fire()
        check(player.isPlaying, "Unnotified stop recovered by active monitoring")
        for event in [AVAudioSession.mediaServicesWereLostNotification, AVAudioSession.mediaServicesWereResetNotification] {
            let old = AVAudioPlayer.instances.last!
            app.audioEvent(Notification(name: event))
            check(old !== AVAudioPlayer.instances.last && AVAudioPlayer.instances.last!.isPlaying, "Media service event recreates player")
        }
        audio.category = .ambient
        app.audioEvent(Notification(name: AVAudioSession.routeChangeNotification,
                                    userInfo: [AVAudioSessionRouteChangeReasonKey: UInt(3)]))
        check(audio.category == .playback && AVAudioPlayer.instances.last!.isPlaying, "External category change repaired")
        player = AVAudioPlayer.instances.last!
        let beforeDecoder = audio.activations
        app.audioPlayerDecodeErrorDidOccur(player, error: nil)
        check(audio.activations == beforeDecoder + 1 && AVAudioPlayer.instances.last !== player
              && Timer.live.count == 1 && Timer.live[0].interval == 1,
              "First decoder failure immediately recreates playback and retains one-second monitoring")
        Timer.live[0].fire()
        let staleTimer = Timer.live[0]
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        let newTimer = Timer.live[0]
        staleTimer.fireStale()
        check(Timer.live.count == 1 && Timer.live[0] === newTimer, "Stale timer cannot cancel or duplicate its replacement")
        AVAudioPlayer.rejectPlay = true
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        check(app.audioEnabled && Timer.live[0].interval == 1, "play failure retains intent and retry")
        AVAudioPlayer.rejectPlay = false
        Timer.live[0].fire()
        Bundle.main.resourceAvailable = false
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        check(app.audioEnabled && Timer.live[0].interval == 1, "Missing resource cannot silently disable monitoring")
        Bundle.main.resourceAvailable = true
        Timer.live[0].fire()
        player = AVAudioPlayer.instances.last!
        let timer = Timer.live[0]
        app.setAudio(false)
        let offActivations = audio.activations
        timer.fireStale()
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        app.audioPlayerDidFinishPlaying(player, successfully: false)
        app.restore()
        check(Timer.live.isEmpty && audio.activations == offActivations && !player.isPlaying, "Only Off cancels recovery; stale events stay inert")
        for _ in 0..<100 { app.setAudio(true); app.setAudio(false) }
        check(Timer.live.isEmpty, "100 toggle cycles leak no active timer")
        print("SUMMARY: \(checks) controller checks passed using platform doubles, not iOS call scheduling")
    }
}
