#!/usr/bin/env python3
"""Targeted host-Swift diagnostics; no official acceptance/runtime/product credit."""
import argparse
from datetime import datetime, timezone
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
BASE = 'd3f20d7e3905dcc300f0a5ebf155aa4cc2869774'
SOURCE_HELPER = '07b77a96d65470fd37d7e24708d50a514f5c58b4'
BACKGROUND = '46be6421e93cac43400e99ceeb89ee1290479ce9'
REPOSITORY = 'AAAHN-AAAHN/heiher-socks5-ios'
BRANCH = 'refs/heads/work/udp-echo-main-20261028'
INPUT_HASHES = {
    'candidates.json': '417a9a87daa6aa281543bbc28fc8974e8c4c4d29a4e25ea9cd74441bdb77bb39',
    'candidates.bundle': '43660a7b68e2c5f9de2efee4d43d12f5e3faf14c6ea74c144ab12363a51d01c6',
}
FORBIDDEN = ('e5980901a6c0b7a8b12ddc37461e22405f7dbe0e',
             '0a62910f5e444edbf176fe3ccd52363e5b8f869e')
SCOPE = ('DIAGNOSTIC ONLY: unchanged Background counter and scheduler host tests. '
         'No full owner acceptance, Apple UI/Simulator runtime, IPA/product, '
         'canonical publication or official final-gate credit.')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def source_identity(root, expected):
    require(git(root, 'rev-parse', 'HEAD').decode().strip() == expected,
            'The detached source HEAD differs')
    git(root, 'diff', '--exit-code', 'HEAD', '--')
    git(root, 'diff', '--cached', '--exit-code', 'HEAD', '--')
    files = {}
    for record in git(root, 'ls-tree', '-rz', expected).split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        relative = os.fsdecode(name)
        path = root / relative
        require(kind == 'blob' and mode in ('100644', '100755') and
                path.is_file() and not path.is_symlink(), 'Unexpected source file: ' + relative)
        raw = path.read_bytes()
        require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob,
                'Source bytes differ: ' + relative)
        require(bool(path.stat().st_mode & 0o111) == (mode == '100755'),
                'Source executable mode differs: ' + relative)
        files[relative] = dict(git_blob=blob, mode=mode, size=len(raw), sha256=sha256(raw))
    return dict(commit=expected, tree=git(root, 'rev-parse', 'HEAD^{tree}').decode().strip(),
                files=files, inventory_sha256=sha256(json.dumps(files, sort_keys=True,
                    separators=(',', ':')).encode()))


