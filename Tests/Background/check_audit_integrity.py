#!/usr/bin/env python3
"""Exercise actual SDK/UI audit entry points before their external Apple boundary.

Exact old Git blobs are negative controls. Temporary Git worktrees and failing
SDK executables test provenance/marker behavior, not Apple compilation or playback.
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
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
                            or (label == 'old-control' and case in ('unstaged', 'staged'))
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
                with mock.patch.object(subprocess, 'check_output', side_effect=ExternalBoundary), \
                     mock.patch.object(subprocess, 'run', side_effect=ExternalBoundary):
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


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    count = 0
    for name, old_blob, prior_blob, output_name in ENTRIES:
        old = original(old_blob)
        current = (ROOT / 'Tests/Background' / name).read_bytes()
        for label, source in [('old-control', old), ('current', current)]:
            cases = ['clean', 'unstaged', 'staged', 'index-only', 'optimized-python']
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
    print(f'SUMMARY: {count} actual audit-entry boundary cases, including retained and exact-prior negative controls')


if __name__ == '__main__':
    main()
