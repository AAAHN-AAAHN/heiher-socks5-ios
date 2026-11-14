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
helper = b'''        @MainActor func recordAudioDiagnostic(_ phase: String) {
            let detail = "phase=\\(phase) uptime=\\(ProcessInfo.processInfo.systemUptime) frame=\\(audio.frame) exists=\\(audio.exists) hittable=\\(audio.isHittable) enabled=\\(audio.isEnabled) value=\\(String(describing: audio.value)) state=\\(audioState.label)\\n\\(app.debugDescription)"
            let attachment = XCTAttachment(string: detail)
            attachment.name = "audio-intent-" + phase
            attachment.lifetime = .keepAlways
            add(attachment)
        }
'''
anchor = b'        let audioState = app.staticTexts["background.audioState"]\n'
point = b'''        XCTAssertEqual(audio.value as? String, "1", "Saved audio intent must survive relaunch")
        expectAudioState("Playing silent WAV continuously", timeout: 10)
        audio.tap()
'''
extra = b'        recordAudioDiagnostic("before-relaunch-off-tap")\n        defer { recordAudioDiagnostic("after-relaunch-off-attempt") }\n'
def diagnostic_source():
    raw = original()
    assert raw.count(point) == 1
    # Scope the helper to the integration test; other classes can share audioState.
    before, rest = raw.split(b'final class IntegrationUITests:', 1)
    body, after = rest.split(b'    @MainActor func testPeriodicUDPEchoThroughRunningServerAndPersistence()', 1)
    assert body.count(anchor) == 1
    body = body.replace(anchor, anchor + helper, 1)
    updated = before + b'final class IntegrationUITests:' + body + b'    @MainActor func testPeriodicUDPEchoThroughRunningServerAndPersistence()' + after
    updated = updated.replace(point, point.replace(b'        audio.tap()\n', extra + b'        audio.tap()\n'), 1)
    assert updated.replace(helper, b'', 1).replace(extra, b'', 1) == raw
    (handoff.OUT / 'diagnostic-generated-test.swift').write_bytes(updated)
    return updated
ui_review.ui_test_source = diagnostic_source
receipt = {'scope': 'NONCANONICAL diagnostic XCTest overlay only; pre-tap snapshot changes timing. No real tap delivery coordinate or Binding setter trace is claimed.', 'product_commit': SOURCE, 'control_commit': os.environ['GITHUB_SHA'], 'run': os.environ['GITHUB_RUN_ID'], 'trial': os.environ['DIAGNOSTIC_TRIAL'], 'producer_manifest': manifest, 'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'retry_inside_test': False, 'original_assertions_retained': True}
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
