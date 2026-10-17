#!/usr/bin/env python3
"""Read-only Apple diagnostics; no product pass, publication or ref mutation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/apple-probe'
OUT.mkdir(parents=True, exist_ok=True)
PLAN = json.loads((ROOT / 'Diagnostics/apple-probe.json').read_text())
assert os.environ['GITHUB_REPOSITORY'] == 'AAAHN-AAAHN/heiher-socks5-ios'
assert os.uname().sysname == 'Darwin'
records = []


def command(label, argv, cwd=ROOT, env=None, timeout=120, required=True):
    began = time.monotonic()
    record = {'label': label, 'argv': [str(arg) for arg in argv]}
    with (OUT / (label + '.log')).open('w') as stream:
        try:
            result = subprocess.run(argv, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
            record['exit_code'] = result.returncode
        except subprocess.TimeoutExpired:
            record.update(exit_code=124, timed_out=True)
    record['elapsed_seconds'] = round(time.monotonic() - began, 3)
    records.append(record)
    (OUT / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
    print(label, record['exit_code'], record['elapsed_seconds'], flush=True)
    if required and record['exit_code']:
        raise RuntimeError(label)
    return record


command('toolchain', ['xcodebuild', '-version'])
command('compiler', ['xcrun', 'swiftc', '--version'])
command('sdk', ['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'])
assert (OUT / 'sdk.log').read_text().strip().startswith('27.')
bundle = ROOT / 'Diagnostics/apple-probe.bundle'
assert hashlib.sha256(bundle.read_bytes()).hexdigest() == PLAN['bundle_sha256']
command('bundle-verify', ['git', 'bundle', 'verify', str(bundle)])
command('import-local-objects', ['git', 'fetch', '--no-tags', str(bundle), PLAN['bundle_ref']])
product = Path(os.environ['RUNNER_TEMP']) / 'background-apple-probe'
command('exact-worktree', ['git', 'worktree', 'add', '--detach', str(product), PLAN['head']])
actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=product, text=True).strip()
assert actual == PLAN['head']
command('clean-source', ['git', 'diff', '--exit-code', 'HEAD', '--'], cwd=product)
owned = product / 'Socks5/BackgroundKeepAlive'
fixture_inputs = OUT / 'fixture-inputs'
fixture_inputs.mkdir()
fixture_path = product / 'Tests/Background/AudioEndpointBoundaryTests.swift'
original = fixture_path.read_text()
marker = '    @MainActor static func main() async throws {\n'
assert original.count(marker) == 1
activity = '        #if os(macOS)\n        let activityEnabled = ProcessInfo.processInfo.environment["LOOP_FOREGROUND_ACTIVITY_PROBE"] == "1"\n        let foregroundActivity = activityEnabled ? ProcessInfo.processInfo.beginActivity(\n            options: .userInitiatedAllowingIdleSystemSleep,\n            reason: "Foreground verification of bounded audio recovery") : nil\n        defer { if let foregroundActivity { ProcessInfo.processInfo.endActivity(foregroundActivity) } }\n        print("HOST_ACTIVITY_PROBE enabled=\\(activityEnabled) options=\\(ProcessInfo.ActivityOptions.userInitiatedAllowingIdleSystemSleep.rawValue)")\n        #endif\n'
modified = original.replace(marker, marker + activity, 1)
(fixture_inputs / fixture_path.name).write_text(modified)
mocks = product / 'Tests/Background/AudioEndpointMocks.swift'
(fixture_inputs / mocks.name).write_bytes(mocks.read_bytes())
cost_original = (ROOT / 'Diagnostics/FixtureCosts.swift').read_text()
cost_marker = '    static func main() throws {\n'
assert cost_original.count(cost_marker) == 1
cost_modified = cost_original.replace(cost_marker, cost_marker + activity.replace(
    '        print("HOST_ACTIVITY_PROBE enabled=\\(activityEnabled) options=\\(ProcessInfo.ActivityOptions.userInitiatedAllowingIdleSystemSleep.rawValue)")\n', ''), 1)
cost_modified = cost_modified.replace('"environment_entry_count":',
    '"activity_enabled": activityEnabled, "thermal_state": ProcessInfo.processInfo.thermalState.rawValue, "low_power_mode": ProcessInfo.processInfo.isLowPowerModeEnabled, "environment_entry_count":', 1)
cost_source = OUT / 'FixtureCostsActivity.swift'
cost_source.write_text(cost_modified)
inputs = {
    'source_commit': actual,
    'source_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=product, text=True).strip(),
    'product_sources': {str(path.relative_to(product)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in sorted(product.glob('Socks5/**/*.swift'))},
    'fixture_original_sha256': hashlib.sha256(original.encode()).hexdigest(),
    'fixture_diagnostic_sha256': hashlib.sha256(modified.encode()).hexdigest(),
    'fixture_insertion': activity,
    'mocks_sha256': hashlib.sha256(mocks.read_bytes()).hexdigest(),
    'cost_original_sha256': hashlib.sha256(cost_original.encode()).hexdigest(),
    'cost_diagnostic_sha256': hashlib.sha256(cost_modified.encode()).hexdigest(),
    'fixture_internal_deadline_seconds': 10, 'fixture_retry_interval_seconds': 0.005,
    'scope': 'Same-binary A/B host-activity comparison. No product source, deadline, timer flags or queue QoS modification.',
}
(OUT / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
command('source-archive', ['git', 'archive', '--format=zip', 'HEAD', '-o', str(OUT / 'source.zip')], cwd=product)
cost_binary = OUT / 'fixture-costs-activity'
command('compile-fixture-costs', ['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5',
        '-strict-concurrency=complete', '-warnings-as-errors', '-Onone', str(cost_source),
        '-o', str(cost_binary)], timeout=120)
base_environment = dict(os.environ)
base_environment.pop('LOOP_FOREGROUND_ACTIVITY_PROBE', None)
for condition in ('A', 'B'):
    environment = dict(base_environment)
    if condition == 'B': environment['LOOP_FOREGROUND_ACTIVITY_PROBE'] = '1'
    command('timer-costs-' + condition, [str(cost_binary)], env=environment, timeout=30, required=False)
spec = importlib.util.spec_from_file_location('owner_probe', product / 'Tests/Background/check_loop_audio.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
driver.HERE = fixture_inputs
fixture_records = []
fixture_root = OUT / 'current-fixtures'
fixture_root.mkdir()
invalid = OUT / 'invalid.wav'
invalid.write_bytes(b'X' + (owned / 'Silence.wav').read_bytes()[1:])
for legacy in (False, True):
    label = 'legacy-debug' if legacy else 'async-debug'
    executable = driver.compile_fixture(
        fixture_root, label,
        driver.adapter_source((owned / 'LoopAudioService.swift').read_text(), legacy),
        (owned / 'PlaybackProgressMonitor.swift').read_text(),
        (owned / 'RecoveryExecutionLease.swift').read_text(),
        'AudioEndpointBoundaryTests.swift', False, fixture_records,
        mocks='AudioEndpointMocks.swift')
    inputs[label + '_binary_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
    for condition in ('A', 'B'):
        environment = dict(base_environment)
        if condition == 'B': environment['LOOP_FOREGROUND_ACTIVITY_PROBE'] = '1'
        command(label + '-failure-1000-' + condition, [str(executable), 'failure-1000',
                str(owned / 'Silence.wav'), str(invalid)], cwd=product,
                env=environment, timeout=30, required=False)
    (OUT / 'current-compile-records.json').write_text(json.dumps(fixture_records, indent=2) + '\n')
(OUT / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
command('final-clean-source', ['git', 'diff', '--exit-code', 'HEAD', '--'], cwd=product)
# Establish unchanged source warnings on the exact pre-implementation owner.
baseline_head = '618b3d2b413937aaad7373ee2af9e693ec81b84a'
baseline = Path(os.environ['RUNNER_TEMP']) / 'background-original-sdk'
command('baseline-worktree', ['git', 'worktree', 'add', '--detach', str(baseline), baseline_head])
baseline_sources = sorted(baseline.glob('Socks5/**/*.swift'))
assert len(baseline_sources) == 5
assert (baseline / 'Socks5/ContentView.swift').read_bytes() == (product / 'Socks5/ContentView.swift').read_bytes()
sdk_path = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
command('baseline-sdk', ['xcrun', 'swiftc', '-typecheck', '-swift-version', '5',
        '-strict-concurrency=complete', '-warnings-as-errors', '-sdk', sdk_path,
        '-target', 'arm64-apple-ios17.2', '-I', str(baseline / 'HevSocks5Server.xcframework/ios-arm64/Headers'),
        *map(str, baseline_sources)], cwd=baseline, timeout=300, required=False)
(OUT / 'baseline-inputs.json').write_text(json.dumps({
    'source_commit': baseline_head, 'target': 'arm64-apple-ios17.2', 'sdk': sdk_path,
    'content_view_identical_to_candidate': True,
    'sources': {str(path.relative_to(baseline)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in baseline_sources},
    'scope': 'Exact unchanged original owner source compiled solely to classify inherited diagnostics',
}, indent=2) + '\n')
(OUT / 'observation.json').write_text(json.dumps({
    'scope': 'A/B diagnostic collection only; individual results are not a full product acceptance',
    'current_probe_source_commit': actual, 'previous_probe_run_id': 39067375932,
    'control_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
    'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'product_branches_changed': False,
}, indent=2) + '\n')
print('Apple host activity comparison collected; no product publication.', flush=True)
