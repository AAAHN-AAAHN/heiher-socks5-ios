import Darwin
import XCTest
import UIKit

/// Drives the actual application; a Simulator pass is not a physical-install pass.
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
            XCTAssertTrue(Self.handshake(recordPayload: true), "Client IP row must come from real relayed UDP payload")
            stop.tap()
            XCTAssertTrue(waitUntil { start.isEnabled && !stop.isEnabled })
            XCTAssertTrue(waitUntil { !Self.handshake() }, "Stop must release the real native listener")
            app.tabBars.buttons["Statistics"].tap()
            XCTAssertTrue(app.navigationBars["Statistics"].waitForExistence(timeout: 5))
            let client = app.buttons["client-1"]
            let form = app.collectionViews.firstMatch
            XCTAssertTrue(form.waitForExistence(timeout: 5))
            for _ in 0..<6 {
                if client.isHittable { break }
                // The recorded Form hierarchy exposes this CollectionView.
                // Target its content, not the application or floating tab bar.
                form.swipeUp()
            }
            XCTAssertTrue(client.waitForExistence(timeout: 5))
            XCTAssertTrue(client.isHittable)
            if !app.staticTexts["Out speed"].exists { client.tap() }
            XCTAssertTrue(app.staticTexts["Out speed"].exists)
            let statistics = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            statistics.name = "statistics-tab-\(orientation.rawValue)"
            statistics.lifetime = .keepAlways
            add(statistics)
            app.tabBars.buttons["Server"].tap()
            XCTAssertTrue(start.waitForExistence(timeout: 5))
        }
    }

    private func waitUntil(_ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(5)
        repeat {
            if condition() { return true }
            Thread.sleep(forTimeInterval: 0.05)
        } while Date() < deadline
        return false
    }

    private static func handshake(recordPayload: Bool = false) -> Bool {
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
        guard received == 2 && reply == [5, 0] else { return false }
        guard recordPayload else { return true }
        let destination = Darwin.socket(AF_INET, SOCK_DGRAM, 0)
        let udp = Darwin.socket(AF_INET, SOCK_DGRAM, 0)
        guard destination >= 0, udp >= 0 else {
            if destination >= 0 { Darwin.close(destination) }
            if udp >= 0 { Darwin.close(udp) }
            return false
        }
        defer { Darwin.close(destination); Darwin.close(udp) }
        guard setsockopt(destination, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                         socklen_t(MemoryLayout.size(ofValue: timeout))) == 0 else { return false }
        address.sin_port = 0
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(destination, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0 else { return false }
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        guard withUnsafeMutablePointer(to: &address, {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                getsockname(destination, $0, &length)
            }
        }) == 0 else { return false }
        let destinationPort = UInt16(bigEndian: address.sin_port)
        let request: [UInt8] = [5, 3, 0, 1, 0, 0, 0, 0, 0, 0]
        guard request.withUnsafeBytes({ Darwin.send(fd, $0.baseAddress, $0.count, 0) }) == request.count else { return false }
        var header = [UInt8](repeating: 0, count: 4)
        guard header.withUnsafeMutableBytes({ Darwin.recv(fd, $0.baseAddress, $0.count, MSG_WAITALL) }) == 4,
              header[0] == 5, header[1] == 0, header[3] == 1 || header[3] == 4 else { return false }
        var endpoint = [UInt8](repeating: 0, count: header[3] == 1 ? 6 : 18)
        guard endpoint.withUnsafeMutableBytes({ Darwin.recv(fd, $0.baseAddress, $0.count, MSG_WAITALL) }) == endpoint.count else { return false }
        address.sin_port = (UInt16(endpoint[endpoint.count - 2]) << 8 | UInt16(endpoint.last!)).bigEndian
        guard withUnsafePointer(to: &address, {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(udp, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }) == 0 else { return false }
        let payload = [UInt8](repeating: 0x5a, count: 64)
        let packet: [UInt8] = [0, 0, 0, 1, 127, 0, 0, 1,
                               UInt8(destinationPort >> 8), UInt8(destinationPort & 255)] + payload
        guard packet.withUnsafeBytes({ Darwin.send(udp, $0.baseAddress, $0.count, 0) }) == packet.count else { return false }
        var external = [UInt8](repeating: 0, count: 64)
        return external.withUnsafeMutableBytes({ Darwin.recv(destination, $0.baseAddress, $0.count, 0) }) == 64 && external == payload
    }
}
