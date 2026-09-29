#!/usr/bin/env python3
"""Actual controller ownership boundaries and exact-old negative controls; no IPA."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
IMPORTS = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
BASELINE = '0224ecec67a7c454d7943affc1790542dee13386'
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
assert mode in ('all', 'debug', 'optimized')
current = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_bytes()
previous = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASELINE])
assert hashlib.sha1(b'blob ' + str(len(previous)).encode() + b'\0' + previous).hexdigest() == BASELINE
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    for label, source in [('current', current), ('unowned-release-negative', previous)]:
        text = source.decode()
        assert text.startswith(IMPORTS)
        (folder / 'Controller.swift').write_text(text.replace(IMPORTS, 'import Foundation\n', 1))
        for optimized in (False, True):
            if mode == 'debug' and optimized or mode == 'optimized' and not optimized:
                continue
            executable = folder / 'test'
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimized else []),
                            str(ROOT / 'Tests/Background/PlatformMocks.swift'),
                            str(folder / 'Controller.swift'),
                            str(ROOT / 'Tests/Background/SessionOwnershipTests.swift'),
                            '-o', str(executable)], check=True, timeout=90)
            result = subprocess.run([str(executable), 'all' if label == 'current' else 'unowned'],
                                    capture_output=True, text=True, timeout=30)
            print('TEST:', label, 'optimized=', optimized, flush=True)
            print(result.stdout, end='', flush=True)
            if label == 'current':
                assert result.returncode == 0 and '0 failed;' in result.stdout, result.stderr
            else:
                assert result.returncode == 1 and 'Off after failed setup preserves unowned shared session' in result.stdout, result.stderr
                print('EXPECTED PRIOR FAILURE: unowned release; not a current-source failure', flush=True)
print('PASS: ownership, pre-activation reentry and healthy resource reuse; not physical LiveContainer evidence', flush=True)
