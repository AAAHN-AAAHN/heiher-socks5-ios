import Foundation

/// Execute the actual model/controller; only the blocking engine is substituted.
@main struct RevalidationTests {
    @MainActor static func main() async throws {
        var checks = 0
        var failures = 0
        func check(_ condition: Bool, _ name: String) {
            checks += 1
            if condition { print("PASS: \(name)") }
            else { failures += 1; print("FAIL: \(name)") }
        }
        let originalControl = CommandLine.arguments.contains("--unicode-only")
        let paths: [WritableKeyPath<ServerSettings, String>] = [
            \.workers, \.listenAddress, \.listenPort, \.udpListenAddress, \.udpListenPort,
            \.bindIPv4Address, \.bindIPv6Address, \.bindInterface, \.authUsername, \.authPassword
        ]
        let pairs = [("\u{00e9}", "e\u{0301}"), ("\u{ac00}", "\u{1100}\u{1161}")]
        for (composed, decomposed) in pairs {
            precondition(composed == decomposed && !composed.utf8.elementsEqual(decomposed.utf8))
            for path in paths {
                var a = ServerSettings()
                a[keyPath: path] = composed
                var b = a
                b[keyPath: path] = decomposed
                check(a != b && b != a && a == a && b == b,
                      "Distinct UTF-8 drafts are unequal; exact copies remain equal")
            }
        }
        // The actual controller must not suppress an on-wire credential change.
        let server = ServerController()
        for path in [\ServerSettings.authUsername, \ServerSettings.authPassword] {
            var a = ServerSettings()
            a.authUsername = "user"
            a.authPassword = "password"
            a[keyPath: path] = pairs[0].0
            var b = a
            b[keyPath: path] = pairs[0].1
            let start = EngineProbe.snapshot().0
            server.apply(a, running: true)
            await waitUntil { EngineProbe.snapshot().0 == start + 1 }
            server.apply(b, running: true)
            // A negative control has no restart; do not disguise that as a timeout.
            for _ in 0..<100 {
                if EngineProbe.snapshot().0 >= start + 2 { break }
                try await Task.sleep(for: .milliseconds(2))
            }
            let configs = EngineProbe.snapshot().2
            let expected = try b.configuration()
            check(EngineProbe.snapshot().0 == start + 2 && configs.last!.utf8.elementsEqual(expected.utf8),
                  "A canonically equivalent credential change reaches the next engine invocation")
            server.apply(b, running: false)
            await waitUntil { !server.isRunning }
        }
        if !originalControl {
            var a = ServerSettings()
            var b = a
            b.listenIPv6Only = true
            check(a != b, "The eleventh Boolean field participates in equality")
            let encode = JSONEncoder()
            encode.outputFormatting = [.sortedKeys]
            a.authUsername = "user"
            a.authPassword = pairs[1].1
            let roundTrip = try JSONDecoder().decode(ServerSettings.self, from: encode.encode(a))
            check(roundTrip == a && roundTrip.authPassword.utf8.elementsEqual(a.authPassword.utf8),
                  "Codable retains raw credential bytes and the existing schema")
            let textPaths = Array(paths.enumerated().filter { ![0, 2, 4].contains($0.offset) }.map(\.element))
            for path in textPaths {
                var value = ServerSettings()
                value.authUsername = "user"; value.authPassword = "password"
                value[keyPath: path] = String(repeating: "x", count: 255)
                _ = try value.configuration()
                value[keyPath: path] += "x"
                do { _ = try value.configuration(); check(false, "Reject overlong executable field") }
                catch { check(true, "Reject overlong executable field") }
                for separator in ["\0", "\n", "\r", "\u{0085}", "\u{2028}", "\u{2029}"] {
                    value[keyPath: path] = "a" + separator + "b"
                    do { _ = try value.configuration(); check(false, "Reject YAML text separator") }
                    catch { check(true, "Reject YAML text separator") }
                }
            }
            a = ServerSettings()
            let before = EngineProbe.snapshot().0
            server.apply(a, running: true)
            await waitUntil { EngineProbe.snapshot().0 == before + 1 }
            b = a; b.listenPort = "20001"
            var c = a; c.listenPort = "20002"
            server.apply(b, running: true)
            server.apply(c, running: true)
            await waitUntil { EngineProbe.snapshot().0 == before + 2 && server.status == "Running" }
            check(EngineProbe.snapshot().2.last!.utf8.elementsEqual(try c.configuration().utf8),
                  "Only the latest configuration starts after an in-flight stop")
            let running = EngineProbe.snapshot().0
            for _ in 0..<100 { server.apply(c, running: true, retry: true) }
            check(EngineProbe.snapshot().0 == running, "Explicit retry never duplicates a still-running invocation")
            server.apply(b, running: true)
            server.apply(c, running: false)
            await waitUntil { !server.isRunning }
            check(EngineProbe.snapshot().0 == running && server.status == "Stopped",
                  "Latest Stop cancels queued reconfiguration and clears status")
            server.apply(c, running: true)
            server.apply(c, running: false)
            await waitUntil { !server.isRunning }
            check(EngineProbe.snapshot().1 == 1, "Stop before worker entry preserves single-invocation ownership")
            let canceledCount = EngineProbe.snapshot().0
            server.apply(c, running: true)
            await waitUntil { EngineProbe.snapshot().0 == canceledCount + 1 }
            var invalid = c; invalid.workers = "bad"
            server.apply(invalid, running: true)
            await waitUntil { !server.isRunning }
            check(EngineProbe.snapshot().0 == canceledCount + 1 && server.status != "Running",
                  "Invalid replacement stops the old invocation without executing invalid YAML")
            for _ in 0..<50 { server.apply(invalid, running: true) }
            check(EngineProbe.snapshot().0 == canceledCount + 1, "Invalid drafts cannot create an automatic retry loop")
            server.apply(invalid, running: false)
            for result: Int32 in [0, -1, -7] {
                EngineProbe.failNext(result)
                let count = EngineProbe.snapshot().0
                server.apply(c, running: true)
                await waitUntil { !server.isRunning }
                for _ in 0..<50 { server.apply(c, running: true) }
                check(EngineProbe.snapshot().0 == count + 1 && server.status.contains("(\(result))"),
                      "Unexpected result \(result) is visible and requires explicit/new intent")
                server.apply(c, running: true, retry: true)
                await waitUntil { EngineProbe.snapshot().0 == count + 2 }
                server.apply(c, running: false)
                await waitUntil { !server.isRunning }
            }
            let count = EngineProbe.snapshot().0
            for _ in 0..<100 { server.apply(invalid, running: false, retry: true) }
            check(EngineProbe.snapshot().0 == count && server.status == "Stopped",
                  "Stopped invalid options never activate the engine, even with retry requested")
            check(EngineProbe.snapshot().1 == 1, "No tested transition overlaps native invocations")
        }
        print("SUMMARY: \(checks) server revalidation assertions; \(failures) failed; engine boundary substituted")
        if failures != 0 { exit(1) }
    }

    @MainActor static func waitUntil(_ condition: () -> Bool) async {
        for _ in 0..<1000 {
            if condition() { return }
            try? await Task.sleep(for: .milliseconds(2))
        }
        fatalError("Engine boundary did not settle in the bounded test window")
    }
}
