import AVFAudio
import CoreLocation
import SwiftUI

/// Saved background services, independent of the SOCKS5 server and statistics.
@MainActor
final class BackgroundKeepAlive: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate, AVAudioPlayerDelegate {
    @Published private(set) var locationEnabled: Bool
    @Published private(set) var audioEnabled: Bool
    @Published private(set) var locationState = "Off"
    @Published private(set) var readCount = 0
    @Published private(set) var lastRead: Date?
    @Published private(set) var audioState = "Off"

    private static let locationKey = "background.continuousLocation"
    private static let audioKey = "background.silentAudio"
    private let defaults: UserDefaults
    private var locationManager: CLLocationManager?
    private var updating = false
    private var requestedPermission = false
    private var player: AVAudioPlayer?
    private var audioCheck: Timer?
    private var retryDelay: TimeInterval = 1

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        locationEnabled = defaults.bool(forKey: Self.locationKey)
        audioEnabled = defaults.bool(forKey: Self.audioKey)
        super.init()
    }

    deinit { audioCheck?.invalidate() }

    /// Called at launch and on return to the foreground. Safe to call repeatedly.
    func restore() {
        if locationEnabled { openLocation() }
        if audioEnabled { resumeAudio() }
    }

    func setLocation(_ enabled: Bool) {
        locationEnabled = enabled
        defaults.set(enabled, forKey: Self.locationKey)
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
        defaults.set(enabled, forKey: Self.audioKey)
        retryDelay = 1
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
            if audioCheck == nil { scheduleAudioCheck(after: 5) }
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
            retryDelay = 1
            audioState = "Playing silent WAV continuously"
            scheduleAudioCheck(after: 5)
        } catch {
            retryAudio(error)
        }
    }

    private func retryAudio(_ error: Error?) {
        discardPlayer()
        audioState = "Waiting to resume: \(error?.localizedDescription ?? "Audio decoder stopped")"
        scheduleAudioCheck(after: retryDelay)
        retryDelay = min(retryDelay * 2, 8)
    }

    private func discardPlayer() {
        player?.delegate = nil
        player?.stop()
        player = nil
    }

    private func scheduleAudioCheck(after delay: TimeInterval) {
        audioCheck?.invalidate()
        // One main-run-loop timer: cheap health checks, bounded retry rate on failure.
        let timer = Timer(timeInterval: delay, repeats: false) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.audioCheck = nil
                self?.resumeAudio()
            }
        }
        timer.tolerance = min(delay * 0.2, 1)
        audioCheck = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    func audioEvent(_ notification: Notification) {
        guard audioEnabled else { return }
        switch notification.name {
        case AVAudioSession.interruptionNotification:
            guard let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
            if type == .began { discardPlayer() }
            // The saved opt-in remains authoritative, even without shouldResume.
        case AVAudioSession.mediaServicesWereLostNotification,
             AVAudioSession.mediaServicesWereResetNotification:
            discardPlayer()
        case AVAudioSession.routeChangeNotification:
            let reason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            if reason == AVAudioSession.RouteChangeReason.categoryChange.rawValue { return }
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
