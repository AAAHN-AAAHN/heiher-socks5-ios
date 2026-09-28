#!/usr/bin/env python3
"""Replay the exact UI sample body using scripted native snapshots/state storage.

No SwiftUI body rendering, Apple scheduling or real network traffic occurs here.
Only the method's enclosing type and external API/storage dependencies are replaced.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
VIEW = ROOT / 'Socks5/Statistics/TrafficStatisticsView.swift'
BASELINE_BLOB = '190950bcb80d7e4449fbdc1f772dcc75d4d7128f'
previous = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASELINE_BLOB])
assert hashlib.sha1(b'blob ' + str(len(previous)).encode() + b'\0' + previous).hexdigest() == BASELINE_BLOB
fixture = (ROOT / 'Tests/Statistics/SamplingContractTests.swift').read_text()
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
assert mode in ('all', 'debug', 'optimized')
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    for label, text in [('current', VIEW.read_text()), ('prior-per-row-negative', previous.decode())]:
        start = text.index('    private func sample()')
        body = text[start:].rsplit('\n}', 1)[0]
        # Import the exact unchanged formatter/model, not a rewritten formula.
        generated = fixture.replace('    // INSERT_EXACT_SAMPLE_METHOD', body)
        assert generated != fixture
        source = folder / 'Replay.swift'
        source.write_text(generated)
        for optimized in (False, True):
            if (mode == 'debug' and optimized) or (mode == 'optimized' and not optimized):
                continue
            executable = folder / 'test'
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimized else []),
                            str(ROOT / 'Socks5/Statistics/TrafficStatistics.swift'),
                            str(source), '-o', str(executable)], check=True, timeout=90)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=45)
            print('TEST:', label, 'optimized=', optimized, flush=True)
            print(result.stdout, end='', flush=True)
            if label == 'current':
                assert result.returncode == 0 and 'PASS:' in result.stdout, result.stderr
            else:
                assert result.returncode == 1 and 'FAIL: one client-state publication' in result.stdout, result.stderr
                print('EXPECTED OLD PUBLICATION-COUNT FAILURE; not incorrect native byte accounting', flush=True)
print('PASS: exact sample-body replay, one publication and unchanged snapshot/rate semantics', flush=True)
