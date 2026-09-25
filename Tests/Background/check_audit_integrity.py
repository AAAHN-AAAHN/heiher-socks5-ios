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

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = [
    ('check_audio_sdk.sh', 'db8596f64c31f493180e13b62a2ae6ba9bbc7410', 'audio-checks'),
    ('check_async_ui.py', '73ab512035973418d6203b5fdc244dca96784985', 'audio-async-ui'),
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
        if case in ('unstaged', 'staged'):
            probe.write_text('uncommitted source\n')
            if case == 'staged':
                git('add', str(probe))
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
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=15)
        reached = (root / 'reached-sdk').exists()
        expected_reached = case == 'clean' or (label == 'old-control' and case in ('unstaged', 'staged'))
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
        if label == 'current' and case in ('staged', 'unstaged') and result.returncode != 1:
            raise RuntimeError('Dirty source was not rejected by Git before the SDK boundary')
        print('PASS:', name, label, case, 'sdk-reached=', reached, 'exit=', result.returncode)


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    for name, old_blob, output_name in ENTRIES:
        old = subprocess.check_output(['git', '-C', str(ROOT), 'show', old_blob])
        if hashlib.sha1(b'blob ' + str(len(old)).encode() + b'\0' + old).hexdigest() != old_blob:
            raise RuntimeError('Wrong old-driver identity')
        current = (ROOT / 'Tests/Background' / name).read_bytes()
        for label, source in [('old-control', old), ('current', current)]:
            cases = ['clean', 'unstaged', 'staged']
            if name.endswith('.py'):
                cases += ['existing-work', 'optimized-python']
            for case in cases:
                exercise(name, source, label, case, output_name)
    print('SUMMARY: 16 actual audit-entry boundary cases, including exact-old negative controls')


if __name__ == '__main__':
    main()
