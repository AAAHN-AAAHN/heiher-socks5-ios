#!/usr/bin/env python3
"""Real Foundation timers/Combine queue ordering around the actual controller.

Audio and location remain explicit doubles. This complements deterministic timer
unit tests; it is not permission to execute while iOS suspends a physical app.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
controller = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_text()
imports = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
assert controller.startswith(imports)
controller = controller.replace(imports, 'import Foundation\nimport Combine\n', 1)
mocks = Path(__file__).with_name('PlatformMocks.swift').read_text()
a = mocks.index('protocol ObservableObject'); b = mocks.index('protocol CLLocationManagerDelegate:')
mocks = mocks[:a] + mocks[b:]
mocks = mocks[:mocks.index('@MainActor final class Timer')]
view = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift').read_text()
a = view.index('    private let audioEvents = '); b = view.index('\n\n    func body', a)
publisher = view[a:b].replace('private let audioEvents', 'let audioEvents', 1)
harness = r'''import Foundation
import Combine

@main struct LiveScheduling {
    @MainActor static func main() {
        var app: BackgroundKeepAlive? = BackgroundKeepAlive()
        weak var weakApp = app
        let session = AVAudioSession.shared
        var attempts: [TimeInterval] = []
        let origin = ProcessInfo.processInfo.systemUptime
        session.onActivation = { attempts.append(ProcessInfo.processInfo.systemUptime - origin) }
        var received = 0
PUBLISHER
        let token = audioEvents.sink { [weak app] event in
            precondition(Thread.isMainThread)
            received += 1
            app?.audioEvent(event)
        }
        func runFor(_ interval: TimeInterval) {
            RunLoop.main.run(until: Date().addingTimeInterval(interval))
        }
        func until(_ condition: () -> Bool, timeout: TimeInterval = 4) {
            let limit = Date().addingTimeInterval(timeout)
            while !condition() && Date() < limit { runFor(0.005) }
            precondition(condition(), "Real scheduling did not reach its postcondition")
        }
        session.rejectActivation = true
        app!.setAudio(true)
        precondition(attempts.count == 1)
        until({ attempts.count >= 3 })
        precondition(attempts.count == 3)
        precondition(attempts[1] - attempts[0] >= 0.85 && attempts[2] - attempts[1] >= 0.85,
                     "Unexpected rapid retry rather than the requested one-second timer")
        print("PASS: real run-loop timer retries failed activation without a busy loop; observed seconds=\(attempts)")
        session.rejectActivation = false
        let beforeSignal = attempts.count
        NotificationCenter.default.post(name: AVAudioSession.resumptionRecommendationNotification, object: nil)
        until({ received == 1 && attempts.count > beforeSignal }, timeout: 0.8)
        precondition(AVAudioPlayer.instances.last!.isPlaying)
        print("PASS: a new queued resumption signal recovers before the next one-second retry")

        let healthy = session.activations
        for _ in 0..<100 { app!.restore() }
        runFor(1.1)
        precondition(session.activations == healthy && AVAudioPlayer.instances.last!.isPlaying)
        print("PASS: healthy real timer and repeated foreground restoration do not recreate/reactivate playback")

        let queued = DispatchGroup()
        queued.enter()
        let interruption = AVAudioSession.interruptionNotification
        DispatchQueue.global().async {
            NotificationCenter.default.post(name: interruption, object: nil)
            queued.leave()
        }
        precondition(queued.wait(timeout: .now() + 2) == .success)
        // The worker finished posting, while its RunLoop delivery is still pending.
        app!.setAudio(false)
        until({ received == 2 })
        runFor(1.1)
        precondition(session.activations == healthy && app!.audioState == "Off")
        print("PASS: Off before queued worker notification delivery remains Off; the old real timer cannot restart audio")

        app!.setLocation(true)
        runFor(0.05)
        precondition(session.activations == healthy && app!.locationEnabled && !app!.audioEnabled)
        app!.setLocation(false)
        token.cancel()
        let deliveries = received
        app = nil
        NotificationCenter.default.post(name: AVAudioSession.interruptionNotification, object: nil)
        runFor(1.1)
        precondition(received == deliveries && weakApp == nil && session.activations == healthy)
        print("PASS: location independence, observer cancellation and controller release with real timers")
        weakApp = nil
        session.onActivation = nil
        print("SCOPE: native Foundation/Combine execution with audio/device doubles; measured timing is not an iOS real-time guarantee")
    }
}
'''.replace('PUBLISHER', publisher)
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    files = [('Platform.swift', mocks), ('Controller.swift', controller), ('LiveScheduling.swift', harness)]
    for name, text in files: (folder / name).write_text(text)
    executable = folder / 'live-scheduling'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                    *[str(folder / name) for name, _ in files], '-o', str(executable)], check=True, timeout=120)
    subprocess.run([str(executable)], check=True, timeout=20)
