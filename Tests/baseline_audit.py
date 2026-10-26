#!/usr/bin/env python3
"""Exact-old/current build-input controls; never substitute for a native build."""
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import struct
import warnings
import zipfile

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


def initialize(root, makefile='Makefile'):
    (root / 'src').mkdir(parents=True)
    (root / 'src/probe.c').write_text('int probe;\n')
    (root / makefile).write_text('all:\n\t@true\n')
    (root / 'build-apple.sh').write_text('#!/bin/sh\nexit 0\n')
    (root / '.gitignore').write_text('build/\n')
    git(root, 'init', '-q')
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost', 'commit', '-qm', 'original')
    return git(root, 'rev-parse', 'HEAD').decode().strip()


def alter(root, case):
    if case == 'clean':
        return
    if case in ('assume-unchanged', 'skip-worktree'):
        git(root, 'update-index', '--' + case, 'src/probe.c')
        (root / 'src/probe.c').write_text('int changed;\n')
        return
    if case == 'clean-filter':
        (root / '.git/info/attributes').write_text('src/probe.c filter=audit\n')
        git(root, 'config', 'filter.audit.clean', 'sed s/changed/probe/g')
        (root / 'src/probe.c').write_text('int changed;\n')
        return
    if case == 'filemode':
        git(root, 'config', 'core.fileMode', 'false')
        (root / 'src/probe.c').chmod(0o755)
        return
    if case in ('ignored-gnu-make', 'ignored-make', 'ignored-configs'):
        name = {'ignored-gnu-make': 'GNUmakefile', 'ignored-make': 'makefile',
                'ignored-configs': 'configs.mk'}[case]
        (root / '.git/info/exclude').write_text(name + '\n')
        (root / name).write_text('all:\n\t@true\n')
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
             'head-only', 'committed-make', 'assume-unchanged', 'skip-worktree',
             'filemode', 'clean-filter', 'ignored-gnu-make', 'ignored-make', 'ignored-configs']
    count = 0
    for label, source in [('old', old), ('current', current)]:
        tree = ast.parse(source)
        functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)
                                     and n.name in ('git', 'patches', 'tracked', 'clean_tracked', 'clean_native', 'apply', 'reverse')], type_ignores=[])
        for operation in ('apply', 'reverse'):
            for case in cases:
                with tempfile.TemporaryDirectory(prefix='baseline-native-input-') as folder:
                    root = Path(folder)
                    # Keep lowercase makefile distinct on case-insensitive hosts.
                    head = initialize(root, 'OriginalMakefile' if case == 'ignored-make' else 'Makefile')
                    alter(root, case)
                    namespace = {'subprocess': subprocess, 'os': os, 'hashlib': hashlib, 'ROOT': root,
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
                        if case in ('assume-unchanged', 'skip-worktree', 'filemode', 'clean-filter',
                                    'ignored-gnu-make', 'ignored-make', 'ignored-configs'):
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
                if accepted != (label == 'old' and optimized) or (
                        label == 'current' and optimized and b'Assertions must be enabled' not in result.stderr):
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
                    subprocess.run(['git', '-C', str(root), 'archive', '--format=zip', head,
                                    '-o', str(out / 'source.zip')], check=True)
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


def linked_outputs(previous, current):
    count = 0
    for label, source in (('previous', previous), ('current', current)):
        for case in ('root', 'directory', 'log'):
            with tempfile.TemporaryDirectory(prefix='baseline-linked-output-') as directory:
                root, outside = Path(directory) / 'repo', Path(directory) / 'outside'
                initialize(root)
                (root / 'Build').mkdir()
                (root / 'Build/build.sh').write_bytes(source)
                (root / 'Build/features.json').write_text('{"name":"baseline"}\n')
                (root / 'Build/check.py').write_text('raise SystemExit(19)\n')
                git(root, 'add', '-f', 'Build')
                git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost',
                    'commit', '-qm', 'Output boundary input')
                outside.mkdir()
                out = root / 'artifacts/baseline'
                witness = outside / 'SUCCESS.txt'
                if case == 'root':
                    (outside / 'baseline').mkdir()
                    witness = outside / 'baseline/SUCCESS.txt'
                    out.parent.symlink_to(outside, target_is_directory=True)
                elif case == 'directory':
                    out.parent.mkdir()
                    out.symlink_to(outside, target_is_directory=True)
                else:
                    out.mkdir(parents=True)
                    (out / 'input-worktree.log').symlink_to(witness)
                witness.write_text('Outside output boundary.\n')
                result = subprocess.run(['bash', 'Build/build.sh'], cwd=root,
                                        capture_output=True, timeout=15)
                preserved = witness.exists() and witness.read_text() == 'Outside output boundary.\n'
                if preserved != (label == 'current') or result.returncode != (1 if label == 'current' else 19):
                    raise RuntimeError((label, case, result.returncode, preserved, result.stderr))
                if label == 'current' and b'Linked ' not in result.stderr:
                    raise RuntimeError(('Wrong output rejection', case, result.stderr))
                print('PASS linked output:', label, case, 'preserved=', preserved, flush=True)
                count += 1
    return count


