import Foundation

/// Shared-session state is scripted, not a LiveContainer host or physical device.
@main struct SessionOwnershipTests {
    @MainActor static func main() {
        var checks = 0
        var failures = 0
        let mode = CommandLine.arguments.dropFirst().first ?? "all"
        precondition(["all", "unowned", "owned", "reuse", "reentrant-failure"].contains(mode))
        let session = AVAudioSession.shared
        func check(_ value: @autoclosure () -> Bool, _ message: String) {
            checks += 1
            if !value() { failures += 1; print("FAIL: \(message)") }
        }
        func reset() {
            precondition(Timer.live.isEmpty && session.pending.isEmpty && DispatchQueue.pendingUtility.isEmpty)
            session.isActive = true // An existing shared session not activated by this controller.
            session.activations = 0; session.deactivations = 0; session.configurations = 0
            session.category = .ambient; session.mode = .default; session.categoryOptions = []
            session.prefersNoInterruptionsFromSystemAlerts = false
            session.rejectCategory = false; session.rejectActivation = false; session.rejectDeactivation = false
            session.onCategory = nil; session.onPreference = nil
            session.deferTransitions = false; DispatchQueue.deferUtility = false
            AVAudioPlayer.rejectInit = false; AVAudioPlayer.rejectPlay = false
            AVAudioPlayer.rejectPreparation = false
            AVAudioPlayer.instances.removeAll(); CLLocationManager.instances.removeAll()
            CLLocationManager.initialAuthorization = .authorizedAlways
            UIApplication.shared.applicationState = .active
        }
        if mode == "all" || mode == "unowned" {
            reset()
            var app: BackgroundKeepAlive? = BackgroundKeepAlive()
            app!.setLocation(true)
            let manager = CLLocationManager.instances.last!
            session.rejectCategory = true
            app!.setAudio(true)
            for _ in 0..<20 {
                app!.restore()
                for name in BackgroundKeepAlive.audioNotifications { app!.audioEvent(Notification(name: name)) }
                Timer.live.first?.fire()
            }
            check(session.activations == 0 && session.deactivations == 0, "Failed setup never acquired the shared session")
            app!.setAudio(false)
            check(session.isActive && session.deactivations == 0, "Off after failed setup preserves unowned shared session")
            for _ in 0..<100 { app!.setAudio(false); app!.restore() }
            check(session.deactivations == 0, "Repeated Off does not release an unowned session")
            check(!app!.audioEnabled && app!.audioState == "Off" && Timer.live.isEmpty, "Unowned Off clears local retry state")
            check(app!.locationEnabled && manager.starts == 1 && manager.stops == 0, "Failed audio/Off leaves independent location running")
            app!.setLocation(false)
            let released = { [weak app] in app == nil }
            app = nil
            check(released() && session.deactivations == 0, "Unowned destruction has no late release")

            for boundary in 0..<2 {
                for turnBackOn in [false, true] {
                    reset()
                    let owner = BackgroundKeepAlive()
                    let callback = {
                        session.onCategory = nil; session.onPreference = nil
                        owner.setAudio(false)
                        if turnBackOn { owner.setAudio(true) }
                    }
                    if boundary == 0 { session.onCategory = callback }
                    else { session.onPreference = callback }
                    owner.setAudio(true)
                    check(session.deactivations == 0, "Reentrant pre-activation Off never sends an unowned release")
                    check(session.activations == (turnBackOn ? 1 : 0), "Latest On proceeds without a fictitious release")
                    check(owner.audioEnabled == turnBackOn && Timer.live.count == (turnBackOn ? 1 : 0), "Latest intent and timer stay consistent")
                    check(session.isActive, "Shared active state is preserved until an owned Off")
                    owner.setAudio(false)
                    check(session.deactivations == (turnBackOn ? 1 : 0), "A subsequently acquired session is released exactly once")
                    check(Timer.live.isEmpty, "Reentrant sequence leaves no timer after Off")
                }
            }
        }
        if mode == "all" || mode == "reentrant-failure" {
            for boundary in 0..<2 {
                for delayed in [false, true] {
                    for failure in 0..<4 {
                        reset()
                        let owner = BackgroundKeepAlive()
                        session.deferTransitions = delayed
                        session.rejectActivation = failure == 0
                        AVAudioPlayer.rejectInit = failure == 1
                        AVAudioPlayer.rejectPreparation = failure == 2
                        AVAudioPlayer.rejectPlay = failure == 3
                        let callback = {
                            session.onCategory = nil; session.onPreference = nil
                            owner.setAudio(false)
                            owner.setAudio(true)
                        }
                        if boundary == 0 { session.onCategory = callback }
                        else { session.onPreference = callback }
                        owner.setAudio(true)
                        if delayed { session.completeNext() }
                        check(session.activations == 1 && session.deactivations == 0,
                              "Failed reentrant latest On cannot consume the same resume request twice")
                        check(session.pending.isEmpty && Timer.live.count == 1,
                              "Failed latest On waits for its single retry deadline")
                        check(owner.audioEnabled && owner.audioState.hasPrefix("Waiting to resume"),
                              "Failure preserves On without claiming playback")
                        session.rejectActivation = false
                        AVAudioPlayer.rejectInit = false
                        AVAudioPlayer.rejectPreparation = false
                        AVAudioPlayer.rejectPlay = false
                        Timer.live.first?.fire()
                        if delayed { session.completeNext() }
                        check(session.activations == 2 && AVAudioPlayer.instances.last?.isPlaying == true,
                              "One scheduled retry recovers after platform failure ends")
                        owner.setAudio(false)
                        if delayed { session.completeNext() }
                        check(session.deactivations == 1 && Timer.live.isEmpty && session.pending.isEmpty,
                              "Owned cleanup after reentrant failure completes exactly once")
                    }
                }
            }
        }
        if mode == "all" || mode == "owned" {
            for failure in 0..<4 {
                reset()
                let owner = BackgroundKeepAlive()
                session.rejectActivation = failure == 0
                AVAudioPlayer.rejectInit = failure == 1
                AVAudioPlayer.rejectPreparation = failure == 2
                AVAudioPlayer.rejectPlay = failure == 3
                owner.setAudio(true)
                check(session.activations == 1, "Each post-request failure retains activation ownership")
                owner.setAudio(false)
                check(session.deactivations == 1 && !session.isActive, "Owned failure still releases once")
                check(Timer.live.isEmpty && !AVAudioPlayer.instances.contains(where: \.isPlaying), "Owned failure stops local work")
            }
            reset()
            let owner = BackgroundKeepAlive()
            session.deferTransitions = true
            owner.setAudio(true); owner.setAudio(false); owner.setAudio(true)
            check(session.pending.count == 1 && session.pending[0].active, "Off-On cannot overlap pending activation")
            session.completeNext()
            check(session.pending.count == 1 && !session.pending[0].active, "Old owned activation drains its release first")
            session.completeNext()
            check(session.pending.count == 1 && session.pending[0].active, "Latest activation follows completed release")
            session.completeNext()
            check(AVAudioPlayer.instances.last?.isPlaying == true && Timer.live.count == 1, "Deferred Off-On reaches playback")
            session.rejectDeactivation = true
            owner.setAudio(false); session.completeNext()
            check(Timer.live.isEmpty && owner.audioState.hasPrefix("Off; session release failed"), "Failed owned release stays Off without retries")
            session.rejectDeactivation = false
            owner.setAudio(false); session.completeNext()
            check(!session.isActive && session.deactivations == 3, "Explicit Off can retry a failed owned release")
        }
        if mode == "all" || mode == "reuse" {
            reset()
            let owner = BackgroundKeepAlive()
            owner.setLocation(true); owner.setAudio(true)
            let manager = CLLocationManager.instances.last!
            let player = AVAudioPlayer.instances.last!
            let configurations = session.configurations
            for _ in 0..<10_000 {
                owner.audioEvent(Notification(name: AVAudioSession.routeChangeNotification))
                owner.locationManager(manager, didUpdateLocations: [CLLocation()])
                Timer.live.first?.fire()
            }
            check(session.activations == 1 && session.configurations == configurations, "Healthy checks do not reconfigure or reactivate")
            check(AVAudioPlayer.instances.count == 1 && player.isPlaying && player.plays == 1, "Healthy checks reuse the same player")
            check(CLLocationManager.instances.count == 1 && manager.starts == 1 && manager.stops == 0, "Location callbacks reuse one manager")
            check(owner.readCount == 10_000 && owner.lastRead != nil, "Diagnostic counts advance without coordinate history")
            check(Timer.live.count == 1 && Timer.live[0].interval == 0.5, "Exactly one half-second deadline remains")
            owner.setAudio(false)
            check(owner.locationEnabled && manager.stops == 0, "Audio Off leaves location active")
            owner.setLocation(false)
            check(manager.stops == 1 && manager.delegate == nil && Timer.live.isEmpty, "Final Off removes callbacks and timers")
        }
        print("SUMMARY: \(checks) ownership/reuse assertions; \(failures) failed; platform doubles, not host arbitration")
        if failures != 0 { exit(1) }
    }
}
