#!/usr/bin/env python3
"""Inspect archive and IPA bytes; never claim an installed device was exercised."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import sys
import zipfile

app, ipa = Path(sys.argv[1]), Path(sys.argv[2])
info = plistlib.loads((app / 'Info.plist').read_bytes())
assert info['CFBundleIdentifier'] == 'hev.Socks5'
assert info['MinimumOSVersion'] == '17.2'
assert info['DTSDKName'].startswith('iphoneos27.')
binary = (app / 'Socks5').read_bytes()
magic, cpu, subtype, kind, count, size, flags, reserved = struct.unpack_from('<8I', binary)
assert magic == 0xfeedfacf and cpu == 0x100000c
cursor, libraries, version, signed = 32, [], None, False
for _ in range(count):
    cmd, length = struct.unpack_from('<II', binary, cursor)
    assert length >= 8 and cursor + length <= len(binary)
    if cmd == 0x32:
        platform, minimum, sdk = struct.unpack_from('<III', binary, cursor + 8)
        assert platform == 2 and sdk >> 16 == 27
        version = {'platform': platform, 'minos': minimum, 'sdk': sdk}
    if cmd in (0xc, 0x80000018, 0x8000001f, 0x80000023):
        start = cursor + struct.unpack_from('<I', binary, cursor + 8)[0]
        libraries.append(binary[start:cursor+length].split(b'\0')[0].decode())
    if cmd in (0x21, 0x2c):
        assert struct.unpack_from('<I', binary, cursor+16)[0] == 0
    if cmd == 0x1d: signed = True
    cursor += length
assert version is not None
assert not any('BackgroundTasks.framework' in s or 'NetworkExtension.framework' in s for s in libraries)
assert not any(k.startswith('BGTask') for k in info)
assert not list(app.rglob('*.appex'))
with zipfile.ZipFile(ipa) as z:
    assert z.testzip() is None
    assert z.read('Payload/Socks5.app/Socks5') == binary
    assert plistlib.loads(z.read('Payload/Socks5.app/Info.plist')) == info
    assert not any(n.endswith(('.swift', '.py', '.patch', '.c')) for n in z.namelist())
print(json.dumps({'bundle': info['CFBundleIdentifier'], 'version': info['CFBundleShortVersionString'],
                  'build': info['CFBundleVersion'], 'sdk': info['DTSDKName'],
                  'minimumOS': info['MinimumOSVersion'], 'macho': version,
                  'backgroundModes': info.get('UIBackgroundModes', []), 'dylibs': libraries,
                  'hasCodeSignatureCommand': signed, 'sha256': hashlib.sha256(ipa.read_bytes()).hexdigest(),
                  'scope': 'Archive/IPA inspection only. User installation must sign/import; no device certification.'}, indent=2))
