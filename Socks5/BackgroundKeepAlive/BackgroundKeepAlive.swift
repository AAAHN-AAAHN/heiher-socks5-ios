import AVFAudio
import CoreLocation
import SwiftUI

/// Background services; the app root supplies persisted user intent.
@MainActor
final class BackgroundKeepAlive: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate, AVAudioPlayerDelegate {
    @Published private(set) var locationEnabled = false
    @Published private(set) var audioEnabled = false
    @Published private(set) var locationState = "Off"
    @Published private(set) var readCount = 0
    @Published private(set) var lastRead: Date?
    @Published private(set) var audioState = "Off"

    private var locationManager: CLLocationManager?
    private var updating = false
    private var requestedPermission = false
    private var player: AVAudioPlayer?
    private var audioCheck: Timer?
    private var restoringAudio = false
    private var invalidatedDuringRestore = false
    private var playerFailurePending = false

    // Both the subscriber and handler use this registry: no unhandled new names.
    // Keep the legacy notification for compatibility alongside the iOS 27 signals.
    private static let invalidatingAudioNotifications: [Notification.Name] = {
        var names = [AVAudioSession.interruptionNotification,
                     AVAudioSession.mediaServicesWereLostNotification,
                     AVAudioSession.mediaServicesWereResetNotification]
        if #available(iOS 27.0, *) {
            names += [AVAudioSession.didBecomeInactiveNotification,
                      AVAudioSession.resumptionRecommendationNotification]
        }
        return names
    }()

    static let audioNotifications: [Notification.Name] = {
        var names = invalidatingAudioNotifications + [
            AVAudioSession.routeChangeNotification,
            AVAudioSession.silenceSecondaryAudioHintNotification,
            AVAudioSession.spatialPlaybackCapabilitiesChangedNotification,
            AVAudioSession.renderingModeChangeNotification,
            AVAudioSession.renderingCapabilitiesChangeNotification,
            UIApplication.willResignActiveNotification,
            UIApplication.didEnterBackgroundNotification,
            UIApplication.willEnterForegroundNotification,
            UIApplication.protectedDataDidBecomeAvailableNotification
        ]
        if #available(iOS 26.0, *) {
            names += [AVAudioSession.outputMuteStateChangeNotification,
                      AVAudioSession.userIntentToUnmuteOutputNotification]
        }
        if #available(iOS 27.0, *) {
            names.append(AVAudioSession.didBecomeActiveNotification)
        }
        return names
    }()

    deinit { audioCheck?.invalidate() }

    /// Called at launch and on return to the foreground. Safe to call repeatedly.
    func restore() {
        if locationEnabled { openLocation() }
        if audioEnabled { resumeAudio() }
    }

    func setLocation(_ enabled: Bool) {
        locationEnabled = enabled
        if enabled {
            openLocation()
        } else {
            locationManager?.stopUpdatingLocation()
            locationManager?.delegate = nil
            locationManager = nil
            updating = false
            requestedPermission = false
            locationState = "Off"
        }
    }

    private func openLocation() {
        guard locationEnabled else { return }
        if locationManager == nil {
            let manager = CLLocationManager()
            locationManager = manager
            // Coordinates are discarded; navigation-grade accuracy is unnecessary.
            manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
            manager.distanceFilter = kCLDistanceFilterNone
            manager.allowsBackgroundLocationUpdates = true
            manager.showsBackgroundLocationIndicator = true
            manager.pausesLocationUpdatesAutomatically = false
            // A delegate may report authorization immediately; configure first.
            manager.delegate = self
        }
        if let manager = locationManager { authorizeAndStart(manager) }
    }

    private func authorizeAndStart(_ manager: CLLocationManager) {
        guard manager === locationManager, locationEnabled else { return }
        switch manager.authorizationStatus {
        case .notDetermined:
            locationState = "Waiting for location permission"
            if !requestedPermission, UIApplication.shared.applicationState == .active {
                requestedPermission = true
                manager.requestAlwaysAuthorization()
            }
        case .authorizedAlways, .authorizedWhenInUse:
            requestedPermission = false
            guard !updating else { return }
            // A new When-In-Use background session must be started in foreground.
            // Do not interrupt a session that was already started there.
            if manager.authorizationStatus == .authorizedWhenInUse,
               UIApplication.shared.applicationState != .active {
                locationState = "Return to the app to start the location session"
                return
            }
            updating = true
            locationState = "Waiting for a location update"
            manager.startUpdatingLocation()
        case .denied, .restricted:
            manager.stopUpdatingLocation()
            updating = false
            requestedPermission = false
            locationState = "Location access unavailable; enable it in Settings"
        @unknown default:
            manager.stopUpdatingLocation()
            updating = false
            locationState = "Location authorization unavailable"
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        authorizeAndStart(manager)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard manager === locationManager, locationEnabled, updating, !locations.isEmpty else { return }
        // Keep only diagnostic count/time, never coordinates or a location history.
        readCount += 1
        lastRead = Date()
        locationState = "Continuous location active"
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        guard manager === locationManager, locationEnabled else { return }
        if (error as? CLError)?.code == .denied {
            manager.stopUpdatingLocation()
            updating = false
        }
        // A temporary failure must not erase the user's saved preference.
        locationState = "Location error: \(error.localizedDescription)"
    }

    func setAudio(_ enabled: Bool) {
        // Applying saved Off at launch must not deactivate a host's shared audio.
        // Repeated On still reconciles an interrupted or failed session.
        guard enabled || audioEnabled else { return }
        audioEnabled = enabled
        if enabled {
            resumeAudio()
        } else {
            audioCheck?.invalidate()
            audioCheck = nil
            playerFailurePending = false
            discardPlayer()
            try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
            audioState = "Off"
        }
    }

    private func resumeAudio(recreate: Bool = false) {
        guard audioEnabled else { return }
        // A signal raised synchronously by setCategory/setActive/play invalidates
        // this attempt; it must not recursively enter another activation/play.
        guard !restoringAudio else {
            if recreate { invalidatedDuringRestore = true }
            return
        }
        restoringAudio = true
        invalidatedDuringRestore = false
        defer { restoringAudio = false }
        if recreate { discardPlayer() }
        guard audioEnabled else { return }
        if player?.isPlaying == true {
            if audioCheck == nil { scheduleAudioCheck(after: 1) }
            return
        }
        audioCheck?.invalidate()
        audioCheck = nil
        do {
            let session = AVAudioSession.sharedInstance()
            if player == nil || session.category != .playback || session.mode != .default || session.categoryOptions != [.mixWithOthers] {
                try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            }
            guard audioEnabled else { return }
            if player == nil || !session.prefersNoInterruptionsFromSystemAlerts {
                try? session.setPrefersNoInterruptionsFromSystemAlerts(true)
            }
            guard audioEnabled else { return }
            try session.setActive(true)
            guard audioEnabled else {
                // Off may arrive inside activation before that call completes.
                try? session.setActive(false, options: [.notifyOthersOnDeactivation])
                return
            }
            if player == nil {
                guard let url = Bundle.main.url(forResource: "Silence", withExtension: "wav") else {
                    throw NSError(domain: "BackgroundKeepAlive", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: "Silence.wav is missing"])
                }
                player = try AVAudioPlayer(contentsOf: url)
                player?.delegate = self
                player?.numberOfLoops = -1
            }
            guard let current = player, current.play(), current.isPlaying, audioEnabled,
                  player === current, !invalidatedDuringRestore else {
                throw NSError(domain: "BackgroundKeepAlive", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "Audio playback could not start or was interrupted during recovery"])
            }
            audioState = "Playing silent WAV continuously"
            scheduleAudioCheck(after: 1)
        } catch {
            retryAudio(error)
        }
    }

    private func retryAudio(_ error: Error?) {
        guard audioEnabled else { return }
        let wasRestoring = restoringAudio
        restoringAudio = true
        defer { restoringAudio = wasRestoring }
        discardPlayer()
        guard audioEnabled else { return }
        audioState = "Waiting to resume: \(error?.localizedDescription ?? "Audio playback stopped")"
        // Repeated failures must not postpone an already scheduled retry.
        if audioCheck == nil { scheduleAudioCheck(after: 1) }
    }

    private func playerStopped(_ error: Error?) {
        guard audioEnabled else { return }
        if restoringAudio {
            invalidatedDuringRestore = true
            playerFailurePending = true
        } else if playerFailurePending {
            // Another failure before a healthy sample belongs to the same recovery
            // episode. Preserve the one-second retry instead of a decoder spin.
            retryAudio(error)
        } else {
            playerFailurePending = true
            resumeAudio(recreate: true)
        }
    }

    private func discardPlayer() {
        // Detach first so callbacks raised by stop cannot see the old player.
        let previous = player
        player = nil
        previous?.delegate = nil
        previous?.stop()
    }

    private func scheduleAudioCheck(after delay: TimeInterval) {
        audioCheck?.invalidate()
        // One timer: one-second health checks or retries until disabled.
        let timer = Timer(timeInterval: delay, repeats: false) { [weak self] timer in
            MainActor.assumeIsolated {
                guard let self, self.audioCheck === timer else { return }
                self.audioCheck = nil
                if self.player?.isPlaying == true { self.playerFailurePending = false }
                self.resumeAudio()
            }
        }
        audioCheck = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    func audioEvent(_ notification: Notification) {
        guard audioEnabled, Self.audioNotifications.contains(notification.name) else { return }
        if Self.invalidatingAudioNotifications.contains(notification.name) {
            // No metadata/shouldResume gate: saved On means best-effort recovery,
            // even with missing context or stale isPlaying. iOS can still refuse.
            resumeAudio(recreate: true)
            return
        }
        if notification.name == AVAudioSession.routeChangeNotification,
           notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                == AVAudioSession.RouteChangeReason.categoryChange.rawValue {
            let session = AVAudioSession.sharedInstance()
            if session.category != .playback || session.mode != .default || session.categoryOptions != [.mixWithOthers] {
                resumeAudio(recreate: true)
                return
            }
            // Ignore our own normal configuration echo while waiting to create a
            // player. A real stopped player must still be checked immediately.
            if player == nil {
                if audioCheck == nil, !restoringAudio { scheduleAudioCheck(after: 1) }
                return
            }
        }
        if #available(iOS 27.0, *), notification.name == AVAudioSession.didBecomeActiveNotification,
           player == nil, restoringAudio || audioCheck != nil {
            // Successful setActive can notify before player creation/play fails.
            // Do not let its delayed echo turn one-second retries into a busy loop.
            return
        }
        // Routes, rendering/mute hints and lifecycle transitions are checkpoints,
        // not reasons to rebuild healthy playback or override the user's mute.
        resumeAudio()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let id = ObjectIdentifier(player)
        onMain { [weak self] in
            guard let self, let current = self.player,
                  ObjectIdentifier(current) == id, self.audioEnabled else { return }
            self.playerStopped(nil)
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        let id = ObjectIdentifier(player)
        onMain { [weak self] in
            guard let self, let current = self.player,
                  ObjectIdentifier(current) == id, self.audioEnabled else { return }
            self.playerStopped(error)
        }
    }

    private nonisolated func onMain(_ action: @escaping @MainActor @Sendable () -> Void) {
        if Thread.isMainThread {
            MainActor.assumeIsolated { action() }
        } else {
            Task { @MainActor in action() }
        }
    }
}
