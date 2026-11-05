import Darwin
import XCTest
import UIKit

/// Integrates durable intent, native execution and four real tabs; Simulator evidence only.
final class IntegrationUITests: XCTestCase {
    @MainActor func testServerControlsAndTabNavigation() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        addTeardownBlock { @MainActor in app.terminate(); XCUIDevice.shared.orientation = .portrait }
        app.launch()
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
        // Each case owns its initial intent; relaunches inside the case retain it.
        addTeardownBlock { @MainActor in resetAudio() }
        resetAudio()
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
        XCTAssertTrue(audio.waitForExistence(timeout: 5))
        XCTAssertTrue(audio.isHittable)
        XCTAssertEqual(audio.value as? String, "0")
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

    @MainActor func testPeriodicUDPEchoThroughRunningServerAndPersistence() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        addTeardownBlock { @MainActor in app.terminate(); XCUIDevice.shared.orientation = .portrait }
        XCUIDevice.shared.orientation = .portrait
        app.launch()
        let state = app.staticTexts["background.udpEcho.state"]
        let sentElements = app.descendants(matching: .any)
            .matching(identifier: "background.udpEcho.sentCount")
        let sent = sentElements.element
        let destination = app.textFields
            .matching(identifier: "background.udpEcho.destinations").firstMatch
        let period = app.textFields["background.udpEcho.period"]

