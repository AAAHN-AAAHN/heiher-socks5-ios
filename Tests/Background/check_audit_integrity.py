#!/usr/bin/env python3
"""Exercise actual SDK/UI audit entry points before their external Apple boundary.

Exact old Git blobs are negative controls. Temporary Git worktrees and failing
SDK executables test provenance/marker behavior, not Apple compilation or playback.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import native_inputs
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = [
    ('check_audio_sdk.sh', 'db8596f64c31f493180e13b62a2ae6ba9bbc7410', '355880ba630159f012a4f495bff1277461f416cd', 'audio-checks'),
    ('check_async_ui.py', '73ab512035973418d6203b5fdc244dca96784985', '3a6432e0da8cd9e4fae50deb4ab6ad7dd464a8c8', 'audio-async-ui'),
]
MARKERS = ('SUCCESS.txt', 'advisory-check.txt', 'app-sha256.txt')


def exercise(name, source, label, case, output_name):
    with tempfile.TemporaryDirectory(prefix='background-audit-integrity-') as temporary:
        root = Path(temporary)
        path = root / 'Tests/Background' / name
        path.parent.mkdir(parents=True)
        path.write_bytes(source)
        (path.parent / 'native_inputs.py').write_bytes((ROOT / 'Tests/Background/native_inputs.py').read_bytes())
        (root / 'Build').mkdir()
        (root / 'Build/features.json').write_text(json.dumps({'name': 'background'}))
        (root / '.gitignore').write_text('artifacts/\n.build/\ntools/\nreached-sdk\n')
        probe = root / 'tracked-source.txt'
        probe.write_text('committed source\n')
        def git(*args):
            return subprocess.run(['git', '-C', str(root), *args], check=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        git('init', '-q')
        git('add', '.')
        git('-c', 'user.name=Audit Fixture', '-c', 'user.email=audit@localhost',
            'commit', '-qm', 'Isolated audit-driver input')
        commit = git('rev-parse', 'HEAD').stdout.decode().strip()
        core = root / '.build/core'
        (core / 'src').mkdir(parents=True)
        raw_header = b'/* Controlled audit fixture; no compiled product. */\n'
        (core / 'src/hev-main.h').write_bytes(raw_header)
        framework = core / 'HevSocks5Server.xcframework'
        for target in ('ios-arm64', 'ios-arm64_x86_64-simulator'):
            headers = framework / target / 'Headers'
            headers.mkdir(parents=True)
            (headers / 'hev-main.h').write_bytes(raw_header)
            (framework / target / 'libhev-socks5-server.a').write_bytes(b'fixture library')
        with mock.patch.object(native_inputs, 'ROOT', root):
            native_inputs.record(core, commit)
        native = root / 'artifacts/background'
        (native / 'tested-commit.txt').write_text(commit + '\n')
        (native / 'SUCCESS.txt').write_text('Controlled fixture only\n')
        if case == 'native-stale':
            (native / 'compiled-headers/source-commit.txt').write_text('0' * 40 + '\n')
        elif case == 'native-changed-header':
            (native / 'compiled-headers/hev-main.h').write_bytes(b'changed header')
        elif case == 'native-changed-framework':
            (framework / 'ios-arm64/libhev-socks5-server.a').write_bytes(b'changed library')
        elif case == 'native-missing-success':
            (native / 'SUCCESS.txt').unlink()
        elif case == 'native-missing-receipt':
            (native / 'built-framework.json').unlink()
        if case in ('unstaged', 'staged', 'index-only'):
            probe.write_text('uncommitted source\n')
            if case != 'unstaged':
                git('add', str(probe))
            if case == 'index-only':
                probe.write_text('committed source\n')
        out = root / 'artifacts' / output_name
        out.mkdir(parents=True)
        for marker in MARKERS:
            (out / marker).write_text('PRIOR SUCCESS\n')
        diagnostic = out / 'prior-diagnostic.log'
        diagnostic.write_text('Keep prior failure evidence.\n')
        tools = root / 'tools'
        tools.mkdir()
        for tool in ('xcodebuild', 'xcrun'):
            executable = tools / tool
            executable.write_text('#!/bin/sh\nprintf reached > reached-sdk\nexit 23\n')
            executable.chmod(0o755)
        if case == 'existing-work':
            (root / '.build/audio-async-ui').mkdir(parents=True)
        python_flags = ['-O'] if case == 'optimized-python' else []
        command = ['bash', str(path)] if name.endswith('.sh') else [sys.executable, *python_flags, str(path)]
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'])
        if case == 'optimized-python':
            env['PYTHONOPTIMIZE'] = '1'
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=15)
        reached = (root / 'reached-sdk').exists()
        expected_reached = (case == 'clean'
                            or (label == 'old-control' and (case in ('unstaged', 'staged') or case.startswith('native-')))
                            or (label != 'current' and case == 'index-only')
                            or (label != 'current' and name.endswith('.sh') and case == 'optimized-python'))
        if result.returncode == 0 or reached != expected_reached:
            raise RuntimeError((name, label, case, result.returncode, reached, result.stdout, result.stderr))
        if (out / 'SUCCESS.txt').exists():
            raise RuntimeError('A failed audit retained its overall success marker')
        if name.endswith('.py'):
            stale = [(out / marker).exists() for marker in MARKERS[1:]]
            if stale != [label == 'old-control'] * 2:
                raise RuntimeError((label, case, 'advisory/product marker invalidation', stale))
        if diagnostic.read_text() != 'Keep prior failure evidence.\n':
            raise RuntimeError('Prior diagnostics were removed')
        if label == 'current' and case in ('staged', 'unstaged', 'index-only') and result.returncode != 1:
            raise RuntimeError('Dirty source was not rejected by Git before the SDK boundary')
        print('PASS:', name, label, case, 'sdk-reached=', reached, 'exit=', result.returncode)


def original(blob):
    data = subprocess.check_output(['git', '-C', str(ROOT), 'show', blob])
    if hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() != blob:
        raise RuntimeError('Wrong old-driver identity')
    return data


def optimization_boundaries():
    # Compile the exact driver body with the indicated Python optimization. Stop
    # at its first external command; no fake successful Swift or Apple run occurs.
    class ExternalBoundary(Exception):
        pass
    # Old entry bodies extract the old view's Combine publisher before invoking
    # a compiler. Give those exact controls their exact historical local inputs;
    # the current service intentionally no longer has that view-owned publisher.
    baseline = '618b3d2b413937aaad7373ee2af9e693ec81b84a'
    prior_inputs = {
        ROOT / path: subprocess.check_output(['git', '-C', str(ROOT), 'show', baseline + ':' + path]).decode()
        for path in ('Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift',
                     'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift',
                     'Tests/Background/PlatformMocks.swift')
    }
    actual_read = Path.read_text
    count = 0
    for name, blob in [
        ('check_async_session.py', '09a38bab32299a982f22a1af1843afb2dfc12029'),
        ('check_subscription.py', '4c5628fdb86dd585f03408c453ae399c4e9ab615'),
        ('check_live_scheduling.py', '2f4a200372b0989dc23cf2581aa3cc4cf8899a58'),
    ]:
        path = ROOT / 'Tests/Background' / name
        for label, source in [('prior-control', original(blob)), ('current', path.read_bytes())]:
            for optimize in (0, 1):
                reached = False
                def input_read(path, *args, **kwargs):
                    if label == 'prior-control' and path in prior_inputs:
                        return prior_inputs[path]
                    return actual_read(path, *args, **kwargs)
                with mock.patch.object(subprocess, 'check_output', side_effect=ExternalBoundary), \
                     mock.patch.object(subprocess, 'run', side_effect=ExternalBoundary), \
                     mock.patch.object(Path, 'read_text', autospec=True, side_effect=input_read):
                    try:
                        exec(compile(source, str(path), 'exec', optimize=optimize),
                             {'__name__': '__main__', '__file__': str(path)})
                    except ExternalBoundary:
                        reached = True
                    except SystemExit as error:
                        if not error.code:
                            raise RuntimeError('Rejected input reported success')
                if reached != (label == 'prior-control' or optimize == 0):
                    raise RuntimeError((name, label, optimize, reached))
                count += 1
                print('PASS:', name, label, 'optimization=', optimize, 'external-boundary=', reached)
    return count


def native_copy_boundaries():
    # These are small byte fixtures for receipt/copy integrity, never native binaries.
    count = 0
    for case in ('clean-copy', 'changed-library', 'extra-file', 'missing-file', 'linked-file',
                 'changed-module', 'changed-header', 'linked-header', 'linked-headers',
                 'stale-framework', 'receipt-file-map'):
        with tempfile.TemporaryDirectory(prefix='background-native-input-') as temporary:
            root = Path(temporary)
            (root / 'Build').mkdir()
            (root / 'Build/features.json').write_text(json.dumps({'name': 'background'}))
            core = root / '.build/core'
            (core / 'src').mkdir(parents=True)
            (core / 'src/hev-main.h').write_bytes(b'fixture header')
            framework = core / 'HevSocks5Server.xcframework'
            for target in ('ios-arm64', 'ios-arm64_x86_64-simulator'):
                headers = framework / target / 'Headers'
                headers.mkdir(parents=True)
                (headers / 'hev-main.h').write_bytes(b'fixture header')
                (framework / target / 'libhev-socks5-server.a').write_bytes(b'fixture library')
            commit = 'a' * 40
            with mock.patch.object(native_inputs, 'ROOT', root), mock.patch.object(native_inputs, 'head', return_value=commit):
                native_inputs.record(core, commit)
                out = root / 'artifacts/background'
                (out / 'SUCCESS.txt').write_text('fixture only')
                (out / 'tested-commit.txt').write_text(commit)
                target = framework / 'ios-arm64/libhev-socks5-server.a'
                if case == 'changed-library':
                    target.write_bytes(b'changed')
                elif case == 'extra-file':
                    (framework / 'extra').write_bytes(b'extra')
                elif case == 'missing-file':
                    target.unlink()
                elif case == 'linked-file':
                    target.unlink()
                    target.symlink_to(core / 'src/hev-main.h')
                elif case == 'changed-module':
                    (out / 'compiled-headers/module.modulemap').write_bytes(b'changed')
                elif case == 'changed-header':
                    (out / 'compiled-headers/hev-main.h').write_bytes(b'changed')
                elif case == 'linked-header':
                    header = out / 'compiled-headers/hev-main.h'
                    header.unlink()
                    header.symlink_to(core / 'src/hev-main.h')
                elif case == 'linked-headers':
                    headers = out / 'compiled-headers'
                    headers.rename(out / 'moved-headers')
                    headers.symlink_to(out / 'moved-headers', target_is_directory=True)
                elif case in ('stale-framework', 'receipt-file-map'):
                    receipt = json.loads((out / 'built-framework.json').read_bytes())
                    if case == 'stale-framework':
                        receipt['source_commit'] = 'b' * 40
                    else:
                        receipt['files'].pop('ios-arm64/libhev-socks5-server.a')
                    (out / 'built-framework.json').write_text(json.dumps(receipt))
                if case == 'clean-copy':
                    destination = root / 'Copied.xcframework'
                    destination.mkdir()
                    (destination / 'stock-library').write_bytes(b'stale')
                    with mock.patch.object(sys, 'argv', ['native_inputs.py', 'copy', str(destination)]):
                        native_inputs.main()
                    if native_inputs.snapshot(destination) != native_inputs.snapshot(framework):
                        raise RuntimeError('Native prepared framework copy differs')
                else:
                    try:
                        native_inputs.verify()
                    except (RuntimeError, OSError):
                        pass
                    else:
                        raise RuntimeError('Native input mutation was accepted: ' + case)
            count += 1
            print('PASS: native receipt/copy integrity', case)
    return count


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    count = 0
    for name, old_blob, prior_blob, output_name in ENTRIES:
        old = original(old_blob)
        current = (ROOT / 'Tests/Background' / name).read_bytes()
        for label, source in [('old-control', old), ('current', current)]:
            cases = ['clean', 'unstaged', 'staged', 'index-only', 'optimized-python',
                     'native-stale', 'native-changed-header', 'native-changed-framework',
                     'native-missing-success', 'native-missing-receipt']
            if name.endswith('.py'):
                cases += ['existing-work']
            for case in cases:
                exercise(name, source, label, case, output_name)
                count += 1
        prior = original(prior_blob)
        cases = ['index-only'] + (['optimized-python'] if name.endswith('.sh') else [])
        for case in cases:
            exercise(name, prior, 'prior-input-guard', case, output_name)
            count += 1
    count += optimization_boundaries()
    count += native_copy_boundaries()
    print(f'SUMMARY: {count} actual audit-entry boundary cases, including retained and exact-prior negative controls')
    subprocess.run([sys.executable, str(ROOT / 'Tests/Background/check_simulator_cleanup.py')], check=True)


if __name__ == '__main__':
    main()
