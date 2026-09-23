#!/usr/bin/env python3
"""Actual Combine/NotificationCenter forwarding with the production publisher.

Audio/device types are scripted doubles. This is not actual iOS event delivery or
SwiftUI view-lifetime testing. The entire SwiftUI source is separately SDK-checked.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_text()
imports = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
assert source.startswith(imports)
source = source.replace(imports, 'import Foundation\nimport Combine\n', 1)
mocks = Path(__file__).with_name('PlatformMocks.swift').read_text()
a = mocks.index('protocol ObservableObject'); b = mocks.index('protocol CLLocationManagerDelegate:')
mocks = mocks[:a] + mocks[b:]
a = mocks.index('@MainActor final class Timer'); mocks = mocks[:a]
view = (root / 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift').read_text()
a = view.index('    private let audioEvents = '); b = view.index('\n\n    func body', a)
publisher = view[a:b].replace('private let audioEvents', 'let audioEvents', 1)
harness = '''import Foundation
import Combine

@main struct SubscriptionTest {
    @MainActor static func main() {
        let app = BackgroundKeepAlive()
        var received = 0
PUBLISHER
        let token = audioEvents.sink { notification in
            precondition(Thread.isMainThread)
            received += 1
            app.audioEvent(notification)
        }
        func drain(until condition: () -> Bool) {
            let deadline = Date().addingTimeInterval(2)
            while !condition() && Date() < deadline {
                RunLoop.main.run(until: Date().addingTimeInterval(0.005))
            }
            precondition(condition(), "Notification never reached the production handler")
        }
        for onWorker in [false, true] {
            for name in BackgroundKeepAlive.audioNotifications {
                app.setAudio(true)
                AVAudioPlayer.instances.last!.isPlaying = false
                let previous = received
                if onWorker {
                    DispatchQueue.global().async { NotificationCenter.default.post(name: name, object: nil) }
                } else {
                    NotificationCenter.default.post(name: name, object: nil)
                }
                drain { received == previous + 1 }
                precondition(AVAudioPlayer.instances.last!.isPlaying)
                app.setAudio(false)
            }
        }
        precondition(received == 34)
        token.cancel()
        NotificationCenter.default.post(name: AVAudioSession.interruptionNotification, object: nil)
        RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        precondition(received == 34)
        print("PASS: all 17 production-registry notifications from main and worker reach the actual Combine subscriber on main (34 deliveries)")
        print("PASS: cancelling the actual Combine subscription detaches it")
        print("SCOPE: real Foundation/Combine; mocked audio types, no iOS system-generated interruption or SwiftUI hosting")
    }
}
'''.replace('PUBLISHER', publisher)
with tempfile.TemporaryDirectory() as folder:
    directory = Path(folder)
    for name, content in [('Controller.swift', source), ('Platform.swift', mocks), ('SubscriptionTest.swift', harness)]:
        (directory / name).write_text(content)
    executable = directory / 'subscription-test'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                    str(directory / 'Platform.swift'), str(directory / 'Controller.swift'),
                    str(directory / 'SubscriptionTest.swift'), '-o', str(executable)], check=True, timeout=120)
    subprocess.run([str(executable)], check=True, timeout=20)