def workflow_boundaries(current_build):
    workflow = (ROOT / '.github/workflows/verify-build.yml').read_text()
    previous = git(ROOT, 'show', 'ca489e2f20be17b459dc36ec5dad37cfe4806f3c:.github/workflows/verify-build.yml').decode()
    # Assert the real workflow consumes only the outputs of the actual build step.
    for required in ('id: build', 'run: bash Build/build.sh',
                     "if: ${{ always() && steps.build.outputs.artifact_path != '' }}",
                     'path: ${{ steps.build.outputs.artifact_path }}',
                     'name: Socks5-${{ steps.build.outputs.composition }}-${{ runner.os }}'):
        if required not in workflow:
            raise RuntimeError(('Missing workflow boundary', required))
    count = 0
    with tempfile.TemporaryDirectory(prefix='baseline-checkout-ref-') as directory:
        root = Path(directory)
        event_commit = initialize(root)
        git(root, 'branch', '-f', 'event-tip', event_commit)
        alter(root, 'head-only')
        branch_commit = git(root, 'rev-parse', 'HEAD').decode().strip()
        git(root, 'branch', '-f', 'event-tip', branch_commit)
        for label, source in (('previous', previous), ('current', workflow)):
            match = re.search(r'ref: \$\{\{ inputs.ref \|\| github\.(ref|sha) \}\}', source)
            if match is None:
                raise RuntimeError('Unknown checkout selection')
            for explicit in (False, True):
                selected = event_commit if explicit or match[1] == 'sha' else 'refs/heads/event-tip'
                actual = git(root, 'rev-parse', selected).decode().strip()
                expected = branch_commit if label == 'previous' and not explicit else event_commit
                if actual != expected:
                    raise RuntimeError((label, 'checkout identity', explicit, actual, expected))
                print('PASS checkout:', label, 'explicit=', explicit, 'event_commit=', actual == event_commit, flush=True)
                count += 1
    # Retain the original name-injection negative control, not a rewritten old implementation.
    old = original('8877581c104fbf4bba975596db5ef859468ebfb4').decode()
    block = old.split('      - name: Name artifact\n', 1)[1].split('      - uses:', 1)[0]
    script = block.split('        run: ', 1)[1]
    script = textwrap.dedent(script[2:]) if script.startswith('|\n') else script
    names = ('baseline', 'background', '../../victim', 'baseline\nUNEXPECTED=1', '', None, 3)
    for name in names:
        with tempfile.TemporaryDirectory(prefix='baseline-old-artifact-name-') as directory:
            root = Path(directory)
            (root / 'Build').mkdir()
            (root / 'Build/features.json').write_text(json.dumps({'name': name}))
            env = dict(os.environ, GITHUB_ENV=str(root / 'github-env'))
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=root,
                                    env=env, capture_output=True, timeout=15)
            expected = name if name in ('baseline', 'background') else 'invalid-composition'
            correct = (root / 'github-env').read_text() == f'NAME={expected}\n'
            if result.returncode != 0 or correct != (name in ('baseline', 'background')):
                raise RuntimeError(('Historical artifact name', name, result.stderr))
            print('PASS artifact name: previous', repr(name), flush=True)
            count += 1
    cases = [(str(i), name) for i, name in enumerate(names)]
    cases += [(case, 'baseline') for case in ('malformed', 'missing', 'root-link',
                                            'directory-link', 'log-link', 'dirty', 'optimized')]
    for case, name in cases:
        with tempfile.TemporaryDirectory(prefix='baseline-current-publication-') as directory:
            root, outside = Path(directory) / 'repo', Path(directory) / 'outside'
            initialize(root)
            (root / 'Build').mkdir()
            (root / 'Build/build.sh').write_bytes(current_build)
            config = root / 'Build/features.json'
            config.write_text(json.dumps({'name': name}))
            (root / 'Build/check.py').write_text('raise SystemExit(19)\n')
            git(root, 'add', '-f', 'Build')
            git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost',
                'commit', '-qm', 'Publication input')
            if case == 'malformed':
                config.write_text('{')
            elif case == 'missing':
                config.unlink()
            elif case == 'dirty':
                alter(root, 'modified-c')
            out = root / 'artifacts' / (name if name in ('baseline', 'background') else 'baseline')
            outside.mkdir()
            witness = outside / 'witness'
            witness.write_bytes(b'preserve outside bytes')
            if case == 'root-link':
                out.parent.symlink_to(outside, target_is_directory=True)
            elif case == 'directory-link':
                out.parent.mkdir()
                out.symlink_to(outside, target_is_directory=True)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'SUCCESS.txt').write_text('old success')
            product = out / f'Socks5-{out.name}-unsigned.ipa'
            product.write_bytes(b'old product')
            if case == 'log-link':
                (out / 'input-worktree.log').symlink_to(witness)
            output = Path(directory) / 'step-output'
            output.touch()
            env = dict(os.environ, GITHUB_OUTPUT=str(output))
            env.pop('PYTHONOPTIMIZE', None)
            if case == 'optimized':
                env['PYTHONOPTIMIZE'] = '1'
            result = subprocess.run(['bash', 'Build/build.sh'], cwd=root, env=env,
                                    capture_output=True, timeout=15)
            ready = case in ('0', '1', 'dirty', 'optimized')
            expected = f'composition={name}\nartifact_path=artifacts/{name}\n' if ready else ''
            if output.read_text() != expected or result.returncode == 0:
                raise RuntimeError(('Publication gate', case, result.returncode, output.read_text(), result.stderr))
            if ready:
                if (out / 'SUCCESS.txt').exists() or product.exists():
                    raise RuntimeError('Published stale product/verdict')
                if result.returncode != (19 if case in ('0', '1') else 1):
                    raise RuntimeError(('Wrong prepared-output rejection', case, result.stderr))
            elif case.endswith('link') and b'Linked ' not in result.stderr:
                raise RuntimeError(('Wrong linked-output rejection', case, result.stderr))
            elif case in ('2', '3', '4', '5', '6') and b'Invalid composition name' not in result.stderr:
                raise RuntimeError(('Wrong name rejection', case, result.stderr))
            if witness.read_bytes() != b'preserve outside bytes':
                raise RuntimeError('External output changed')
            print('PASS upload gate:', case, 'prepared=', ready, flush=True)
            count += 1
    return count


