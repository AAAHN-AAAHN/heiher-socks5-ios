// Appended to the unchanged sample fixture's support types by sampling_contract.py.
// Real Swift tasks, controlled sleep/native snapshots; no SwiftUI lifecycle claim.
enum SampleScenePhase { case active, inactive, background }

@MainActor enum SleepBoundary {
    static var requests: [Duration] = []
    static var pending: CheckedContinuation<Void, Error>?
    static var observer: CheckedContinuation<Void, Never>?

    static func sleep(for duration: Duration) async throws {
        precondition(pending == nil, "one awaited sleep per sampling loop")
        requests.append(duration)
        try await withCheckedThrowingContinuation { continuation in
            pending = continuation
            let waiting = observer
            observer = nil
            waiting?.resume()
        }
    }

    static func waitForSleep() async {
        if pending == nil {
            await withCheckedContinuation { observer = $0 }
        }
    }

    static func resume(throwing: Bool = false) {
        let continuation = pending!
        pending = nil
        if throwing { continuation.resume(throwing: CancellationError()) }
        else { continuation.resume() }
    }
}

extension SamplingHarness {
    func runTask(isVisible: Bool, scenePhase: SampleScenePhase) async {
        // INSERT_EXACT_TASK_BODY
    }
}

@main struct SamplingTaskTests {
    @MainActor static func main() async {
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ message: String) {
            checks += 1
            if !condition() { print("FAIL:", message); exit(1) }
        }
        let view = SamplingHarness()
        for phase in [SampleScenePhase.active, .inactive, .background] {
            await view.runTask(isVisible: false, scenePhase: phase)
            if phase != .active { await view.runTask(isVisible: true, scenePhase: phase) }
        }
        let cancelled = Task { await view.runTask(isVisible: true, scenePhase: .active) }
        cancelled.cancel() // MainActor cannot enter the new body before this cancellation.
        await cancelled.value
        check(view.$statistics.writes == 0 && view.$clients.writes == 0 &&
              view.$clientsIncomplete.writes == 0, "hidden/inactive/pre-cancelled tasks do not reset display state")
        check(NativeSnapshot.queries == 0 && NativeSnapshot.copies == 0 &&
              SleepBoundary.requests.isEmpty, "hidden/inactive/pre-cancelled tasks perform no sampling or sleep")

        NativeSnapshot.rows = [HevSocks5EndpointStats(id: 7, received: 100, sent: 200)]
        let visible = Task { await view.runTask(isVisible: true, scenePhase: .active) }
        await SleepBoundary.waitForSleep()
        check(view.statistics.received == 100 && view.statistics.sent == 200 &&
              view.statistics.sumRate == 0, "entry reads current native totals with a zero-rate baseline")
        for (interval, incoming, outgoing) in [(0.5, UInt64(300), UInt64(500)), (0.75, 150, 75)] {
            let queries = NativeSnapshot.queries
            let copies = NativeSnapshot.copies
            let writes = view.$clients.writes
            NativeSnapshot.rows[0].received += incoming
            NativeSnapshot.rows[0].sent += outgoing
            ProcessInfo.processInfo.systemUptime += interval
            SleepBoundary.resume()
            await SleepBoundary.waitForSleep()
            check(NativeSnapshot.queries == queries + 1 && NativeSnapshot.copies == copies + 1 &&
                  view.$clients.writes == writes + 1, "one sample/publication per resumed sleep")
            check(view.statistics.receiveRate == Double(incoming) / interval &&
                  view.statistics.sendRate == Double(outgoing) / interval &&
                  view.clients.entries[7]?.traffic.sumRate == Double(incoming + outgoing) / interval,
                  "Total and peer rates use actual elapsed time, including delayed half-second sampling")
        }
        let queries = NativeSnapshot.queries
        visible.cancel()
        SleepBoundary.resume(throwing: true)
        await visible.value
        check(NativeSnapshot.queries == queries && SleepBoundary.pending == nil,
              "cancellation thrown from sleep prevents another sample")

        // Traffic accumulates while hidden; no task polls or resets these counters.
        NativeSnapshot.rows[0].received += 10_000
        NativeSnapshot.rows[0].sent += 20_000
        ProcessInfo.processInfo.systemUptime += 20
        let writes = view.$statistics.writes
        await view.runTask(isVisible: false, scenePhase: .active)
        check(NativeSnapshot.queries == queries && view.$statistics.writes == writes,
              "hidden traffic performs no display sampling")
        let resumed = Task { await view.runTask(isVisible: true, scenePhase: .active) }
        await SleepBoundary.waitForSleep()
        check(view.statistics.received == NativeSnapshot.rows[0].received &&
              view.statistics.sent == NativeSnapshot.rows[0].sent && view.statistics.sumRate == 0 &&
              view.clients.entries[7]?.traffic.sumRate == 0, "re-entry preserves native volume and resets rate baselines")
        let resumedQueries = NativeSnapshot.queries
        resumed.cancel()
        SleepBoundary.resume() // Model a sleep that completes despite concurrent cancellation.
        await resumed.value
        check(NativeSnapshot.queries == resumedQueries && SleepBoundary.pending == nil,
              "post-sleep cancellation guard prevents another sample")
        check(SleepBoundary.requests.count == 4 &&
              SleepBoundary.requests.allSatisfy { $0 == .milliseconds(500) },
              "every active loop requests 500 ms; no duplicate or hidden sleeps")
        print("PASS:", checks, "exact task-body checks; visibility, cancellation, 500 ms and re-entry; no SwiftUI lifecycle claim")
    }
}
