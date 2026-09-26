#!/usr/bin/env python3
"""Exact-old/current build-input controls; never substitute for a native build."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OLD_CHECK = '69f82a5b376aad46c97bf91fc92ac389eaf2a7bb'
OLD_BUILD = '0b442eca70839f1cbc0f8006142463b1abd1723a'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def original(blob):
    data = git(ROOT, 'show', blob)
    if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != blob:
        raise RuntimeError('Incorrect historical control')
    return data


def initialize(root):
    (root / 'src').mkdir(parents=True)
    (root / 'src/probe.c').write_text('int probe;\n')
    (root / 'Makefile').write_text('all:\n\t@true\n')
    (root / 'build-apple.sh').write_text('#!/bin/sh\nexit 0\n')
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost', 'commit', '-qm', 'original')
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def alter(root, case):
    if case == 'clean':
        return
    path = root / ('src/probe.c' if case.endswith('c') else 'Makefile')
    before = path.read_bytes()
    if case == 'deleted-script':
        (root / 'build-apple.sh').unlink()
        return
    path.write_bytes(before + b'# changed\n')
    if case.startswith(('staged-', 'index-')):
        git(root, 'add', str(path))
    if case.startswith('index-'):
        path.write_bytes(before)


def native_boundaries(old, current):
    cases = ['clean', 'modified-c', 'modified-make', 'deleted-script',
             'staged-c', 'staged-make', 'index-c', 'index-make']
    count = 0
    for label, source in [('old', old), ('current', current)]:
        tree = ast.parse(source)
        functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                                     and n.name in ('git', 'patches', 'apply', 'reverse')], type_ignores=[])
        for operation in ('apply', 'reverse'):
            for case in cases:
                with tempfile.TemporaryDirectory(prefix='baseline-native-input-') as folder:
                    root = Path(folder)
                    head = initialize(root)
                    alter(root, case)
                    namespace = {'subprocess': subprocess, 'ROOT': root,
                                 'CONFIG': {'sources': {'.': head}, 'patches': []}}
                    exec(compile(functions, '<exact-check-functions>', 'exec'), namespace)
                    accepted = True
                    try:
                        namespace[operation](root)
                    except (AssertionError, subprocess.CalledProcessError):
                        accepted = False
                    expected = case == 'clean'
                    if label == 'old':
                        expected = case not in ('modified-c', 'staged-c') if operation == 'apply' else case.startswith(('clean', 'staged-'))
                    if accepted != expected:
                        raise RuntimeError((label, operation, case, accepted, expected))
                    print('PASS native:', label, operation, case, 'accepted=', accepted, flush=True)
                    count += 1
    return count


def optimization(old, current):
    count = 0
    for label, source in [('old', old), ('current', current)]:
        for optimized in (False, True):
            with tempfile.TemporaryDirectory(prefix='baseline-assertions-') as folder:
                root = Path(folder)
                initialize(root)
                (root / 'Build').mkdir()
                (root / 'Build/check.py').write_bytes(source)
                config = {'name': 'baseline', 'features': ['invalid'], 'patches': [],
                          'sources': {}, 'upstream_app': 'unavailable'}
                for name, value in [('features.json', config), ('upstream.json', config),
                                    ('baseline-framework.json', dict(config, files={}))]:
                    (root / 'Build' / name).write_text(json.dumps(value))
                env = dict(os.environ)
                env.pop('PYTHONOPTIMIZE', None)
                command = [sys.executable, *(['-O'] if optimized else []), 'Build/check.py', 'baseline']
                result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=15)
                accepted = result.returncode == 0
                if accepted != (label == 'old' and optimized):
                    raise RuntimeError((label, optimized, result.returncode, result.stderr))
                print('PASS assertions:', label, optimized, 'accepted=', accepted, flush=True)
                count += 1
    return count


def shell_boundaries(old, current):
    count = 0
    for label, source in [('old', old), ('current', current)]:
        for case in ('clean', 'modified-c', 'staged-c', 'index-c', 'optimized'):
            with tempfile.TemporaryDirectory(prefix='baseline-shell-input-') as folder:
                root = Path(folder)
                initialize(root)
                (root / 'Build').mkdir()
                (root / 'Build/build.sh').write_bytes(source)
                (root / 'Build/features.json').write_text('{"name":"baseline"}\n')
                # Stop at the next validator, before any build/network/SDK work.
                (root / 'Build/check.py').write_text(
                    'from pathlib import Path\nPath("reached-validator").touch()\nraise SystemExit(19)\n')
                git(root, 'add', '.')
                git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost', 'commit', '-qm', 'entry')
                if case != 'optimized':
                    alter(root, case)
                out = root / 'artifacts/baseline'
                out.mkdir(parents=True)
                (out / 'SUCCESS.txt').write_text('obsolete pass\n')
                (out / 'previous.log').write_text('Keep diagnostics.\n')
                env = dict(os.environ)
                env.pop('PYTHONOPTIMIZE', None)
                if case == 'optimized':
                    env['PYTHONOPTIMIZE'] = '1'
                result = subprocess.run(['bash', 'Build/build.sh'], cwd=root, env=env, capture_output=True, timeout=15)
                reached = (root / 'reached-validator').exists()
                stale = (out / 'SUCCESS.txt').exists()
                if result.returncode == 0 or reached != (label == 'old' or case == 'clean') or stale != (label == 'old'):
                    raise RuntimeError((label, case, result.returncode, reached, stale, result.stderr))
                if (out / 'previous.log').read_text() != 'Keep diagnostics.\n':
                    raise RuntimeError('Historical diagnostics deleted')
                print('PASS shell:', label, case, 'reached=', reached, 'stale=', stale, flush=True)
                count += 1
    return count


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    # Do not let caller-specific Git environment change isolated fixture identity.
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        os.environ.pop(key, None)
    old, current = original(OLD_CHECK), (ROOT / 'Build/check.py').read_bytes()
    count = native_boundaries(old, current) + optimization(old, current)
    count += shell_boundaries(original(OLD_BUILD), (ROOT / 'Build/build.sh').read_bytes())
    print(f'SUMMARY: {count} exact-old/current input, assertion and marker cases; no native/Apple execution')


if __name__ == '__main__':
    main()
