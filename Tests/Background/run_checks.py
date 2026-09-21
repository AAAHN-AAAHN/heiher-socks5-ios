#!/usr/bin/env python3
"""Compile the actual controller against scripted platform doubles; no IPA code changes."""
import hashlib
from pathlib import Path
import subprocess
import tempfile
import wave

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
    for name in ['ControllerTests', 'DelegateTests']:
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                        str(Path(__file__).with_name('PlatformMocks.swift')),
                        str(temp / 'BackgroundKeepAlive.swift'),
                        str(Path(__file__).with_name(name + '.swift')),
                        '-o', str(temp / name)], check=True)
        subprocess.run([str(temp / name)], check=True)
asset = root / 'Socks5/BackgroundKeepAlive/Silence.wav'
with wave.open(str(asset), 'rb') as wav:
    assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 8000, 400)
    samples = wav.readframes(wav.getnframes())
    assert samples == bytes(800)
print('PASS: all 400 signed 16-bit PCM samples are exactly zero; WAV header remains valid')
print('WAV SHA256:', hashlib.sha256(asset.read_bytes()).hexdigest())
