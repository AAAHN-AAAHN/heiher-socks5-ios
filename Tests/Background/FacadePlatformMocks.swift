import Foundation
#if canImport(Combine)
import Combine
#else
protocol ObservableObject: AnyObject {
    associatedtype ObjectWillChangePublisher = ObservableObjectPublisher
    var objectWillChange: ObjectWillChangePublisher { get }
}
@propertyWrapper struct Published<Value> { var wrappedValue: Value }
// Keep the publisher type non-Sendable like Combine's actual declaration.
// Only this fixture's subscriber state and operations belong to MainActor.
final class ObservableObjectPublisher {
    @MainActor private var next = 0
    @MainActor private var observers: [Int: (()) -> Void] = [:]
    @MainActor init() {}
    @MainActor func sink(receiveValue: @escaping (()) -> Void) -> FacadeSubscription {
        next += 1
        let id = next
        observers[id] = receiveValue
        return FacadeSubscription { [weak self] in self?.observers.removeValue(forKey: id) }
    }
    @MainActor func send() { for callback in Array(observers.values) { callback(()) } }
}
@MainActor final class FacadeSubscription {
    private let end: () -> Void
    init(_ end: @escaping () -> Void) { self.end = end }
    func cancel() { end() }
}
#endif

protocol CLLocationManagerDelegate: AnyObject {
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager)
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation])
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error)
}
enum CLAuthorizationStatus { case notDetermined, authorizedAlways, authorizedWhenInUse, denied, restricted }
let kCLLocationAccuracyThreeKilometers = 3000.0
let kCLDistanceFilterNone = -1.0
struct CLLocation {}
struct CLError: Error {
    enum Code { case denied, locationUnknown }
    let code: Code
}

@MainActor final class CLLocationManager {
    static var initialAuthorization = CLAuthorizationStatus.authorizedAlways
    static var instances: [CLLocationManager] = []
    static var notifyOnDelegate = false
    weak var delegate: CLLocationManagerDelegate? {
        didSet { if Self.notifyOnDelegate { delegate?.locationManagerDidChangeAuthorization(self) } }
    }
    var authorizationStatus = initialAuthorization
    var desiredAccuracy = 0.0
    var distanceFilter = 0.0
    var allowsBackgroundLocationUpdates = false
    var showsBackgroundLocationIndicator = false
    var pausesLocationUpdatesAutomatically = true
    var starts = 0
    var stops = 0
    var requests = 0
    var accuracyAtStart = 0.0
    var backgroundAtStart = false
    var pausingAtStart = true
    init() { Self.instances.append(self) }
    func requestAlwaysAuthorization() { requests += 1 }
    func startUpdatingLocation() {
        starts += 1
        accuracyAtStart = desiredAccuracy
        backgroundAtStart = allowsBackgroundLocationUpdates
        pausingAtStart = pausesLocationUpdatesAutomatically
    }
    func stopUpdatingLocation() { stops += 1 }
}

@MainActor final class UIApplication {
    enum State { case active, inactive, background }
    static let shared = UIApplication()
    var applicationState = State.active
    nonisolated static let willResignActiveNotification = Notification.Name("WillResignActive")
    nonisolated static let didEnterBackgroundNotification = Notification.Name("DidEnterBackground")
    nonisolated static let willEnterForegroundNotification = Notification.Name("WillEnterForeground")
    nonisolated static let protectedDataDidBecomeAvailableNotification = Notification.Name("ProtectedDataAvailable")
    nonisolated static let didBecomeActiveNotification = Notification.Name("AppDidBecomeActive")
}

let AVAudioSessionInterruptionTypeKey = "InterruptionType"
let AVAudioSessionInterruptionOptionKey = "InterruptionOption"
enum AVAudioSession {
    enum InterruptionType: UInt { case ended = 0, began = 1 }
    struct InterruptionOptions: OptionSet, Sendable {
        let rawValue: UInt
        static let shouldResume = Self(rawValue: 1)
    }
    static let interruptionNotification = Notification.Name("Interruption")
    static let routeChangeNotification = Notification.Name("RouteChange")
    static let mediaServicesWereLostNotification = Notification.Name("ServicesLost")
    static let mediaServicesWereResetNotification = Notification.Name("ServicesReset")
    static let silenceSecondaryAudioHintNotification = Notification.Name("SecondaryAudioHint")
    static let spatialPlaybackCapabilitiesChangedNotification = Notification.Name("SpatialCapabilities")
    static let renderingModeChangeNotification = Notification.Name("RenderingMode")
    static let renderingCapabilitiesChangeNotification = Notification.Name("RenderingCapabilities")
    static let outputMuteStateChangeNotification = Notification.Name("OutputMute")
    static let userIntentToUnmuteOutputNotification = Notification.Name("UnmuteIntent")
    static let didBecomeActiveNotification = Notification.Name("SessionActive")
    static let didBecomeInactiveNotification = Notification.Name("SessionInactive")
    enum ResumptionRecommendation: Sendable { case shouldResume, shouldNotResume }
    final class ResumptionContext: Sendable {
        let recommendation: ResumptionRecommendation
        init(_ recommendation: ResumptionRecommendation) { self.recommendation = recommendation }
    }
    static let resumptionContextKey = "ResumptionContext"
    static let resumptionRecommendationNotification = Notification.Name("ResumptionRecommendation")
}
