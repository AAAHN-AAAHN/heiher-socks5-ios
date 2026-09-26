#!/usr/bin/env python3
"""Exercise real audit entry points; fake only the next expensive tool boundary.

Isolated Git fixtures distinguish source/index drift and stale compiled headers.
No fixture tool is used by the actual native or Apple verification.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OLD_BUILD = {'server-control': '478440512666300558f341c8302c967d81c0c50b',
             'settings-persistence': 'a5ee19a72c65edb83e23280f359d7161cc21d064'}
OLD_SDK = 'f866730b0de75f9d2aaf17800b8fed9c2619ae79'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def original(blob):
    data = git(ROOT, 'show', blob)
    actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if actual != blob:
        raise RuntimeError('Original entry has the wrong Git identity')
    return data


def exercise(entry, data, label, case, name):
    with tempfile.TemporaryDirectory(prefix='input-integrity-') as folder:
        root = Path(folder)
        path = root / entry
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        (root / 'Build/features.json').write_text(json.dumps({'name': name}))
        (root / 'Build/check.py').write_text(
            'from pathlib import Path\nPath("boundary.txt").write_text("native")\nraise SystemExit(23)\n')
        (root / 'tracked.txt').write_text('original\n')
        git(root, 'init', '-q')
        git(root, 'add', '.')
        git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-qm', 'Fixture only')
        commit = git(root, 'rev-parse', 'HEAD').decode().strip()
        output = root / 'artifacts' / name
        headers = output / 'compiled-headers'
        headers.mkdir(parents=True)
        diagnostic = output / 'prior-diagnostic.log'
        diagnostic.write_bytes(b'preserve prior diagnostics\n')
        for marker in ['SUCCESS.txt', 'sdk-success.txt']:
            (output / marker).write_text('prior success\n')
        for filename in ['hev-main.h', 'module.modulemap']:
            (headers / filename).write_text('// fixture: ' + filename + '\n')
        (headers / 'source-commit.txt').write_text(commit + '\n')
        sums = ''.join(hashlib.sha256((headers / f).read_bytes()).hexdigest() + '  ' + f + '\n'
                       for f in ['hev-main.h', 'module.modulemap'])
        (headers / 'SHA256SUMS.txt').write_text(sums)
        tools = root / 'tools'; tools.mkdir()
        xcode = tools / 'xcodebuild'
        xcode.write_text('#!/bin/sh\nprintf sdk > boundary.txt\nexit 23\n')
        xcode.chmod(0o755)
        tracked = root / 'tracked.txt'
        if case in ('unstaged', 'staged', 'index-only'):
            tracked.write_text('different\n')
            if case != 'unstaged': git(root, 'add', 'tracked.txt')
            if case == 'index-only': tracked.write_text('original\n')
        elif case == 'stale-headers':
            (headers / 'source-commit.txt').write_text('0' * 40 + '\n')
        elif case == 'changed-header':
            (headers / 'hev-main.h').write_text('// changed signature\n')
        elif case == 'changed-module':
            (headers / 'module.modulemap').write_text('// changed module\n')
        elif case == 'missing-native-success':
            (output / 'SUCCESS.txt').unlink()
        elif case == 'missing-header-identity':
            (headers / 'source-commit.txt').unlink()
        elif case != 'clean':
            raise RuntimeError(case)
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'], BUILD_IPA='0')
        result = subprocess.run(['bash', str(path)], cwd=root, env=env,
                                capture_output=True, text=True, timeout=15)
        reached = (root / 'boundary.txt').exists()
        expected_reached = label == 'old' or case == 'clean'
        if reached != expected_reached or result.returncode == 0:
            raise RuntimeError((entry, label, case, result.returncode, result.stdout, result.stderr))
        if reached and result.returncode != 23:
            raise RuntimeError('Downstream fixture did not preserve its failure')
        if (output / 'sdk-success.txt').exists():
            raise RuntimeError('A rejected attempt retained SDK success')
        if entry == 'Build/build.sh' and (output / 'SUCCESS.txt').exists():
            raise RuntimeError('A rejected native attempt retained success')
        if diagnostic.read_bytes() != b'preserve prior diagnostics\n':
            raise RuntimeError('Prior diagnostics changed')
        print(f'PASS: {entry} {label} {case}; reached-tool={reached}; exit={result.returncode}')


def main():
    name = json.loads((ROOT / 'Build/features.json').read_bytes())['name']
    count = 0
    for entry, blob in [('Build/build.sh', OLD_BUILD[name]), ('Build/check_swift_sdk.sh', OLD_SDK)]:
        cases = ['clean', 'unstaged', 'staged', 'index-only']
        if entry.endswith('check_swift_sdk.sh'):
            cases += ['stale-headers', 'changed-header', 'changed-module',
                      'missing-native-success', 'missing-header-identity']
        for label, data in [('old', original(blob)), ('current', (ROOT / entry).read_bytes())]:
            for case in cases:
                exercise(entry, data, label, case, name)
                count += 1
    print(f'PASS: {count} exact old/current Git/header entry cases; no native or SDK execution in these fixtures.')


if __name__ == '__main__':
    main()
