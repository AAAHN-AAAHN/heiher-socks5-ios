#!/usr/bin/env python3
"""Run current transition tests, exact-old blocking control and legacy worker tests.

Only platform imports are replaced in the controller. The private legacy adapter
is exposed by a same-file test extension; its body/availability dispatch is not rewritten.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if not __debug__:
    raise SystemExit('Assertions must be enabled.')

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'
IMPORTS = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
OLD = '75de52d096607eaee96abb0f06ee03378c17e547'
current = (ROOT / CONTROLLER).read_text()
assert current.startswith(IMPORTS)
FIRST_ASYNC = '67f7ecd6b1f0b5d251ddf2d909568d0a3468e973'
first_async = subprocess.check_output(['git', '-C', str(ROOT), 'show', FIRST_ASYNC])
assert hashlib.sha1(b'blob ' + str(len(first_async)).encode() + b'\0' + first_async).hexdigest() == FIRST_ASYNC
original = subprocess.check_output(['git', '-C', str(ROOT), 'show', OLD])
assert hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest() == OLD
negative = r'''import Foundation
@main struct OldBlockingControl {
    @MainActor static func main() {
        let session = AVAudioSession.shared
        let app = BackgroundKeepAlive()
        session.synchronousDelay = 0.12
        let start = ProcessInfo.processInfo.systemUptime
        app.setAudio(true)
        precondition(ProcessInfo.processInfo.systemUptime - start >= 0.1)
        precondition(session.synchronousCalls == 1 && session.synchronousOnMain)
        app.setAudio(false)
        precondition(session.synchronousCalls == 2 && session.synchronousOnMain)
        print("PASS: exact old controller blocks the main thread for both synchronous session calls under a delayed system double")
    }
}
'''
legacy = r'''import Foundation
@MainActor final class ResultState { var result: Bool?; var beats = 0 }
@main struct LegacyWorkerTests {
    @MainActor static func main() {
        DispatchQueue.scriptUtility = false
        let session = AVAudioSession.shared
        session.synchronousDelay = 0.12
        let state = ResultState()
        let timer = Foundation.Timer.scheduledTimer(withTimeInterval: 0.01, repeats: true) { _ in
            MainActor.assumeIsolated { state.beats += 1 }
        }
        defer { timer.invalidate() }
        func transition(_ active: Bool) {
            state.result = nil
            BackgroundKeepAlive.exerciseLegacySession(active) { success, _ in
                DispatchQueue.main.async { state.result = success }
            }
            let limit = Date().addingTimeInterval(2)
            while state.result == nil && Date() < limit {
                Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.005))
            }
            precondition(state.result != nil)
        }
        transition(true)
        precondition(state.result == true && session.isActive && !session.synchronousOnMain && state.beats >= 3)
        print("PASS: actual legacy adapter waits on a utility worker while the main run loop remains responsive")
        transition(false)
        precondition(state.result == true && !session.isActive && !session.synchronousOnMain)
        session.rejectActivation = true
        transition(true)
        precondition(state.result == false && !session.isActive)
        print("PASS: legacy adapter propagates successful release and activation errors without main-thread setActive")
    }
}
'''
implicit = r'''import Foundation
@main struct ImplicitPreparationControl {
    @MainActor static func main() {
        AVAudioPlayer.preparationDelay = 0.12
        let app = BackgroundKeepAlive()
        let start = ProcessInfo.processInfo.systemUptime
        app.setAudio(true)
        precondition(ProcessInfo.processInfo.systemUptime - start >= 0.1)
        precondition(AVAudioSession.shared.synchronousCalls == 0)
        precondition(AVAudioPlayer.implicitPreparations == 1 && AVAudioPlayer.preparationsOnMain == 1)
        app.setAudio(false)
        print("PASS: exact first async candidate still implicitly prepares its player on main despite native async session calls")
    }
}
'''
preparation_worker = r'''import Foundation
@MainActor final class PreparationResult { var result: Bool?; var beats = 0 }
@main struct PreparationWorkerTests {
    @MainActor static func main() {
        DispatchQueue.scriptUtility = false
        AVAudioPlayer.preparationDelay = 0.12
        let player = try! AVAudioPlayer(contentsOf: URL(fileURLWithPath: "/Silence.wav"))
        let state = PreparationResult()
        let timer = Foundation.Timer.scheduledTimer(withTimeInterval: 0.01, repeats: true) { _ in
            MainActor.assumeIsolated { state.beats += 1 }
        }
        defer { timer.invalidate() }
        func observe(_ stage: String, _ values: String) {
            FileHandle.standardError.write(Data("OBSERVE: preparation-worker \(stage) \(values)\n".utf8))
        }
        let started = ProcessInfo.processInfo.systemUptime
        observe("before-request", "main=\(Thread.isMainThread)")
        BackgroundKeepAlive.exercisePreparation(player) { success in
            DispatchQueue.main.async { state.result = success }
        }
        let limit = Date().addingTimeInterval(2)
        while state.result == nil && Date() < limit {
            Foundation.RunLoop.main.run(until: Date().addingTimeInterval(0.005))
        }
        observe("after-wait", "result=\(String(describing: state.result)) beats=\(state.beats) elapsed=\(ProcessInfo.processInfo.systemUptime - started)")
        precondition(state.result == true && state.beats >= 3)
        observe("after-wait-check", "preparations=\(AVAudioPlayer.preparations) onMain=\(AVAudioPlayer.preparationsOnMain)")
        precondition(AVAudioPlayer.preparations == 1 && AVAudioPlayer.preparationsOnMain == 0)
        observe("after-count-check", "prepared=\(player.isPrepared) playing=\(player.isPlaying)")
        precondition(player.isPrepared && !player.isPlaying)
        observe("before-play", "plays=\(player.plays) implicit=\(AVAudioPlayer.implicitPreparations)")
        precondition(player.play() && AVAudioPlayer.implicitPreparations == 0)
        observe("after-play-check", "plays=\(player.plays) implicit=\(AVAudioPlayer.implicitPreparations)")
        player.stop()
        print("PASS: actual preparation adapter works off main while its run loop progresses; prepared play adds no implicit preparation")
    }
}
'''
extension = r'''
extension BackgroundKeepAlive {
    nonisolated static func exercisePreparation(_ player: AVAudioPlayer,
                                                 completion: @escaping @Sendable (Bool) -> Void) {
        prepareAudioPlayer(player, completion: completion)
    }
    nonisolated static func exerciseLegacySession(_ active: Bool,
                                                  completion: @escaping @Sendable (Bool, Error?) -> Void) {
        changeLegacyAudioSession(active, completion: completion)
    }
}
'''


def preserve_failure(folder, mocks, exe, label, optimize, started, error):
    """Keep this failed fixture before TemporaryDirectory removes its inputs."""
    out = ROOT / 'artifacts/audio-checks/async-session-failure' / label / ('optimized' if optimize else 'debug')
    out.mkdir(parents=True, exist_ok=True)
    files = [folder / 'Controller.swift', folder / 'Test.swift', mocks, exe]
    for path in files:
        shutil.copy2(path, out / path.name)
    reports = []
    if sys.platform == 'darwin':
        for path in (Path.home() / 'Library/Logs/DiagnosticReports').glob(exe.name + '*.ips'):
            if path.stat().st_mtime >= started:
                text = path.read_text(errors='replace')
                if str(exe) in text or str(exe.resolve()) in text:
                    shutil.copy2(path, out / path.name)
                    reports.append(path.name)
    (out / 'failure.json').write_text(json.dumps({
        'label': label, 'optimized': optimize, 'error': str(error),
        'returncode': getattr(error, 'returncode', None),
        'execution_timeout_seconds': 30,
        'commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'fixture_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
        'crash_reports': reports,
        'scope': 'Only this failed fixture; no report wait, retry or product change.',
    }, indent=2) + '\n')
    print('Preserved failed async-session fixture:', out, flush=True)


with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    mocks = ROOT / 'Tests/Background/PlatformMocks.swift'
    for label, source, test in [
        ('current-delayed', current, (ROOT / 'Tests/Background/AsyncSessionTests.swift').read_text()),
        ('current-preparation', current, (ROOT / 'Tests/Background/PreparationTests.swift').read_text()),
        ('old-blocking-control', original.decode(), negative),
        ('first-async-implicit-preparation', first_async.decode(), implicit),
        ('preparation-worker', current + extension, preparation_worker),
        ('legacy-worker', current + extension, legacy),
    ]:
        (folder / 'Controller.swift').write_text(source.replace(IMPORTS, 'import Foundation\n', 1))
        (folder / 'Test.swift').write_text(test)
        for optimize in (False, True):
            exe = folder / ('test-' + str(optimize))
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimize else []), str(mocks), str(folder / 'Controller.swift'),
                            str(folder / 'Test.swift'), '-o', str(exe)], check=True, timeout=90)
            print('TEST:', label, 'optimized=', optimize, flush=True)
            started = time.time()
            try:
                subprocess.run([str(exe)], check=True, timeout=30)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                try:
                    preserve_failure(folder, mocks, exe, label, optimize, started, error)
                except Exception as preservation_error:
                    print('Failed to preserve fixture:', repr(preservation_error), flush=True)
                raise
print('PASS: delayed session/preparation, exact old controls and real preparation/legacy adapters; DEBUG and optimized')
