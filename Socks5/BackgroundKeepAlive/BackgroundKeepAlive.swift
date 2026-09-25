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
    private enum SessionTransition { case activating, preparing, deactivating }
    private var sessionTransition: SessionTransition?
    private var deactivationPending = false

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
            // Authorization can return here after a reset or temporary grant.
            if updating {
                updating = false
                manager.stopUpdatingLocation()
            }
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
        // Initial/repeated Off must not deactivate a host's unused shared session.
        // An explicitly repeated Off may retry this controller's failed release.
        guard enabled || audioEnabled || deactivationPending else { return }
        audioEnabled = enabled
        if enabled {
            resumeAudio()
        } else {
            audioCheck?.invalidate()
            audioCheck = nil
            playerFailurePending = false
            deactivationPending = true
            invalidatedDuringRestore = true
            audioState = "Off"
            // Stop locally now, even when a system activation is still pending.
            let wasRestoring = restoringAudio
            restoringAudio = true
            discardPlayer()
            restoringAudio = wasRestoring
            deactivateAudio()
        }
    }

    private func resumeAudio(recreate: Bool = false) {
        guard audioEnabled else { return }
        // One transition at a time, including the callback's hop to MainActor.
        // Invalidations during activation must not publish stale playback success.
        guard !restoringAudio, sessionTransition == nil else {
            if recreate { invalidatedDuringRestore = true }
            return
        }
        guard !deactivationPending else { deactivateAudio(); return }
        restoringAudio = true
        invalidatedDuringRestore = false
        if recreate { discardPlayer() }
        guard audioEnabled, !deactivationPending else { finishAudioRestore(); return }
        if player?.isPlaying == true {
            if audioCheck == nil { scheduleAudioCheck(after: 1) }
            finishAudioRestore()
            return
        }
        audioCheck?.invalidate()
        audioCheck = nil
        do {
            let session = AVAudioSession.sharedInstance()
            if player == nil || session.category != .playback || session.mode != .default || session.categoryOptions != [.mixWithOthers] {
                try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            }
            guard audioEnabled, !deactivationPending else { finishAudioRestore(); return }
            if player == nil || !session.prefersNoInterruptionsFromSystemAlerts {
                try? session.setPrefersNoInterruptionsFromSystemAlerts(true)
            }
            guard audioEnabled, !deactivationPending else { finishAudioRestore(); return }
            audioState = "Activating audio session"
            beginSessionTransition(active: true)
        } catch {
            retryAudio(error)
            finishAudioRestore()
        }
    }

    private func audioActivated(_ success: Bool, error: Error?) {
        guard sessionTransition == .activating else { return }
        sessionTransition = nil
        // An Off must be drained even after Off-On: a prior release must never
        // complete after the next activation and disable the new session.
        guard audioEnabled, !deactivationPending else { finishAudioRestore(); return }
        do {
            guard success, error == nil, !invalidatedDuringRestore else {
                throw error ?? NSError(domain: "BackgroundKeepAlive", code: 3,
                                       userInfo: [NSLocalizedDescriptionKey: "Audio session activation failed or was interrupted during recovery"])
            }
            if player == nil {
                guard let url = Bundle.main.url(forResource: "Silence", withExtension: "wav") else {
                    throw NSError(domain: "BackgroundKeepAlive", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: "Silence.wav is missing"])
                }
                player = try AVAudioPlayer(contentsOf: url)
                player?.numberOfLoops = -1
            }
            guard let preparing = player else { finishAudioRestore(); return }
            // prepareToPlay may synchronously activate audio even after our async
            // session activation. Transfer exclusive access until it completes;
            // no delegate, timer or Off handler touches this player on the worker.
            player = nil
            preparing.delegate = nil
            sessionTransition = .preparing
            Self.prepareAudioPlayer(preparing) { [weak self] success in
                Self.onMain { [weak self] in
                    guard let self else {
                        preparing.stop()
                        Self.changeAudioSession(false) { _, _ in }
                        return
                    }
                    self.audioPrepared(preparing, success: success)
                }
            }
        } catch {
            retryAudio(error)
            finishAudioRestore()
        }
    }

    private func audioPrepared(_ prepared: AVAudioPlayer, success: Bool) {
        guard sessionTransition == .preparing else { return }
        sessionTransition = nil
        player = prepared
        player?.delegate = self
        defer { finishAudioRestore() }
        guard audioEnabled, !deactivationPending else { discardPlayer(); return }
        do {
            guard success, !invalidatedDuringRestore else {
                throw NSError(domain: "BackgroundKeepAlive", code: 4,
                              userInfo: [NSLocalizedDescriptionKey: "Audio preparation failed or was interrupted during recovery"])
            }
            // Preparation completed; retain MainActor play/Off ordering without
            // making play perform its implicit synchronous preparation here.
            guard prepared.play(), prepared.isPlaying, audioEnabled,
                  player === prepared, !invalidatedDuringRestore else {
                throw NSError(domain: "BackgroundKeepAlive", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "Audio playback could not start or was interrupted during recovery"])
            }
            audioState = "Playing silent WAV continuously"
            scheduleAudioCheck(after: 1)
        } catch {
            retryAudio(error)
        }
    }

    private nonisolated static func prepareAudioPlayer(_ player: AVAudioPlayer,
                                                       completion: @escaping @Sendable (Bool) -> Void) {
        DispatchQueue.global(qos: .utility).async {
            completion(player.prepareToPlay())
        }
    }

    private func finishAudioRestore() {
        restoringAudio = false
        if deactivationPending { deactivateAudio() }
    }

    private func deactivateAudio() {
        guard deactivationPending, !restoringAudio, sessionTransition == nil else { return }
        deactivationPending = false
        beginSessionTransition(active: false)
    }

    private func audioDeactivated(_ success: Bool, error: Error?) {
        guard sessionTransition == .deactivating else { return }
        sessionTransition = nil
        // Playback is already stopped. Do not spin or start a timer while Off.
        deactivationPending = !audioEnabled && (!success || error != nil)
        if audioEnabled {
            resumeAudio()
        } else if deactivationPending {
            audioState = "Off; session release failed: \(error?.localizedDescription ?? "Deactivation was not accepted")"
        } else {
            audioState = "Off"
        }
    }

    private func beginSessionTransition(active: Bool) {
        sessionTransition = active ? .activating : .deactivating
        Self.changeAudioSession(active) { [weak self] success, error in
            Self.onMain { [weak self] in
                guard let self else {
                    // A released controller must not leave its late activation on.
                    if active, success { Self.changeAudioSession(false) { _, _ in } }
                    return
                }
                if active { self.audioActivated(success, error: error) }
                else { self.audioDeactivated(success, error: error) }
            }
        }
    }

    private nonisolated static func changeAudioSession(_ active: Bool,
                                                       completion: @escaping @Sendable (Bool, Error?) -> Void) {
        if #available(iOS 27.0, *) {
            let session = AVAudioSession.sharedInstance()
            if active { session.activate(options: [], completionHandler: completion) }
            else { session.deactivate(options: [.notifyOthersOnDeactivation], completionHandler: completion) }
        } else {
            changeLegacyAudioSession(active, completion: completion)
        }
    }

    private nonisolated static func changeLegacyAudioSession(_ active: Bool,
                                                             completion: @escaping @Sendable (Bool, Error?) -> Void) {
        // The same in-flight gate serializes the compatibility path. Never wait
        // on MainActor, and obtain the system session on the worker itself.
        DispatchQueue.global(qos: .utility).async {
            do {
                try AVAudioSession.sharedInstance().setActive(active, options: active ? [] : [.notifyOthersOnDeactivation])
                completion(true, nil)
            } catch {
                completion(false, error)
            }
        }
    }

    private func retryAudio(_ error: Error?) {
        guard audioEnabled else { return }
        let wasRestoring = restoringAudio
        restoringAudio = true
        defer {
            restoringAudio = wasRestoring
            if deactivationPending { deactivateAudio() }
        }
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
                if audioCheck == nil, !restoringAudio, sessionTransition == nil { scheduleAudioCheck(after: 1) }
                return
            }
        }
        if #available(iOS 27.0, *), notification.name == AVAudioSession.didBecomeActiveNotification,
           player == nil, restoringAudio || audioCheck != nil {
            // Successful activation can notify before player creation/play fails.
            // Do not let its delayed echo turn one-second retries into a busy loop.
            return
        }
        // Routes, rendering/mute hints and lifecycle transitions are checkpoints,
        // not reasons to rebuild healthy playback or override the user's mute.
        resumeAudio()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        // Keep a weak object identity across the hop, not an address that may be reused.
        Self.onMain { [weak self, weak player] in
            guard let self, let player, self.player === player, self.audioEnabled else { return }
            self.playerStopped(nil)
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        // Keep a weak object identity across the hop, not an address that may be reused.
        Self.onMain { [weak self, weak player] in
            guard let self, let player, self.player === player, self.audioEnabled else { return }
            self.playerStopped(error)
        }
    }

    private nonisolated static func onMain(_ action: @escaping @MainActor @Sendable () -> Void) {
        if Thread.isMainThread {
            MainActor.assumeIsolated { action() }
        } else {
            Task { @MainActor in action() }
        }
    }
}
