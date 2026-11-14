"""Diagnostic-only XCTest overlay; product bytes and original assertions unchanged."""
import hashlib
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
archive = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root / 'Build'))
import review_handoff as handoff
import release_source
import ui_review

SOURCE = '738f949d549b9e703fbd6e9e8a1862db29278065'
TREE = 'a87ecc114b5f8b387468dd97ef72e8d7ac9967fb'
manifest, payloads = handoff.read_archive(archive, '8b7d758b144cd69be0d62b0753f00530575d19bb99293991d5e89d3976e78d7a')
assert manifest['producer'] == {'repository': 'AAAHN-AAAHN/heiher-socks5-ios', 'run_id': '43587714393', 'attempt': '1', 'job': 'verify-macos'}
assert release_source.check_source() == SOURCE
handoff.check_payloads(manifest, payloads, {'commit': SOURCE, 'tree': TREE})
assert not handoff.PRODUCT.exists()
for name, (raw, mode) in payloads.items():
    target = (handoff.PRODUCT / name[len('product/'):]) if name.startswith('product/') else handoff.OUT / name[len('phases/'):]
    assert not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    target.chmod(mode)
release_source.check_product()
original = ui_review.ui_test_source
trace_swift = r'''
import UIKit
import ObjectiveC
// NONCANONICAL diagnostic binary only. Bounded Boolean/revision trace; no settings content.
@MainActor private enum DiagnosticAudioTrace {
    static var count = 0
    static let installation: Void = {
        guard let original = class_getInstanceMethod(UIApplication.self, #selector(UIApplication.sendEvent(_:))),
              let probe = class_getInstanceMethod(UIApplication.self, #selector(UIApplication.diagnosticAudioSendEvent(_:))) else { return }
        method_exchangeImplementations(original, probe)
    }()
    static func record(_ event: String) {
        _ = installation
        guard count < 200 else { return }
        count += 1
        let line = "\(ProcessInfo.processInfo.processIdentifier) \(ProcessInfo.processInfo.systemUptime) \(count) wall=\(Date.timeIntervalSinceReferenceDate) \(event)\n"
        guard let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else { return }
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let file = directory.appendingPathComponent("audio-diagnostic.txt")
            if !FileManager.default.fileExists(atPath: file.path) { _ = FileManager.default.createFile(atPath: file.path, contents: nil) }
            let handle = try FileHandle(forWritingTo: file)
            defer { try? handle.close() }
            let size = try handle.seekToEnd()
            guard size < 524288 else { return }
            try handle.write(contentsOf: Data(line.utf8))
        } catch { NSLog("AUDIO_DIAGNOSTIC_WRITE_FAILURE %@", String(describing: error)) }
    }
}

@MainActor extension UIApplication {
    @objc func diagnosticAudioSendEvent(_ event: UIEvent) {
        let touches = Array(event.allTouches ?? []).prefix(5)
        for touch in touches where touch.phase == .began || touch.phase == .ended || touch.phase == .cancelled {
            let point = touch.location(in: touch.window)
            var names: [String] = []
            var view = touch.view
            while let current = view, names.count < 6 {
                names.append(String(describing: type(of: current)))
                view = current.superview
            }
            DiagnosticAudioTrace.record("touch-before phase=\(touch.phase.rawValue) timestamp=\(touch.timestamp) x=\(point.x) y=\(point.y) viewFrame=\(String(describing: touch.view?.frame)) views=\(names.joined(separator: "/"))")
        }
        diagnosticAudioSendEvent(event) // Exchanged original; never suppress or synthesize events.
        for touch in touches where touch.phase == .began || touch.phase == .ended || touch.phase == .cancelled {
            DiagnosticAudioTrace.record("touch-after phase=\(touch.phase.rawValue) timestamp=\(touch.timestamp)")
        }
    }
}
'''.replace('private enum DiagnosticAudioTrace', 'enum DiagnosticAudioTrace')
def diagnostic_source():
    app = ui_review.WORK / 'application'
    path = app / 'Socks5/AppRoot.swift'
    raw = path.read_text()
    marker = '    private func applyAudioIntent(_ enabled: Bool) {\n'
    assert raw.count(marker) == 1
    details = r'enabled=\(enabled) value=\(settings.value.background.silentAudio) stamp=\(settings.audioChange) load=\(settings.loadState)'
    updated = raw.replace(marker, marker + '        DiagnosticAudioTrace.record("setter-entry ' + details + '")\n        defer { DiagnosticAudioTrace.record("setter-exit ' + details + '") }\n', 1)
    guard = '        guard settings.audioChange == previous else { return }'
    assert updated.count(guard) == 1
    updated = updated.replace(guard, '        guard settings.audioChange == previous else { DiagnosticAudioTrace.record("setter-guard-skip"); return }', 1)
    marker = '    private func restoreServices() {\n'
    assert updated.count(marker) == 1
    details = r'value=\(settings.value.background.silentAudio) stamp=\(settings.audioChange) change=\(settings.change) load=\(settings.loadState)'
    updated = updated.replace(marker, marker + '        DiagnosticAudioTrace.record("restore-entry ' + details + '")\n        defer { DiagnosticAudioTrace.record("restore-exit ' + details + '") }\n', 1)
    path.write_text(updated + trace_swift)
    path = app / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'
    facade = path.read_text(); marker = '    func setAudio(_ enabled: Bool) {\n'
    assert facade.count(marker) == 1
    facade = facade.replace(marker, marker + r'        DiagnosticAudioTrace.record("service-entry enabled=\(enabled) old=\(audioEnabled) state=\(audioState)")' + '\n' + r'        defer { DiagnosticAudioTrace.record("service-exit enabled=\(enabled) now=\(audioEnabled) state=\(audioState)") }' + '\n', 1)
    path.write_text(facade)
    # Keep exact original test bodies. Only temporary app sources gain trace calls.
    (handoff.OUT / 'instrumented-AppRoot.swift').write_text(updated + trace_swift)
    (handoff.OUT / 'instrumented-BackgroundKeepAlive.swift').write_text(facade)
    return original()
