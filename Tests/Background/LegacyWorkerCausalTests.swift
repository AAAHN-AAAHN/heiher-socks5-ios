// Declared causal variant of the historical legacy-worker fixture.
// The exact historical controller and PlatformMocks.swift remain unchanged.
// The first setActive waits inside its existing onActivation hook until three
// actual main Timer callbacks occur, within the same two-second total deadline.
// Subsequent release/rejected activation and all historical assertions remain.
import Foundation

final class LegacyActivationHeartbeatGate: @unchecked Sendable {
    private let condition = NSCondition()
    private let deadline: TimeInterval
    private var activating = false
    private var began: TimeInterval?
    private var ended: TimeInterval?
    private var activationOnMain = false
    private var beats: [TimeInterval] = []
    private var releasedByHeartbeats = false
    private var holdCalls = 0

    init(deadline: TimeInterval) { self.deadline = deadline }

    func holdFirstActivation() {
        condition.lock(); defer { condition.unlock() }
        guard began == nil else { return }
        holdCalls += 1
        activating = true
        activationOnMain = Thread.isMainThread
        began = ProcessInfo.processInfo.systemUptime
        while beats.count < 3 {
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            if remaining <= 0 { break }
            _ = condition.wait(until: Date().addingTimeInterval(remaining))
        }
        ended = ProcessInfo.processInfo.systemUptime
        releasedByHeartbeats = beats.count >= 3 && ended! <= deadline
        activating = false
    }

    func heartbeat() -> Bool {
        condition.lock(); defer { condition.unlock() }
        guard activating else { return false }
        beats.append(ProcessInfo.processInfo.systemUptime)
        if beats.count >= 3 { condition.signal() }
        return true
    }

    func snapshot() -> [String: Any] {
        condition.lock(); defer { condition.unlock() }
        return ["activationBegan": began ?? -1, "activationEnded": ended ?? -1,
                "activationOnMain": activationOnMain, "heartbeatTimes": beats,
                "releasedByHeartbeats": releasedByHeartbeats, "holdCalls": holdCalls,
                "deadline": deadline]
    }
}

@MainActor final class ResultState { var result: Bool?; var beats = 0 }
@main struct LegacyWorkerCausalTests {
    @MainActor static func main() {
        DispatchQueue.scriptUtility = false
        let session = AVAudioSession.shared
        session.synchronousDelay = 0.12
        let state = ResultState()
        let started = ProcessInfo.processInfo.systemUptime
        let firstDeadline = started + 2
        let gate = LegacyActivationHeartbeatGate(deadline: firstDeadline)
        session.onActivation = { gate.holdFirstActivation() }
        let timer = Foundation.Timer.scheduledTimer(withTimeInterval: 0.01, repeats: true) { _ in
            MainActor.assumeIsolated {
                if gate.heartbeat() { state.beats += 1 }
            }
        }
        defer { timer.invalidate(); session.onActivation = nil }
        var firstTransition = true
        func transition(_ active: Bool) {
            let isFirst = firstTransition
            firstTransition = false
            state.result = nil
            let completion: @Sendable (Bool, Error?) -> Void = { success, _ in
                DispatchQueue.main.async { state.result = success }
            }
            if isFirst && CommandLine.arguments.dropFirst().first == "blocking-control" {
                // Deliberately invalid caller: the unchanged synchronous mock
                // runs on main. firstDeadline was fixed before this can block.
                do {
                    try session.setActive(active)
                    completion(true, nil)
                } catch {
                    completion(false, error)
                }
            } else {
                BackgroundKeepAlive.exerciseLegacySession(active, completion: completion)
            }
            let requestReturned = ProcessInfo.processInfo.systemUptime
            let limit = Date().addingTimeInterval(2)
            while state.result == nil && Date() < limit
                && (!isFirst || ProcessInfo.processInfo.systemUptime < firstDeadline) {
                Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.005))
            }
            if isFirst {
                var observation = gate.snapshot()
                observation["resultReceived"] = state.result != nil
                observation["result"] = state.result ?? false
                observation["sessionIsActive"] = session.isActive
                observation["synchronousOnMain"] = session.synchronousOnMain
                observation["synchronousCalls"] = session.synchronousCalls
                observation["beats"] = state.beats
                observation["requestReturned"] = requestReturned
                observation["observationUptime"] = ProcessInfo.processInfo.systemUptime
                observation["elapsed"] = ProcessInfo.processInfo.systemUptime - started
                observation["observedOnMain"] = Thread.isMainThread
                let data = try! JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys])
                FileHandle.standardError.write(Data("LEGACY_HEARTBEAT_OBSERVATION ".utf8) + data + Data("\n".utf8))
                if state.result != true || !session.isActive || session.synchronousOnMain
                    || state.beats < 3 || observation["releasedByHeartbeats"] as? Bool != true {
                    FileHandle.standardError.write(Data("LEGACY_HEARTBEAT_DID_NOT_PROGRESS\n".utf8))
                }
            }
            precondition(state.result != nil)
        }
        transition(true)
        precondition(state.result == true && session.isActive && !session.synchronousOnMain && state.beats >= 3)
        precondition(gate.snapshot()["releasedByHeartbeats"] as? Bool == true)
        session.onActivation = nil
        print("PASS: actual legacy adapter waits on a utility worker while the main run loop remains responsive")
        transition(false)
        precondition(state.result == true && !session.isActive && !session.synchronousOnMain)
        session.rejectActivation = true
        transition(true)
        precondition(state.result == false && !session.isActive)
        print("PASS: legacy adapter propagates successful release and activation errors without main-thread setActive")
    }
}
