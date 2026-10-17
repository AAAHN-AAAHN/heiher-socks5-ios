#!/usr/bin/env python3
"""Import exact local commits into review refs, then run existing product gates.

Only the three enumerated review refs may be written. Product publication is a
separate reviewed operation after the resulting evidence has been inspected.
The bundle retains authoring commits, ancestry and documentation freeze identity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/resume'
PROFILES = {
    'background': ('feature/background',
                   '618b3d2b413937aaad7373ee2af9e693ec81b84a',
                   'work/loop-background-candidate-20261017'),
    'settings': ('feature/settings-persistence',
                 'a22bc4579a82e46b9e20389182bc1e63e6deedbf',
                 'work/loop-settings-candidate-20261017'),
    'integrated': ('release/integrated',
                   'ed6b920cee4f3e5f0469807e521f19bf6f92f92e',
                   'work/loop-release-candidate-20261018'),
}


def git(*args, cwd=None):
    return subprocess.check_output(['git', *args], cwd=ROOT if cwd is None else cwd, text=True,
                                   stderr=subprocess.STDOUT, timeout=120).strip()


def manifest():
    data = json.loads((ROOT / 'Diagnostics/resume-manifest.json').read_text())
    assert data['schema'] == 1
    assert data['repository'] == 'AAAHN-AAAHN/heiher-socks5-ios'
    assert os.environ['GITHUB_REPOSITORY'] == data['repository']
    assert data['bundle']['path'] == 'Diagnostics/resume.bundle'
    assert re.fullmatch('[0-9a-f]{64}', data['bundle']['sha256'])
    assert 1 <= len(data['candidates']) <= len(PROFILES)
    names = set()
    for entry in data['candidates']:
        name = entry['profile']
        assert name in PROFILES and name not in names
        names.add(name)
        product, baseline, review = PROFILES[name]
        assert entry['product_branch'] == product
        assert entry['baseline'] == baseline
        assert entry['candidate_branch'] == review
        assert re.fullmatch('[0-9a-f]{40}', entry['head'])
        local_name = 'release' if name == 'integrated' else name
        assert entry['bundle_ref'] == 'refs/heads/resume/' + local_name + '-20261018'
        expected = entry['expected_candidate']
        assert expected is None or re.fullmatch('[0-9a-f]{40}', expected)
    return data


def remote_head(branch):
    result = git('ls-remote', '--heads', 'origin', 'refs/heads/' + branch)
    return result.split()[0] if result else None


def device_inventory():
    """Record available Apple execution targets without claiming device testing."""
    records = []
    commands = [
        ('simulators', ['xcrun', 'simctl', 'list', '--json']),
        ('physical-devices', ['xcrun', 'devicectl', 'list', 'devices',
                              '--json-output', str(OUT / 'physical-devices.json')]),
    ]
    for name, command in commands:
        record = {'name': name, 'argv': command}
        try:
            with (OUT / (name + '.log')).open('w') as stream:
                result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=45)
            record['exit_code'] = result.returncode
        except subprocess.TimeoutExpired:
            record.update(exit_code=124, timed_out=True)
        records.append(record)
    (OUT / 'device-inventory.json').write_text(json.dumps({
        'commands': records, 'scope': 'Read-only runner inventory; no physical execution',
    }, indent=2) + '\n')


def import_candidates(data):
    bundle = ROOT / data['bundle']['path']
    actual = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert actual == data['bundle']['sha256'], 'Bundle digest differs'
    (OUT / 'bundle-verification.txt').write_text(git('bundle', 'verify', str(bundle)) + '\n')
    heads = dict((line.split()[1], line.split()[0])
                 for line in git('bundle', 'list-heads', str(bundle)).splitlines())
    matrix, records, refspecs = [], [], []
    for entry in data['candidates']:
        assert heads[entry['bundle_ref']] == entry['head']
        git('fetch', '--no-tags', str(bundle), entry['bundle_ref'])
        git('merge-base', '--is-ancestor', entry['baseline'], entry['head'])
        observed = remote_head(entry['candidate_branch'])
        assert observed in (entry['expected_candidate'], entry['head']), (entry, observed)
        if observed:
            git('merge-base', '--is-ancestor', observed, entry['head'])
        # A regular atomic push rejects concurrent/non-fast-forward changes.
        if observed != entry['head']:
            refspecs.append(entry['head'] + ':refs/heads/' + entry['candidate_branch'])
        records.append(dict(entry, tree=git('rev-parse', entry['head'] + '^{tree}'),
                            observed_candidate=observed))
        for platform in ('ubuntu-24.04', 'xcode-27'):
            matrix.append({'profile': entry['profile'], 'head': entry['head'], 'os': platform})
    (OUT / 'import-plan.json').write_text(json.dumps(records, indent=2) + '\n')
    if refspecs:
        (OUT / 'candidate-push.txt').write_text(git('push', '--atomic', 'origin', *refspecs) + '\n')
    for entry in data['candidates']:
        assert remote_head(entry['candidate_branch']) == entry['head']
    (OUT / 'import-result.json').write_text(json.dumps({
        'result': 'PASS', 'bundle_sha256': actual, 'candidates': records,
        'product_branches_changed': False,
    }, indent=2) + '\n')
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
        stream.write('matrix=' + json.dumps({'include': matrix}, separators=(',', ':')) + '\n')
    print('Imported exact review commits:', ', '.join(e['head'] for e in data['candidates']), flush=True)


def verify(data):
    profile, head = os.environ['RESUME_PROFILE'], os.environ['RESUME_HEAD']
    entry = next(e for e in data['candidates'] if e['profile'] == profile)
    assert entry['head'] == head
    product = Path(os.environ['RUNNER_TEMP']) / ('resume-product-' + profile)
    assert not product.exists()
    git('worktree', 'add', '--detach', str(product), head)
    assert git('rev-parse', 'HEAD', cwd=product) == head
    records = []
    environment = dict(os.environ, BUILD_IPA='0' if profile == 'settings' else '1')
    success = False
    started = time.time()

    def run(label, argv, timeout):
        before = time.monotonic()
        record = {'label': label, 'argv': argv}
        try:
            with (OUT / (label + '.log')).open('w') as stream:
                result = subprocess.run(argv, cwd=product, env=environment,
                                        stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            record['exit_code'] = result.returncode
        except subprocess.TimeoutExpired:
            record['exit_code'] = 124
            record['timed_out'] = True
        record['elapsed_seconds'] = round(time.monotonic() - before, 3)
        records.append(record)
        (OUT / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
        print(label, record['exit_code'], record['elapsed_seconds'], flush=True)
        if record['exit_code']:
            print((OUT / (label + '.log')).read_text(errors='replace')[-12000:], flush=True)
            raise RuntimeError('Required gate failed: ' + label)

    try:
        run('swift-toolchain', ['swiftc', '--version'], 60)
        if sys.platform == 'darwin':
            device_inventory()
        run('clean-worktree', ['git', 'diff', '--exit-code', 'HEAD', '--'], 60)
        run('clean-index', ['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 60)
        run('documentation', ['python3', 'Build/check_documentation.py'], 180)
        run('documentation-contract', ['python3', 'Tests/documentation_contract.py'], 300)
        run('build', ['bash', 'Build/build.sh'], 2400)
        if sys.platform == 'darwin':
            run('apple-toolchain', ['xcodebuild', '-version'], 60)
            run('apple-sdk', ['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'], 60)
            sdk = (OUT / 'apple-sdk.log').read_text().strip()
            assert sdk.startswith('27.'), sdk
            if profile == 'background':
                run('audio-sdk', ['bash', 'Tests/Background/check_audio_sdk.sh'], 900)
                run('audio-ui', ['python3', 'Tests/Background/check_async_ui.py'], 1200)
            elif profile == 'settings':
                run('sdk', ['bash', 'Build/check_swift_sdk.sh'], 300)
                run('strict-sdk', ['bash', str(ROOT / 'Diagnostics/strict_sdk_check.sh'), profile], 300)
                run('settings-ui', ['python3', 'Tests/Settings/ui_audit.py'], 1200)
            else:
                run('sdk', ['bash', 'Build/check_swift_sdk.sh'], 300)
                run('strict-sdk', ['bash', str(ROOT / 'Diagnostics/strict_sdk_check.sh'), profile], 300)
                run('package', ['python3', 'Build/verify_release.py'], 300)
                run('simulator', ['python3', 'Build/simulator_review.py'], 1200)
                run('integrated-ui', ['python3', 'Build/ui_review.py'], 1200)
        run('final-worktree', ['git', 'diff', '--exit-code', 'HEAD', '--'], 60)
        run('final-index', ['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 60)
        success = True
    finally:
        source_error = None
        if (product / 'Build/record_evidence.py').exists():
            try:
                run('record-source', ['python3', 'Build/record_evidence.py'], 180)
            except Exception as error:
                success = False
                source_error = error
        else:
            git('archive', '--format=zip', head, '-o', str(OUT / 'verified-source.zip'), cwd=product)
            git('bundle', 'create', str(OUT / 'history.bundle'), 'HEAD', cwd=product)
        if (product / 'artifacts').is_dir():
            shutil.copytree(product / 'artifacts', ROOT / 'artifacts/product', dirs_exist_ok=True)
        (OUT / 'final-status.txt').write_text(git('status', '--porcelain=v1', cwd=product) + '\n')
        (OUT / 'result.json').write_text(json.dumps({
            'result': 'PASS' if success else 'FAIL', 'profile': profile, 'source_commit': head,
            'source_tree': git('rev-parse', 'HEAD^{tree}', cwd=product),
            'control_commit': git('rev-parse', 'HEAD'), 'platform': sys.platform,
            'run_id': os.environ['GITHUB_RUN_ID'], 'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
            'started_at_unix': started, 'elapsed_seconds': round(time.time() - started, 3),
            'commands': records, 'product_branches_changed': False,
            'physical_device_execution': False,
        }, indent=2) + '\n')
        if source_error is not None:
            raise source_error


if __name__ == '__main__':
    assert __debug__, 'Assertions must be enabled'
    OUT.mkdir(parents=True, exist_ok=True)
    plan = manifest()
    assert sys.argv[1:] in (['import'], ['verify'])
    if sys.argv[1] == 'import':
        import_candidates(plan)
    else:
        verify(plan)