ui_review.ui_test_source = diagnostic_source
original_run = ui_review.run
def trace_run(args, *positional, **keywords):
    try:
        return original_run(args, *positional, **keywords)
    finally:
        if args[:2] == ['xcodebuild', 'test-without-building']:
            import subprocess
            identifier = (ui_review.OUT / 'created-device.txt').read_text().strip()
            try:
                container = subprocess.check_output(['xcrun', 'simctl', 'get_app_container', identifier, 'hev.Socks5', 'data'], text=True, timeout=30).strip()
                trace = Path(container) / 'Library/Application Support/audio-diagnostic.txt'
                (handoff.OUT / 'audio-diagnostic.txt').write_bytes(trace.read_bytes())
            except Exception as error:
                (handoff.OUT / 'audio-diagnostic-collection-error.txt').write_text(repr(error))
ui_review.run = trace_run
receipt = {'scope': 'NONCANONICAL instrumented app binary; bounded synchronous trace perturbs timing. Tests unchanged. Not release acceptance.', 'product_commit': SOURCE, 'control_commit': os.environ['GITHUB_SHA'], 'run': os.environ['GITHUB_RUN_ID'], 'trial': os.environ['DIAGNOSTIC_TRIAL'], 'producer_manifest': manifest, 'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'retry_inside_test': False, 'original_assertions_retained': True}
try:
    ui_review.main()
    receipt['result'] = 'passed-instrumented-test-not-root-cause-resolution'
except BaseException as error:
    receipt['result'] = 'failed'
    receipt['error'] = repr(error)
    raise
finally:
    marker = ui_review.OUT / 'SUCCESS.txt'
    if marker.exists(): marker.rename(ui_review.OUT / 'DIAGNOSTIC-ONLY-SUCCESS.txt')
    (handoff.OUT / 'diagnostic-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    release_source.check_source()