        @MainActor func toggle() -> XCUIElement {
            let row = app.switches["background.udpEcho.enabled"]
            let backing = row.switches.firstMatch
            return backing.exists ? backing : row
        }
        @MainActor func reveal(_ element: XCUIElement, upward: Bool = true) {
            for _ in 0..<12 {
                if element.exists && element.isHittable { break }
                let form = app.collectionViews.firstMatch.exists ?
                    app.collectionViews.firstMatch : app.scrollViews.firstMatch
                if upward { form.swipeUp() } else { form.swipeDown() }
            }
            XCTAssertTrue(element.exists && element.isHittable, "Use the actual reachable control")
        }
        @MainActor func background() {
            XCTAssertTrue(app.tabBars.buttons["Background"].waitForExistence(timeout: 10))
            app.tabBars.buttons["Background"].tap()
            reveal(toggle())
        }
        @MainActor func expectState(_ text: String) {
            reveal(state)
            let expectation = XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "label == %@", text), object: state)
            XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 10), .completed)
        }
        @MainActor func sentValue() -> UInt64? {
            guard sentElements.count == 1, sent.label == "Sent",
                  let value = sent.value as? String else { return nil }
            return UInt64(value)
        }
        @MainActor func sentCount() throws -> UInt64 {
            reveal(sent)
            return try XCTUnwrap(sentValue(),
                                 "Sent must be one element labeled Sent with the numeric datagram count as its value")
        }
        @MainActor func replace(_ field: XCUIElement, with text: String) {
            reveal(field)
            XCTAssertTrue(field.isEnabled)
            field.tap()
            // A tap may place the insertion point before the existing text.
            app.typeKey("a", modifierFlags: .command)
            app.typeText(text)
            XCTAssertEqual(field.value as? String, text)
        }
        @MainActor func server(running: Bool) {
            XCTAssertTrue(app.tabBars.buttons["Server"].waitForExistence(timeout: 10))
            app.tabBars.buttons["Server"].tap()
            let control = app.buttons[running ? "Start" : "Stop"]
            reveal(control)
            XCTAssertTrue(waitUntil { app.buttons["Start"].isEnabled || app.buttons["Stop"].isEnabled })
            if control.isEnabled { control.tap() }
            XCTAssertTrue(waitUntil { app.buttons["Stop"].isEnabled == running &&
                app.buttons["Start"].isEnabled != running })
            XCTAssertTrue(waitUntil { Self.handshake() == running }, "Actual native listener must follow Start/Stop")
        }
        @MainActor func saved() {
            if app.keyboards.firstMatch.exists {
                let done = app.buttons["background.udpEcho.done"]
                XCTAssertTrue(done.waitForExistence(timeout: 5))
                XCTAssertTrue(done.isHittable, "Done must be reachable above the keyboard")
                done.tap()
                XCTAssertTrue(waitUntil { !app.keyboards.firstMatch.exists },
                              "Keyboard must close before tab navigation")
            }
            let tab = app.tabBars.buttons["Settings"]
            XCTAssertTrue(waitUntil { tab.isHittable }, "Settings tab must be reachable")
            tab.tap()
            let export = app.buttons["Export JSON"]
            XCTAssertTrue(export.waitForExistence(timeout: 5))
            XCTAssertTrue(waitUntil {
                export.isHittable && export.isEnabled &&
                    !app.staticTexts["Loading saved settings..."].exists &&
                    !app.staticTexts["Saving changes..."].exists && !app.buttons["Retry Save"].exists
            }, "Accepted settings must be durable before testing process recreation")
        }
        @MainActor func expectFields(enabled: Bool) {
            background()
            XCTAssertEqual(toggle().value as? String, enabled ? "1" : "0")
            reveal(destination)
            XCTAssertEqual(destination.value as? String, "127.0.0.1,::1")
            reveal(period)
            XCTAssertEqual(period.value as? String, "00200", "Persist the user's raw period text")
        }
        func packets(atLeast minimum: [String: Int], replies: Bool) throws -> EchoObservation {
            let deadline = Date().addingTimeInterval(10)
            repeat {
                let value = try Self.echoFixture("snapshot")
                XCTAssertEqual(value.replies, replies)
                XCTAssertTrue(value.valid, "UDP7 must receive the one-byte payload from the native loopback relay")
                if ["4", "6"].allSatisfy({ value.counts[$0, default: 0] >= minimum[$0, default: 0] }) {
                    return value
                }
                Thread.sleep(forTimeInterval: 0.05)
            } while Date() < deadline
            XCTFail("The actual app must continue periodic sends to both UDP7 destinations")
            throw NSError(domain: "IntegratedUDPEcho", code: 1)
        }
        func quiet() throws {
            // Drain datagrams already accepted before Stop/Off, then observe four periods.
            Thread.sleep(forTimeInterval: 0.4)
            let before = try Self.echoFixture("snapshot")
            Thread.sleep(forTimeInterval: 0.8)
            let after = try Self.echoFixture("snapshot")
            XCTAssertEqual(after.epoch, before.epoch)
            XCTAssertEqual(after.counts, before.counts, "Stopped/Off intent must leave no periodic sends")
            XCTAssertTrue(after.valid)
        }

        _ = try Self.echoFixture("reply")
        server(running: false)
        background()
        if toggle().value as? String == "1" { toggle().tap() }
        expectState("Off")
        replace(destination, with: "127.0.0.1,::1")
        replace(period, with: "00200")
        saved()
        background()
        toggle().tap()
        XCTAssertEqual(toggle().value as? String, "1")
        expectState("Waiting for SOCKS5 server")
        reveal(sent)
        let initialAccessibility = XCTAttachment(string:
            "matches: \(sentElements.count)\nlabel: \(String(reflecting: sent.label))\nvalue: \(String(reflecting: sent.value))")
        initialAccessibility.name = "integrated-udp-echo-initial-accessibility"
        initialAccessibility.lifetime = .keepAlways
        add(initialAccessibility)
        let initialCapture = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        initialCapture.name = "integrated-udp-echo-initial-zero"
        initialCapture.lifetime = .keepAlways
        add(initialCapture)
        XCTAssertEqual(try sentCount(), 0, "A new On starts at zero while no server is running")
        try quiet()
        server(running: true)
        let replying = try packets(atLeast: ["4": 3, "6": 3], replies: true)
        XCTAssertEqual(replying.ports["4"]?.count, 1, "Periodic sends must reuse the IPv4 association")
        XCTAssertEqual(replying.ports["6"]?.count, 1, "Periodic sends must reuse the IPv6 association")
        background()
        expectState("Sending UDP Echo")
        reveal(sent)
        XCTAssertTrue(waitUntil { (sentValue() ?? 0) > 0 }, "Actual sends must update the Sent row")
        let replyingCount = try sentCount()
        let capture = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        capture.name = "integrated-udp-echo-running"; capture.lifetime = .keepAlways; add(capture)

        // Keep the receiving sockets open while deliberately sending no replies.
        _ = try Self.echoFixture("drop")
        let silent = try packets(atLeast: ["4": 4, "6": 4], replies: false)
        let continued = try packets(atLeast: silent.counts.mapValues { $0 + 3 }, replies: false)
        XCTAssertEqual(continued.ports["4"]?.count, 1)
        XCTAssertEqual(continued.ports["6"]?.count, 1)
        XCTAssertTrue(waitUntil { (sentValue() ?? 0) > replyingCount },
                      "Sent must continue increasing without Echo replies")
        let silentCount = try sentCount()
        server(running: false)
        expectFields(enabled: true)
        expectState("Waiting for SOCKS5 server")
        try quiet()
        let stoppedCount = try sentCount()
        XCTAssertGreaterThanOrEqual(stoppedCount, silentCount, "Stopping the server must preserve the same On count")
        let stopped = try Self.echoFixture("snapshot")
        server(running: true)
        _ = try packets(atLeast: stopped.counts.mapValues { $0 + 3 }, replies: false)
        background()
        expectState("Sending UDP Echo")
        reveal(sent)
        XCTAssertTrue(waitUntil { (sentValue() ?? 0) > stoppedCount },
                      "Server restart must continue the existing On count")

        // Relaunch must restore actual sends, the On intent and both raw inputs.
        saved()
        app.terminate()
        XCTAssertTrue(waitUntil { !Self.handshake() })
        let terminated = try Self.echoFixture("snapshot")
        app.launch()
        expectFields(enabled: true)
        XCTAssertTrue(waitUntil { Self.handshake() })
        _ = try packets(atLeast: terminated.counts.mapValues { $0 + 3 }, replies: false)
        reveal(sent)
        XCTAssertTrue(waitUntil { (sentValue() ?? 0) > 0 })
        let relaunchedCount = try sentCount()
        reveal(toggle(), upward: false)
        toggle().tap()
        XCTAssertEqual(toggle().value as? String, "0")
        expectState("Off")
        try quiet()
        let offCount = try sentCount()
        XCTAssertGreaterThanOrEqual(offCount, relaunchedCount, "Off retains all accepted sends from the ending On")
        XCTAssertTrue(Self.handshake(), "Echo Off must leave the independently running server intact")
        // A stopped server makes the next On's zero observable before any new send.
        server(running: false)
        background()
        expectState("Off")
        XCTAssertEqual(try sentCount(), offCount, "The final Off count must remain visible")
        reveal(toggle(), upward: false)
        toggle().tap()
        expectState("Waiting for SOCKS5 server")
        XCTAssertEqual(try sentCount(), 0, "The next Off-to-On must reset the displayed count")
        reveal(toggle(), upward: false)
        toggle().tap()
        expectState("Off")
        XCTAssertEqual(try sentCount(), 0)
        server(running: true)
        saved()
        app.terminate()
        XCTAssertTrue(waitUntil { !Self.handshake() })
        app.launch()
        expectFields(enabled: false)
        expectState("Off")
        XCTAssertTrue(waitUntil { Self.handshake() }, "Saved server Start survives Echo Off")
        try quiet()
        server(running: false)
        saved()
        let final = try Self.echoFixture("snapshot")
        let evidence = XCTAttachment(string: "UDP7 fixture: \(final.counts); Echo Off, server stopped, raw fields preserved")
        evidence.name = "integrated-udp-echo-final"; evidence.lifetime = .keepAlways; add(evidence)
    }

    private struct EchoObservation: Decodable {
        let epoch: Int
        let replies: Bool
        let counts: [String: Int]
        let ports: [String: [Int]]
        let valid: Bool
    }

    /// Test-runner control channel only; the application sees only ordinary UDP7 traffic.
    private static func echoFixture(_ command: String) throws -> EchoObservation {
        let port = try XCTUnwrap(UInt16(ProcessInfo.processInfo.environment["UDP_ECHO_FIXTURE_PORT"] ?? ""),
                                "The temporary test scheme must identify its host UDP7 fixture")
        let fd = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
        defer { Darwin.close(fd) }
        var noSignal: Int32 = 1
        var timeout = timeval(tv_sec: 5, tv_usec: 0)
        guard setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &noSignal,
                         socklen_t(MemoryLayout.size(ofValue: noSignal))) == 0,
              setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout,
                         socklen_t(MemoryLayout.size(ofValue: timeout))) == 0,
              setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout,
                         socklen_t(MemoryLayout.size(ofValue: timeout))) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        guard inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1,
              withUnsafePointer(to: &address, {
                  $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                      Darwin.connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                  }
              }) == 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
        let request = Array((command + "\n").utf8)
        var offset = 0
        while offset < request.count {
            let count = request.withUnsafeBytes {
                Darwin.send(fd, $0.baseAddress!.advanced(by: offset), $0.count - offset, 0)
            }
            guard count > 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            offset += count
        }
        var response = Data()
        var buffer = [UInt8](repeating: 0, count: 1024)
        while !response.contains(10) && response.count < 16_384 {
            let receiveStartedUnix = Date().timeIntervalSince1970
            let receiveStarted = ProcessInfo.processInfo.systemUptime
            let count = buffer.withUnsafeMutableBytes { Darwin.recv(fd, $0.baseAddress, $0.count, 0) }
            let receiveErrno = errno
            guard count > 0 else {
                throw NSError(domain: NSPOSIXErrorDomain, code: Int(receiveErrno), userInfo: [
                    NSLocalizedDescriptionKey: "UDP Echo fixture recv: command=\(command), " +
                        "count=\(count), errno=\(receiveErrno), received_bytes=\(response.count), " +
                        "started_unix=\(receiveStartedUnix), finished_unix=\(Date().timeIntervalSince1970), " +
                        "elapsed_seconds=\(ProcessInfo.processInfo.systemUptime - receiveStarted)"
                ])
            }
            response.append(contentsOf: buffer.prefix(count))
        }
        return try JSONDecoder().decode(EchoObservation.self, from: response)
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
