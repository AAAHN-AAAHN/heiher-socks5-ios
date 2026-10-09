// Appended to the unchanged sample fixture's support types by sampling_contract.py.
// Real Swift tasks, controlled wall clock/sleep/native snapshots; no SwiftUI lifecycle claim.
enum SampleScenePhase { case active, inactive, background }

@MainActor struct Date {
    static var now = 100.125
    static var reads = 0
    static var nativeWork = 0.0

    var timeIntervalSinceReferenceDate: Double {
        Self.reads += 1
        return Self.now
    }

    // The task replay's native read substitute calls this before returning.
    static func advanceForNativeRead() {
        now += nativeWork
        ProcessInfo.processInfo.systemUptime += nativeWork
        nativeWork = 0
    }
}

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
        func checkWait(until target: Double, _ reason: String) {
            let requested = SleepBoundary.requests.last!
            check(requested == .seconds(target - Date.now),
                  "next sleep targets device-clock .0/.5 boundary: \(reason)")
            check(requested > .zero && requested <= .milliseconds(500),
                  "one strictly future boundary, at most 500 ms away: \(reason)")
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
              SleepBoundary.requests.isEmpty && Date.reads == 0,
              "hidden/inactive/pre-cancelled tasks perform no sampling, clock reads or sleep")

        NativeSnapshot.rows = [HevSocks5EndpointStats(id: 7, received: 100, sent: 200)]
        let visible = Task { await view.runTask(isVisible: true, scenePhase: .active) }
        await SleepBoundary.waitForSleep()
        check(view.statistics.received == 100 && view.statistics.sent == 200 &&
              view.statistics.sumRate == 0, "entry reads current native totals with a zero-rate baseline")
        checkWait(until: 100.5, "entry between boundaries")
        let modern = 813_628_800.0
        // Explicit expected boundaries; the production rounding expression is
        // extracted from the view, not copied into the test's expected values.
        let cases: [(wall: Double, next: Double, elapsed: Double, work: Double, reason: String)] = [
            (100.5, 101, 0.5, 0, "exact half-second"),
            (101, 101.5, 0.5, 0, "exact whole second"),
            (101.25, 101.5, 0.25, 0, "between boundaries"),
            (101.5.nextDown, 101.5, 0.25, 0, "just before half-second"),
            (101.5.nextUp, 102, 0.125, 0, "just after half-second"),
            (102.0.nextDown, 102, 0.5, 0, "just before whole second"),
            (102.0.nextUp, 102.5, 0.5, 0, "just after whole second"),
            (106.25, 106.5, 4.25, 0, "late wake skips missed boundaries"),
            (106.5, 108, 0.25, 1.25, "native read work overruns two boundaries"),
            (3_600.25, 3_600.5, 0.5, 0, "wall clock jumps forward"),
            (-0.75, -0.5, 0.5, 0, "wall clock jumps backward before reference date"),
            (-0.5, 0, 0.5, 0, "negative half-second"),
            (0, 0.5, 0.5, 0, "reference-date boundary"),
            ((modern + 0.5).nextDown, modern + 0.5, 0.75, 0, "modern epoch just before half-second"),
            ((modern + 0.5).nextUp, modern + 1, 0.5, 0, "modern epoch just after half-second"),
            (modern.nextDown, modern, 0.5, 0, "modern epoch just before whole second"),
            (modern.nextUp, modern + 0.5, 0.5, 0, "modern epoch just after whole second"),
        ]
        for (index, test) in cases.enumerated() {
            let queries = NativeSnapshot.queries
            let copies = NativeSnapshot.copies
            let writes = view.$clients.writes
            let incoming = UInt64(index + 1) * 300
            let outgoing = UInt64(index + 1) * 75
            NativeSnapshot.rows[0].received += incoming
            NativeSnapshot.rows[0].sent += outgoing
            Date.now = test.wall
            Date.nativeWork = test.work
            ProcessInfo.processInfo.systemUptime += test.elapsed
            SleepBoundary.resume()
            await SleepBoundary.waitForSleep()
            check(NativeSnapshot.queries == queries + 1 && NativeSnapshot.copies == copies + 1 &&
                  view.$clients.writes == writes + 1, "one sample/publication per resumed sleep")
            let interval = test.elapsed + test.work
            let receiveRate = Double(incoming) / interval
            let sendRate = Double(outgoing) / interval
            check(view.statistics.received == NativeSnapshot.rows[0].received &&
                  view.statistics.sent == NativeSnapshot.rows[0].sent &&
                  view.statistics.receiveRate == receiveRate && view.statistics.sendRate == sendRate &&
                  view.clients.entries[7]?.traffic.sumRate == receiveRate + sendRate,
                  "Total and peer rates use actual elapsed uptime despite device-clock changes")
            check(Date.nativeWork == 0 && Date.now == test.wall + test.work,
                  "next boundary is selected after sample work completes")
            checkWait(until: test.next, test.reason)
        }
        let queries = NativeSnapshot.queries
        let clockReads = Date.reads
        visible.cancel()
        SleepBoundary.resume(throwing: true)
        await visible.value
        check(NativeSnapshot.queries == queries && SleepBoundary.pending == nil && Date.reads == clockReads,
              "cancellation thrown from sleep prevents another sample or clock read")

        // Traffic accumulates while hidden; no task polls or resets these counters.
        NativeSnapshot.rows[0].received += 10_000
        NativeSnapshot.rows[0].sent += 20_000
        ProcessInfo.processInfo.systemUptime += 20
        let writes = view.$statistics.writes
        await view.runTask(isVisible: false, scenePhase: .active)
        check(NativeSnapshot.queries == queries && view.$statistics.writes == writes && Date.reads == clockReads,
              "hidden traffic performs no display sampling")
        Date.now = modern + 0.25
        let resumed = Task { await view.runTask(isVisible: true, scenePhase: .active) }
        await SleepBoundary.waitForSleep()
        check(view.statistics.received == NativeSnapshot.rows[0].received &&
              view.statistics.sent == NativeSnapshot.rows[0].sent && view.statistics.sumRate == 0 &&
              view.clients.entries[7]?.traffic.sumRate == 0, "re-entry preserves native volume and resets rate baselines")
        checkWait(until: modern + 0.5, "re-entry chooses the current device-clock boundary")
        let resumedQueries = NativeSnapshot.queries
        let resumedClockReads = Date.reads
        resumed.cancel()
        SleepBoundary.resume() // Model a sleep that completes despite concurrent cancellation.
        await resumed.value
        check(NativeSnapshot.queries == resumedQueries && SleepBoundary.pending == nil &&
              Date.reads == resumedClockReads, "post-sleep cancellation guard prevents another sample or clock read")
        check(SleepBoundary.requests.count == cases.count + 2 && Date.reads == SleepBoundary.requests.count,
              "one clock read and one sleep per active loop; no duplicate or hidden sleeps")
        print("PASS:", checks, "exact task-body checks; device-clock boundaries, overruns, clock changes, visibility, cancellation and re-entry; no SwiftUI lifecycle claim")
    }
}
