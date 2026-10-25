import Foundation
#if canImport(Combine)
import Combine
#endif

private final class FacadeValue<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: T
    init(_ value: T) { self.value = value }
    func use<R>(_ body: (inout T) -> R) -> R { lock.lock(); defer { lock.unlock() }; return body(&value) }
}
private final class FacadeEndpoint: LoopAudioEndpoint, Sendable {
    struct State {
        var playing = false
        var failures = 0
        var starts: [Double] = []
        var stops = 0
        var inspections = 0
    }
    let state = FacadeValue(State())
    func perform(_ command: LoopAudioService.Command, context: LoopAudioService.Context,
                 completion: @escaping @Sendable (LoopAudioService.Reply) -> Void) {
        let now = ProcessInfo.processInfo.systemUptime
        let reply = state.use { value -> LoopAudioService.Reply in
            switch command {
            case .stop: value.playing = false; value.stops += 1
            case .start:
                guard context.mayStart() else { return .init(superseded: true) }
                value.starts.append(now)
                if value.failures > 0 { value.failures -= 1; return .init(error: "Controlled activation rejection") }
                value.playing = true
            case .inspect: value.inspections += 1
            }
            return .init(sample: .init(generation: 1, epoch: context.epoch, playing: value.playing,
                configured: true, position: now.truncatingRemainder(dividingBy: 0.05), deviceTime: now,
                duration: 0.05, rate: 1, startedAt: now, finishedAt: now, bufferDuration: 0.001))
        }
        completion(reply)
    }
}
// Only the UIKit singleton selection is replaced for this host fixture. The
// injected service below always runs the actual service and facade bodies.
extension LoopAudioService {
    @MainActor static let shared = LoopAudioService { _, _ in FacadeEndpoint() }
}

