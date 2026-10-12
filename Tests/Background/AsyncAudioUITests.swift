import XCTest
import UIKit

/// Uses the actual iOS27 audio APIs; Simulator success is not host/device certification.
final class AsyncAudioUITests: XCTestCase {
    @MainActor func testAsyncSessionPlaybackAndOff() {
        continueAfterFailure = false
        let app = XCUIApplication()
        addTeardownBlock { @MainActor in
            app.terminate()
            XCUIDevice.shared.orientation = .portrait
        }
        let audio = app.switches["Loop silent WAV"].switches.element(boundBy: 0)
        let audioState = app.staticTexts["background.audioState"]
        @MainActor func expectAudioState(_ value: String, timeout: TimeInterval = 5) {
            XCTAssertTrue(audioState.waitForExistence(timeout: timeout))
            let expectation = XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "label == %@", value), object: audioState)
            XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: timeout), .completed)
        }
        @MainActor func resetAudio() {
            XCUIDevice.shared.orientation = .portrait
            if app.state != .runningForeground { app.launch() }
            XCTAssertTrue(app.tabBars.buttons["Background"].waitForExistence(timeout: 10))
            app.tabBars.buttons["Background"].tap()
            XCTAssertTrue(audio.waitForExistence(timeout: 5))
            XCTAssertTrue(audio.isHittable)
            if audio.value as? String == "1" { audio.tap() }
            XCTAssertEqual(audio.value as? String, "0")
            expectAudioState("Off")
        }
        addTeardownBlock { @MainActor in resetAudio() }
        resetAudio()
        for _ in 0..<3 {
            audio.tap()
            XCTAssertEqual(audio.value as? String, "1")
            expectAudioState("Playing silent WAV continuously", timeout: 10)
            audio.tap()
            XCTAssertEqual(audio.value as? String, "0")
            expectAudioState("Off")
        }
        audio.tap()
        expectAudioState("Playing silent WAV continuously", timeout: 10)
        // The old generic Off selector can match Location while audio is Playing.
        XCTAssertTrue(app.staticTexts["Off"].firstMatch.exists)
        XCTAssertNotEqual(audioState.label, "Off")
        let playing = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        playing.name = "async-audio-playing"
        playing.lifetime = .keepAlways
        add(playing)
        app.terminate()
        app.launch()
        app.tabBars.buttons["Background"].tap()
        XCTAssertEqual(audio.value as? String, "1")
        expectAudioState("Playing silent WAV continuously", timeout: 10)
        audio.tap()
        XCTAssertEqual(audio.value as? String, "0")
        // Rapid user intent changes must settle at the final explicit Off.
        for _ in 0..<4 { audio.tap(); audio.tap() }
        XCTAssertEqual(audio.value as? String, "0")
        app.tabBars.buttons["Server"].tap()
        app.tabBars.buttons["Background"].tap()
        XCTAssertEqual(audio.value as? String, "0")
        expectAudioState("Off")
        let off = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        off.name = "async-audio-final-off"
        off.lifetime = .keepAlways
        add(off)
        app.terminate()
        app.launch()
        app.tabBars.buttons["Background"].tap()
        XCTAssertEqual(audio.value as? String, "0")
        expectAudioState("Off")
    }
}
