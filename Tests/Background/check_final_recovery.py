#!/usr/bin/env python3
"""Exact-controller ordered triples and long recovery histories, not Apple runtime."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
IMPORTS = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
source = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_text()
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
assert mode in ('all', 'debug', 'optimized')
assert source.startswith(IMPORTS)
constant = 'private static let audioCheckInterval: TimeInterval = 0.5'
assert source.count(constant) == 1
assert source.count('scheduleAudioCheck()') == 6  # Five calls and one declaration.
assert source.count('Timer(timeInterval: Self.audioCheckInterval, repeats: false)') == 1
assert 'scheduleAudioCheck(after:' not in source and 'serviceProbeInterval' not in source
assert 'player?.numberOfLoops = -1' in source
# Production app timers only. Test deadlines and native network timeouts are not
# audio polling intervals and must not be changed to half a second.
application = '\n'.join(path.read_text() for path in sorted((ROOT / 'Socks5').rglob('*.swift')))
assert len(re.findall(r'\bTimer\s*\(', application)) == 1
assert not re.search(r'\b(?:asyncAfter|scheduledTimer|makeTimerSource)\s*\(|\bTask\.sleep\b', application)
print('SOURCE SHA256:', hashlib.sha256(source.encode()).hexdigest(), flush=True)
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    for label, text in [('current', source), ('deliberate-interval-mutation', source.replace(constant, constant[:-3] + '1.0', 1))]:
        (folder / 'Controller.swift').write_text(text.replace(IMPORTS, 'import Foundation\n', 1))
        for optimized in (False, True):
            if (mode == 'debug' and optimized) or (mode == 'optimized' and not optimized):
                continue
            executable = folder / 'test'
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimized else []),
                            str(ROOT / 'Tests/Background/PlatformMocks.swift'),
                            str(folder / 'Controller.swift'),
                            str(ROOT / 'Tests/Background/FinalRecoveryTests.swift'),
                            '-o', str(executable)], check=True, timeout=90)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=90)
            print('TEST:', label, 'optimized=', optimized, flush=True)
            print(result.stdout, end='', flush=True)
            if label == 'current':
                assert result.returncode == 0 and result.stdout.count('PASS:') == 2, result.stderr
            else:
                assert result.returncode == 1 and 'one half-second timer' in result.stdout, result.stderr
                print('EXPECTED MUTATION REJECTION: deliberately defective copy, not production failure', flush=True)
print('PASS: exact current source, half-second timer coverage and finite recovery histories; not physical-device proof', flush=True)
