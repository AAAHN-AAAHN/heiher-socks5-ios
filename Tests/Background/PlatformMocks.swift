// Scripted platform doubles for the unmodified production controller logic.
// These tests cannot simulate actual iOS scheduling or call/audio priority.
import Foundation

protocol ObservableObject {}
@propertyWrapper struct Published<Value> {
    var wrappedValue: Value
}
protocol CLLocationManagerDelegate: AnyObject {
    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager)
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation])
    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error)
}
protocol AVAudioPlayerDelegate: AnyObject {
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool)
    func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?)
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
    weak var delegate: CLLocationManagerDelegate?
    var authorizationStatus = initialAuthorization
    var desiredAccuracy = 0.0
    var distanceFilter = 0.0
    var allowsBackgroundLocationUpdates = false
    var showsBackgroundLocationIndicator = false
    var pausesLocationUpdatesAutomatically = true
    var starts = 0
    var stops = 0
    var requests = 0
    init() { Self.instances.append(self) }
    func requestAlwaysAuthorization() { requests += 1 }
    func startUpdatingLocation() { starts += 1 }
    func stopUpdatingLocation() { stops += 1 }
}

@MainActor final class UIApplication {
    enum State { case active, inactive, background }
    static let shared = UIApplication()
    var applicationState = State.active
    static let willResignActiveNotification = Notification.Name("WillResignActive")
    static let didEnterBackgroundNotification = Notification.Name("DidEnterBackground")
    static let willEnterForegroundNotification = Notification.Name("WillEnterForeground")
    static let protectedDataDidBecomeAvailableNotification = Notification.Name("ProtectedDataAvailable")
    static let didBecomeActiveNotification = Notification.Name("AppDidBecomeActive")
}

let AVAudioSessionInterruptionTypeKey = "InterruptionType"
let AVAudioSessionInterruptionOptionKey = "InterruptionOption"
let AVAudioSessionRouteChangeReasonKey = "RouteChangeReason"

@MainActor final class AVAudioSession {
    enum Category { case playback, ambient }
    enum Mode { case `default`, voiceChat }
    enum InterruptionType: UInt { case ended = 0, began = 1 }
    enum RouteChangeReason: UInt { case newDeviceAvailable = 1, oldDeviceUnavailable = 2, categoryChange = 3 }
    struct CategoryOptions: OptionSet {
        let rawValue: Int
        static let mixWithOthers = Self(rawValue: 1)
    }
    struct SetActiveOptions: OptionSet {
        let rawValue: Int
        static let notifyOthersOnDeactivation = Self(rawValue: 1)
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
    static let resumptionRecommendationNotification = Notification.Name("ResumptionRecommendation")
    static let shared = AVAudioSession()
    static func sharedInstance() -> AVAudioSession { shared }
    var category = Category.ambient
    var mode = Mode.default
    var categoryOptions: CategoryOptions = []
    var prefersNoInterruptionsFromSystemAlerts = false
    var rejectActivation = false
    var rejectCategory = false
    var rejectPreference = false
    var activations = 0
    var deactivations = 0
    var configurations = 0
    var onCategory: (() -> Void)?
    var onActivation: (() -> Void)?
    func setCategory(_ category: Category, mode: Mode, options: CategoryOptions) throws {
        if rejectCategory { throw NSError(domain: "MockCategory", code: 1) }
        configurations += 1
        self.category = category
        self.mode = mode
        categoryOptions = options
        onCategory?()
    }
    func setPrefersNoInterruptionsFromSystemAlerts(_ value: Bool) throws {
        if rejectPreference { throw NSError(domain: "MockPreference", code: 1) }
        prefersNoInterruptionsFromSystemAlerts = value
    }
    func setActive(_ active: Bool, options: SetActiveOptions = []) throws {
        if active {
            activations += 1
            onActivation?()
            if rejectActivation { throw NSError(domain: "MockAudioPriority", code: 1) }
        } else { deactivations += 1 }
    }
}

@MainActor final class AVAudioPlayer {
    static var instances: [AVAudioPlayer] = []
    static var rejectInit = false
    static var rejectPlay = false
    static var onPlay: ((AVAudioPlayer) -> Void)?
    static var onStop: (() -> Void)?
    weak var delegate: AVAudioPlayerDelegate?
    var numberOfLoops = 0
    var isPlaying = false
    var plays = 0
    var stops = 0
    init(contentsOf url: URL) throws {
        if Self.rejectInit { throw NSError(domain: "MockDecoder", code: 1) }
        Self.instances.append(self)
    }
    func play() -> Bool {
        plays += 1
        isPlaying = !Self.rejectPlay
        let result = isPlaying
        Self.onPlay?(self)
        return result
    }
    func stop() { stops += 1; isPlaying = false; Self.onStop?() }
}

@MainActor enum Bundle {
    static let main = ResourceBundle()
    final class ResourceBundle {
        var resourceAvailable = true
        func url(forResource: String, withExtension: String) -> URL? {
            resourceAvailable ? URL(fileURLWithPath: "/Silence.wav") : nil
        }
    }
}

@MainActor final class Timer {
    static var scheduled: [Timer] = []
    static var live: [Timer] { scheduled.filter(\.valid) }
    let interval: TimeInterval
    var tolerance: TimeInterval = 0
    nonisolated(unsafe) var valid = true
    private let block: @Sendable (Timer) -> Void
    init(timeInterval: TimeInterval, repeats: Bool, block: @escaping @Sendable (Timer) -> Void) {
        precondition(!repeats)
        interval = timeInterval
        self.block = block
    }
    nonisolated func invalidate() { valid = false }
    func fireStale() { block(self) }
    func fire() {
        guard valid else { return }
        valid = false
        block(self)
        Self.scheduled.removeAll { !$0.valid }
    }
}

@MainActor enum RunLoop {
    static let main = MainRunLoop()
    @MainActor final class MainRunLoop {
        enum Mode { case common }
        func add(_ timer: Timer, forMode: Mode) {
            Timer.scheduled.removeAll { !$0.valid }
            Timer.scheduled.append(timer)
        }
    }
}
