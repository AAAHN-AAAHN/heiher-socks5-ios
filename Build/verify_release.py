#!/usr/bin/env python3
"""Inspect the actual archived IPA, not the source-only or simulator configuration."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import zipfile

if not __debug__:
    raise SystemExit('Assertions must be enabled')
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/integrated'
ARCHIVE = ROOT / '.build/integrated.xcarchive'
APP = ARCHIVE / 'Products/Applications/Socks5.app'
info = plistlib.loads((APP / 'Info.plist').read_bytes())
assert info['CFBundleIdentifier'] == 'hev.Socks5'
assert info['CFBundleShortVersionString'] == '1.1.0' and info['CFBundleVersion'] == '7'
assert info['MinimumOSVersion'] == '17.2'
assert info['DTSDKName'].startswith('iphoneos27.')
assert set(info['UIBackgroundModes']) == {'audio', 'location'}
assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
for key in ('NSLocalNetworkUsageDescription', 'NSLocationWhenInUseUsageDescription', 'NSLocationAlwaysAndWhenInUseUsageDescription'):
    assert info.get(key), key
assert not any(key.startswith('BGTask') for key in info)
assert not list(APP.rglob('*.appex'))
assert (APP / 'Assets.car').exists()
assert info['CFBundleIcons']['CFBundlePrimaryIcon']['CFBundleIconName'] == 'AppIcon'
assert hashlib.sha256((APP / 'Silence.wav').read_bytes()).hexdigest() == '26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e'
binary = (APP / 'Socks5').read_bytes()
magic, cpu, subtype, kind, ncmds, commands_size, flags, reserved = struct.unpack_from('<8I', binary)
assert magic == 0xfeedfacf and cpu == 0x100000c
cursor = 32
libraries = []
build = None
signature = False
for _ in range(ncmds):
    cmd, size = struct.unpack_from('<II', binary, cursor)
    assert size >= 8 and cursor + size <= len(binary)
    if cmd == 0x32:
        platform, minimum, sdk = struct.unpack_from('<III', binary, cursor + 8)
        build = {'platform': platform, 'minimum': minimum, 'sdk': sdk}
        assert platform == 2 and sdk >> 16 == 27
    if cmd in (0xc, 0x80000018, 0x8000001f, 0x80000023):
        offset = struct.unpack_from('<I', binary, cursor + 8)[0]
        libraries.append(binary[cursor + offset:cursor + size].split(b'\0')[0].decode())
    if cmd == 0x1d:
        signature = True
    if cmd in (0x21, 0x2c):
        assert struct.unpack_from('<I', binary, cursor + 16)[0] == 0
    cursor += size
assert build is not None
assert not any('BackgroundTasks.framework' in x or 'NetworkExtension.framework' in x for x in libraries)
dwarf = ARCHIVE / 'dSYMs/Socks5.app.dSYM/Contents/Resources/DWARF/Socks5'
uuids = subprocess.check_output(['xcrun', 'dwarfdump', '--uuid', str(APP / 'Socks5'), str(dwarf)], text=True)
ids = re.findall(r'UUID: ([0-9A-Fa-f-]+) \(arm64\)', uuids)
assert len(ids) == 2 and ids[0] == ids[1]
symbols = subprocess.check_output(['xcrun', 'nm', '-g', str(dwarf)], text=True)
for name in ('hev_socks5_server_stats', 'hev_socks5_server_prepare'):
    assert re.search(r'^[0-9a-fA-F]+\s+[Tt]\s+_' + name + '$', symbols, re.M), name
(OUT / 'archive-symbols.txt').write_text(symbols)
(OUT / 'archive-uuid.txt').write_text(uuids)
ipa = OUT / 'Socks5-integrated-unsigned.ipa'
with zipfile.ZipFile(ipa) as archive:
    assert archive.testzip() is None
    assert archive.read('Payload/Socks5.app/Socks5') == binary
    assert plistlib.loads(archive.read('Payload/Socks5.app/Info.plist')) == info
    assert not any(n.endswith(('.swift', '.py', '.c', '.patch')) for n in archive.namelist())
result = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
          'version': info['CFBundleShortVersionString'], 'build': info['CFBundleVersion'],
          'bundle_id': info['CFBundleIdentifier'], 'minimum_os': info['MinimumOSVersion'],
          'sdk': info['DTSDKName'], 'macho': build, 'dylibs': libraries, 'signature_load_command': signature,
          'archive_uuid': ids[0], 'sha256': hashlib.sha256(ipa.read_bytes()).hexdigest(),
          'scope': 'Actual ARM64 archive/package verification. Installer must sign/import; no physical SideStore/LiveContainer certification.'}
(OUT / 'package-review.json').write_text(json.dumps(result, indent=2) + '\n')
(OUT / 'packaged-Info.plist').write_bytes((APP / 'Info.plist').read_bytes())
print(json.dumps(result, indent=2))
