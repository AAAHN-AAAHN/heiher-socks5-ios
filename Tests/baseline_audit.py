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
import textwrap

ROOT = Path(__file__).resolve().parents[1]
OLD_CHECK = '69f82a5b376aad46c97bf91fc92ac389eaf2a7bb'
OLD_BUILD = '0b442eca70839f1cbc0f8006142463b1abd1723a'
PREVIOUS_BUILD = '1dd6b7b08f5031cc549981353cdc95707555e8f2'


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
    (root / '.gitignore').write_text('build/\n')
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost', 'commit', '-qm', 'original')
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def alter(root, case):
    if case == 'clean':
        return
    if case == 'head-only':
        git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost',
            'commit', '--allow-empty', '-qm', 'Different source identity')
        return
    extra = {'untracked-c': 'src/extra.c', 'untracked-config': '.rev-id',
             'ignored-c': 'src/build/extra.c', 'ignored-output': 'build/extra.o',
             'ignored-config': '.rev-id'}
    if case in extra:
        if case == 'ignored-config':
            (root / '.git/info/exclude').write_text('.rev-id\n')
        path = root / extra[case]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('untracked input\n')
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
    if case == 'committed-make':
        git(root, 'add', '.')
        git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost',
            'commit', '-qm', 'Different native input')


def native_boundaries(old, current):
    cases = ['clean', 'modified-c', 'modified-make', 'deleted-script',
             'staged-c', 'staged-make', 'index-c', 'index-make',
             'untracked-c', 'untracked-config', 'ignored-c', 'ignored-output', 'ignored-config',
             'head-only', 'committed-make']
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
                    expected = case in ('clean', 'ignored-output')
                    if label == 'old':
                        expected = case not in ('modified-c', 'staged-c') if operation == 'apply' else case.startswith(('clean', 'staged-'))
                        if case in ('untracked-c', 'untracked-config', 'ignored-c', 'ignored-output', 'ignored-config'):
                            expected = True
                        if case in ('head-only', 'committed-make'):
                            expected = operation == 'reverse'
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
                # The native build/ ignore must not hide this Build/ harness.
                git(root, '-c', 'core.ignorecase=true', 'add', '-f', 'Build')
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


