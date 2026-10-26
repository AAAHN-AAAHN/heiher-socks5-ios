import XCTest
import UIKit

/// Uses the actual native server with loopback targets. SENT is not a reply.
final class PeriodicPingUITests: XCTestCase {
    @MainActor func testPeriodicPingControlsAndPersistence() {
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
        let saved = app.staticTexts["background.pingStorageState"]
        @MainActor func waitSaved() {
            let check = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "Settings saved"), object: saved)
            XCTAssertEqual(XCTWaiter.wait(for: [check], timeout: 5), .completed)
        }
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
            // Select the whole field through the real edit menu; caret placement
            // is not guaranteed by a tap, even at the trailing edge of a short value.
            field.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
            XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
            field.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).press(forDuration: 1)
            let menuItem = app.menuItems["Select All"].firstMatch
            let selectAll = menuItem.exists ? menuItem : app.buttons["Select All"].firstMatch
            XCTAssertTrue(selectAll.waitForExistence(timeout: 5))
            selectAll.tap()
            field.typeText(value)
            XCTAssertEqual(field.value as? String, value)
            let done = app.buttons["background.pingDone"]
            XCTAssertTrue(done.waitForExistence(timeout: 5))
            done.tap()
            // Focus clears before the keyboard dismissal animation finishes.
            XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5))
        }
        @MainActor func expect(_ text: String) {
            let check = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", text), object: state)
            XCTAssertEqual(XCTWaiter.wait(for: [check], timeout: 5), .completed)
        }
        @MainActor func startServer() {
            app.tabBars.buttons["Server"].tap()
            let start = app.buttons["Start"].firstMatch
            XCTAssertTrue(start.waitForExistence(timeout: 5))
            XCTAssertTrue(start.isEnabled)
            start.tap()
            revealPing()
            expect("Sending ICMP to 2 destination(s)")
        }
        @MainActor func stopServer() {
            app.tabBars.buttons["Server"].tap()
            let stop = app.buttons["Stop"].firstMatch
            XCTAssertTrue(stop.waitForExistence(timeout: 5))
            XCTAssertTrue(stop.isEnabled)
            stop.tap()
            let start = app.buttons["Start"].firstMatch
            let idle = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == YES"), object: start)
            XCTAssertEqual(XCTWaiter.wait(for: [idle], timeout: 5), .completed)
            revealPing()
        }
        revealPing()
        XCTAssertEqual(toggle.value as? String, "0")
        XCTAssertEqual(destinations.value as? String, "1.1.1.1")
        XCTAssertEqual(period.value as? String, "1000")
        expect("Off")
        replace(destinations, "127.0.0.1, ::1")
        replace(period, "250")
        // Tap the switch at the trailing edge, not the noninteractive row center.
        // Tab changes must not replace the app-root sender owner.
        app.tabBars.buttons["Server"].tap()
        revealPing()
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        XCTAssertEqual(toggle.value as? String, "1")
        expect("Waiting for native ICMP server")
        startServer()
        let sending = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        sending.name = "periodic-ping-sending"
        sending.lifetime = .keepAlways
        add(sending)
        app.tabBars.buttons["Server"].tap()
        revealPing()
        XCTAssertEqual(toggle.value as? String, "1")
        stopServer()
        expect("Waiting for native ICMP server")
        waitSaved()
        app.terminate()
        app.launch()
        revealPing()
        XCTAssertEqual(toggle.value as? String, "1")
        XCTAssertEqual(destinations.value as? String, "127.0.0.1, ::1")
        XCTAssertEqual(period.value as? String, "250")
        expect("Waiting for native ICMP server")
        startServer()
        replace(period, "0")
        expect("Period must be a positive whole number of milliseconds.")
        XCTAssertEqual(toggle.value as? String, "1")
        replace(period, "250")
        app.tabBars.buttons["Server"].tap()
        revealPing()
        expect("Sending ICMP to 2 destination(s)")
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        XCTAssertEqual(toggle.value as? String, "0")
        expect("Off")
        stopServer()
        expect("Off")
        let capture = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        capture.name = "periodic-ping-final-off"
        capture.lifetime = .keepAlways
        add(capture)
        waitSaved()
        app.terminate()
        app.launch()
        revealPing()
        XCTAssertEqual(toggle.value as? String, "0")
        XCTAssertEqual(destinations.value as? String, "127.0.0.1, ::1")
        XCTAssertEqual(period.value as? String, "250")
        expect("Off")
    }
}
