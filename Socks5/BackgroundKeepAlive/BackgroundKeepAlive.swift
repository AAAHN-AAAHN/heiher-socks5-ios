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
            manager.delegate = self
            // Coordinates are discarded; navigation-grade accuracy is unnecessary.
            manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
            manager.distanceFilter = kCLDistanceFilterNone
            manager.allowsBackgroundLocationUpdates = true
            manager.showsBackgroundLocationIndicator = true
            manager.pausesLocationUpdatesAutomatically = false
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
        audioEnabled = enabled
        if enabled {
            resumeAudio()
        } else {
            audioCheck?.invalidate()
            audioCheck = nil
            discardPlayer()
            try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
            audioState = "Off"
        }
    }

    private func resumeAudio() {
        guard audioEnabled else { return }
        if player?.isPlaying == true {
            if audioCheck == nil { scheduleAudioCheck(after: 2) }
            return
        }
        audioCheck?.invalidate()
        audioCheck = nil
        do {
            let session = AVAudioSession.sharedInstance()
            if player == nil || session.category != .playback || session.mode != .default || session.categoryOptions != [.mixWithOthers] {
                try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            }
            if player == nil || !session.prefersNoInterruptionsFromSystemAlerts {
                try? session.setPrefersNoInterruptionsFromSystemAlerts(true)
            }
            try session.setActive(true)
            if player == nil {
                guard let url = Bundle.main.url(forResource: "Silence", withExtension: "wav") else {
                    throw NSError(domain: "BackgroundKeepAlive", code: 1,
                                  userInfo: [NSLocalizedDescriptionKey: "Silence.wav is missing"])
                }
                player = try AVAudioPlayer(contentsOf: url)
                player?.delegate = self
                player?.numberOfLoops = -1
            }
            guard player?.play() == true else {
                throw NSError(domain: "BackgroundKeepAlive", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "Audio playback could not start"])
            }
            audioState = "Playing silent WAV continuously"
            scheduleAudioCheck(after: 2)
        } catch {
            retryAudio(error)
        }
    }

    private func retryAudio(_ error: Error?) {
        guard audioEnabled else { return }
        discardPlayer()
        audioState = "Waiting to resume: \(error?.localizedDescription ?? "Audio decoder stopped")"
        scheduleAudioCheck(after: 1)
    }

    private func discardPlayer() {
        player?.delegate = nil
        player?.stop()
        player = nil
    }

    private func scheduleAudioCheck(after delay: TimeInterval) {
        audioCheck?.invalidate()
        // One timer: two-second health checks or one-second retries until disabled.
        let timer = Timer(timeInterval: delay, repeats: false) { [weak self] timer in
            MainActor.assumeIsolated {
                guard let self, self.audioCheck === timer else { return }
                self.audioCheck = nil
                self.resumeAudio()
            }
        }
        audioCheck = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    func audioEvent(_ notification: Notification) {
        guard audioEnabled else { return }
        switch notification.name {
        case AVAudioSession.interruptionNotification:
            // Every interruption is actionable, including missing/unknown metadata.
            // Recreate even if an interrupted player still reports isPlaying.
            discardPlayer()
        case AVAudioSession.mediaServicesWereLostNotification,
             AVAudioSession.mediaServicesWereResetNotification:
            discardPlayer()
        case AVAudioSession.routeChangeNotification:
            let reason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            if reason == AVAudioSession.RouteChangeReason.categoryChange.rawValue {
                let session = AVAudioSession.sharedInstance()
                if session.category == .playback && session.mode == .default && session.categoryOptions == [.mixWithOthers] {
                    if audioCheck == nil { scheduleAudioCheck(after: player?.isPlaying == true ? 2 : 1) }
                    return
                }
                discardPlayer()
            }
        default:
            return
        }
        resumeAudio()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        let id = ObjectIdentifier(player)
        onMain { [weak self] in
            guard let self, let current = self.player,
                  ObjectIdentifier(current) == id, self.audioEnabled else { return }
            self.discardPlayer()
            self.resumeAudio()
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        let id = ObjectIdentifier(player)
        onMain { [weak self] in
            guard let self, let current = self.player,
                  ObjectIdentifier(current) == id, self.audioEnabled else { return }
            // Decoder failures can repeat immediately; pace retries rather than spin.
            self.retryAudio(error)
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
