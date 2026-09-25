import XCTest
import UIKit

/// Uses the actual iOS27 audio APIs; Simulator success is not host/device certification.
final class AsyncAudioUITests: XCTestCase {
    @MainActor func testAsyncSessionPlaybackAndOff() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        XCTAssertTrue(app.tabBars.buttons["Background"].waitForExistence(timeout: 10))
        app.tabBars.buttons["Background"].tap()
        let audio = app.switches["Loop silent WAV"].switches.element(boundBy: 0)
        XCTAssertTrue(audio.waitForExistence(timeout: 5))
        XCTAssertTrue(audio.isHittable)
        XCTAssertEqual(audio.value as? String, "0")
        for _ in 0..<3 {
            audio.tap()
            XCTAssertEqual(audio.value as? String, "1")
            XCTAssertTrue(app.staticTexts["Playing silent WAV continuously"].waitForExistence(timeout: 10))
            audio.tap()
            XCTAssertEqual(audio.value as? String, "0")
            XCTAssertTrue(app.staticTexts["Off"].firstMatch.waitForExistence(timeout: 5))
        }
        audio.tap()
        XCTAssertTrue(app.staticTexts["Playing silent WAV continuously"].waitForExistence(timeout: 10))
        let playing = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        playing.name = "async-audio-playing"
        playing.lifetime = .keepAlways
        add(playing)
        app.terminate()
        app.launch()
        app.tabBars.buttons["Background"].tap()
        XCTAssertEqual(audio.value as? String, "1")
        XCTAssertTrue(app.staticTexts["Playing silent WAV continuously"].waitForExistence(timeout: 10))
        audio.tap()
        XCTAssertEqual(audio.value as? String, "0")
        // Rapid user intent changes must settle at the final explicit Off.
        for _ in 0..<4 { audio.tap(); audio.tap() }
        XCTAssertEqual(audio.value as? String, "0")
        app.tabBars.buttons["Server"].tap()
        app.tabBars.buttons["Background"].tap()
        XCTAssertEqual(audio.value as? String, "0")
        let off = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        off.name = "async-audio-final-off"
        off.lifetime = .keepAlways
        add(off)
        app.terminate()
        app.launch()
        app.tabBars.buttons["Background"].tap()
        XCTAssertEqual(audio.value as? String, "0")
    }
}
