import Foundation
import Dispatch
#if os(Linux)
import Glibc
#else
import Darwin
#endif

// Diagnostic only. No environment keys or values are emitted.
@inline(never) func environmentFlag() -> Bool {
    ProcessInfo.processInfo.environment["LOOP_ENDPOINT_TRACE"] == "1"
}
@inline(never) func storedFlag(_ value: Bool) -> Bool { value }

func measure(_ name: String, count: Int, _ operation: () -> Int) -> [String: Any] {
    let began = ProcessInfo.processInfo.systemUptime
    let cpu = clock()
    var checksum = 0
    for _ in 0..<count { checksum += operation() }
    let elapsed = ProcessInfo.processInfo.systemUptime - began
    return ["name": name, "calls": count, "elapsed_seconds": elapsed,
            "per_call_seconds": elapsed / Double(count),
            "cpu_seconds": Double(clock() - cpu) / Double(CLOCKS_PER_SEC),
            "checksum": checksum]
}

// Locked diagnostic metadata, never an audio or product object.
final class TimerProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    private var started = 0.0
    private var prior = 0.0
    private var minimum = Double.infinity
    private var maximum = 0.0
    private var finished = 0.0
    private let queue = DispatchQueue(label: "Probe.control")
    private let done = DispatchSemaphore(value: 0)
    private var timer: DispatchSourceTimer?

    func run() -> [String: Any] {
        let source = DispatchSource.makeTimerSource(queue: queue)
        lock.lock()
        timer = source
        started = ProcessInfo.processInfo.systemUptime
        prior = started
        lock.unlock()
        source.setEventHandler { [self] in
            let now = ProcessInfo.processInfo.systemUptime
            lock.lock()
            let delta = now - prior
            prior = now
            minimum = min(minimum, delta)
            maximum = max(maximum, delta)
            count += 1
            let complete = count >= 1000
            if complete { finished = now }
            lock.unlock()
            if complete { source.cancel(); done.signal() }
            else { source.schedule(deadline: .now() + 0.005, leeway: .milliseconds(1)) }
        }
        source.schedule(deadline: .now() + 0.005, leeway: .milliseconds(1))
        source.resume()
        let status = done.wait(timeout: .now() + 10)
        source.cancel()
        // A diagnostic timeout remains a timeout; no completion is invented.
        lock.lock(); defer { lock.unlock() }
        return ["name": "same_timer_1000", "requested_interval": 0.005,
                "leeway": 0.001, "deadline": 10, "completed_ticks": count,
                "complete": status == .success,
                "elapsed_seconds": (finished == 0 ? ProcessInfo.processInfo.systemUptime : finished) - started,
                "minimum_interval": minimum.isFinite ? minimum : 0, "maximum_interval": maximum]
    }
}

@main struct FixtureCosts {
    static func main() throws {
        let flag = environmentFlag()
        let measurements = [
            measure("environment_getter", count: 8030) { environmentFlag() ? 1 : 0 },
            measure("cached_flag", count: 8030) { storedFlag(flag) ? 1 : 0 },
            measure("default_error_description", count: 1000) {
                NSError(domain: "ControlledAudioBoundary", code: 1).localizedDescription.utf8.count
            },
            TimerProbe().run()
        ]
        let result: [String: Any] = [
            "scope": "Diagnostic host costs only; no product pass, audio playback or physical-device claim.",
            "environment_entry_count": ProcessInfo.processInfo.environment.count,
            "measurements": measurements
        ]
        let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data("\n".utf8))
    }
}
