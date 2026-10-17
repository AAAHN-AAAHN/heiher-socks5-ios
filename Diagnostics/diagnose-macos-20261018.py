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

# Download and verify the exact failing artifact, including the original Mach-O.
archive = OUT / 'original-macos-artifact.zip'
with archive.open('wb') as stream, (OUT / 'download-original.log').open('w') as errors:
    subprocess.run(['gh', 'api', '--method', 'GET',
                    'repos/AAAHN-AAAHN/heiher-socks5-ios/actions/artifacts/12113096783/zip'],
                   cwd=ROOT, stdout=stream, stderr=errors, check=True, timeout=120)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == '8bd1cbe8e163d003a884e948db8f317399a8a834503f1eb235484af329b393ce'
unpacked = Path(os.environ['RUNNER_TEMP']) / 'original-macos-artifact'
with zipfile.ZipFile(archive) as source_zip:
    assert source_zip.testzip() is None
    for entry in source_zip.infolist():
        name = PurePosixPath(entry.filename)
        assert not name.is_absolute() and '..' not in name.parts
        assert ((entry.external_attr >> 16) & 0o170000) != 0o120000
    source_zip.extractall(unpacked)
case = unpacked / 'product/background-loop/failures/1792267999961308000-legacy-debug-failure-1000'
binary = case / 'compiled-input/fixture'
binary_digest = hashlib.sha256(binary.read_bytes()).hexdigest()
assert binary_digest == 'e2d4ef48c6d21878a7e97be34313933464bd72ab7391f73671a18d805f2461ec'
binary.chmod(0o700)
environment = dict(os.environ, LOOP_ENDPOINT_TRACE='1')
observation = command('original-failure-trace', [str(binary), 'failure-1000',
                      str(case / 'Silence.wav'), str(case / 'invalid.wav')],
                      cwd=case, env=environment, timeout=45, required=False)
trace = (OUT / 'original-failure-trace.log').read_text(errors='replace')

# Reuse the unchanged owner compiler/adapter translation for just the two new
# diagnostic cases. Their internal ten-second predicate remains unchanged.
spec = importlib.util.spec_from_file_location('owner_probe', product / 'Tests/Background/check_loop_audio.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
fixture_records = []
owned = product / 'Socks5/BackgroundKeepAlive'
fixture_root = OUT / 'current-fixtures'
fixture_root.mkdir()
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
            str(owned / 'Silence.wav'), str(case / 'invalid.wav')],
            cwd=product, timeout=30, required=False)
    (OUT / 'current-compile-records.json').write_text(json.dumps(fixture_records, indent=2) + '\n')

(OUT / 'observation.json').write_text(json.dumps({
    'scope': 'One diagnostic execution of the exact originally failing binary; not a product acceptance run',
    'original_run_id': 39065614794, 'original_job_id': 117492543775, 'original_artifact_id': 12113096783,
    'original_source_commit': '8c2e3592a48a3d2fa67d0bd4cfe6ddcf4a874d0c',
    'original_binary_sha256': binary_digest, 'trace_enabled': True,
    'current_probe_source_commit': actual,
    'fixture_internal_deadline_seconds': 10, 'fixture_retry_interval_seconds': 0.005,
    'observation': observation, 'trace_lines': len(trace.splitlines()),
    'control_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
    'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'product_branches_changed': False,
}, indent=2) + '\n')
print('Apple diagnostic collection complete; no product acceptance or ref publication.', flush=True)
