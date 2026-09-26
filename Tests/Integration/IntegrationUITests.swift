import Darwin
import XCTest
import UIKit

/// Integrates durable intent, native execution and four real tabs; Simulator evidence only.
final class StatisticsUITests: XCTestCase {
    @MainActor func testServerControlsAndTabNavigation() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        XCTAssertTrue(app.tabBars.buttons["Server"].waitForExistence(timeout: 10))
        for orientation in [UIDeviceOrientation.portrait, .landscapeLeft] {
            XCUIDevice.shared.orientation = orientation
            app.tabBars.buttons["Server"].tap()
            let start = app.buttons["Start"]
            let stop = app.buttons["Stop"]
            XCTAssertTrue(start.waitForExistence(timeout: 5))
            for _ in 0..<6 {
                if start.isHittable && stop.isHittable { break }
                app.scrollViews.firstMatch.swipeUp()
            }
            XCTAssertTrue(start.isHittable, "Start must be reachable by actual scrolling")
            XCTAssertTrue(stop.isHittable, "Stop must not remain covered by the floating tab bar")
            XCTAssertTrue(start.isEnabled)
            XCTAssertFalse(stop.isEnabled)
            let capture = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            capture.name = "server-controls-\(orientation.rawValue)"
            capture.lifetime = .keepAlways
            add(capture)
            start.tap()
            XCTAssertTrue(waitUntil { stop.isEnabled && !start.isEnabled })
            XCTAssertTrue(waitUntil { Self.handshake() }, "Start must reach the real native listener")
            // A fresh app process must restore saved Start, not only the switch state.
            app.terminate()
            app.launch()
            XCTAssertTrue(app.tabBars.buttons["Server"].waitForExistence(timeout: 10))
            app.tabBars.buttons["Server"].tap()
            XCTAssertTrue(waitUntil { Self.handshake() }, "Saved Start must restore the native listener")
            for _ in 0..<6 {
                if stop.isHittable { break }
                app.scrollViews.firstMatch.swipeUp()
            }
            XCTAssertTrue(stop.isHittable)
            stop.tap()
            XCTAssertTrue(waitUntil { start.isEnabled && !stop.isEnabled })
            XCTAssertTrue(waitUntil { !Self.handshake() }, "Stop must release the real native listener")
            app.tabBars.buttons["Statistics"].tap()
            XCTAssertTrue(app.navigationBars["Statistics"].waitForExistence(timeout: 5))
            let statistics = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            statistics.name = "statistics-tab-\(orientation.rawValue)"
            statistics.lifetime = .keepAlways
            add(statistics)
            app.tabBars.buttons["Server"].tap()
            XCTAssertTrue(start.waitForExistence(timeout: 5))
        }
        XCUIDevice.shared.orientation = .portrait
        app.tabBars.buttons["Background"].tap()
        XCTAssertTrue(app.navigationBars["Background"].waitForExistence(timeout: 5))
        // The labeled SwiftUI row contains a separate actionable switch.
        let audio = app.switches["Loop silent WAV"].switches.element(boundBy: 0)
        XCTAssertTrue(audio.waitForExistence(timeout: 5))
        XCTAssertTrue(audio.isHittable)
        XCTAssertEqual(audio.value as? String, "0")
        let audioState = app.staticTexts["background.audioState"]
        func expectAudioState(_ value: String, timeout: TimeInterval = 5) {
            XCTAssertTrue(audioState.waitForExistence(timeout: timeout))
            let expectation = XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "label == %@", value), object: audioState)
            XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: timeout), .completed)
        }
        expectAudioState("Off")
        audio.tap()
        XCTAssertEqual(audio.value as? String, "1")
        expectAudioState("Playing silent WAV continuously", timeout: 10)
        // Starting/stopping the combined engine must not turn the independent audio off.
        app.tabBars.buttons["Server"].tap()
        for _ in 0..<6 {
            if app.buttons["Start"].isHittable && app.buttons["Stop"].isHittable { break }
            app.scrollViews.firstMatch.swipeUp()
        }
        XCTAssertTrue(app.buttons["Start"].isHittable)
        app.buttons["Start"].tap()
        XCTAssertTrue(waitUntil { Self.handshake() })
        XCTAssertTrue(app.buttons["Stop"].isHittable)
        app.buttons["Stop"].tap()
        XCTAssertTrue(waitUntil { !Self.handshake() })
        app.tabBars.buttons["Background"].tap()
        XCTAssertEqual(audio.value as? String, "1")
        expectAudioState("Playing silent WAV continuously", timeout: 10)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.navigationBars["Background"].waitForExistence(timeout: 10))
        XCTAssertEqual(audio.value as? String, "1", "Saved audio intent must survive relaunch")
        expectAudioState("Playing silent WAV continuously", timeout: 10)
        audio.tap()
        XCTAssertEqual(audio.value as? String, "0")
        expectAudioState("Off")
        XCTAssertEqual(app.switches["Continuous location"].value as? String, "0")
        let background = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        background.name = "integrated-background"; background.lifetime = .keepAlways; add(background)
        app.tabBars.buttons["Settings"].tap()
        XCTAssertTrue(app.buttons["Export JSON"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Import JSON"].exists)
        let settings = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        settings.name = "integrated-settings"; settings.lifetime = .keepAlways; add(settings)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 10))
        XCTAssertFalse(Self.handshake(), "Saved Stop must not start a listener on relaunch")
    }

    private func waitUntil(_ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(5)
        repeat {
            if condition() { return true }
            Thread.sleep(forTimeInterval: 0.05)
        } while Date() < deadline
        return false
    }

    private static func handshake() -> Bool {
        let fd = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { Darwin.close(fd) }
        var noSignal: Int32 = 1
        guard setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout.size(ofValue: noSignal))) == 0 else { return false }
        var timeout = timeval(tv_sec: 1, tv_usec: 0)
        guard setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout))) == 0,
              setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout))) == 0 else { return false }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = UInt16(1080).bigEndian
        guard inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1 else { return false }
        let connected = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard connected == 0 else { return false }
        let greeting: [UInt8] = [5, 1, 0]
        guard greeting.withUnsafeBytes({ Darwin.send(fd, $0.baseAddress, $0.count, 0) }) == greeting.count else { return false }
        var reply = [UInt8](repeating: 0, count: 2)
        let received = reply.withUnsafeMutableBytes { Darwin.recv(fd, $0.baseAddress, $0.count, MSG_WAITALL) }
        return received == 2 && reply == [5, 0]
    }
}
