#!/usr/bin/env python3
"""A rejected audit must not reuse successful markers from an earlier attempt.

Run the actual shell entry points in isolated directories. Only their first
external validation boundary is replaced with a deterministic failure; no native
engine, SDK, assertion, timeout or production source is replaced in the real run.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def check(entry, markers, original_blob, name):
    current = (ROOT / entry).read_bytes()
    original = subprocess.check_output(['git', '-C', str(ROOT), 'show', original_blob])
    identity = hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest()
    if identity != original_blob:
        raise RuntimeError('Original shell control has the wrong Git identity')
    for label, source, seeded in [('old-control', original, True),
                                   ('current-retry', current, True),
                                   ('current-first-failure', current, False)]:
        with tempfile.TemporaryDirectory(prefix='audit-driver-') as temporary:
            root = Path(temporary)
            path = root / entry
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source)
            build = root / 'Build'
            build.mkdir(exist_ok=True)
            (build / 'features.json').write_text(json.dumps({'name': name}))
            (build / 'check.py').write_text('raise SystemExit(23)\n')
            tools = root / 'tools'
            tools.mkdir()
            for tool in ('git', 'xcodebuild'):
                executable = tools / tool
                executable.write_text('#!/bin/sh\nexit 23\n')
                executable.chmod(0o755)
            output = root / 'artifacts' / name
            output.mkdir(parents=True)
            diagnostic = output / 'previous-diagnostic.log'
            diagnostic.write_bytes(b'Keep earlier diagnostic evidence.\n')
            for marker in markers:
                if seeded:
                    (output / marker).write_text('PRIOR SUCCESS\n')
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'], BUILD_IPA='0')
            result = subprocess.run(['bash', str(path)], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=15)
            if result.returncode != 23:
                raise RuntimeError((entry, label, result.returncode, result.stdout, result.stderr))
            expected_present = label == 'old-control'
            for marker in markers:
                if (output / marker).exists() != expected_present:
                    raise RuntimeError((entry, label, marker, 'stale-success contract'))
            if diagnostic.read_bytes() != b'Keep earlier diagnostic evidence.\n':
                raise RuntimeError('Prior diagnostic evidence was removed')
            print('PASS:', entry, label, 'exit=23; marker/diagnostic postconditions verified')


def main():
    check('Tests/AppIcon/run_checks.sh', ['SUCCESS.txt'],
          '1a8b2819c744d250327670c8dd97153b3da830dc', 'icon-checks')


if __name__ == '__main__':
    main()