@main struct FacadeBoundaryTests {
    @MainActor static var assertions = 0
    @MainActor static func check(_ value: Bool, _ message: String) {
        assertions += 1
        if !value {
            FileHandle.standardError.write(Data(("FAIL: " + message + "\n").utf8))
            fatalError(message)
        }
    }
    @MainActor static func until(_ condition: () -> Bool, _ message: String, timeout: Double = 3) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        while !condition() && ProcessInfo.processInfo.systemUptime < deadline {
            try await Task.sleep(nanoseconds: 1_000_000)
        }
        check(condition(), message)
    }
    @MainActor private static func occupyMainExecutorForSchedulingBoundary() {
        // Test-only synchronous blocking is deliberate: suspension with
        // Task.sleep would free the executor and erase this boundary. Darwin
        // forbids calling semaphore wait directly from an async function.
        _ = DispatchSemaphore(value: 0).wait(timeout: .now() + 1.1)
    }
    @MainActor static func main() async throws {
        let name = CommandLine.arguments[1]
        let endpoint = FacadeEndpoint()
        let service = LoopAudioService { _, _ in endpoint }
        var app: BackgroundKeepAlive? = BackgroundKeepAlive(audioService: service)
        func playing() -> Bool { app?.audioState == "Playing silent WAV continuously" }
        func off() -> Bool { app?.audioState == "Off" }
        func diagnostics() async -> LoopAudioService.Diagnostics {
            await withCheckedContinuation { continuation in service.diagnostics { continuation.resume(returning: $0) } }
        }
        func stop() async throws {
            app?.setAudio(false)
            try await until(off, "FACADE_OFF_DID_NOT_DRAIN")
        }
        switch name {
        case "reentry-intent":
            var once = false
            let subscription = app!.objectWillChange.sink { _ in
                if !once && app?.audioEnabled == true { once = true; app?.setAudio(false) }
            }
            app!.setAudio(true)
            check(once && app?.audioEnabled == false, "FACADE_REENTRANT_INTENT_OVERWRITTEN")
            var observed = await diagnostics()
            let deadline = ProcessInfo.processInfo.systemUptime + 3
            while (observed.operation != nil || !off() || endpoint.state.use { $0.playing }) &&
                    ProcessInfo.processInfo.systemUptime < deadline {
                try await Task.sleep(nanoseconds: 1_000_000)
                observed = await diagnostics()
            }
            check(!endpoint.state.use { $0.playing } && off() && !observed.timerActive,
                  "FACADE_REENTRANT_OFF_LOST")
            subscription.cancel()
        case "reentry-publication":
            var once = false
            let subscription = app!.objectWillChange.sink { _ in
                if !once && playing() { once = true; app?.setAudio(false) }
            }
            app!.setAudio(true)
            try await until({ once && off() && app?.audioEnabled == false }, "FACADE_PUBLICATION_OVERWROTE_OFF")
            check(app?.audioDetail == "", "FACADE_TORN_STATE_PUBLICATION")
            subscription.cancel()
        case "echo":
            app!.setAudio(true)
            try await until(playing, "FACADE_INITIAL_START")
            var publications = 0
            let subscription = app!.objectWillChange.sink { _ in publications += 1 }
            for _ in 0..<10_000 { app!.syncAudio(true) }
            check(publications == 0, "IDENTICAL_ECHO_PUBLISHED")
            for _ in 0..<100 { app!.restore() }
            try await Task.sleep(nanoseconds: 30_000_000)
            check(endpoint.state.use { $0.starts.count } == 1, "HEALTHY_RESTORE_RESTARTED")
            try await stop()
            subscription.cancel()
        case "owner":
            app!.setAudio(true)
            try await until(playing, "OWNER_INITIAL_START")
            var second: BackgroundKeepAlive? = BackgroundKeepAlive(audioService: service)
            second!.setAudio(true)
            let released = { [weak app] in app == nil }
            app = nil
            check(released(), "FACADE_OWNER_RETAINED")
            try await Task.sleep(nanoseconds: 30_000_000)
            check(endpoint.state.use { $0.playing && $0.stops == 0 }, "OLD_OWNER_RELEASE_STOPPED_NEW_OWNER")
            second = nil
            try await until({ endpoint.state.use { !$0.playing && $0.stops == 1 } }, "LAST_OWNER_CLEANUP_MISSING")
        case "notifications":
            let delivered = FacadeValue([Notification.Name]())
            let names = BackgroundKeepAlive.audioNotifications
            service.observeAudioNotifications(names) { note in
                delivered.use { $0.append(note.name) }
                return BackgroundKeepAlive.audioEventValue(note)
            }
            service.observeAudioNotifications(names) { _ in preconditionFailure("Duplicate subscription") }
            app!.setAudio(true)
            try await until(playing, "NOTIFICATION_INITIAL_START")
            for name in names { NotificationCenter.default.post(name: name, object: nil) }
            let posted = FacadeValue(false)
            DispatchQueue.global().async {
                for name in names { NotificationCenter.default.post(name: name, object: nil) }
                posted.use { $0 = true }
            }
            try await until({ posted.use { $0 } && delivered.use { $0.count == names.count * 2 } }, "POSTING_THREAD_REGISTRY_DELIVERY")
            check(Set(delivered.use { $0 }) == Set(names), "NOTIFICATION_REGISTRY_DROPPED_NAME")
            check(names.count == 17, "IOS27_NOTIFICATION_REGISTRY_INCOMPLETE")
            try await stop()
            let starts = endpoint.state.use { $0.starts.count }
            for name in names { NotificationCenter.default.post(name: name, object: nil) }
            try await Task.sleep(nanoseconds: 30_000_000)
            check(endpoint.state.use { $0.starts.count } == starts && off(), "NOTIFICATION_RESTARTED_OFF")
        case "inactive-source":
            service.observeAudioNotifications(BackgroundKeepAlive.audioNotifications,
                                              normalize: { BackgroundKeepAlive.audioEventValue($0) })
            func postInactive(_ context: Any?) {
                NotificationCenter.default.post(name: AVAudioSession.didBecomeInactiveNotification, object: nil,
                    userInfo: context.map { [AVAudioSession.deactivationContextKey: $0] })
            }
            func settled(_ starts: Int, _ message: String) async throws {
                let deadline = ProcessInfo.processInfo.systemUptime + 3
                var ready = false
                repeat {
                    let observed = await diagnostics()
                    ready = observed.operation == nil && playing() &&
                        endpoint.state.use { $0.playing && $0.starts.count == starts }
                    if !ready { try await Task.sleep(nanoseconds: 1_000_000) }
                } while !ready && ProcessInfo.processInfo.systemUptime < deadline
                check(ready, message)
            }
            app!.setAudio(true)
            try await settled(1, "INACTIVE_SOURCE_INITIAL_START")
            try await stop()
            app!.setAudio(true)
            try await settled(2, "INACTIVE_SOURCE_RENEWED_START")
            // Model a completed Off's application-deactivation notification
            // arriving after renewed playback. This is a controlled order,
            // not a claim about an observed device's notification timing.
            postInactive(AVAudioSession.DeactivationContext(.app))
            // Cross the notification's control drain before counting a later
            // inspection. An old in-flight sample is not a positive result.
            _ = await diagnostics()
            let inspections = endpoint.state.use { $0.inspections }
            let deadline = ProcessInfo.processInfo.systemUptime + 3
            var inspected = false
            repeat {
                let observedInspections = endpoint.state.use { $0.inspections }
                let observed = await diagnostics()
                let unchanged = endpoint.state.use { $0.starts.count == 2 && $0.playing }
                if !unchanged { check(false, "APP_DEACTIVATION_INVALIDATED_RENEWED_PLAYBACK") }
                inspected = observedInspections > inspections && observed.operation == nil && playing()
                if !inspected { try await Task.sleep(nanoseconds: 1_000_000) }
            } while !inspected && ProcessInfo.processInfo.systemUptime < deadline
            check(inspected, "APP_DEACTIVATION_NOT_INSPECTED")

            // The same-process host case is observable only through the actual
            // player's state; an application hint must still recover a stop.
            endpoint.state.use { $0.playing = false }
            postInactive(AVAudioSession.DeactivationContext(.app))
            try await settled(3, "APP_DEACTIVATION_STOP_NOT_RECOVERED")
            postInactive(AVAudioSession.DeactivationContext(.system))
            try await settled(4, "SYSTEM_DEACTIVATION_NOT_RECOVERED")
            postInactive(nil)
            try await settled(5, "MISSING_DEACTIVATION_CONTEXT_NOT_RECOVERED")
            postInactive("malformed")
            try await settled(6, "MALFORMED_DEACTIVATION_CONTEXT_NOT_RECOVERED")

            let legacy = Notification(name: AVAudioSession.interruptionNotification,
                userInfo: [AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.began.rawValue])
            NotificationCenter.default.post(legacy)
            try await settled(7, "LEGACY_BEGIN_NOT_RECOVERED")
            let ended = Notification(name: AVAudioSession.interruptionNotification,
                userInfo: [AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.ended.rawValue,
                           AVAudioSessionInterruptionOptionKey: AVAudioSession.InterruptionOptions.shouldResume.rawValue])
            if case .available = BackgroundKeepAlive.audioEventValue(ended) {} else {
                check(false, "LEGACY_RESUME_ADVICE_CHANGED")
            }
            let noResume = Notification(name: AVAudioSession.interruptionNotification,
                userInfo: [AVAudioSessionInterruptionTypeKey: AVAudioSession.InterruptionType.ended.rawValue])
            if case .hint = BackgroundKeepAlive.audioEventValue(noResume) {} else {
                check(false, "LEGACY_NEGATIVE_ADVICE_CHANGED")
            }
            if case .hint = BackgroundKeepAlive.audioEventValue(Notification(name: AVAudioSession.interruptionNotification)) {} else {
                check(false, "LEGACY_MISSING_METADATA_CHANGED")
            }
            try await stop()
            let starts = endpoint.state.use { $0.starts.count }
            postInactive(AVAudioSession.DeactivationContext(.app))
            postInactive(AVAudioSession.DeactivationContext(.system))
            postInactive(nil)
            postInactive("malformed")
            _ = await diagnostics()
            check(endpoint.state.use { $0.starts.count == starts } && off(), "INACTIVE_SOURCE_RESTARTED_OFF")
        case "scheduling":
            endpoint.state.use { $0.failures = 100 }
            app!.setAudio(true)
            try await until({ endpoint.state.use { !$0.starts.isEmpty } }, "INITIAL_RETRY_NOT_ENTERED")
            occupyMainExecutorForSchedulingBoundary()
            let starts = endpoint.state.use { $0.starts }
            check(starts.count == 3, "CONTROL_TIMER_STOPPED_WITH_MAIN")
            check(starts[1] - starts[0] >= 0.45 && starts[2] - starts[1] >= 0.45,
                  "DEFAULT_RETRY_PACING_SHORTENED")
            endpoint.state.use { $0.failures = 0 }
            service.notify(.available)
            try await until(playing, "FIRST_AVAILABILITY_DID_NOT_EXPEDITE", timeout: 0.3)
            try await stop()
        case "location":
            app!.setLocation(true)
            let manager = CLLocationManager.instances.last!
            check(manager.starts == 1 && manager.allowsBackgroundLocationUpdates && !manager.pausesLocationUpdatesAutomatically,
                  "LOCATION_CONTRACT_CHANGED")
            app!.setAudio(true)
            try await until(playing, "INDEPENDENT_AUDIO_START")
            app!.setLocation(false)
            check(app!.audioEnabled && endpoint.state.use { $0.playing }, "LOCATION_STOP_DISABLED_AUDIO")
            try await stop()
            app!.setLocation(true)
            check(!app!.audioEnabled && app!.locationEnabled, "AUDIO_STOP_DISABLED_LOCATION")
            app!.setLocation(false)
            // Use the actual facade publisher. Darwin supplies Apple Combine;
            // Linux supplies the same synchronous object publisher boundary.
            // Publication must commit location values before nested user intent.
            for scenario in ["intent-off", "intent-on", "start-off", "permission-off", "update-off", "off-state-on"] {
                CLLocationManager.initialAuthorization = scenario == "permission-off" ? .notDetermined : .authorizedAlways
                if ["intent-on", "update-off", "off-state-on"].contains(scenario) { app!.setLocation(true) }
                let updateManager = CLLocationManager.instances.last
                let beforeManagers = CLLocationManager.instances.count
                let nestedOn = scenario == "intent-on" || scenario == "off-state-on"
                var reentered = false
                var startsAtOff = 0
                var requestsAtOff = 0
                let subscription = app!.objectWillChange.sink { _ in
                    guard !reentered else { return }
                    if scenario == "off-state-on", app!.locationEnabled { return }
                    if scenario == "start-off" || scenario == "permission-off" {
                        guard app!.locationEnabled, CLLocationManager.instances.count > beforeManagers else { return }
                    }
                    reentered = true
                    app!.setLocation(nestedOn)
                    startsAtOff = CLLocationManager.instances.reduce(0) { $0 + $1.starts }
                    requestsAtOff = CLLocationManager.instances.reduce(0) { $0 + $1.requests }
                }
                switch scenario {
                case "intent-on", "off-state-on": app!.setLocation(false)
                case "update-off": app!.locationManager(updateManager!, didUpdateLocations: [CLLocation()])
                default: app!.setLocation(true)
                }
                check(reentered, "LOCATION_PUBLICATION_MISSING_\(scenario)")
                check(app!.locationEnabled == nestedOn, "LOCATION_LATEST_INTENT_OVERWRITTEN_\(scenario)")
                check(nestedOn ? app!.locationState != "Off" : app!.locationState == "Off",
                      "LOCATION_LATEST_STATE_OVERWRITTEN_\(scenario)")
                if scenario == "start-off" {
                    check(CLLocationManager.instances.reduce(0) { $0 + $1.starts } == startsAtOff,
                          "LOCATION_START_AFTER_NEWER_OFF")
                }
                if scenario == "permission-off" {
                    check(CLLocationManager.instances.reduce(0) { $0 + $1.requests } == requestsAtOff,
                          "LOCATION_PERMISSION_AFTER_NEWER_OFF")
                }
                if nestedOn {
                    check(CLLocationManager.instances.last?.delegate != nil,
                          "LOCATION_NEWER_MANAGER_DETACHED_\(scenario)")
                } else {
                    check(CLLocationManager.instances.allSatisfy { $0.delegate == nil },
                          "LOCATION_OFF_RETAINED_DELEGATE_\(scenario)")
                }
                subscription.cancel()
                app!.setLocation(false)
            }
            CLLocationManager.initialAuthorization = .authorizedAlways
        default: fatalError("Unknown facade scenario")
        }
        app = nil
        let final = await diagnostics()
        check(final.maximumOutstanding <= 1 && final.scheduledIngress <= 1, "FACADE_SERVICE_RESOURCE_BOUND")
        print("PASS: facade \(name), \(assertions) assertions; Foundation notifications and actual service/facade; platform doubles")
    }
}
