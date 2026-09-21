import Foundation

@main struct DelegateTests {
    @MainActor static func main() async {
        let name = "BackgroundDelegates.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defer { defaults.removePersistentDomain(forName: name) }
        let app = BackgroundKeepAlive(defaults: defaults)
        app.setAudio(true)
        let finished = AVAudioPlayer.instances.last!
        await Task.detached { app.audioPlayerDidFinishPlaying(finished, successfully: false) }.value
        await waitUntil { AVAudioPlayer.instances.last !== finished }
        precondition(AVAudioPlayer.instances.last!.isPlaying)
        print("PASS: audio completion on a worker safely recovers on MainActor")
        let decoder = AVAudioPlayer.instances.last!
        await Task.detached { app.audioPlayerDecodeErrorDidOccur(decoder, error: nil) }.value
        await waitUntil { app.audioState.hasPrefix("Waiting to resume") }
        precondition(app.audioEnabled && Timer.live.count == 1)
        print("PASS: decoder failure on a worker safely schedules bounded recovery")
        Timer.live[0].fire()
        precondition(AVAudioPlayer.instances.last!.isPlaying)
        app.setAudio(false)
        let activations = AVAudioSession.shared.activations
        await Task.detached { app.audioPlayerDidFinishPlaying(decoder, successfully: true) }.value
        for _ in 0..<20 { await Task.yield() }
        precondition(AVAudioSession.shared.activations == activations && Timer.live.isEmpty)
        print("PASS: an off-main stale delegate cannot restart disabled audio")
    }

    @MainActor static func waitUntil(_ condition: () -> Bool) async {
        for _ in 0..<10_000 {
            if condition() { return }
            await Task.yield()
        }
        preconditionFailure("Delegate did not reach MainActor")
    }
}
