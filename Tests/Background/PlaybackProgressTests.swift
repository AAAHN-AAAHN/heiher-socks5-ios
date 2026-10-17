import Foundation

@main struct PlaybackProgressTests {
    static func check(_ value: Bool, _ message: String) {
        if !value {
            FileHandle.standardError.write(Data(("FAIL: " + message + "\n").utf8))
            fatalError(message)
        }
    }
    static func sample(_ time: Double, _ position: Double, clock: Double? = nil,
                       generation: UInt64 = 1, epoch: UInt64 = 0, duration: Double = 0.05,
                       rate: Double = 1, bracket: Double = 0, buffer: Double = 0.001,
                       playing: Bool = true, configured: Bool = true) -> PlaybackProgressMonitor.Sample {
        .init(generation: generation, epoch: epoch, playing: playing, configured: configured,
              position: position, deviceTime: clock ?? time, duration: duration, rate: rate,
              startedAt: time - bracket, finishedAt: time, bufferDuration: buffer)
    }
    static func main() {
        var cases = 0
        // A 50-ms loop sampled at 500 ms aliases. Probe deadlines must observe
        // progress without making an ordinary periodic tick a restart signal.
        for quantization in [0.0, 0.002, 0.004, 0.012] {
            var monitor = PlaybackProgressMonitor()
            var time = 1.0
            var shortProbes = 0
            var consecutive = 0
            for index in 0..<1000 {
                let phase = time.truncatingRemainder(dividingBy: 0.05)
                let position = quantization == 0 ? phase : floor(phase / quantization) * quantization
                let result = monitor.inspect(sample(time, position, buffer: max(0.001, quantization)),
                                             speculativeRecoveryCertified: true)
                check(!result.mayRebuild, "NORMAL_ALIAS_OR_QUANTIZATION_REBUILT")
                if result.nextDelay < 0.5 {
                    consecutive += 1; shortProbes += 1
                    check(consecutive <= 3, "PROBE_BUDGET_EXCEEDED")
                } else { consecutive = 0 }
                let jitter = index % 19 == 0 ? 0.003 : 0
                time += result.nextDelay + jitter
            }
            check(shortProbes < 600, "UNBOUNDED_EXTRA_PROBES")
            cases += 1
        }
        // A deliberately stopped reported player with a moving device clock is
        // suspect only after two informative windows. Default policy cannot act.
        for certified in [false, true] {
            var monitor = PlaybackProgressMonitor()
            var time = 1.0
            var rebuilds = 0
            var suspect = false
            for _ in 0..<1000 {
                let result = monitor.inspect(sample(time, 0), speculativeRecoveryCertified: certified)
                if result.mayRebuild { rebuilds += 1; check(time >= 7, "SPECULATION_BEFORE_TWO_WINDOWS") }
                suspect = suspect || result.health == .suspectedStall
                time += result.nextDelay
            }
            check(suspect && rebuilds == (certified ? 1 : 0), "SPECULATIVE_BUDGET_OR_CERTIFICATE")
            // A known failure is a separate episode; no old window survives it.
            monitor.knownFailure(now: time)
            let after = monitor.inspect(sample(time, 0, generation: 2, epoch: 1), speculativeRecoveryCertified: true)
            check(!after.mayRebuild, "OLD_WINDOW_CROSSED_RESOURCE_EPOCH")
            cases += 1
        }
        // Long property reads, invalid values, stale ordering and clock changes
        // must remain inconclusive, even with an explicit speculative certificate.
        let invalid: [PlaybackProgressMonitor.Sample] = [
            sample(2, .nan), sample(2, .infinity), sample(2, -0.001), sample(2, 0.06),
            sample(2, 0, clock: -.infinity), sample(2, 0, duration: 0), sample(2, 0, rate: 0),
            sample(2, 0, bracket: 0.101), sample(2, 0, bracket: -0.01), sample(2, 0, buffer: -1),
            sample(2, 0, playing: false), sample(2, 0, configured: false),
            sample(0.5, 0), sample(1.5, 0, clock: 1), sample(1.5, 0, clock: 7),
            sample(1.017, 0.017, generation: 2), sample(1.017, 0.017, epoch: 2),
            sample(1.017, 0.017, duration: 0.06), sample(1.017, 0.017, rate: 2),
        ]
        for invalidSample in invalid {
            var monitor = PlaybackProgressMonitor()
            _ = monitor.inspect(sample(1, 0))
            let result = monitor.inspect(invalidSample, speculativeRecoveryCertified: true)
            check(result.health == .inconclusive && !result.mayRebuild, "INVALID_PROGRESS_WAS_TRUSTED")
            cases += 1
        }
        var mismatch = PlaybackProgressMonitor()
        _ = mismatch.inspect(sample(1, 0))
        let inconsistent = mismatch.inspect(sample(1.017, 0.008))
        check(inconsistent.health != .progressObserved, "POSITION_DEVICE_DISAGREEMENT_ACCEPTED")
        var matching = PlaybackProgressMonitor()
        _ = matching.inspect(sample(1, 0, rate: 2))
        check(matching.inspect(sample(1.017, 0.034, rate: 2)).health == .progressObserved,
              "VALID_RATE_ADJUSTED_PROGRESS_REJECTED")
        // Rendering cannot be proved from identical reported properties. This
        // pair represents healthy and inaudibly stalled hardware with equal data.
        var healthy = PlaybackProgressMonitor(), opaqueStall = PlaybackProgressMonitor()
        for index in 0..<20 {
            let time = 1 + Double(index) * 0.017
            let input = sample(time, time.truncatingRemainder(dividingBy: 0.05))
            let a = healthy.inspect(input), b = opaqueStall.inspect(input)
            check(a.health == b.health && !b.mayRebuild, "INVENTED_RENDERING_OBSERVABILITY")
        }
        print("PASS: \(cases + 3) progress trace classes; alias, quantization, bounded speculation, clocks and observability")
    }
}
