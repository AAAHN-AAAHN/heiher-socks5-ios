#!/usr/bin/env python3
"""Temporary copied-app tracing of a reproduced UI failure, never a product test."""
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ui', ROOT / 'Tests/Background/check_async_ui.py')
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
original_add = ui.add_test_target
original_run = ui.run


def add(app):
    original_add(app)
    path = app / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'
    source = path.read_text()
    insertions = {
        '    func setAudio(_ enabled: Bool) {': 'RecoveryTrace.emit("setAudio \\(enabled)")',
        '    private func resumeAudio(recreate: Bool = false) {': 'RecoveryTrace.emit("resume recreate=\\(recreate) restoring=\\(restoringAudio) transition=\\(String(describing: sessionTransition)) waiting=\\(waitingToRetry) unavailable=\\(servicesUnavailable)")',
        '    private func audioActivated(_ success: Bool, error: Error?) {': 'RecoveryTrace.emit("activated \\(success) invalidated=\\(invalidatedDuringRestore) error=\\(String(describing: error))")',
        '    private func audioPrepared(_ prepared: AVAudioPlayer, success: Bool) {': 'RecoveryTrace.emit("prepared \\(success) invalidated=\\(invalidatedDuringRestore)")',
        '    private func beginSessionTransition(active: Bool) {': 'RecoveryTrace.emit("sessionRequest \\(active)")',
        '    func audioEvent(_ notification: Notification) {': 'RecoveryTrace.emit("event \\(notification.name.rawValue)")',
        '    private func retryAudio(_ error: Error?) {': 'RecoveryTrace.emit("retry \\(String(describing: error))")',
    }
    for old, statement in insertions.items():
        assert source.count(old) == 1, old
        source = source.replace(old, old + '\n        ' + statement, 1)
    old = '            completion(player.prepareToPlay())'
    assert source.count(old) == 1
    source = source.replace(old, '''            RecoveryTrace.emit("prepare worker enter")
            let prepared = player.prepareToPlay()
            RecoveryTrace.emit("prepare worker exit \\(prepared)")
            completion(prepared)''', 1)
    source += r'''

// Test-copy-only diagnostic; absent from the committed production file.
private enum RecoveryTrace {
    static let lock = NSLock()
    static func emit(_ message: String) {
        lock.lock()
        defer { lock.unlock() }
        let url = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("recovery-trace.txt")
        let data = "\(ProcessInfo.processInfo.systemUptime) main=\(Thread.isMainThread) \(message)\n".data(using: .utf8)!
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        do {
            let file = try FileHandle(forWritingTo: url)
            defer { try? file.close() }
            try file.seekToEnd()
            try file.write(contentsOf: data)
        } catch { NSLog("RecoveryTrace write failed: %@", String(describing: error)) }
    }
}
'''
    path.write_text(source)
    (ui.OUT / 'diagnostic-controller.swift').write_text(source)


def run(args, *a, **kw):
    try:
        return original_run(args, *a, **kw)
    finally:
        if list(map(str, args))[:2] == ['xcodebuild', 'test']:
            runtime = json.loads((ui.OUT / 'runtime.json').read_text())
            try:
                container = Path(ui.output('xcrun', 'simctl', 'get_app_container', runtime['udid'], 'hev.Socks5', 'data').strip())
                shutil.copyfile(container / 'tmp/recovery-trace.txt', ui.OUT / 'recovery-trace.txt')
            except Exception as exc:
                (ui.OUT / 'trace-copy-error.txt').write_text(str(exc))


ui.add_test_target = add
ui.run = run
try:
    ui.main()
finally:
    (ui.OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    (ui.OUT / 'DIAGNOSTIC_ONLY.txt').write_text('Copied app contains tracing. Not uninstrumented validation, never an IPA.\n')
