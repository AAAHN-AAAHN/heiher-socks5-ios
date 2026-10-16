import AVFAudio
import CoreLocation
import SwiftUI

/// MainActor facade: persisted intent and location callbacks; AV calls are owned
/// exclusively by LoopAudioService's I/O lane, never by a view or a timer here.
@MainActor
final class BackgroundKeepAlive: NSObject, ObservableObject, @preconcurrency CLLocationManagerDelegate {
    @Published private(set) var locationEnabled = false
    @Published private(set) var audioEnabled = false
    @Published private(set) var locationState = "Off"
    @Published private(set) var readCount = 0
    @Published private(set) var lastRead: Date?
    @Published private(set) var audioState = "Off"
    @Published private(set) var audioDetail = ""

    private var locationManager: CLLocationManager?
    private var updating = false
    private var requestedPermission = false
    private let audio: LoopAudioService
    private var audioOwner: UInt64 = 0

    init(audioService: LoopAudioService? = nil) {
        audio = audioService ?? .shared
        super.init()
        audioOwner = audio.register { [weak self] state in
            guard let self else { return }
            if audioState != state.text { audioState = state.text }
            if audioDetail != state.detail { audioDetail = state.detail }
        }
    }

    deinit { audio.unregister(audioOwner) }

    // Both the subscriber and handler use this registry: no unhandled new names.
    // Keep the legacy notification for compatibility alongside the iOS 27 signals.
    private static let sessionLifecycleNotifications: [Notification.Name] = {
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
        var names = sessionLifecycleNotifications + [
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

    /// Calling this repeatedly never creates another owner or subscription.
    func restore() {
        if locationEnabled { openLocation() }
        if audioEnabled { audio.notify(.available) }
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
        audioEnabled = enabled
        // Explicit intent precedes any root persistence. Echoes use syncAudio.
        audio.setEnabled(enabled, owner: audioOwner)
    }

    func syncAudio(_ enabled: Bool) {
        guard audioEnabled != enabled else { return }
        audioEnabled = enabled
        audio.setEnabled(enabled, owner: audioOwner, explicit: false)
    }

    func audioEvent(_ notification: Notification) {
        guard audioEnabled, Self.audioNotifications.contains(notification.name) else { return }
        audio.notify(Self.audioEventValue(notification))
    }

    /// Normalize notification metadata without querying a mutable AV object.
    nonisolated static func audioEventValue(_ notification: Notification) -> LoopAudioService.Event {
        let name = notification.name
        if name == AVAudioSession.mediaServicesWereLostNotification { return .mediaLost }
        if name == AVAudioSession.mediaServicesWereResetNotification { return .mediaReset }
        if name == AVAudioSession.interruptionNotification {
            guard let type = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt else { return .hint }
            if type == AVAudioSession.InterruptionType.began.rawValue { return .interrupted }
            guard type == AVAudioSession.InterruptionType.ended.rawValue else { return .hint }
            let flags = notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt ?? 0
            return AVAudioSession.InterruptionOptions(rawValue: flags).contains(.shouldResume) ? .available : .hint
        }
        if name == AVAudioSession.routeChangeNotification { return .routeChanged }
        if name == UIApplication.willEnterForegroundNotification ||
            name == UIApplication.protectedDataDidBecomeAvailableNotification { return .available }
        if #available(iOS 27.0, *), name == AVAudioSession.didBecomeInactiveNotification { return .interrupted }
        if #available(iOS 27.0, *), name == AVAudioSession.resumptionRecommendationNotification {
            let context = notification.userInfo?[AVAudioSession.resumptionContextKey] as? AVAudioSession.ResumptionContext
            return context?.recommendation == .shouldNotResume ? .hint : .available
        }
        return .hint
    }
}
