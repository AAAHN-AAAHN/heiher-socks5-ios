import Foundation

/// Value-only corroboration. Neither a moving device clock nor a stationary loop
/// position alone proves whether this player is rendering. No AV objects live here.
struct PlaybackProgressMonitor {
    enum Health: String, Sendable {
        case reportedPlaying = "Playback reported by the system"
        case progressObserved = "Playback position advancing"
        case suspectedStall = "Playback progress is suspect"
        case inconclusive = "Playback progress cannot be confirmed"
    }

    struct Sample: Sendable {
        let generation: UInt64
        let epoch: UInt64
        let playing: Bool
        let configured: Bool
        let position: Double
        let deviceTime: Double
        let duration: Double
        let rate: Double
        let startedAt: Double
        let finishedAt: Double
        /// The actual I/O buffer interval, not assumed sample-accurate precision.
        let bufferDuration: Double
    }

    struct Assessment: Sendable {
        let health: Health
        let nextDelay: Double
        let mayRebuild: Bool
    }

    private var previous: Sample?
    private var lastEvidence = 0.0
    private var warmUntil = 0.0
    private var nextBurst = 0.0
    private var burst: [Sample] = []
    private var suspectWindows = 0
    private var lastRebuild = -Double.infinity
    private var speculativeUsed = false
    private static let offsets = [0.0, 0.017, 0.048, 0.091]

    mutating func reset(now: Double) {
        previous = nil
        lastEvidence = now
        warmUntil = now + 2
        nextBurst = now + 3
        burst.removeAll(keepingCapacity: true)
        suspectWindows = 0
        // Do not reset the speculative budget just because we recreated a player.
    }

    mutating func knownFailure(now: Double) {
        speculativeUsed = false
        reset(now: now)
    }

    private func valid(_ s: Sample) -> Bool {
        [s.position, s.deviceTime, s.duration, s.rate, s.startedAt,
         s.finishedAt, s.bufferDuration].allSatisfy(\.isFinite)
            && s.duration > 0 && s.rate > 0 && s.bufferDuration >= 0
            && s.position >= 0 && s.position <= s.duration
            && s.deviceTime >= 0 && s.startedAt >= 0
            && s.finishedAt >= s.startedAt && s.finishedAt - s.startedAt <= 0.1
            && s.playing && s.configured
    }

    private func compatible(_ a: Sample, _ b: Sample) -> Bool {
        a.generation == b.generation && a.epoch == b.epoch
            && abs(a.duration - b.duration) < 0.000001 && a.rate == b.rate
            && b.startedAt >= a.finishedAt && b.finishedAt - a.finishedAt <= 1
            && b.deviceTime >= a.deviceTime
    }

    private func distance(_ x: Double, period: Double) -> Double {
        let r = abs(x.truncatingRemainder(dividingBy: period))
        return min(r, period - r)
    }

    private func tolerance(_ a: Sample, _ b: Sample) -> Double {
        max(0.00025, max(a.bufferDuration, b.bufferDuration)
            + (a.finishedAt - a.startedAt) + (b.finishedAt - b.startedAt)) * max(a.rate, b.rate)
    }

    mutating func inspect(_ s: Sample, speculativeRecoveryCertified: Bool = false) -> Assessment {
        guard valid(s) else {
            previous = nil
            burst.removeAll(keepingCapacity: true)
            suspectWindows = 0
            return Assessment(health: .inconclusive, nextDelay: 0.5, mayRebuild: false)
        }
        let now = s.finishedAt
        guard let p = previous else {
            reset(now: now)
            previous = s
            return Assessment(health: .reportedPlaying, nextDelay: 0.5, mayRebuild: false)
        }
        guard compatible(p, s) else {
            reset(now: now)
            previous = s
            return Assessment(health: .inconclusive, nextDelay: 0.5, mayRebuild: false)
        }
        previous = s
        let moved = distance(s.position - p.position, period: s.duration) > tolerance(p, s)
        if moved {
            lastEvidence = now
            suspectWindows = 0
            speculativeUsed = false
            burst.removeAll(keepingCapacity: true)
            return Assessment(health: .progressObserved, nextDelay: 0.5, mayRebuild: false)
        }
        guard now >= warmUntil, now - lastEvidence >= 3 else {
            return Assessment(health: .reportedPlaying, nextDelay: 0.5, mayRebuild: false)
        }
        if burst.isEmpty {
            guard now >= nextBurst else {
                return Assessment(health: .inconclusive, nextDelay: 0.5, mayRebuild: false)
            }
            burst = [s]
            nextBurst = now + 3
            return Assessment(health: .inconclusive, nextDelay: Self.offsets[1], mayRebuild: false)
        }
        burst.append(s) // Maximum four samples; no history proportional to uptime.
        let elapsed = now - burst[0].finishedAt
        if burst.count < 4, let offset = Self.offsets.dropFirst().first(where: { $0 > elapsed + 0.001 }) {
            return Assessment(health: .inconclusive, nextDelay: offset - elapsed, mayRebuild: false)
        }
        var informative = 0
        for a in burst.dropLast() {
            guard compatible(a, s) else { continue }
            let uncertainty = tolerance(a, s)
            let expected = distance((s.deviceTime - a.deviceTime) * s.rate, period: s.duration)
            let observed = distance(s.position - a.position, period: s.duration)
            // A timing/quantization bound that covers the whole loop is inconclusive.
            if uncertainty < s.duration / 8 && expected > uncertainty * 3 && observed <= uncertainty {
                informative += 1
            }
        }
        burst.removeAll(keepingCapacity: true)
        suspectWindows = informative >= 2 ? min(2, suspectWindows + 1) : 0
        let suspect = suspectWindows >= 2
        let rebuild = speculativeRecoveryCertified && suspect && !speculativeUsed && now - lastRebuild >= 30
        if rebuild {
            speculativeUsed = true
            lastRebuild = now
        }
        return Assessment(health: suspect ? .suspectedStall : .inconclusive,
                          nextDelay: 0.5, mayRebuild: rebuild)
    }
}
