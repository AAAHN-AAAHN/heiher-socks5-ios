import AVFAudio
import CoreLocation
import SwiftUI

/// Optional experiments only; the SOCKS5 engine is not changed.
@MainActor
final class BackgroundKeepAlive: NSObject, ObservableObject, CLLocationManagerDelegate {
    enum LocationMode { case off, continuous, held, cycled }

    @Published private(set) var locationMode: LocationMode = .off
    @Published private(set) var locationState = "Off"
    @Published private(set) var readCount = 0
    @Published private(set) var lastRead: Date?
    @Published private(set) var audioEnabled = false
    @Published private(set) var audioState = "Off"

    private var locationManager: CLLocationManager?
    private var readTimer: Timer?
    private var awaitingRead = false
    private var updating = false
    private var player: AVAudioPlayer?
    private var interrupted = false

    func selectLocation(_ mode: LocationMode) {
        readTimer?.invalidate()
        readTimer = nil
        closeLocation()
        locationMode = mode
        readCount = 0
        lastRead = nil
        locationState = "Off"
        if mode != .off { openLocation() }
    }

    private func openLocation() {
        guard locationMode != .off else { return }
        let manager = CLLocationManager()
        locationManager = manager
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
        manager.pausesLocationUpdatesAutomatically = false
        authorizeAndStart(manager)
    }

    private func authorizeAndStart(_ manager: CLLocationManager) {
        guard manager === locationManager, locationMode != .off else { return }
        switch manager.authorizationStatus {
        case .notDetermined:
            locationState = "Waiting for location permission"
            manager.requestAlwaysAuthorization()
        case .authorizedAlways, .authorizedWhenInUse:
            guard !updating else { return }
            updating = true
            awaitingRead = true
            locationState = "Waiting for a location update"
            manager.startUpdatingLocation()
        case .denied, .restricted:
            selectLocation(.off)
            locationState = "Location access denied; enable it in Settings"
        @unknown default:
            selectLocation(.off)
            locationState = "Location authorization unavailable"
        }
    }

    private func closeLocation() {
        locationManager?.stopUpdatingLocation()
        locationManager?.delegate = nil
        locationManager = nil
        updating = false
        awaitingRead = false
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        authorizeAndStart(manager)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard manager === locationManager, awaitingRead, !locations.isEmpty else { return }
        // Consume and discard the coordinates. Retain only diagnostic count/time.
        readCount += 1
        lastRead = Date()
        if locationMode == .continuous {
            locationState = "Continuous session active"
            return
        }
        awaitingRead = false
        if locationMode == .cycled {
            closeLocation()
            locationState = "Session closed; waiting 5 s"
        } else {
            locationState = "Session open; waiting 5 s"
        }
        let timer = Timer(timeInterval: 5, target: self,
                          selector: #selector(readAgain), userInfo: nil, repeats: false)
        readTimer = timer
        RunLoop.main.add(timer, forMode: .common)
    }

    @objc private func readAgain() {
        readTimer = nil
        switch locationMode {
        case .held:
            // Keep the service open, then wait for the NEXT callback, not cached data.
            awaitingRead = true
            locationState = "Session open; waiting for next update"
        case .cycled:
            openLocation()
        default:
            break
        }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        guard manager === locationManager else { return }
        if (error as? CLError)?.code == .denied {
            selectLocation(.off)
        }
        locationState = "Location error: \(error.localizedDescription)"
    }

    func setAudio(_ enabled: Bool) {
        audioEnabled = enabled
        interrupted = false
        if enabled {
            startAudio()
        } else {
            stopAudio()
            audioState = "Off"
        }
    }

    private func startAudio() {
        guard audioEnabled, !interrupted else { return }
        do {
            guard let url = Bundle.main.url(forResource: "Silence", withExtension: "wav") else {
                throw NSError(domain: "BackgroundKeepAlive", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: "Silence.wav is missing"])
            }
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
            try session.setActive(true)
            if player == nil {
                player = try AVAudioPlayer(contentsOf: url)
                player?.numberOfLoops = -1
                player?.prepareToPlay()
            }
            guard player?.play() == true else {
                throw NSError(domain: "BackgroundKeepAlive", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "Audio playback could not start"])
            }
            audioState = "Playing silent WAV continuously"
        } catch {
            stopAudio()
            audioEnabled = false
            audioState = "Audio error: \(error.localizedDescription)"
        }
    }

    private func stopAudio() {
        player?.stop()
        player = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    func audioInterruption(_ notification: Notification) {
        guard audioEnabled,
              let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        if type == .began {
            interrupted = true
            player?.pause()
            audioState = "Interrupted by iOS"
        } else {
            let rawOptions = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            let mayResume = AVAudioSession.InterruptionOptions(rawValue: rawOptions).contains(.shouldResume)
            interrupted = !mayResume
            if mayResume {
                startAudio()
            } else {
                audioState = "Paused; toggle audio off/on to resume"
            }
        }
    }

    func audioServicesReset() {
        player = nil
        interrupted = false
        if audioEnabled { audioState = "Audio reset; return to the app to resume" }
        if UIApplication.shared.applicationState == .active { becameActive() }
    }

    func becameActive() {
        if audioEnabled, !interrupted, player?.isPlaying != true { startAudio() }
    }
}
