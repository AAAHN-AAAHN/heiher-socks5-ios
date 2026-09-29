import Darwin
import XCTest
import UIKit

/// Actual app root/store and native listener; no injected settings or mock counters.
final class SettingsPersistenceUITests: XCTestCase {
    @MainActor func testDurableDraftIntentAndTab() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        let workers = app.textFields.element(boundBy: 0)
        let start = app.buttons["Start"]
        let stop = app.buttons["Stop"]
        let serverTab = app.tabBars.buttons["Server"]
        let settingsTab = app.tabBars.buttons["Settings"]
        XCTAssertTrue(workers.waitForExistence(timeout: 10))
        XCTAssertEqual(workers.value as? String, "4")
        XCTAssertEqual(app.textFields.count, 9)
        XCTAssertEqual(app.secureTextFields.count, 1)
        XCTAssertFalse(Self.handshake(), "Fresh store must not start the engine")
        replace(workers, with: "0")
        reveal(start, in: app, upward: true)
        start.tap()
        let error = app.staticTexts["Use 1-64 workers, a listen port of 1-65535, and a UDP port of 0-65535."]
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertTrue(start.isEnabled && stop.isEnabled)
        XCTAssertFalse(Self.handshake())
        capture("invalid-draft-saved")
        app.terminate()
        app.launch()
        XCTAssertTrue(workers.waitForExistence(timeout: 10))
        XCTAssertEqual(workers.value as? String, "0", "Invalid stopped draft must survive recreation")
        reveal(stop, in: app, upward: true)
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertTrue(stop.isEnabled, "Saved invalid Start is cancellable")
        XCTAssertFalse(Self.handshake(), "Invalid saved intent must not execute")
        stop.tap()
        XCTAssertTrue(app.staticTexts["Stopped"].waitForExistence(timeout: 5))
        reveal(workers, in: app, upward: false)
        replace(workers, with: "2")
        for orientation in [UIDeviceOrientation.portrait, .landscapeLeft] {
            XCUIDevice.shared.orientation = orientation
            reveal(start, in: app, upward: true)
            start.tap()
            XCTAssertTrue(waitUntil { Self.handshake() && Self.handshake(ipv6: true) })
            XCTAssertFalse(start.isEnabled)
            XCTAssertTrue(stop.isEnabled)
            settingsTab.tap()
            XCTAssertTrue(app.buttons["Export JSON"].waitForExistence(timeout: 5))
            XCTAssertTrue(app.buttons["Import JSON"].exists)
            capture("settings-running-\(orientation.rawValue)")
            app.terminate()
            app.launch()
            XCTAssertTrue(app.buttons["Export JSON"].waitForExistence(timeout: 10), "Selected tab must be restored")
            let restored = waitUntil { Self.handshake() && Self.handshake(ipv6: true) }
            if !restored {
                // Diagnose an already failed deadline; never retry Start or pass
                // based on this later observation.
                serverTab.tap()
                reveal(stop, in: app, upward: true)
                print("FAILED RESTORATION STATE: " + app.debugDescription)
                capture("failed-restoration-\(orientation.rawValue)")
            }
            XCTAssertTrue(restored, "Saved Start resumes when app executes")
            serverTab.tap()
            reveal(stop, in: app, upward: true)
            XCTAssertFalse(start.isEnabled)
            XCTAssertTrue(stop.isEnabled)
            stop.tap()
            XCTAssertTrue(waitUntil { start.isEnabled && !stop.isEnabled })
            XCTAssertTrue(waitUntil { !Self.handshake() && !Self.handshake(ipv6: true) })
            reveal(workers, in: app, upward: false)
            XCTAssertEqual(workers.value as? String, "2")
            capture("stopped-restored-\(orientation.rawValue)")
        }
        XCUIDevice.shared.orientation = .portrait
        settingsTab.tap()
        // The actual import/export sheets open and cancel; no iCloud/provider claim.
        for title in ["Import JSON", "Export JSON"] {
            let button = app.buttons[title]
            XCTAssertTrue(button.waitForExistence(timeout: 5) && button.isHittable)
            button.tap()
            let cancel = app.buttons["Cancel"].firstMatch
            XCTAssertTrue(cancel.waitForExistence(timeout: 10), title + " sheet must be dismissible")
            cancel.tap()
            XCTAssertTrue(waitUntil { button.isHittable })
        }
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["Export JSON"].waitForExistence(timeout: 10))
        XCTAssertFalse(Self.handshake(), "Saved Stop persists across process restart")
        capture("relaunched-settings-stopped")
    }

    @MainActor private func reveal(_ element: XCUIElement, in app: XCUIApplication, upward: Bool) {
        for _ in 0..<12 {
            if element.exists && element.isHittable { break }
            if upward { app.scrollViews.firstMatch.swipeUp() }
            else { app.scrollViews.firstMatch.swipeDown() }
        }
        XCTAssertTrue(element.exists && element.isHittable, "Control must be reachable without production UI substitutions")
    }

    @MainActor private func replace(_ field: XCUIElement, with text: String) {
        XCTAssertTrue(field.isEnabled)
        field.tap()
        let previous = field.value as? String ?? ""
        field.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: previous.count) + text)
        XCTAssertEqual(field.value as? String, text)
    }

    private func waitUntil(_ condition: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(5)
        repeat {
            if condition() { return true }
            Thread.sleep(forTimeInterval: 0.05)
        } while Date() < end
        return false
    }

    private func capture(_ name: String) {
        let image = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        image.name = name; image.lifetime = .keepAlways
        add(image)
    }

    private static func handshake(ipv6: Bool = false) -> Bool {
        let fd = Darwin.socket(ipv6 ? AF_INET6 : AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { Darwin.close(fd) }
        var noSignal: Int32 = 1
        var timeout = timeval(tv_sec: 0, tv_usec: 250_000)
        guard setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout.size(ofValue: noSignal))) == 0,
              setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout))) == 0,
              setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout.size(ofValue: timeout))) == 0 else { return false }
        let connected: Bool
        if ipv6 {
            var address = sockaddr_in6()
            address.sin6_len = UInt8(MemoryLayout<sockaddr_in6>.size)
            address.sin6_family = sa_family_t(AF_INET6)
            address.sin6_port = UInt16(1080).bigEndian
            guard inet_pton(AF_INET6, "::1", &address.sin6_addr) == 1 else { return false }
            connected = withUnsafePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in6>.size)) == 0
                }
            }
        } else {
            var address = sockaddr_in()
            address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            address.sin_family = sa_family_t(AF_INET)
            address.sin_port = UInt16(1080).bigEndian
            guard inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1 else { return false }
            connected = withUnsafePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
                }
            }
        }
        guard connected else { return false }
        let request: [UInt8] = [5, 1, 0]
        guard request.withUnsafeBytes({ Darwin.send(fd, $0.baseAddress, $0.count, 0) }) == request.count else { return false }
        var reply: [UInt8] = [0, 0]
        return reply.withUnsafeMutableBytes { Darwin.recv(fd, $0.baseAddress, $0.count, MSG_WAITALL) } == 2 && reply == [5, 0]
    }
}
