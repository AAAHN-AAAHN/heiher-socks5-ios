import Foundation

/// Script only the preparation dispatch boundary; actual worker behavior is tested separately.
@main struct PreparationTests {
    @MainActor static func main() {
        let session = AVAudioSession.shared
        session.deferTransitions = true
        DispatchQueue.deferUtility = true
        let app = BackgroundKeepAlive()
        var checks = 0
        func check(_ condition: @autoclosure () -> Bool, _ label: String) {
            precondition(condition(), label)
            checks += 1
            print("PASS: \(label)")
        }
        func beginPreparation() -> AVAudioPlayer {
            app.setAudio(true)
            precondition(session.pending.count == 1 && session.pending[0].active)
            session.completeNext()
            precondition(session.pending.isEmpty && DispatchQueue.pendingUtility.count == 1)
            return AVAudioPlayer.instances.last!
        }
        func off() {
            app.setAudio(false)
            for _ in 0..<6 {
                if !DispatchQueue.pendingUtility.isEmpty { DispatchQueue.completeUtility() }
                else if !session.pending.isEmpty { session.completeNext() }
                else { break }
            }
            precondition(!app.audioEnabled && Timer.live.isEmpty && session.pending.isEmpty)
            precondition(DispatchQueue.pendingUtility.isEmpty && !session.isActive)
            precondition(!AVAudioPlayer.instances.contains(where: \.isPlaying))
        }
        let first = beginPreparation()
        check(first.delegate == nil && !first.isPlaying && first.plays == 0,
              "The preparation worker exclusively owns an unplayed player without a delegate")
        for _ in 0..<100 { app.restore(); app.setAudio(true) }
        check(DispatchQueue.pendingUtility.count == 1 && session.pending.isEmpty && Timer.live.isEmpty,
              "Repeated restore does not overlap preparation, session transition or timer")
        app.setLocation(true)
        check(CLLocationManager.instances.last!.starts == 1, "Location remains independent while preparation is pending")
        app.setLocation(false)
        app.setAudio(false)
        check(first.stops == 0 && !first.isPlaying && session.pending.isEmpty,
              "Off does not concurrently stop an exclusively worker-owned preparing player")
        DispatchQueue.completeUtility()
        check(first.plays == 0 && first.stops == 1 && session.pending.count == 1 && !session.pending[0].active,
              "Preparation after Off is stopped without playback before serialized release")
        session.completeNext()
        check(app.audioState == "Off" && !session.isActive, "Preparation cancellation settles at actual session Off")

        let superseded = beginPreparation()
        app.setAudio(false)
        app.setAudio(true)
        DispatchQueue.completeUtility()
        check(superseded.plays == 0 && session.pending.count == 1 && !session.pending[0].active,
              "Off-On during preparation drains the old release before new activation")
        session.completeNext()
        session.completeNext()
        check(DispatchQueue.pendingUtility.count == 1, "Latest On prepares only after the old release completes")
        DispatchQueue.completeUtility()
        check(AVAudioPlayer.instances.last!.isPlaying && Timer.live.count == 1,
              "Latest On reaches prepared playback and exactly one health timer")
        off()

        let invalidated = beginPreparation()
        app.audioEvent(Notification(name: AVAudioSession.mediaServicesWereResetNotification))
        DispatchQueue.completeUtility()
        check(invalidated.plays == 0 && invalidated.stops == 1 && Timer.live.count == 1,
              "A reset during preparation prevents stale playback success")
        check(Timer.live[0].interval == 1 && session.pending.isEmpty,
              "Invalidated preparation retains the one-second retry without overlapping work")
        Timer.live[0].fire()
        session.completeNext()
        DispatchQueue.completeUtility()
        check(AVAudioPlayer.instances.last!.isPlaying, "A fresh prepared request recovers after invalidation")
        off()

        let rejected = beginPreparation()
        AVAudioPlayer.rejectPreparation = true
        DispatchQueue.completeUtility()
        AVAudioPlayer.rejectPreparation = false
        check(rejected.plays == 0 && app.audioState.hasPrefix("Waiting to resume") && Timer.live.count == 1,
              "Failed preparation never falls back to implicit main-thread preparation in play")
        Timer.live[0].fire()
        session.completeNext()
        DispatchQueue.completeUtility()
        check(AVAudioPlayer.instances.last!.isPlaying, "Preparation failure recovers through the existing retry")
        off()

        let queued = beginPreparation()
        let preparation = DispatchQueue.pendingUtility.removeFirst()
        let posted = DispatchSemaphore(value: 0)
        DispatchQueue.global().async { preparation(); posted.signal() }
        precondition(posted.wait(timeout: .now() + 2) == .success)
        app.setAudio(false)
        check(session.pending.isEmpty && queued.stops == 0,
              "The transition stays owned while worker completion is queued for MainActor")
        Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        check(queued.plays == 0 && queued.stops == 1 && session.pending.count == 1,
              "Off before queued preparation delivery rejects playback and drains release")
        session.completeNext()
        check(!session.isActive && Timer.live.isEmpty, "Queued preparation completion leaves Off stable")

        var seed: UInt64 = 0xD001FACE
        for _ in 0..<3000 {
            seed = seed &* 6364136223846793005 &+ 1
            switch (seed >> 32) % 8 {
            case 0: app.setAudio(false)
            case 1: app.setAudio(true)
            case 2:
                if !session.pending.isEmpty { session.completeNext(success: (seed & 15) != 0) }
            case 3:
                if !DispatchQueue.pendingUtility.isEmpty {
                    AVAudioPlayer.rejectPreparation = (seed & 15) == 0
                    DispatchQueue.completeUtility()
                    AVAudioPlayer.rejectPreparation = false
                }
            case 4: Timer.live.first?.fire()
            case 5: app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
            case 6: app.restore()
            default:
                if let player = AVAudioPlayer.instances.last, player.isPlaying {
                    app.audioPlayerDecodeErrorDidOccur(player, error: nil)
                }
            }
            precondition(session.pending.count + DispatchQueue.pendingUtility.count <= 1)
            precondition(Timer.live.count <= 1 && AVAudioPlayer.instances.filter(\.isPlaying).count <= 1)
            if !app.audioEnabled { precondition(Timer.live.isEmpty && !AVAudioPlayer.instances.contains(where: \.isPlaying)) }
        }
        off()
        check(AVAudioPlayer.implicitPreparations == 0,
              "All current playback, including 3000 mixed transitions, uses explicit completed preparation")
        check(session.synchronousCalls == 0, "Prepared iOS27 execution preserves native async session calls")

        var temporary: BackgroundKeepAlive? = BackgroundKeepAlive()
        let isReleased = { [weak temporary] in temporary == nil }
        temporary!.setAudio(true)
        session.completeNext()
        let orphan = AVAudioPlayer.instances.last!
        temporary = nil
        check(isReleased(), "A pending preparation does not retain its controller")
        DispatchQueue.completeUtility()
        check(orphan.plays == 0 && orphan.stops == 1 && session.pending.count == 1 && !session.pending[0].active,
              "An orphaned prepared player is stopped and receives best-effort asynchronous release")
        session.completeNext()
        check(!session.isActive && Timer.live.isEmpty, "Orphan preparation cleanup leaves no active session or timer")
        print("SUMMARY: \(checks) preparation assertions; 3000 mixed transitions; scripted boundaries, not device trials")
    }
}