def verify_bundle(output):
    manifest_path = ROOT / 'Diagnostics/candidates.json'
    bundle = ROOT / 'Diagnostics/candidates.bundle'
    for name, digest in INPUT_HASHES.items():
        require(sha256((ROOT / 'Diagnostics' / name).read_bytes()) == digest,
                'Copied official input bytes differ: ' + name)
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest['sha256'] == INPUT_HASHES['candidates.bundle'], 'Bundle declaration differs')
    expected = []
    identities = {}
    for group, prefix in (('candidates', 'candidate'), ('support', 'support')):
        for entry in manifest[group]:
            name, commit = entry['name'], entry['sha']
            require(name not in identities and re.fullmatch('[0-9a-f]{40}', commit),
                    'Invalid or duplicate candidate identity')
            identities[name] = commit
            expected.append(commit + ' refs/heads/' + prefix + '/' + name)
    require(set(identities) == {'main', 'udp', 'background', 'statistics', 'server',
                                'settings', 'icon', 'integrated'}, 'Source8 inventory differs')
    require(identities['background'] == BACKGROUND, 'Background diagnostic input differs')
    heads = git(ROOT, 'bundle', 'list-heads', str(bundle)).decode().splitlines()
    require(sorted(heads) == sorted(expected), 'Bundle advertised heads differ')
    with (output / 'bundle-verify.log').open('wb') as log:
        subprocess.run(['git', '-C', str(ROOT), 'bundle', 'verify', str(bundle)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    before = git(ROOT, 'for-each-ref', '--format=%(refname) %(objectname)')
    with (output / 'bundle-unbundle.log').open('wb') as log:
        subprocess.run(['git', '-C', str(ROOT), 'bundle', 'unbundle', str(bundle)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    require(git(ROOT, 'for-each-ref', '--format=%(refname) %(objectname)') == before,
            'Object import changed refs')
    for commit in identities.values():
        require(git(ROOT, 'cat-file', '-t', commit).strip() == b'commit', 'Missing candidate commit')
        for excluded in FORBIDDEN:
            result = subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', excluded, commit])
            require(result.returncode == 1, 'Forbidden ancestry or missing ancestry evidence')
    return identities, before


def execute(output, label, command, cwd):
    started = time.monotonic()
    with (output / (label + '.log')).open('wb') as log:
        # Driver-owned compile/process deadlines and assertions remain unchanged.
        process = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    return dict(label=label, command=command, returncode=process.returncode,
                duration_seconds=time.monotonic() - started, log=label + '.log')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--verify-only', action='store_true',
                        help='Local input preflight only; do not invoke Swift or claim CI execution')
    options = parser.parse_args()
    require(__debug__, 'Assertions must be enabled')
    output = options.output.absolute()
    require(not output.exists(), 'Use a fresh diagnostic output directory')
    output.mkdir(parents=True)
    report = dict(scope=SCOPE, official_acceptance_credit=False, runtime_credit=False,
                  product_credit=False, canonical_credit=False, status='NOT_COMPLETED',
                  started_utc=datetime.now(timezone.utc).isoformat(), tests=[],
                  input_source_helper=SOURCE_HELPER, copied_input_sha256=INPUT_HASHES,
                  official_run_left_unchanged='41914246081', verify_only=options.verify_only)
    source = output / 'candidate-background'
    source_created = False
    before = None
    failure = None
    try:
        helper = git(ROOT, 'rev-parse', 'HEAD').decode().strip()
        report['diagnostic_helper_commit'] = helper
        git(ROOT, 'merge-base', '--is-ancestor', BASE, 'HEAD')
        if not options.verify_only:
            require(os.environ.get('GITHUB_ACTIONS') == 'true' and
                    os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
                    os.environ.get('GITHUB_REF') == BRANCH and
                    os.environ.get('GITHUB_SHA') == helper, 'Actual diagnostic CI identity differs')
            require(re.fullmatch('[1-9][0-9]*', os.environ.get('GITHUB_RUN_ID', '')) and
                    re.fullmatch('[1-9][0-9]*', os.environ.get('GITHUB_RUN_ATTEMPT', '')),
                    'Actual run/attempt identity is missing')
            require(not git(ROOT, 'status', '--porcelain', '--untracked-files=all').strip(),
                    'Diagnostic helper checkout is not clean')
            report['execution'] = {name: os.environ[name] for name in (
                'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
                'GITHUB_JOB', 'RUNNER_OS', 'DIAGNOSTIC_PLATFORM')}
            helper_identity = source_identity(ROOT, helper)
            save(output / 'diagnostic-helper-identity.json', helper_identity)
        else:
            report['execution'] = 'LOCAL INPUT PREFLIGHT ONLY; no CI or Swift execution claimed'
            report['helper_worktree_status'] = git(ROOT, 'status', '--porcelain', '--untracked-files=all').decode()
        inputs = output / 'inputs'
        inputs.mkdir()
        for name in INPUT_HASHES:
            shutil.copyfile(ROOT / 'Diagnostics' / name, inputs / name)
        report['source8'], before = verify_bundle(output)
        git(ROOT, 'worktree', 'add', '--detach', str(source), BACKGROUND)
        source_created = True
        original = source_identity(source, BACKGROUND)
        save(output / 'background-source-identity.json', original)
        report['candidate'] = {key: original[key] for key in ('commit', 'tree', 'inventory_sha256')}
        if options.verify_only:
            report['status'] = 'INPUTS_VERIFIED_TESTS_NOT_RUN'
        else:
            for label, command in [('swift-toolchain', ['swiftc', '--version']),
                                   ('clang-toolchain', ['clang', '--version'])]:
                tool = execute(output, label, command, source)
                report.setdefault('toolchain', []).append(tool)
                require(tool['returncode'] == 0, 'Required toolchain unavailable: ' + label)
            for label, script in [('counter', 'check_udp_echo_counter.py'),
                                  ('scheduler', 'UDPEchoSchedulerTests.py')]:
                result = execute(output, label, [sys.executable, '-B',
                    'Tests/Background/' + script, '--output', str(output / label)], source)
                report['tests'].append(result)
                save(output / 'result.json', report)
            report['status'] = ('TARGETED_TESTS_PASSED' if all(item['returncode'] == 0 for item in report['tests'])
                                else 'TARGETED_TESTS_FAILED')
        require(source_identity(source, BACKGROUND) == original, 'The diagnostic changed candidate source')
        report['candidate_source_unchanged'] = True
    except Exception as error:
        failure = error
        report['error'] = repr(error)
        report['status'] = 'DIAGNOSTIC_FAILED'
    finally:
        if source_created:
            try:
                git(ROOT, 'worktree', 'remove', '--force', str(source))
            except Exception as error:
                report['cleanup_error'] = repr(error)
                failure = failure or error
                report['status'] = 'DIAGNOSTIC_FAILED'
        if before is not None:
            unchanged = git(ROOT, 'for-each-ref', '--format=%(refname) %(objectname)') == before
            report['ordinary_refs_unchanged'] = unchanged
            report['ordinary_refs_sha256'] = sha256(before)
            if not unchanged:
                failure = failure or RuntimeError('Diagnostic changed refs')
                report['status'] = 'DIAGNOSTIC_FAILED'
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save(output / 'result.json', report)
        print(json.dumps({key: report[key] for key in ('scope', 'status', 'official_acceptance_credit',
                                                       'runtime_credit', 'product_credit', 'canonical_credit')}))
    if failure:
        raise failure
    return 1 if report['status'] == 'TARGETED_TESTS_FAILED' else 0


if __name__ == '__main__':
    sys.exit(main())
