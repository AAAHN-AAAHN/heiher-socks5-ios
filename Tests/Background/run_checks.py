#!/usr/bin/env python3
"""Compile the actual controller against scripted platform doubles; no IPA code changes."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import wave

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
root = Path(__file__).resolve().parents[2]
source = root / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'
code = source.read_text()
# Replace only framework imports. The controller body is unchanged.
assert code.startswith('import AVFAudio\nimport CoreLocation\nimport SwiftUI\n')
tested = code.replace('import AVFAudio\nimport CoreLocation\nimport SwiftUI\n', 'import Foundation\n', 1)
print('Controller SHA256:', hashlib.sha256(source.read_bytes()).hexdigest(), flush=True)
with tempfile.TemporaryDirectory() as temp:
    temp = Path(temp)
    (temp / 'BackgroundKeepAlive.swift').write_text(tested)
    for name in ['ControllerTests', 'DelegateTests', 'RecoveryTests', 'LifecycleTests', 'CallbackLifetimeTests', 'AuthorizationResetTests']:
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                        str(Path(__file__).with_name('PlatformMocks.swift')),
                        str(temp / 'BackgroundKeepAlive.swift'),
                        str(Path(__file__).with_name(name + '.swift')),
                        '-o', str(temp / name)], check=True, timeout=90)
        subprocess.run([str(temp / name)], check=True, timeout=30)
    # The exact previous controller must fail the new authorization-reset fixture.
    old_blob = '63e9e895ed6141e2b021ba80742cbddb13d04052'
    old = subprocess.check_output(['git', '-C', str(root), 'show', old_blob])
    assert hashlib.sha1(b'blob ' + str(len(old)).encode() + b'\0' + old).hexdigest() == old_blob
    (temp / 'BackgroundKeepAlive.swift').write_text(old.decode().replace(
        'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n', 'import Foundation\n', 1))
    executable = temp / 'OldAuthorizationReset'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                    str(Path(__file__).with_name('PlatformMocks.swift')),
                    str(temp / 'BackgroundKeepAlive.swift'),
                    str(Path(__file__).with_name('AuthorizationResetTests.swift')),
                    '-o', str(executable)], check=True, timeout=90)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    print(result.stdout, end='')
    assert result.returncode == 1 and result.stdout.count('FAIL:') == 28
    assert 'SUMMARY: 49 authorization-reset assertions; 28 failed;' in result.stdout
    print('PASS: exact old controller fails authorization-reset regression as expected; not a current-source failure')
asset = root / 'Socks5/BackgroundKeepAlive/Silence.wav'
with wave.open(str(asset), 'rb') as wav:
    assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 8000, 400)
    samples = wav.readframes(wav.getnframes())
    assert samples == bytes(800)
print('PASS: all 400 signed 16-bit PCM samples are exactly zero; WAV header remains valid')
print('WAV SHA256:', hashlib.sha256(asset.read_bytes()).hexdigest())
