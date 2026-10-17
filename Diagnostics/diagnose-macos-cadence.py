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
sources = sorted(product.glob('Socks5/**/*.swift'))
assert len(sources) == 8
headers = product / 'HevSocks5Server.xcframework/ios-arm64/Headers'
sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
inputs = {
    'source_commit': actual,
    'source_tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=product, text=True).strip(),
    'sources': {str(p.relative_to(product)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    'headers': {str(p.relative_to(product)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(headers.rglob('*')) if p.is_file()},
    'sdk': sdk, 'scope': 'Actual eight-source SDK preflight with unchanged baseline headers; not a native rebuild',
}
(OUT / 'sdk-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
command('actual-sdk-preflight', ['xcrun', 'swiftc', '-typecheck', '-swift-version', '5',
        '-strict-concurrency=complete', '-warnings-as-errors', '-sdk', sdk,
        '-target', 'arm64-apple-ios17.2', '-I', str(headers), *map(str, sources)],
        cwd=product, timeout=300, required=False)
command('source-archive', ['git', 'archive', '--format=zip', 'HEAD', '-o', str(OUT / 'source.zip')], cwd=product)

# Query the actual deployment-target boundary for checked locked value metadata.
lock_source = ROOT / 'Diagnostics/CheckedLockProbe.swift'
command('checked-lock-sdk', ['xcrun', 'swiftc', '-typecheck', '-swift-version', '5',
        '-strict-concurrency=complete', '-warnings-as-errors', '-sdk', sdk,
        '-target', 'arm64-apple-ios17.2', str(lock_source)], timeout=120, required=False)
interface_records = []
sdk_root = Path(sdk)
for base in (sdk_root / 'usr/lib/swift', sdk_root / 'System/Library/Frameworks/os.framework'):
    if not base.exists():
        continue
    for path in sorted(base.rglob('*.swiftinterface')):
        if 'os.swiftmodule' not in path.parts:
            continue
        content = path.read_text(errors='replace')
        if 'OSAllocatedUnfairLock' not in content:
            continue
        destination = OUT / 'sdk-interfaces' / path.relative_to(sdk_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
        interface_records.append({'path': str(path), 'artifact_path': str(destination.relative_to(OUT)),
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
(OUT / 'checked-lock-inputs.json').write_text(json.dumps({
    'source_sha256': hashlib.sha256(lock_source.read_bytes()).hexdigest(),
    'deployment_target': 'arm64-apple-ios17.2', 'sdk': sdk,
    'interfaces': interface_records,
}, indent=2) + '\n')

# Diagnostic costs do not exercise or alter the product policy.
cost_source = ROOT / 'Diagnostics/FixtureCosts.swift'
inputs['cost_probe_sha256'] = hashlib.sha256(cost_source.read_bytes()).hexdigest()
(OUT / 'sdk-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
cost_binary = OUT / 'fixture-costs'
command('compile-fixture-costs', ['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5',
        '-strict-concurrency=complete', '-warnings-as-errors', '-Onone', str(cost_source),
        '-o', str(cost_binary)], timeout=120)
command('fixture-costs', [str(cost_binary)], timeout=30, required=False)

spec = importlib.util.spec_from_file_location('owner_probe', product / 'Tests/Background/check_loop_audio.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
fixture_records = []
owned = product / 'Socks5/BackgroundKeepAlive'
fixture_root = OUT / 'current-fixtures'
fixture_root.mkdir()
invalid = OUT / 'invalid.wav'
invalid.write_bytes(b'invalid controlled fixture')
for legacy in (False, True):
    label = 'legacy-debug' if legacy else 'async-debug'
    executable = driver.compile_fixture(
        fixture_root, label,
        driver.adapter_source((owned / 'LoopAudioService.swift').read_text(), legacy),
        (owned / 'PlaybackProgressMonitor.swift').read_text(),
        (owned / 'RecoveryExecutionLease.swift').read_text(),
        'AudioEndpointBoundaryTests.swift', False, fixture_records,
        mocks='AudioEndpointMocks.swift')
    command('current-' + label + '-failure-1000', [str(executable), 'failure-1000',
            str(owned / 'Silence.wav'), str(invalid)],
            cwd=product, timeout=30, required=False)
    (OUT / 'current-compile-records.json').write_text(json.dumps(fixture_records, indent=2) + '\n')
(OUT / 'observation.json').write_text(json.dumps({
    'scope': 'Diagnostic execution of host costs, actual SDK preflight and unchanged finite-failure predicates; not full product acceptance',
    'current_probe_source_commit': actual,
    'previous_probe_run_id': 39066352164,
    'fixture_internal_deadline_seconds': 10,
    'fixture_retry_interval_seconds': 0.005,
    'control_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
    'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'product_branches_changed': False,
}, indent=2) + '\n')
print('Apple cadence diagnostic collection complete; no product acceptance or ref publication.', flush=True)
