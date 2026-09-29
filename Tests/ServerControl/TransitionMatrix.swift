import Foundation

/// The controller body is unchanged. Only dispatch/engine return timing is held.
@main struct TransitionMatrix {
    @MainActor static func main() async throws {
        var assertions = 0
        func check(_ value: @autoclosure () -> Bool, _ name: String) {
            assertions += 1
            precondition(value(), name)
        }
        var a = ServerSettings()
        a.authUsername = "u"; a.authPassword = "a"
        var b = a; b.authPassword = "b"
        var invalid = a; invalid.workers = "0"
        let invalidStatus = ServerConfigurationError.invalid(
            "Use 1-64 workers, a listen port of 1-65535, and a UDP port of 0-65535.").localizedDescription
        // Every four-command suffix while A owns the pending native invocation:
        // same intent, explicit same retry, replacement B, invalid replacement, Stop.
        var schedules = 0
        for code: Int32 in [0, -7] {
            for trace in 0..<625 {
                TransitionBoundary.reset()
                let server = ServerController()
                server.apply(a, running: true)
                check(server.isRunning && server.status == "Running", "Initial invocation state")
                var number = trace
                var last = 0
                var requestedQuit = false
                for _ in 0..<4 {
                    last = number % 5; number /= 5
                    requestedQuit = requestedQuit || last >= 2
                    switch last {
                    case 0: server.apply(a, running: true)
                    case 1: server.apply(a, running: true, retry: true)
                    case 2: server.apply(b, running: true)
                    case 3: server.apply(invalid, running: true)
                    default: server.apply(a, running: false)
                    }
                    check(TransitionBoundary.dispatches == 1, "Do not replace until native return")
                    check(TransitionBoundary.prepares == 1, "Prepare exactly once before dispatch")
                    check(TransitionBoundary.quits == (requestedQuit ? 1 : 0), "Quit exactly once per invocation")
                    check(server.isRunning, "In-flight cancellation retains invocation ownership")
                }
                TransitionBoundary.finish(code)
                let restart = requestedQuit && last < 3
                let expected = restart ? "Running" : (last == 4 ? "Stopped" :
                    (last == 3 ? invalidStatus : "Server exited (\(code)). Check settings, then press Start."))
                await settle { server.status == expected && server.isRunning == restart &&
                    TransitionBoundary.dispatches == (restart ? 2 : 1) }
                check(TransitionBoundary.prepares == (restart ? 2 : 1), "Validation precedes preparation")
                if restart {
                    let target = last == 2 ? b : a
                    server.apply(target, running: false)
                    TransitionBoundary.finish(0)
                    await settle { !server.isRunning && server.status == "Stopped" }
                    let wanted = try target.configuration()
                    check(TransitionBoundary.lastConfiguration.utf8.elementsEqual(wanted.utf8),
                          "Only latest desired raw bytes reach replacement engine")
                } else {
                    let count = TransitionBoundary.dispatches
                    let target = last == 3 ? invalid : a
                    for _ in 0..<10 { server.apply(target, running: last != 4) }
                    check(TransitionBoundary.dispatches == count, "No implicit retry after invalid/exited work")
                    server.apply(target, running: false)
                    check(server.status == "Stopped", "Stop clears error without launch")
                }
                check(TransitionBoundary.pending == nil, "No orphaned worker closure")
                schedules += 1
            }
        }
        // Return occurred, but its MainActor delivery has not run yet. A late
        // request cannot prepare a second invocation before completion processing.
        for mode in 0..<5 {
            TransitionBoundary.reset()
            let server = ServerController()
            server.apply(a, running: true)
            TransitionBoundary.finish(-1)
            switch mode {
            case 0: server.apply(a, running: false)
            case 1: server.apply(b, running: true)
            case 2: server.apply(invalid, running: true)
            case 3:
                server.apply(b, running: true); server.apply(a, running: false)
            default:
                server.apply(a, running: false); server.apply(a, running: true)
            }
            check(TransitionBoundary.prepares == 1, "Late intent does not overlap completion ownership")
            let restart = mode == 1 || mode == 4
            await settle { server.isRunning == restart && TransitionBoundary.dispatches == (restart ? 2 : 1) &&
                server.status == (restart ? "Running" : (mode == 2 ? invalidStatus : "Stopped")) }
            server.apply(a, running: false)
            if restart {
                TransitionBoundary.finish(0)
                await settle { !server.isRunning }
            }
            check(TransitionBoundary.pending == nil, "Late completion drained")
        }
        // The closure must retain the root-owned controller until its completion,
        // then release it; view disappearance must neither cancel nor leak it.
        TransitionBoundary.reset()
        weak var released: ServerController?
        do {
            let server = ServerController(); released = server
            server.apply(a, running: true)
        }
        check(released != nil, "Worker retains controller independently of caller lifetime")
        released?.apply(a, running: false)
        TransitionBoundary.finish(0)
        await settle { released == nil }
        check(TransitionBoundary.pending == nil, "Completed owner is released")
        print("PASS: \(schedules) four-intent schedules, five delayed-completion schedules, owner lifetime; \(assertions) assertions. Controlled engine/dispatch, actual controller and MainActor completion; not native socket trials.")
    }

    @MainActor private static func settle(_ condition: () -> Bool) async {
        for _ in 0..<1000 {
            if condition() { return }
            await Task.yield()
        }
        preconditionFailure("Controlled actor completion did not satisfy the expected postcondition")
    }
}
