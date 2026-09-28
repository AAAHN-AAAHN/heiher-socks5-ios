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
            XCTAssertTrue(Self.handshake(recordPayload: true), "First IP row must come from real IPv4 UDP relay")
            XCTAssertTrue(Self.handshake(recordPayload: true, ipv6: true), "Second IP row must come from real IPv6 control-peer relay")
            stop.tap()
            XCTAssertTrue(waitUntil { start.isEnabled && !stop.isEnabled })
            XCTAssertTrue(waitUntil { !Self.handshake() }, "Stop must release the real native listener")
            app.tabBars.buttons["Statistics"].tap()
            XCTAssertTrue(app.navigationBars["Statistics"].waitForExistence(timeout: 5))
            let form = app.collectionViews.firstMatch
            XCTAssertTrue(form.waitForExistence(timeout: 5))
            let top = app.staticTexts["total-title"]
            for _ in 0..<6 {
                if top.exists && top.isHittable { break }
                form.swipeDown()
            }
            XCTAssertTrue(top.exists && top.isHittable)
            var previousHeaderY = top.frame.minY
            for id in ["total", "client-1", "client-2"] {
                let speed = app.descendants(matching: .any).matching(identifier: id + "-speed").firstMatch
                let usage = app.descendants(matching: .any).matching(identifier: id + "-usage").firstMatch
                for _ in 0..<6 {
                    if speed.exists && speed.isHittable && usage.exists && usage.isHittable { break }
                    let from = form.coordinate(withNormalizedOffset: CGVector(dx: 0.8, dy: 0.65))
                    let to = form.coordinate(withNormalizedOffset: CGVector(dx: 0.8, dy: 0.40))
                    from.press(forDuration: 0.05, thenDragTo: to,
                               withVelocity: .slow, thenHoldForDuration: 0.1)
                }
                XCTAssertTrue(speed.exists && speed.isHittable, "Speed must be visible without expanding a row")
                XCTAssertTrue(usage.exists && usage.isHittable, "Usage must be visible without expanding a row")
                XCTAssertLessThan(speed.frame.minY, usage.frame.minY)
                let speedText = speed.label + " " + (speed.value as? String ?? "")
                let usageText = usage.label + " " + (usage.value as? String ?? "")
                XCTAssertTrue(speedText.contains("In") && speedText.contains("Out") && speedText.contains("bps"))
                XCTAssertTrue(usageText.contains("In") && usageText.contains("Out") && usageText.contains("Total"))
                if id != "total" {
                    let header = app.staticTexts[id]
                    XCTAssertTrue(header.exists)
                    XCTAssertEqual(header.label, id == "client-1" ? "127.0.0.1" : "::1")
                    if orientation == .portrait {
                        XCTAssertGreaterThan(header.frame.minY, previousHeaderY, "Total then client registration order")
                        previousHeaderY = header.frame.minY
                    }
                }
            }
            let statistics = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
            statistics.name = "statistics-two-lines-\(orientation.rawValue)"
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

    private static func handshake(recordPayload: Bool = false, ipv6: Bool = false) -> Bool {
        let family = ipv6 ? AF_INET6 : AF_INET
        let fd = Darwin.socket(family, SOCK_STREAM, 0)
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
        guard connectLoopback(fd, ipv6: ipv6, port: 1080) else { return false }
        let greeting: [UInt8] = [5, 1, 0]
        guard greeting.withUnsafeBytes({ Darwin.send(fd, $0.baseAddress, $0.count, 0) }) == greeting.count else { return false }
        var reply = [UInt8](repeating: 0, count: 2)
        let received = reply.withUnsafeMutableBytes { Darwin.recv(fd, $0.baseAddress, $0.count, MSG_WAITALL) }
        guard received == 2 && reply == [5, 0] else { return false }
        guard recordPayload else { return true }
        let destination = Darwin.socket(AF_INET, SOCK_DGRAM, 0)
        let udp = Darwin.socket(family, SOCK_DGRAM, 0)
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
        let relayPort = UInt16(endpoint[endpoint.count - 2]) << 8 | UInt16(endpoint.last!)
        guard connectLoopback(udp, ipv6: ipv6, port: relayPort),
              setsockopt(udp, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                         socklen_t(MemoryLayout.size(ofValue: timeout))) == 0 else { return false }
        let payload = [UInt8](repeating: 0x5a, count: 64)
        let packet: [UInt8] = [0, 0, 0, 1, 127, 0, 0, 1,
                               UInt8(destinationPort >> 8), UInt8(destinationPort & 255)] + payload
        guard packet.withUnsafeBytes({ Darwin.send(udp, $0.baseAddress, $0.count, 0) }) == packet.count else { return false }
        var external = [UInt8](repeating: 0, count: 64)
        var peer = sockaddr_storage()
        var peerLength = socklen_t(MemoryLayout<sockaddr_storage>.size)
        let count = withUnsafeMutablePointer(to: &peer) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { source in
                external.withUnsafeMutableBytes {
                    Darwin.recvfrom(destination, $0.baseAddress, $0.count, 0, source, &peerLength)
                }
            }
        }
        guard count == payload.count && external == payload else { return false }
        let echoed = withUnsafePointer(to: &peer) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { source in
                external.withUnsafeBytes {
                    Darwin.sendto(destination, $0.baseAddress, $0.count, 0, source, peerLength)
                }
            }
        }
        guard echoed == payload.count else { return false }
        var response = [UInt8](repeating: 0, count: 128)
        let responseCount = response.withUnsafeMutableBytes {
            Darwin.recv(udp, $0.baseAddress, $0.count, 0)
        }
        return responseCount >= payload.count && Array(response.prefix(responseCount).suffix(payload.count)) == payload
    }

    private static func connectLoopback(_ fd: Int32, ipv6: Bool, port: UInt16) -> Bool {
        if ipv6 {
            var address = sockaddr_in6()
            address.sin6_len = UInt8(MemoryLayout<sockaddr_in6>.size)
            address.sin6_family = sa_family_t(AF_INET6)
            address.sin6_port = port.bigEndian
            guard inet_pton(AF_INET6, "::1", &address.sin6_addr) == 1 else { return false }
            return withUnsafePointer(to: &address) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in6>.size)) == 0
                }
            }
        }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        guard inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1 else { return false }
        return withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }
}
