import Foundation

/// Real worker/actor hops with scripted audio objects. Unlike the other fixtures,
/// release the old player before delivering its queued callback to MainActor.
@main struct CallbackLifetimeTests {
    private enum Event: CaseIterable, Sendable {
        case completion, decoding

        nonisolated func send(to app: BackgroundKeepAlive, player: AVAudioPlayer) {
            switch self {
            case .completion: app.audioPlayerDidFinishPlaying(player, successfully: false)
            case .decoding: app.audioPlayerDecodeErrorDidOccur(player, error: nil)
            }
        }
    }

    @MainActor static func main() async {
        var checks = 0
        func check(_ value: @autoclosure () -> Bool, _ message: String) {
            precondition(value(), message)
            checks += 1
            print("PASS: \(message)")
        }
        let queue = DispatchQueue(label: "Background.callback-lifetime")
        let app = BackgroundKeepAlive()
        let session = AVAudioSession.shared

        // MainActor cannot process the callback until this synchronous function
        // returns and its caller yields. The worker owns the argument only until
        // the delegate call returns. Do not retain it in the test after that.
        func enqueue(_ event: Event) {
            let old = AVAudioPlayer.instances.last!
            let done = DispatchSemaphore(value: 0)
            queue.async {
                precondition(!Thread.isMainThread)
                event.send(to: app, player: old)
                done.signal()
            }
            precondition(done.wait(timeout: .now() + 2) == .success)
            queue.sync {} // Also wait for the worker closure to release old.
        }
        func drain() async {
            for _ in 0..<100 { await Task.yield() }
            try? await Task.sleep(for: .milliseconds(20))
        }
        for event in Event.allCases {
            app.setAudio(true)
            let beforeCurrent = session.activations
            enqueue(event)
            await drain()
            check(session.activations == beforeCurrent + 1 && AVAudioPlayer.instances.last!.isPlaying,
                  "Current \(event) still recovers on MainActor without an initial timer delay")
            app.setAudio(false)
            AVAudioPlayer.instances.removeAll()

            app.setAudio(true)
            let stillAlive = AVAudioPlayer.instances.last!
            enqueue(event)
            app.audioEvent(Notification(name: AVAudioSession.interruptionNotification))
            let replacement = AVAudioPlayer.instances.last!
            let beforeStale = session.activations
            await drain()
            check(session.activations == beforeStale && AVAudioPlayer.instances.last === replacement,
                  "Queued \(event) for a replaced but living player is ignored")
            check(stillAlive !== replacement && !stillAlive.isPlaying,
                  "Replacement detached and stopped the old \(event) player")
            app.setAudio(false)
            AVAudioPlayer.instances.removeAll()

            app.setAudio(true)
            weak var released = AVAudioPlayer.instances.last
            let oldID = ObjectIdentifier(released!)
            enqueue(event)
            app.setAudio(false)
            AVAudioPlayer.instances.removeAll() // The old tests retained all instances.
            check(released == nil, "Queued \(event) does not retain a discarded player")
            var reused = false
            var attempts = 0
            for attempt in 1...20_000 {
                app.setAudio(true)
                attempts = attempt
                if ObjectIdentifier(AVAudioPlayer.instances.last!) == oldID {
                    reused = true
                    break
                }
                app.setAudio(false)
                AVAudioPlayer.instances.removeAll()
            }
            // Allocator address reuse is observed, not required to occur on every
            // platform. The identity and no-restart postconditions always apply.
            if !app.audioEnabled { app.setAudio(true) }
            let current = AVAudioPlayer.instances.last!
            let timer = Timer.live[0]
            let beforeReleased = session.activations
            await drain()
            print("OBSERVATION: \(event) released-address-reused=\(reused); allocations=\(attempts)")
            check(session.activations == beforeReleased && AVAudioPlayer.instances.last === current,
                  "Released \(event) callback cannot restart the new player, including address reuse")
            check(current.isPlaying && Timer.live.count == 1 && Timer.live[0] === timer,
                  "Released \(event) callback preserves healthy playback and its original deadline")
            app.setAudio(false)
            AVAudioPlayer.instances.removeAll()

            app.setAudio(true)
            enqueue(event)
            app.setAudio(false)
            let beforeOff = session.activations
            AVAudioPlayer.instances.removeAll()
            await drain()
            check(!app.audioEnabled && session.activations == beforeOff && Timer.live.isEmpty,
                  "Queued \(event) after Off is inert even after the player is deallocated")
        }
        check(!app.audioEnabled && Timer.live.isEmpty, "No active audio or timer left after the test")
        print("SUMMARY: \(checks) callback lifetime assertions; actual worker/actor scheduling with audio doubles, not an iPhone run")
    }
}
