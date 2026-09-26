import Foundation

@main struct DelegateTests {
    @MainActor static func main() {
        let app = BackgroundKeepAlive()
        app.setAudio(true)
        let finished = AVAudioPlayer.instances.last!
        send { app.audioPlayerDidFinishPlaying(finished, successfully: false) }
        waitUntil { AVAudioPlayer.instances.last !== finished }
        precondition(AVAudioPlayer.instances.last!.isPlaying)
        print("PASS: audio completion on a worker safely recovers on MainActor")
        let decoder = AVAudioPlayer.instances.last!
        send { app.audioPlayerDecodeErrorDidOccur(decoder, error: nil) }
        waitUntil { app.audioState.hasPrefix("Waiting to resume") }
        precondition(app.audioEnabled && Timer.live.count == 1)
        print("PASS: decoder failure on a worker safely schedules one-second recovery")
        Timer.live[0].fire()
        precondition(AVAudioPlayer.instances.last!.isPlaying)
        app.setAudio(false)
        let activations = AVAudioSession.shared.activations
        send { app.audioPlayerDidFinishPlaying(decoder, successfully: true) }
        Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        precondition(AVAudioSession.shared.activations == activations && Timer.live.isEmpty)
        print("PASS: an off-main stale delegate cannot restart disabled audio")
        app.setAudio(true)
        let firstDecoder = AVAudioPlayer.instances.last!
        send { app.audioPlayerDecodeErrorDidOccur(firstDecoder, error: nil) }
        waitUntil { AVAudioPlayer.instances.last !== firstDecoder }
        precondition(AVAudioPlayer.instances.last!.isPlaying && Timer.live.count == 1)
        print("PASS: first off-main decoder failure recovers immediately on MainActor")
        app.setAudio(false)
    }

    private static func send(_ callback: @escaping @Sendable () -> Void) {
        let posted = DispatchSemaphore(value: 0)
        DispatchQueue.global().async { callback(); posted.signal() }
        precondition(posted.wait(timeout: .now() + 2) == .success)
    }

    @MainActor static func waitUntil(_ condition: () -> Bool) {
        let deadline = Date().addingTimeInterval(2)
        while Date() < deadline {
            if condition() { return }
            Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.001))
        }
        preconditionFailure("Delegate did not reach MainActor")
    }
}