def source_boundaries(current_check, current_build):
    count = 0
    previous_check = original('ad64d0d551689bf1f702ef0c6c2e27c98b9a1e8c')
    previous_build = original('8b046dd79d8e0181fce227f658f75e0db1ac5d79')
    for label, checker, build in (('previous', previous_check, previous_build),
                                  ('current', current_check, current_build)):
        for case in ('clean', 'assume-unchanged', 'skip-worktree', 'filemode', 'clean-filter'):
            with tempfile.TemporaryDirectory(prefix='baseline-final-source-') as directory:
                root = Path(directory)
                initialize(root)
                (root / 'Build').mkdir()
                (root / 'Build/check.py').write_bytes(checker)
                (root / 'Build/features.json').write_text(
                    '{"name":"baseline","features":[],"patches":[],"sources":{}}\n')
                git(root, 'add', '-f', 'Build')
                git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost',
                    'commit', '-qm', 'Final boundary input')
                head = git(root, 'rev-parse', 'HEAD').decode().strip()
                alter(root, case)
                out = root / 'artifacts/baseline'
                out.mkdir(parents=True)
                tail = build.decode().split('python3 Build/check.py reverse', 1)[1]
                tail = 'python3 Build/check.py reverse' + tail
                result = subprocess.run(['bash', '-euo', 'pipefail', '-c', tail], cwd=root,
                                        env=dict(os.environ, ROOT=str(root), CORE=str(root),
                                                 OUT=str(out), NAME='baseline', COMMIT=head),
                                        capture_output=True, timeout=15)
                accepted = label == 'previous' or case == 'clean'
                if (result.returncode == 0) != accepted or (out / 'SUCCESS.txt').exists() != accepted:
                    raise RuntimeError((label, 'final source', case, result.returncode, result.stderr))
                if not accepted and b'Changed source input:' not in result.stderr:
                    raise RuntimeError(('Wrong final-source rejection', case, result.stderr))
                print('PASS final source:', label, case, 'accepted=', accepted, flush=True)
                count += 1
    functions = ast.Module(body=[n for n in ast.parse(current_check).body
                                 if isinstance(n, ast.FunctionDef) and n.name in ('git', 'tracked', 'archive')],
                           type_ignores=[])
    for case in ('valid', 'export-ignore', 'export-subst', 'missing', 'bytes', 'mode',
                 'symlink-type', 'extra', 'duplicate', 'directory', 'crc'):
        with tempfile.TemporaryDirectory(prefix='baseline-source-archive-') as directory:
            root = Path(directory)
            initialize(root)
            (root / 'src/probe.c').write_text('/* $Format:%H$ */\nint probe;\n')
            (root / 'src/probe-link').symlink_to('probe.c')
            (root / 'build-apple.sh').chmod(0o755)
            git(root, 'add', '.')
            git(root, '-c', 'user.name=Input fixture', '-c', 'user.email=audit@localhost',
                'commit', '-qm', 'Archive modes and literal source')
            if case.startswith('export-'):
                (root / '.git/info/attributes').write_text('src/probe.c ' + case + '\n')
            archive_path = root / 'source.zip'
            archive_path.write_bytes(git(root, 'archive', '--format=zip', 'HEAD'))
            if case not in ('valid', 'export-ignore', 'export-subst'):
                with zipfile.ZipFile(archive_path) as source:
                    entries = [(info, source.read(info)) for info in source.infolist()]
                with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED) as target:
                    for info, data in entries:
                        if case == 'missing' and info.filename == 'src/probe.c':
                            continue
                        if case == 'bytes' and info.filename == 'src/probe.c':
                            data += b'\nchanged\n'
                        if ((case == 'mode' and info.filename == 'build-apple.sh') or
                                (case == 'symlink-type' and info.filename == 'src/probe-link')):
                            info.external_attr, info.create_system = 0, 0
                        info.compress_type = zipfile.ZIP_STORED
                        target.writestr(info, data)
                    if case == 'extra':
                        target.writestr('extra', b'extra')
                    elif case == 'duplicate':
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            target.writestr('src/probe.c', b'duplicate')
                    elif case == 'directory':
                        target.writestr('unexpected/', b'')
                if case == 'crc':
                    with zipfile.ZipFile(archive_path) as source:
                        info = source.getinfo('src/probe.c')
                    data = bytearray(archive_path.read_bytes())
                    offset = info.header_offset
                    name_size, extra_size = struct.unpack_from('<HH', data, offset + 26)
                    data[offset + 30 + name_size + extra_size] ^= 1
                    archive_path.write_bytes(data)
            namespace = {'subprocess': subprocess, 'os': os, 'hashlib': hashlib,
                         'zipfile': zipfile, 'Path': Path, 'ROOT': root}
            exec(compile(functions, '<exact-source-archive-check>', 'exec'), namespace)
            accepted = True
            try:
                namespace['archive'](archive_path, 'HEAD')
            except (AssertionError, zipfile.BadZipFile):
                accepted = False
            if accepted != (case == 'valid'):
                raise RuntimeError(('source archive', case, accepted))
            print('PASS archive:', case, 'accepted=', accepted, flush=True)
            count += 1
    return count


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    # Do not let caller-specific Git environment change isolated fixture identity.
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GITHUB_OUTPUT'):
        os.environ.pop(key, None)
    old, current = original(OLD_CHECK), (ROOT / 'Build/check.py').read_bytes()
    count = native_boundaries(old, current) + optimization(old, current)
    current_build = (ROOT / 'Build/build.sh').read_bytes()
    count += shell_boundaries(original(OLD_BUILD), current_build)
    count += publication_boundaries(original(PREVIOUS_BUILD), current_build)
    count += workflow_boundaries(current_build)
    count += source_boundaries(current, current_build)
    count += linked_outputs(original(PREVIOUS_BUILD), current_build)
    print(f'SUMMARY: {count} exact-old/current input, assertion, publication and cleanup cases; no native/Apple execution')


if __name__ == '__main__':
    main()
