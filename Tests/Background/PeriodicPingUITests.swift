import XCTest
import UIKit

/// Uses only loopback targets. Send status is not a claim that a peer replied.
final class PeriodicPingUITests: XCTestCase {
    @MainActor func testPeriodicPingControlsAndSessionLifetime() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        XCUIDevice.shared.orientation = .portrait
        addTeardownBlock { @MainActor in
            app.terminate()
            XCUIDevice.shared.orientation = .portrait
        }
        let toggle = app.switches["background.pingEnabled"].firstMatch
        let destinations = app.textFields["background.pingDestinations"]
        let period = app.textFields["background.pingPeriod"]
        let state = app.staticTexts["background.pingState"]
        @MainActor func revealPing() {
            XCTAssertTrue(app.tabBars.buttons["Background"].waitForExistence(timeout: 10))
            app.tabBars.buttons["Background"].tap()
            for _ in 0..<6 {
                if period.isHittable && toggle.isHittable { break }
                app.swipeUp()
            }
            XCTAssertTrue(toggle.isHittable)
            XCTAssertTrue(period.isHittable)
        }
        @MainActor func replace(_ field: XCUIElement, _ value: String) {
            field.tap()
            let old = field.value as? String ?? ""
            field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: old.count) + value)
        }
        @MainActor func expect(_ text: String) {
            let check = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", text), object: state)
            XCTAssertEqual(XCTWaiter.wait(for: [check], timeout: 5), .completed)
        }
        revealPing()
        XCTAssertEqual(toggle.value as? String, "0")
        XCTAssertEqual(destinations.value as? String, "1.1.1.1")
        XCTAssertEqual(period.value as? String, "1000")
        expect("Off")
        replace(destinations, "127.0.0.1, ::1")
        replace(period, "250")
        // Switching tabs dismisses editing without changing the app-root owner.
        app.tabBars.buttons["Server"].tap()
        revealPing()
        toggle.tap()
        expect("Sending ICMP to 2 destination(s)")
        app.tabBars.buttons["Server"].tap()
        revealPing()
        XCTAssertEqual(toggle.value as? String, "1")
        replace(period, "0")
        expect("Period must be a positive whole number of milliseconds.")
        XCTAssertEqual(toggle.value as? String, "1")
        replace(period, "250")
        app.tabBars.buttons["Server"].tap()
        revealPing()
        expect("Sending ICMP to 2 destination(s)")
        toggle.tap()
        expect("Off")
        let capture = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        capture.name = "periodic-ping-final-off"
        capture.lifetime = .keepAlways
        add(capture)
        app.terminate()
        app.launch()
        revealPing()
        XCTAssertEqual(toggle.value as? String, "0")
        XCTAssertEqual(destinations.value as? String, "1.1.1.1")
        XCTAssertEqual(period.value as? String, "1000")
        expect("Off")
    }
}
