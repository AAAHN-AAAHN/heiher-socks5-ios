#!/usr/bin/env python3
"""Verify current recovery properties and exact build9 negative controls.

Only the three platform imports are substituted. No production function rewrites.
Old expected failures expose policy defects; they are not current test successes.
"""
from pathlib import Path
import hashlib
import subprocess
import tempfile
import sys

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
PATH = 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'
IMPORTS = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
OLD = 'bfc4656ad197aa8b8f0266d032ec72e964c25ba9'
CASES = ('healthy-advice', 'activation-advice', 'preparation-advice',
         'generic-storm', 'inactive-storm', 'negative-advice-storm',
         'positive-advice-storm', 'end-preserves-healthy',
         'end-after-invalidated-activation', 'end-after-invalidated-preparation',
         'lost-no-probes', 'lost-missing-reset', 'lost-probe-interruption', 'lost-activation-reset', 'lost-preparation-reset',
         'lost-foreground', 'lost-explicit-on', 'lost-positive-advice',
         'configuration-drift', 'silent-stop', 'first-decoder-stop',
         'reset-storm', 'own-echo', 'lost-off-reentry', 'no-completion',
         'owner-release', 'initial-off', 'reentry-matrix', 'mixed-transitions')
OLD_FAILURES = ('healthy-advice', 'activation-advice', 'preparation-advice',
                'generic-storm', 'inactive-storm', 'negative-advice-storm',
                'positive-advice-storm', 'end-preserves-healthy',
                'configuration-drift', 'owner-release')
current = (ROOT / PATH).read_text()
old = subprocess.check_output(['git', '-C', str(ROOT), 'show', OLD + ':' + PATH]).decode()
assert hashlib.sha256(old.encode()).hexdigest() == '05ef30ec0af599e7cfccaec8fad2b7655d2f038173a605bdbc6631f7b84fc261'
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    for label, source in [('current', current), ('old-negative', old)]:
        assert source.startswith(IMPORTS)
        (folder / 'Controller.swift').write_text(source.replace(IMPORTS, 'import Foundation\n', 1))
        for optimize in (False, True):
            if mode == 'debug' and optimize or mode == 'optimized' and not optimize:
                continue
            exe = folder / ('test-' + label + str(optimize))
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimize else []),
                            str(ROOT / 'Tests/Background/PlatformMocks.swift'), str(folder / 'Controller.swift'),
                            str(ROOT / 'Tests/Background/InterruptionPolicyTests.swift'), '-o', str(exe)],
                           check=True, timeout=90)
            for case in CASES if label == 'current' else OLD_FAILURES:
                result = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=30)
                print('TEST:', label, 'optimized=', optimize, case, flush=True)
                print(result.stdout, end='', flush=True)
                if label == 'current':
                    assert result.returncode == 0, (case, result.stderr)
                else:
                    assert result.returncode == 1 and 'FAIL:' in result.stdout and 'SUMMARY:' in result.stdout, (case, result.stderr)
                    print('EXPECTED OLD POLICY FAILURE (not current):', case, flush=True)
print('PASS: current recovery invariants and exact-build9 negative controls; not Apple/physical interruptions')
