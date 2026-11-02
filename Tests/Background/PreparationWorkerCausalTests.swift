// A declared replacement for the historical preparation-worker timing fixture.
// The historical controller and platform double remain byte-for-byte inputs.
// Three real main-timer callbacks must occur while prepareToPlay is still active;
// the existing two-second fixture and thirty-second process limits do not grow.
import Foundation

final class PreparationHeartbeatGate: @unchecked Sendable {
    private let condition = NSCondition()
    private let deadline: TimeInterval
    private var preparing = false
    private var began: TimeInterval?
    private var ended: TimeInterval?
    private var beats: [TimeInterval] = []
    private var releasedByHeartbeats = false

    init(deadline: TimeInterval) { self.deadline = deadline }

    func holdPreparation() {
        condition.lock(); defer { condition.unlock() }
        preparing = true
        began = ProcessInfo.processInfo.systemUptime
        while beats.count < 3 {
            let remaining = deadline - ProcessInfo.processInfo.systemUptime
            if remaining <= 0 { break }
            _ = condition.wait(until: Date().addingTimeInterval(remaining))
        }
        ended = ProcessInfo.processInfo.systemUptime
        releasedByHeartbeats = beats.count >= 3 && ended! <= deadline
        preparing = false
    }

    func heartbeat() -> Bool {
        condition.lock(); defer { condition.unlock() }
        guard preparing else { return false }
        beats.append(ProcessInfo.processInfo.systemUptime)
        if beats.count >= 3 { condition.signal() }
        return true
    }

    func snapshot() -> [String: Any] {
        condition.lock(); defer { condition.unlock() }
        return ["preparationBegan": began ?? -1, "preparationEnded": ended ?? -1,
                "heartbeatTimes": beats, "releasedByHeartbeats": releasedByHeartbeats,
                "deadline": deadline]
    }
}

@MainActor final class CausalPreparationResult {
    var result: Bool?
    var beats = 0
}

@main struct PreparationWorkerCausalTests {
    @MainActor static func main() {
        DispatchQueue.scriptUtility = false
        AVAudioPlayer.preparationDelay = 0.12
        let player = try! AVAudioPlayer(contentsOf: URL(fileURLWithPath: "/Silence.wav"))
        let state = CausalPreparationResult()
        let started = ProcessInfo.processInfo.systemUptime
        let deadline = started + 2
        let gate = PreparationHeartbeatGate(deadline: deadline)
        AVAudioPlayer.onPrepare = { gate.holdPreparation() }
        let timer = Foundation.Timer.scheduledTimer(withTimeInterval: 0.01, repeats: true) { _ in
            MainActor.assumeIsolated {
                if gate.heartbeat() { state.beats += 1 }
            }
        }
        defer { timer.invalidate(); AVAudioPlayer.onPrepare = nil }
        let completion: @Sendable (Bool) -> Void = { success in
            DispatchQueue.main.async { state.result = success }
        }
        if CommandLine.arguments.dropFirst().first == "blocking-control" {
            // Deliberately invalid test input: perform the same mock preparation
            // directly on main. This must not pass the causal heartbeat check.
            completion(player.prepareToPlay())
        } else {
            BackgroundKeepAlive.exercisePreparation(player, completion: completion)
        }
        let requestReturned = ProcessInfo.processInfo.systemUptime
        while state.result == nil && ProcessInfo.processInfo.systemUptime < deadline {
            Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.005))
        }
        var observation = gate.snapshot()
        observation["resultReceived"] = state.result != nil
        observation["result"] = state.result ?? false
        observation["beats"] = state.beats
        observation["preparations"] = AVAudioPlayer.preparations
        observation["preparationsOnMain"] = AVAudioPlayer.preparationsOnMain
        observation["requestReturned"] = requestReturned
        observation["elapsed"] = ProcessInfo.processInfo.systemUptime - started
        let data = try! JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys])
        FileHandle.standardError.write(Data("PREPARATION_HEARTBEAT_OBSERVATION ".utf8) + data + Data("\n".utf8))
        if state.result != true || state.beats < 3 {
            FileHandle.standardError.write(Data("PREPARATION_HEARTBEAT_DID_NOT_PROGRESS\n".utf8))
        }
        precondition(state.result == true && state.beats >= 3)
        precondition(observation["releasedByHeartbeats"] as? Bool == true)
        precondition(AVAudioPlayer.preparations == 1 && AVAudioPlayer.preparationsOnMain == 0)
        precondition(player.isPrepared && !player.isPlaying)
        precondition(player.play() && AVAudioPlayer.implicitPreparations == 0)
        player.stop()
        print("PASS: three real main heartbeats occurred during exact historical preparation; prepared play adds no implicit preparation")
    }
}
