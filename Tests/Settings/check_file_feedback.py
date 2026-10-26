#!/usr/bin/env python3
"""Independent actual-source Settings UI feedback regression/negative control."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

CASES = {
    'delayed-export-alone': None,
    'delayed-export-new-import-picker': 'STALE_EXPORT_PRESENTED_OVER_NEW_IMPORT_PICKER',
    'normal-import-success-clears-error': 'NORMAL_IMPORT_SUCCESS_LEFT_STALE_ERROR',
    'normal-import-invalid': None,
    'normal-provider-error': None,
    'normal-export-clears-error': 'NORMAL_EXPORT_LEFT_STALE_ERROR',
    'normal-export-error': None,
    'normal-retry-success-clears-error': 'NORMAL_RETRY_SUCCESS_LEFT_STALE_ERROR',
    'normal-retry-error': None,
    'current-import-cancelled-off': 'EXPECTED_IMPORT_CANCELLATION_SHOWN_AS_ERROR',
    'old-provider-error-new-import-success': 'OLDER_PROVIDER_FAILURE_LEFT_STALE_ERROR',
    'old-cancel-new-import-success': 'EXPECTED_IMPORT_CANCELLATION_SHOWN_AS_ERROR',
    'old-provider-error-new-invalid': None,
    'old-provider-error-new-export-success': 'OLDER_PROVIDER_FAILURE_LEFT_STALE_ERROR',
    'old-provider-error-new-export-error': 'OLDER_IMPORT_REPLACED_NEWER_EXPORT_ERROR',
    'old-provider-error-new-retry-success': 'OLDER_PROVIDER_FAILURE_LEFT_STALE_ERROR',
}

def end(text, opening):
    depth = 0
    for index in range(opening, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if depth == 0:
            return index
    raise AssertionError('Unbalanced SettingsView source')

def build_sources(root, work):
    manifest = []
    sources = []
    for name in ('Socks5/Server/ServerSettings.swift', 'Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift'):
        raw = (root / name).read_bytes()
        manifest.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
        code = raw.decode()
        if platform.system() != 'Darwin':
            code = code.replace('import SwiftUI\n', 'import Foundation\n')
        target = work / Path(name).name
        target.write_text(code)
        sources.append(target)
    view = (root / 'Socks5/Settings/SettingsView.swift').read_text()
    fixture = Path(__file__).with_name('SettingsFeedbackTests.swift.in').read_text()
    state = re.findall(r'^    @State private var ([^\n]+)$', view, flags=re.M)
    assert state and fixture.count('// STATE_DECLARATIONS') == 1
    fixture = fixture.replace('// STATE_DECLARATIONS', '\n    '.join('var ' + value for value in state))
    helper_anchor = '    private func beginFileRequest() -> UUID {'
    helper = ''
    assert view.count(helper_anchor) <= 1
    if helper_anchor in view:
        helper_start = view.index(helper_anchor)
        helper_open = helper_start + len(helper_anchor) - 1
        helper = view[helper_start:end(view, helper_open) + 1]
    fixture = fixture.replace('// FILE_REQUEST_HELPER', helper)
    actions = {}
    for marker, anchor, callback in (
        ('IMPORT_ACTION', '.fileImporter(isPresented: $importing, allowedContentTypes: [.json]) {', True),
        ('EXPORT_ACTION', 'Button("Export JSON") {', False),
        ('RETRY_ACTION', 'Button("Retry Save") {', False),
        ('EXPORT_COMPLETION', 'defaultFilename: "Socks5-settings") {', True),
        ('IMPORT_OPEN_ACTION', 'Button("Import JSON") {', False),
    ):
        assert view.count(anchor) == 1 and fixture.count('// ' + marker) == 1, marker
        opening = view.index(anchor) + len(anchor) - 1
        action = view[opening + 1:end(view, opening)]
        if callback:
            assert action.startswith(' result in')
            action = action[len(' result in'):]
        actions[marker] = {'sha256': hashlib.sha256(action.encode()).hexdigest(), 'exact_body': action}
        if marker == 'EXPORT_ACTION':
            # Add only a controllable timing boundary; delegate production JSON
            # encoding after the gate. Preserve all control-flow/state statements.
            before, after = 'try snapshot.encoded()', 'try ExportBoundary.shared.encode(snapshot)'
            assert action.count(before) == 1
            action = action.replace(before, after)
            actions[marker]['test_only_timing_substitution'] = {'original': before, 'replacement': after, 'count': 1}
        if marker not in ('EXPORT_COMPLETION', 'IMPORT_OPEN_ACTION'):
            assert action.count('Task { @MainActor in') == 1
            start = action.index('Task { @MainActor in')
            finish = end(action, action.index('{', start)) + 1
            action = action[:start] + '_ = await ' + action[start:finish] + '.value' + action[finish:]
        fixture = fixture.replace('// ' + marker, action)
    test = work / 'SettingsFeedbackTests.swift'
    test.write_text(fixture)
    sources.append(test)
    if platform.system() != 'Darwin':
        sources.extend(root / 'Tests/Settings' / name for name in ('HostUI.swift', 'HostProvider.swift'))
    manifest.append({'path': 'Socks5/Settings/SettingsView.swift', 'sha256': hashlib.sha256(view.encode()).hexdigest(), 'bytes': len(view.encode())})
    return sources, {'sources': manifest, 'actions': actions, 'state_declarations': state,
                     'file_request_helper_exact': helper, 'helper_sha256': hashlib.sha256(helper.encode()).hexdigest()}

def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--expect-original', action='store_true')
    parser.add_argument('--extract-only', action='store_true')
    args = parser.parse_args()
    root, out = args.source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = out / 'compiled-source'; work.mkdir(exist_ok=True)
    inputs, manifest = build_sources(root, work)
    (out / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.extract_only:
        print('EXTRACTED: exact action bodies; runtime NOT_EXECUTED')
        return
    records = []
    def run(label, command, expected=None):
        result = subprocess.run([str(x) for x in command], cwd=root, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        (out / (label + '.log')).write_text(log)
        ok = (result.returncode == 74 and expected in log and 'CLEANUP: PASS' in log) if expected else result.returncode == 0
        if label.startswith(('debug-', 'optimized-')):
            ok = ok and 'CLEANUP: PASS' in log
        records.append({'label': label, 'command': [str(x) for x in command], 'returncode': result.returncode,
                        'expected_failure_marker': expected, 'accepted': ok})
        (out / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
        if not ok:
            raise RuntimeError(f'{label}: wrong outcome {result.returncode}; required marker {expected!r}')
    for flag, mode in (('-Onone', 'debug'), ('-O', 'optimized')):
        executable = work / ('feedback-' + mode)
        run('compile-' + mode, ['swiftc', '-swift-version', '5', '-strict-concurrency=complete', '-warnings-as-errors', flag,
                              *inputs, '-o', executable])
        for case, expected in CASES.items():
            run(mode + '-' + case, [executable, case], expected if args.expect_original else None)
    summary = {'status': 'PASS', 'platform': platform.system(), 'original_negative_control': args.expect_original,
               'case_count_per_optimization': len(CASES), 'optimization_modes': 2,
               'expected_defect_cases_per_optimization': sum(value is not None for value in CASES.values()) if args.expect_original else 0,
               'records': records, 'limits': 'Actual SettingsStore with controlled Storage seams. Exact UI action bodies, not SwiftUI rendering or physical provider acceptance.'}
    (out / 'verification.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: value for key, value in summary.items() if key != 'records'}))

if __name__ == '__main__':
    main()
