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
    private var waitingToRetry = false
    private var resumeOpportunityUsed = false
    private var resumeAfterRestore = false
    private var servicesUnavailable = false
    private var probingServices = false
    private static let serviceProbeInterval: TimeInterval = 5
    private var ownsAudioSession = false
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

    deinit {
        audioCheck?.invalidate()
        player?.delegate = nil
        player?.stop()
        // Pending activation/preparation has its own weak orphan completion.
        if ownsAudioSession, sessionTransition == nil, !servicesUnavailable {
            Self.changeAudioSession(false) { _, _ in }
        }
    }

    /// Called at launch and on return to the foreground. Safe to call repeatedly.
    func restore() {
        if locationEnabled { openLocation() }
        if audioEnabled { requestAudioResume(servicesAvailable: true) }
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
            // An explicit user request may retry; generic notifications may not.
            servicesUnavailable = false
            waitingToRetry = false
            resumeAudio()
        } else {
            waitingToRetry = false
            resumeOpportunityUsed = false
            resumeAfterRestore = false
            servicesUnavailable = false
            probingServices = false
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
        guard audioEnabled, !servicesUnavailable || probingServices else { return }
        // One transition at a time, including the callback's hop to MainActor.
        // Invalidations during activation must not publish stale playback success.
        guard !restoringAudio, sessionTransition == nil else {
            if recreate { invalidatedDuringRestore = true }
            return
        }
        guard !deactivationPending else { deactivateAudio(); return }
        if waitingToRetry {
            if audioCheck == nil { scheduleAudioCheck(after: 1) }
            return
        }
        // A second silent stop before a healthy sample is the same failure episode.
        if !recreate, player != nil, !audioIsHealthy(), playerFailurePending {
            retryAudio(nil)
            return
        }
        restoringAudio = true
        invalidatedDuringRestore = false
        if recreate { discardPlayer() }
        guard audioEnabled, !deactivationPending else { finishAudioRestore(); return }
        if audioIsHealthy() {
            if audioCheck == nil { scheduleAudioCheck(after: 1) }
            finishAudioRestore()
            return
        }
        if player != nil {
            playerFailurePending = true
            if !audioConfigurationMatches() { discardPlayer() }
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
            if invalidatedDuringRestore {
                retryAudio(nil)
                finishAudioRestore()
                return
            }
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
            // A successful fresh activation establishes service availability;
            // no reset notification is required for a bounded availability probe.
            servicesUnavailable = false
            probingServices = false
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
        if deactivationPending {
            deactivateAudio()
        } else if resumeAfterRestore {
            resumeAfterRestore = false
            if audioEnabled, !servicesUnavailable, !audioIsHealthy() {
                waitingToRetry = false
                resumeAudio()
            }
        }
    }

    private func deactivateAudio() {
        guard deactivationPending, !restoringAudio, sessionTransition == nil else { return }
        deactivationPending = false
        beginSessionTransition(active: false)
    }

    private func audioDeactivated(_ success: Bool, error: Error?) {
        guard sessionTransition == .deactivating else { return }
        sessionTransition = nil
        if success, error == nil { ownsAudioSession = false }
        resumeAfterRestore = false
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
        if active { ownsAudioSession = true }
        Self.changeAudioSession(active) { [weak self] success, error in
            Self.onMain { [weak self] in
                guard let self else {
                    // A released controller must not leave its late activation on.
                    if active { Self.changeAudioSession(false) { _, _ in } }
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
        playerFailurePending = true
        waitingToRetry = true
        probingServices = false
        audioState = servicesUnavailable ? "Waiting for audio services" :
            "Waiting to resume: \(error?.localizedDescription ?? "Audio playback stopped")"
        // One deadline for the entire failed episode, including notification storms.
        if audioCheck == nil {
            scheduleAudioCheck(after: servicesUnavailable ? Self.serviceProbeInterval : 1)
        }
    }

    private func playerStopped(_ error: Error?, resumeOpportunity: Bool = false) {
        guard audioEnabled else { return }
        let expedite = resumeOpportunity && !resumeOpportunityUsed
        if expedite {
            resumeOpportunityUsed = true
            waitingToRetry = false
        }
        if restoringAudio || sessionTransition != nil {
            invalidatedDuringRestore = true
            playerFailurePending = true
            if expedite { resumeAfterRestore = true }
        } else if playerFailurePending && !expedite {
            retryAudio(error)
        } else {
            playerFailurePending = true
            resumeAudio(recreate: true)
        }
    }

    /// Availability advice is not resource invalidation. Coalesce duplicate advice
    /// and preserve valid in-flight work; only a stale completion needs a fresh start.
    private func requestAudioResume(servicesAvailable: Bool = false) {
        guard audioEnabled else { return }
        if servicesAvailable { servicesUnavailable = false }
        guard !servicesUnavailable, !audioIsHealthy() else { return }
        if restoringAudio || sessionTransition != nil {
            if !resumeOpportunityUsed, invalidatedDuringRestore {
                resumeOpportunityUsed = true
                resumeAfterRestore = true
            }
            return
        }
        if !resumeOpportunityUsed {
            resumeOpportunityUsed = true
            waitingToRetry = false
        }
        resumeAudio()
    }

    private func audioConfigurationMatches() -> Bool {
        let session = AVAudioSession.sharedInstance()
        return session.category == .playback && session.mode == .default
            && session.categoryOptions == [.mixWithOthers]
    }

    private func audioIsHealthy() -> Bool {
        player?.isPlaying == true && audioConfigurationMatches()
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
                self.waitingToRetry = false
                self.probingServices = self.servicesUnavailable
                if self.audioIsHealthy() {
                    self.playerFailurePending = false
                    self.resumeOpportunityUsed = false
                }
                self.resumeAudio()
            }
        }
        audioCheck = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    func audioEvent(_ notification: Notification) {
        guard audioEnabled, Self.audioNotifications.contains(notification.name) else { return }
        let name = notification.name
        if name == AVAudioSession.mediaServicesWereLostNotification {
            let newlyUnavailable = !servicesUnavailable
            if newlyUnavailable { resumeOpportunityUsed = false }
            servicesUnavailable = true
            probingServices = false
            invalidatedDuringRestore = true
            playerFailurePending = true
            waitingToRetry = true
            if newlyUnavailable {
                audioCheck?.invalidate()
                audioCheck = nil
            }
            // A preparation worker exclusively owns its detached player until return.
            let wasRestoring = restoringAudio
            restoringAudio = true
            discardPlayer()
            restoringAudio = wasRestoring
            if audioEnabled {
                audioState = "Waiting for audio services"
                // Do not permanently depend on a reset/end notification being
                // delivered. A lost service is probed slowly, never on every hint.
                if audioCheck == nil { scheduleAudioCheck(after: Self.serviceProbeInterval) }
            }
            if deactivationPending { deactivateAudio() }
            return
        }
        if name == AVAudioSession.mediaServicesWereResetNotification {
            servicesUnavailable = false
            playerStopped(nil, resumeOpportunity: true)
            return
        }
        if name == AVAudioSession.interruptionNotification {
            // Preserve explicit On even without shouldResume metadata. A begun or
            // unknown interruption invalidates; an end is an availability checkpoint.
            if notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt == 0 {
                requestAudioResume()
            } else if !servicesUnavailable || probingServices {
                playerStopped(nil)
            }
            return
        }
        if #available(iOS 27.0, *) {
            if name == AVAudioSession.didBecomeInactiveNotification {
                if !servicesUnavailable || probingServices { playerStopped(nil) }
                return
            }
            if name == AVAudioSession.resumptionRecommendationNotification {
                let context = notification.userInfo?[AVAudioSession.resumptionContextKey]
                    as? AVAudioSession.ResumptionContext
                // A negative hint never erases On or stops healthy playback. It
                // simply does not bypass the existing bounded automatic retry.
                if context?.recommendation == .shouldNotResume {
                    resumeAudio()
                } else {
                    requestAudioResume(servicesAvailable: true)
                }
                return
            }
        }
        if name == AVAudioSession.routeChangeNotification,
           notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                == AVAudioSession.RouteChangeReason.categoryChange.rawValue {
            if !audioConfigurationMatches() {
                if !servicesUnavailable || probingServices { playerStopped(nil) }
                return
            }
            // Own configuration echo cannot start a second restore or bypass retry.
            if player == nil { return }
        }
        if #available(iOS 27.0, *), name == AVAudioSession.didBecomeActiveNotification,
           player == nil, restoringAudio || audioCheck != nil {
            return
        }
        // Route/mute/rendering/lifecycle hints inspect; they never cancel backoff.
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
