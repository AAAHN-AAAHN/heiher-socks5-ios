import AVFAudio
import CoreLocation
import SwiftUI
#if canImport(Combine)
import Combine
#endif

/// MainActor facade: persisted intent and location callbacks; AV calls are owned
/// exclusively by LoopAudioService's I/O lane, never by a view or a timer here.
@MainActor
final class BackgroundKeepAlive: NSObject, @MainActor ObservableObject, @preconcurrency CLLocationManagerDelegate {
    let objectWillChange = ObservableObjectPublisher()
    private(set) var locationEnabled = false
    private(set) var audioEnabled = false
    private(set) var locationState = "Off"
    private(set) var readCount = 0
    private(set) var lastRead: Date?
    private(set) var audioState = "Off"
    private(set) var audioDetail = ""

    private var locationManager: CLLocationManager?
    private var updating = false
    private var requestedPermission = false
    private let audio: LoopAudioService
    private var audioOwner: UInt64 = 0

    private var locationValues: (Bool, String, Int, Date?) {
        (locationEnabled, locationState, readCount, lastRead)
    }

    private func publishLocationChange(from previous: (Bool, String, Int, Date?)) {
        // All values and effects agree before a subscriber can accept newer intent.
        // No location write follows this synchronous publication.
        if previous != locationValues { objectWillChange.send() }
    }

    private func isCurrentLocationManager(_ manager: CLLocationManager) -> Bool {
        locationEnabled && manager === locationManager
    }

    init(audioService: LoopAudioService? = nil) {
        audio = audioService ?? .shared
        super.init()
        audioOwner = audio.register { [weak self] state in
            guard let self else { return }
            guard audioState != state.text || audioDetail != state.detail else { return }
            audioState = state.text
            audioDetail = state.detail
            // Publish only after both fields agree. A synchronous observer may
            // accept a newer Off, which this callback must never overwrite.
            objectWillChange.send()
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
        let previous = locationValues
        defer { publishLocationChange(from: previous) }
        if locationEnabled { openLocation() }
        if audioEnabled { audio.notify(.available) }
    }

    func setLocation(_ enabled: Bool) {
        let previous = locationValues
        defer { publishLocationChange(from: previous) }
        locationEnabled = enabled
        if enabled {
            openLocation()
        } else {
            let manager = locationManager
            locationManager = nil
            updating = false
            requestedPermission = false
            locationState = "Off"
            // Reentrant callbacks cannot find or detach a later manager.
            manager?.delegate = nil
            manager?.stopUpdatingLocation()
        }
    }

    private func openLocation() {
        guard locationEnabled else { return }
        if locationManager == nil {
            let manager = CLLocationManager()
            guard locationEnabled, locationManager == nil else { return }
            locationManager = manager
            // Coordinates are discarded; navigation-grade accuracy is unnecessary.
            manager.desiredAccuracy = kCLLocationAccuracyThreeKilometers
            manager.distanceFilter = kCLDistanceFilterNone
            manager.allowsBackgroundLocationUpdates = true
            manager.showsBackgroundLocationIndicator = true
            manager.pausesLocationUpdatesAutomatically = false
            // A delegate may report authorization immediately; configure first.
            guard isCurrentLocationManager(manager) else { return }
            manager.delegate = self
        }
        if let manager = locationManager { authorizeAndStart(manager) }
    }

    private func authorizeAndStart(_ manager: CLLocationManager) {
        guard isCurrentLocationManager(manager) else { return }
        let authorization = manager.authorizationStatus
        guard isCurrentLocationManager(manager) else { return }
        switch authorization {
        case .notDetermined:
            // Authorization can return here after a reset or temporary grant.
            locationState = "Waiting for location permission"
            if updating {
                updating = false
                manager.stopUpdatingLocation()
            }
            guard isCurrentLocationManager(manager), !updating else { return }
            let stillUndetermined = manager.authorizationStatus == .notDetermined
            guard isCurrentLocationManager(manager), stillUndetermined else { return }
            let active = UIApplication.shared.applicationState == .active
            if isCurrentLocationManager(manager), !updating, !requestedPermission, active {
                requestedPermission = true
                manager.requestAlwaysAuthorization()
            }
        case .authorizedAlways, .authorizedWhenInUse:
            requestedPermission = false
            guard !updating else { return }
            // A new When-In-Use background session must be started in foreground.
            // Do not interrupt a session that was already started there.
            let active = UIApplication.shared.applicationState == .active
            guard isCurrentLocationManager(manager), !updating else { return }
            if authorization == .authorizedWhenInUse, !active {
                locationState = "Return to the app to start the location session"
                return
            }
            updating = true
            locationState = "Waiting for a location update"
            manager.startUpdatingLocation()
        case .denied, .restricted:
            updating = false
            requestedPermission = false
            locationState = "Location access unavailable; enable it in Settings"
            manager.stopUpdatingLocation()
        @unknown default:
            updating = false
            locationState = "Location authorization unavailable"
            manager.stopUpdatingLocation()
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        guard isCurrentLocationManager(manager) else { return }
        let previous = locationValues
        defer { publishLocationChange(from: previous) }
        authorizeAndStart(manager)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard manager === locationManager, locationEnabled, updating, !locations.isEmpty else { return }
        let previous = locationValues
        // Keep only diagnostic count/time, never coordinates or a location history.
        readCount += 1
        lastRead = Date()
        locationState = "Continuous location active"
        publishLocationChange(from: previous)
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        guard isCurrentLocationManager(manager) else { return }
        let previous = locationValues
        defer { publishLocationChange(from: previous) }
        let message = "Location error: \(error.localizedDescription)"
        guard isCurrentLocationManager(manager) else { return }
        // Commit diagnostics before a stop call can deliver a newer callback.
        // A temporary failure must not erase the user's saved preference.
        locationState = message
        if (error as? CLError)?.code == .denied {
            updating = false
            manager.stopUpdatingLocation()
        }
    }

    func setAudio(_ enabled: Bool) {
        // Explicit intent precedes any root persistence. Echoes use syncAudio.
        audio.setEnabled(enabled, owner: audioOwner)
        showAudioIntent(enabled)
    }

    func syncAudio(_ enabled: Bool) {
        guard audioEnabled != enabled else { return }
        audio.setEnabled(enabled, owner: audioOwner, explicit: false)
        showAudioIntent(enabled)
    }

    private func showAudioIntent(_ enabled: Bool) {
        let changed = audioEnabled != enabled
        audioEnabled = enabled
        let stopping = !enabled && !audioState.hasPrefix("Off")
        if stopping {
            audioState = "Off \u{2014} stopping"
            audioDetail = ""
        }
        // @Published willSet would allow an observer's newer intent to be
        // overwritten by this setter after reentry. No write follows this send.
        if changed || stopping { objectWillChange.send() }
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
        if #available(iOS 27.0, *), name == AVAudioSession.didBecomeInactiveNotification {
            let context = notification.userInfo?[AVAudioSession.deactivationContextKey] as? AVAudioSession.DeactivationContext
            // Our completed release may be reported after a newer On. Inspect
            // app-requested deactivation without invalidating healthy new work.
            // A real stopped player still recovers through the ordinary check.
            return context?.source == .app ? .hint : .interrupted
        }
        if #available(iOS 27.0, *), name == AVAudioSession.resumptionRecommendationNotification {
            let context = notification.userInfo?[AVAudioSession.resumptionContextKey] as? AVAudioSession.ResumptionContext
            return context?.recommendation == .shouldNotResume ? .hint : .available
        }
        return .hint
    }
}
