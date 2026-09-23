import Foundation

/// Branch-wide regression checks; platform boundaries are scripted, not an iPhone.
@main struct LifecycleTests {
    @MainActor static func main() {
        var checks = 0
        var failures = 0
        func check(_ value: @autoclosure () -> Bool, _ name: String) {
            checks += 1
            if value() { print("PASS: \(name)") }
            else { failures += 1; print("FAIL: \(name)") }
        }
        let session = AVAudioSession.shared
        let app = BackgroundKeepAlive()
        session.isActive = true // Existing host audio, not owned by this controller.
        app.setAudio(false)
        check(session.isActive && session.deactivations == 0,
              "Initial saved Audio Off does not deactivate a host's existing audio session")
        app.setAudio(true)
        let playing = AVAudioPlayer.instances.last!
        let activations = session.activations
        app.setAudio(true)
        check(session.activations == activations && AVAudioPlayer.instances.last === playing,
              "Repeated Audio On preserves healthy playback and its single timer")
        app.setAudio(false)
        let deactivations = session.deactivations
        for _ in 0..<20 { app.setAudio(false); app.restore() }
        check(session.deactivations == deactivations && Timer.live.isEmpty,
              "Repeated Audio Off is idempotent and does not touch a shared session again")

        session.onCategory = { app.setAudio(false) }
        let beforeCategoryOff = session.activations
        app.setAudio(true)
        check(!app.audioEnabled && session.activations == beforeCategoryOff && !session.isActive && Timer.live.isEmpty,
              "Off during category configuration prevents subsequent activation or player creation")
        session.onCategory = nil
        session.onPreference = { app.setAudio(false) }
        let beforePreferenceOff = session.activations
        app.setAudio(true)
        check(!app.audioEnabled && session.activations == beforePreferenceOff && !session.isActive && Timer.live.isEmpty,
              "Off during alert-preference configuration prevents subsequent activation")
        session.onPreference = nil
        session.onActivation = { app.setAudio(false) }
        app.setAudio(true)
        check(!app.audioEnabled && !session.isActive && Timer.live.isEmpty,
              "Off during successful activation is compensated after the outer activation returns")
        session.onActivation = nil
        AVAudioPlayer.onPlay = { _ in app.setAudio(false) }
        app.setAudio(true)
        check(!app.audioEnabled && !session.isActive && !AVAudioPlayer.instances.last!.isPlaying && Timer.live.isEmpty,
              "Off during play leaves no playing object, activation or retry")
        AVAudioPlayer.onPlay = nil
        app.setAudio(true)
        AVAudioPlayer.onStop = {
            AVAudioPlayer.onStop = nil
            app.setAudio(false)
        }
        let beforeStopOff = session.activations
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        check(!app.audioEnabled && !session.isActive && session.activations == beforeStopOff && Timer.live.isEmpty,
              "Off during orphaned-player disposal prevents any new activation")

        app.setAudio(true)
        app.audioPlayerDecodeErrorDidOccur(AVAudioPlayer.instances.last!, error: nil)
        AVAudioPlayer.onStop = {
            AVAudioPlayer.onStop = nil
            app.setAudio(false)
        }
        app.audioPlayerDecodeErrorDidOccur(AVAudioPlayer.instances.last!, error: nil)
        check(!app.audioEnabled && app.audioState == "Off" && Timer.live.isEmpty,
              "Off during retry disposal cannot be overwritten by Waiting state or a new timer")

        // The first failed start remains enabled and retries once per timer firing.
        for failure in 0..<4 {
            session.rejectCategory = failure == 0
            session.rejectActivation = failure == 1
            AVAudioPlayer.rejectInit = failure == 2
            AVAudioPlayer.rejectPlay = failure == 3
            app.setAudio(true)
            check(app.audioEnabled && app.audioState.hasPrefix("Waiting to resume")
                  && Timer.live.count == 1 && Timer.live[0].interval == 1,
                  "Initial failure \(failure) retains intent and exactly one one-second retry")
            for _ in 0..<10 { Timer.live[0].fire() }
            check(app.audioEnabled && Timer.live.count == 1,
                  "Repeated failure \(failure) does not auto-disable or accumulate timers")
            session.rejectCategory = false
            session.rejectActivation = false
            AVAudioPlayer.rejectInit = false
            AVAudioPlayer.rejectPlay = false
            Timer.live[0].fire()
            check(AVAudioPlayer.instances.last!.isPlaying && Timer.live.count == 1,
                  "Clearing failure \(failure) restores playback at the next scheduled retry")
            app.setAudio(false)
        }
        session.rejectPreference = true
        app.setAudio(true)
        check(app.audioEnabled && AVAudioPlayer.instances.last!.isPlaying,
              "Best-effort system-alert preference failure does not block playback")
        session.rejectPreference = false
        app.setAudio(false)

        // Configuration must be ready even if delegate assignment is synchronous.
        CLLocationManager.initialAuthorization = .authorizedAlways
        CLLocationManager.notifyOnDelegate = true
        app.setLocation(true)
        let manager = CLLocationManager.instances.last!
        check(manager.starts == 1 && manager.accuracyAtStart == 3000
              && manager.backgroundAtStart && !manager.pausingAtStart,
              "Location delegate cannot start updates before coarse/background configuration is ready")
        CLLocationManager.notifyOnDelegate = false
        check(manager.distanceFilter == -1 && manager.showsBackgroundLocationIndicator,
              "Continuous coarse location and visible indicator are preserved")
        app.setLocation(false)
        UIApplication.shared.applicationState = .background
        CLLocationManager.initialAuthorization = .authorizedWhenInUse
        app.setLocation(true)
        let whenInUse = CLLocationManager.instances.last!
        check(whenInUse.starts == 0 && app.locationEnabled,
              "A new When-In-Use session waits for foreground instead of starting while backgrounded")
        UIApplication.shared.applicationState = .active
        app.restore()
        check(whenInUse.starts == 1, "Foreground restoration starts the deferred When-In-Use session once")
        UIApplication.shared.applicationState = .background
        app.restore()
        check(whenInUse.starts == 1, "An existing When-In-Use session continues without background restarting")
        app.setLocation(false)
        CLLocationManager.initialAuthorization = .authorizedAlways
        app.setLocation(true)
        let always = CLLocationManager.instances.last!
        check(always.starts == 1, "Always-authorized location is not given a new foreground-only restriction")
        let readCount = app.readCount
        app.locationManager(always, didUpdateLocations: [])
        check(app.readCount == readCount, "An empty location batch is not counted")
        app.locationManager(always, didUpdateLocations: [CLLocation(), CLLocation()])
        check(app.readCount == readCount + 1 && app.lastRead != nil,
              "Location diagnostics count callbacks, not retained coordinates or number of locations")
        app.locationManager(always, didFailWithError: CLError(code: .locationUnknown))
        let oldStarts = always.starts
        app.restore()
        check(always.starts == oldStarts && app.locationEnabled,
              "Temporary unknown location retains the running service without a retry timer")
        app.locationManager(always, didFailWithError: CLError(code: .denied))
        app.locationManager(always, didUpdateLocations: [CLLocation()])
        check(app.readCount == readCount + 1 && app.locationEnabled,
              "Updates after denial are ignored without erasing the user's location preference")
        always.authorizationStatus = .authorizedAlways
        app.locationManagerDidChangeAuthorization(always)
        check(always.starts == oldStarts + 1, "Authorization callback restores the same stopped manager")
        for status in [CLAuthorizationStatus.denied, .restricted] {
            always.authorizationStatus = status
            app.locationManagerDidChangeAuthorization(always)
            let beforeRestore = always.starts
            app.restore()
            check(app.locationEnabled && always.starts == beforeRestore,
                  "Denied/restricted location does not start or silently switch Off")
        }
        app.setLocation(false)
        app.setLocation(true)
        let newManager = CLLocationManager.instances.last!
        let state = app.locationState
        app.locationManagerDidChangeAuthorization(always)
        app.locationManager(always, didUpdateLocations: [CLLocation()])
        app.locationManager(always, didFailWithError: CLError(code: .denied))
        check(newManager !== always && app.locationState == state && always.delegate == nil,
              "All three stale location delegate paths are inert after manager replacement")
        app.setLocation(false)
        UIApplication.shared.applicationState = .inactive
        CLLocationManager.initialAuthorization = .notDetermined
        app.setLocation(true)
        let pending = CLLocationManager.instances.last!
        check(pending.requests == 0 && pending.starts == 0,
              "Permission UI is never requested while inactive")
        UIApplication.shared.applicationState = .active
        for _ in 0..<50 { app.restore(); app.locationManagerDidChangeAuthorization(pending) }
        check(pending.requests == 1, "Repeated foreground/authorization checks request permission once")
        app.setLocation(false)
        CLLocationManager.initialAuthorization = .authorizedAlways
        app.setLocation(true)
        let independent = CLLocationManager.instances.last!
        let starts = independent.starts
        app.setAudio(true)
        app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
        app.setAudio(false)
        check(app.locationEnabled && independent.starts == starts && independent.stops == 0,
              "Audio lifecycle never starts or stops the independent location service")
        app.setAudio(true)
        let audioPlayer = AVAudioPlayer.instances.last!
        let timer = Timer.live[0]
        app.setLocation(false)
        check(app.audioEnabled && audioPlayer.isPlaying && Timer.live[0] === timer,
              "Location Off never changes audio playback or its timer")
        app.setAudio(false)
        // Deterministic adversarial ordering; repetitions are one property test.
        var seed: UInt64 = 0x27_BAC0
        var invariantHeld = true
        for step in 0..<2_000 {
            seed = seed &* 6_364_136_223_846_793_005 &+ 1
            switch Int((seed >> 32) % 9) {
            case 0: app.setAudio(true)
            case 1: app.setAudio(false)
            case 2:
                let names = BackgroundKeepAlive.audioNotifications
                app.audioEvent(Notification(name: names[step % names.count]))
            case 3:
                AVAudioPlayer.instances.last?.isPlaying = false
                Timer.live.first?.fire()
            case 4:
                if let current = AVAudioPlayer.instances.last {
                    app.audioPlayerDecodeErrorDidOccur(current, error: nil)
                }
            case 5:
                if let current = AVAudioPlayer.instances.last {
                    app.audioPlayerDidFinishPlaying(current, successfully: false)
                }
            case 6:
                session.rejectActivation.toggle()
                app.restore()
            case 7:
                AVAudioPlayer.rejectPlay.toggle()
                Timer.live.first?.fire()
            default:
                app.setLocation(!app.locationEnabled)
            }
            let playingCount = AVAudioPlayer.instances.filter(\.isPlaying).count
            if Timer.live.count != (app.audioEnabled ? 1 : 0)
                || playingCount > 1 || (!app.audioEnabled && playingCount != 0) {
                print("Invariant failed at deterministic step \(step)")
                invariantHeld = false
                break
            }
        }
        session.rejectActivation = false
        AVAudioPlayer.rejectPlay = false
        app.setAudio(false)
        app.setLocation(false)
        check(invariantHeld && Timer.live.isEmpty,
              "2000 mixed lifecycle/event/failure transitions preserve one timer, one player and Off")
        print("SUMMARY: \(checks) lifecycle assertions; \(failures) failed; scripted boundaries, not real iPhone events")
        if failures != 0 { exit(1) }
    }
}
