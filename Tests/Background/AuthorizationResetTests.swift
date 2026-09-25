import Foundation

/// Authorization callbacks are scripted; this does not grant physical iOS permissions.
@main struct AuthorizationResetTests {
    @MainActor static func main() {
        var checks = 0
        var failures = 0
        func check(_ value: @autoclosure () -> Bool, _ label: String) {
            checks += 1
            if value() { print("PASS: \(label)") }
            else { failures += 1; print("FAIL: \(label)") }
        }
        for authorization in [CLAuthorizationStatus.authorizedWhenInUse, .authorizedAlways] {
            for state in [UIApplication.State.active, .inactive, .background] {
                UIApplication.shared.applicationState = .active
                CLLocationManager.initialAuthorization = authorization
                let app = BackgroundKeepAlive()
                app.setLocation(true)
                let manager = CLLocationManager.instances.last!
                precondition(manager.starts == 1)
                UIApplication.shared.applicationState = state
                manager.authorizationStatus = .notDetermined
                app.locationManagerDidChangeAuthorization(manager)
                check(manager.stops == 1 && app.locationEnabled,
                      "Reset stops the obsolete location session without clearing On")
                let before = app.readCount
                app.locationManager(manager, didUpdateLocations: [CLLocation()])
                check(app.readCount == before && app.lastRead == nil,
                      "A late batch after authorization reset is not counted")
                for _ in 0..<50 { app.restore(); app.locationManagerDidChangeAuthorization(manager) }
                check(manager.stops == 1 && manager.starts == 1,
                      "Repeated undetermined callbacks neither stop again nor restart")
                check(manager.requests == (state == .active ? 1 : 0),
                      "Permission requests remain active-only and deduplicated")
                manager.authorizationStatus = authorization
                app.locationManagerDidChangeAuthorization(manager)
                let deferred = authorization == .authorizedWhenInUse && state != .active
                check(manager.starts == (deferred ? 1 : 2),
                      "Reauthorization retains the When-In-Use foreground boundary")
                UIApplication.shared.applicationState = .active
                for _ in 0..<50 { app.restore() }
                check(manager.starts == 2, "Reauthorized foreground session actually restarts exactly once")
                let authorizedCount = app.readCount
                app.locationManager(manager, didUpdateLocations: [CLLocation()])
                check(app.readCount == authorizedCount + 1, "The new authorized session accepts updates")
                app.setLocation(false)
                manager.authorizationStatus = .notDetermined
                app.locationManagerDidChangeAuthorization(manager)
                check(!app.locationEnabled && manager.delegate == nil && Timer.live.isEmpty,
                      "Off rejects the old manager and adds no location timer")
            }
        }
        UIApplication.shared.applicationState = .active
        CLLocationManager.initialAuthorization = .notDetermined
        let waiting = BackgroundKeepAlive()
        waiting.setLocation(true)
        let manager = CLLocationManager.instances.last!
        for _ in 0..<50 { waiting.restore(); waiting.locationManagerDidChangeAuthorization(manager) }
        check(manager.stops == 0 && manager.starts == 0 && manager.requests == 1,
              "Initial authorization still requests once without stopping an unused manager")
        waiting.setLocation(false)
        print("SUMMARY: \(checks) authorization-reset assertions; \(failures) failed; scripted permissions, not device tests")
        if failures != 0 { exit(1) }
    }
}
