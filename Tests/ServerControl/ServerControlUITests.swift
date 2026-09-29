import Darwin
import XCTest
import UIKit

/// Drives the unchanged production root and the real prepare/Stop-patched engine.
final class ServerControlUITests: XCTestCase {
    @MainActor func testValidationLifecycleAndMemoryOnlyRoot() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        defer { app.terminate(); XCUIDevice.shared.orientation = .portrait }
        let start = app.buttons["Start"]
        let stop = app.buttons["Stop"]
        let workers = app.textFields.element(boundBy: 0)
        XCTAssertTrue(workers.waitForExistence(timeout: 10))
        XCTAssertEqual(app.textFields.count, 9)
        XCTAssertEqual(app.secureTextFields.count, 1)
        XCTAssertEqual(app.switches.count, 1)
        XCTAssertEqual(workers.value as? String, "4")
        XCTAssertEqual(app.textFields.element(boundBy: 1).value as? String, "::")
        XCTAssertEqual(app.textFields.element(boundBy: 2).value as? String, "1080")
        reveal(start, in: app, upward: true)
        XCTAssertTrue(start.isEnabled)
        XCTAssertFalse(stop.isEnabled)
        XCTAssertFalse(Self.handshake(), "Memory-only root must not autostart")
        reveal(workers, in: app, upward: false)
        replace(workers, with: "0")
        reveal(start, in: app, upward: true)
        start.tap()
        let error = app.staticTexts["Use 1-64 workers, a listen port of 1-65535, and a UDP port of 0-65535."]
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertTrue(start.isEnabled && stop.isEnabled)
        XCTAssertFalse(Self.handshake(), "Invalid draft must never reach a listener")
        capture("invalid-draft")
        stop.tap()
        XCTAssertTrue(app.staticTexts["Stopped"].waitForExistence(timeout: 5))
        XCTAssertFalse(stop.isEnabled)
        reveal(workers, in: app, upward: false)
        replace(workers, with: "1")
        for orientation in [UIDeviceOrientation.portrait, .landscapeLeft] {
            XCUIDevice.shared.orientation = orientation
            reveal(start, in: app, upward: true)
            XCTAssertTrue(start.isHittable && stop.isHittable)
            XCTAssertTrue(start.isEnabled && !stop.isEnabled)
            start.tap()
            XCTAssertTrue(waitUntil { !start.isEnabled && stop.isEnabled })
            XCTAssertTrue(waitUntil { Self.handshake() }, "Running label is not the native-readiness oracle")
            XCTAssertTrue(Self.handshake(ipv6: true), "Default dual-stack listener must retain IPv6")
            for index in 0..<9 { XCTAssertFalse(app.textFields.element(boundBy: index).isEnabled) }
            XCTAssertFalse(app.secureTextFields.firstMatch.isEnabled)
            XCTAssertFalse(app.switches.firstMatch.isEnabled)
            capture("running-\(orientation.rawValue)")
            stop.tap()
            XCTAssertTrue(waitUntil { start.isEnabled && !stop.isEnabled })
            XCTAssertTrue(waitUntil { !Self.handshake() && !Self.handshake(ipv6: true) }, "Stop must release both listener paths")
            for index in 0..<9 { XCTAssertTrue(app.textFields.element(boundBy: index).isEnabled) }
            XCTAssertTrue(app.secureTextFields.firstMatch.isEnabled)
            XCTAssertTrue(app.switches.firstMatch.isEnabled)
            capture("stopped-\(orientation.rawValue)")
        }
        // Drafts and desired state are intentionally not persisted by this owner.
        app.terminate()
        XCUIDevice.shared.orientation = .portrait
        app.launch()
        XCTAssertTrue(workers.waitForExistence(timeout: 10))
        XCTAssertEqual(workers.value as? String, "4")
        reveal(start, in: app, upward: true)
        XCTAssertTrue(start.isEnabled && !stop.isEnabled)
        XCTAssertFalse(Self.handshake())
        capture("relaunched-stopped-defaults")
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
