#!/usr/bin/env python3
"""Mixed-signal regression and exact pre-audit negative controls; no app rewrite."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
IMPORTS = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
BASELINE = 'cfd8398d45f7eb1c7558455cbbcd71f574cd0855'
current = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_bytes()
previous = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASELINE])
assert hashlib.sha1(b'blob ' + str(len(previous)).encode() + b'\0' + previous).hexdigest() == BASELINE
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
assert mode in ('all', 'debug', 'optimized')
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    for label, source in [('current', current), ('pre-audit-negative', previous)]:
        text = source.decode()
        assert text.startswith(IMPORTS)
        (folder / 'Controller.swift').write_text(text.replace(IMPORTS, 'import Foundation\n', 1))
        for optimize in (False, True):
            if mode == 'debug' and optimize or mode == 'optimized' and not optimize:
                continue
            executable = folder / (label + str(optimize))
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimize else []),
                            str(ROOT / 'Tests/Background/PlatformMocks.swift'),
                            str(folder / 'Controller.swift'),
                            str(ROOT / 'Tests/Background/MixedNotificationTests.swift'),
                            '-o', str(executable)], check=True, timeout=90)
            cases = ('deadline', 'storm', 'matrix') if label == 'current' else ('deadline', 'storm')
            for case in cases:
                result = subprocess.run([str(executable), case], capture_output=True, text=True, timeout=45)
                print('TEST:', label, 'optimized=', optimize, case, flush=True)
                print(result.stdout, end='', flush=True)
                if label == 'current':
                    assert result.returncode == 0, (case, result.stderr)
                else:
                    assert result.returncode == 1 and 'FAIL:' in result.stdout and 'SUMMARY:' in result.stdout, (case, result.stderr)
                    print('EXPECTED PRE-AUDIT FAILURE; not a current-source failure', flush=True)
print('PASS: mixed-signal retry budget, deadline and transition invariants; not physical-device timing')