def publication_boundaries(previous, current):
    count = 0
    products = ('SUCCESS.txt', 'Socks5-baseline-unsigned.ipa', 'Socks5-dSYMs.zip',
                'Socks5-baseline-source.zip', 'SHA256SUMS.txt', 'source.zip',
                'history.bundle', 'tested-commit.txt', 'features.json', 'build-info.txt')
    for label, source in [('previous', previous.decode()), ('current', current.decode())]:
        for case in ('unsafe-name', 'failed-retry', 'stable-head', 'moved-head',
                     'fresh-product', 'repeat-product', 'failed-product'):
            with tempfile.TemporaryDirectory(prefix='baseline-publication-') as directory:
                root = Path(directory) / 'repo'
                initialize(root)
                (root / 'Build').mkdir()
                (root / 'Build/build.sh').write_text(source)
                (root / 'Build/features.json').write_text('{"name":"baseline"}\n')
                # Only source/artifact boundaries are exercised, not native/SDK work.
                (root / 'Build/check.py').write_text('pass\n')
                git(root, 'add', '-f', 'Build')
                git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost',
                    'commit', '-qm', 'Build boundary input')
                head = git(root, 'rev-parse', 'HEAD').decode().strip()
                out, core = root / 'artifacts/baseline', root / '.build/core'
                out.mkdir(parents=True)
                env = dict(os.environ, ROOT=str(root), CORE=str(core), OUT=str(out),
                           NAME='baseline', COMMIT=head)
                env.pop('PYTHONOPTIMIZE', None)
                if case in ('unsafe-name', 'failed-retry'):
                    witness = Path(directory) / 'victim/SUCCESS.txt'
                    witness.parent.mkdir()
                    witness.write_text('Outside the output directory.\n')
                    (out / 'previous.log').write_text('Keep diagnostics.\n')
                    for name in products:
                        (out / name).write_text('Obsolete output.\n')
                    if case == 'unsafe-name':
                        (root / 'Build/features.json').write_text('{"name":"../../victim"}\n')
                    else:
                        alter(root, 'modified-c')
                    result = subprocess.run(['bash', 'Build/build.sh'], cwd=root, env=env,
                                            capture_output=True, timeout=15)
                    require = witness.exists() if case == 'unsafe-name' else not any((out / n).exists() for n in products)
                    if result.returncode == 0 or require != (label == 'current'):
                        raise RuntimeError((label, case, result.returncode, result.stderr))
                    if (out / 'previous.log').read_text() != 'Keep diagnostics.\n':
                        raise RuntimeError('Diagnostic record lost')
                elif case in ('stable-head', 'moved-head'):
                    (out / 'tested-commit.txt').write_text(head + '\n')
                    if case == 'moved-head':
                        alter(root, 'head-only')
                    tail = source[source.index('python3 Build/check.py reverse'):]
                    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', tail],
                                            cwd=root, env=env, capture_output=True, timeout=15)
                    accepted = case == 'stable-head' or label == 'previous'
                    if (result.returncode == 0) != accepted or (out / 'SUCCESS.txt').exists() != accepted:
                        raise RuntimeError((label, case, result.returncode, result.stderr))
                else:
                    framework = core / 'HevSocks5Server.xcframework'
                    framework.mkdir(parents=True)
                    (framework / 'generated').write_text('Generated native fixture.\n')
                    retained = root / '.build/baseline-product-source/retained'
                    if case == 'repeat-product':
                        retained.parent.mkdir()
                        retained.write_text('Prior working directory.\n')
                    setup = source[source.index('    PRODUCT='):source.index('    xcodebuild archive')]
                    setup += '\nprintf "%s\\n" "$PRODUCT"\n'
                    setup += 'cmp "$PRODUCT/src/probe.c" "$ROOT/src/probe.c"\n'
                    setup += 'cmp "$PRODUCT/HevSocks5Server.xcframework/generated" "$CORE/HevSocks5Server.xcframework/generated"\n'
                    if case == 'failed-product':
                        setup += 'exit 7\n'
                    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', setup],
                                            cwd=root, env=env, capture_output=True, timeout=15)
                    expected = 1 if label == 'previous' and case == 'repeat-product' else 7 if case == 'failed-product' else 0
                    if result.returncode != expected:
                        raise RuntimeError((label, case, result.returncode, result.stderr))
                    if result.stdout:
                        product = Path(result.stdout.decode().strip())
                        if product.exists() != (label == 'previous'):
                            raise RuntimeError('Disposable product cleanup differs')
                    if case == 'repeat-product' and retained.read_text() != 'Prior working directory.\n':
                        raise RuntimeError('Prior product directory changed')
                print('PASS publication:', label, case, flush=True)
                count += 1
    for option in ('-O', '-OO', 'environment'):
        env = dict(os.environ)
        env.pop('PYTHONOPTIMIZE', None)
        if option == 'environment':
            env['PYTHONOPTIMIZE'] = '1'
        command = [sys.executable, *([] if option == 'environment' else [option]),
                   str(ROOT / 'Tests/tcp_smoke.py')]
        result = subprocess.run(command, env=env, capture_output=True, timeout=15)
        if result.returncode == 0 or b'Assertions must be enabled' not in result.stderr or result.stdout:
            raise RuntimeError(('Smoke assertion policy', option, result.returncode, result.stderr))
        print('PASS smoke assertions:', option, flush=True)
        count += 1
    return count


def artifact_names():
    path = '.github/workflows/verify-build.yml'
    previous = original('8877581c104fbf4bba975596db5ef859468ebfb4').decode()
    count = 0
    for label, workflow in [('previous', previous), ('current', (ROOT / path).read_text())]:
        block = workflow.split('      - name: Name artifact\n', 1)[1].split('      - uses:', 1)[0]
        script = block.split('        run: ', 1)[1]
        script = textwrap.dedent(script[2:]) if script.startswith('|\n') else script
        for name in ('baseline', 'background', '../../victim', 'baseline\nUNEXPECTED=1', '', None, 3):
            with tempfile.TemporaryDirectory(prefix='baseline-artifact-name-') as directory:
                root = Path(directory)
                (root / 'Build').mkdir()
                (root / 'Build/features.json').write_text(json.dumps({'name': name}))
                env = dict(os.environ, GITHUB_ENV=str(root / 'github-env'))
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=root,
                                        env=env, capture_output=True, timeout=15)
                expected = name if name in ('baseline', 'background') else 'invalid-composition'
                correct = (root / 'github-env').read_text() == f'NAME={expected}\n'
                if result.returncode != 0 or correct != (label == 'current' or name in ('baseline', 'background')):
                    raise RuntimeError((label, 'artifact name', name, result.returncode, result.stderr))
                print('PASS artifact name:', label, repr(name), flush=True)
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
    current_build = (ROOT / 'Build/build.sh').read_bytes()
    count += shell_boundaries(original(OLD_BUILD), current_build)
    count += publication_boundaries(original(PREVIOUS_BUILD), current_build)
    count += artifact_names()
    print(f'SUMMARY: {count} exact-old/current input, assertion, publication and cleanup cases; no native/Apple execution')


if __name__ == '__main__':
    main()
