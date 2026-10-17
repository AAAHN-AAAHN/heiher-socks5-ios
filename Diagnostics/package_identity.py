#!/usr/bin/env python3
"""Bind each standalone ARM64 IPA and its dSYM/source archive to this checkout."""
import hashlib
import io
import json
from pathlib import Path
import plistlib
import re
import stat
import struct
import subprocess
import sys
import zipfile

assert __debug__, 'Assertions must be enabled'
assert sys.platform == 'darwin'
root = Path.cwd()
profile = sys.argv[1]
names = {'background': 'background', 'settings': 'settings-persistence'}
assert profile in names
name = names[profile]
config = json.loads((root / 'Build/features.json').read_text())
assert config['name'] == name
out = root / 'artifacts' / name
result_path = out / 'package-identity.json'
result_path.unlink(missing_ok=True)


def git(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=root)


assert not git('diff', '--name-only', 'HEAD', '--').strip()
assert not git('diff', '--cached', '--name-only', 'HEAD', '--').strip()
head = git('rev-parse', 'HEAD').decode().strip()
archive = root / '.build' / (name + '.xcarchive')
app = archive / 'Products/Applications/Socks5.app'
binary_path = app / 'Socks5'
binary = binary_path.read_bytes()
info_bytes = (app / 'Info.plist').read_bytes()
info = plistlib.loads(info_bytes)
assert info['CFBundleIdentifier'] == 'hev.Socks5'
assert info['CFBundleShortVersionString'] == '3.0.0'
assert info['CFBundleVersion'] == '1'
assert info['MinimumOSVersion'] == '17.2'
assert info['DTSDKName'].startswith('iphoneos27.')
assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
assert info.get('NSLocalNetworkUsageDescription')
assert not any(key.startswith('BGTask') for key in info)
assert not list(app.rglob('*.appex'))
if profile == 'background':
    assert set(info['UIBackgroundModes']) == {'audio', 'location'}
    assert hashlib.sha256((app / 'Silence.wav').read_bytes()).hexdigest() == '26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e'
else:
    assert not info.get('UIBackgroundModes')

magic, cpu, subtype, kind, ncmds, commands_size, flags, reserved = struct.unpack_from('<8I', binary)
assert magic == 0xfeedfacf and cpu == 0x100000c and kind == 2
commands_end = 32 + commands_size
assert commands_end <= len(binary)
cursor = 32
build = None
signed = False
libraries = []
for _ in range(ncmds):
    assert cursor + 8 <= commands_end
    command, size = struct.unpack_from('<II', binary, cursor)
    assert size >= 8 and cursor + size <= commands_end
    if command == 0x32:
        platform, minimum, sdk = struct.unpack_from('<III', binary, cursor + 8)
        assert platform == 2 and minimum == (17 << 16 | 2 << 8) and sdk >> 16 == 27
        build = {'platform': platform, 'minimum': minimum, 'sdk': sdk}
    if command == 0x1d:
        signed = True
    if command in (0x21, 0x2c):
        assert struct.unpack_from('<I', binary, cursor + 16)[0] == 0
    if command in (0xc, 0x80000018, 0x8000001f, 0x80000023):
        offset = struct.unpack_from('<I', binary, cursor + 8)[0]
        libraries.append(binary[cursor + offset:cursor + size].split(b'\0')[0].decode())
    cursor += size
assert cursor == commands_end
assert build is not None and not signed
assert not any('BackgroundTasks.framework' in value or 'NetworkExtension.framework' in value for value in libraries)

dwarf = archive / 'dSYMs/Socks5.app.dSYM/Contents/Resources/DWARF/Socks5'
uuids = subprocess.check_output(['xcrun', 'dwarfdump', '--uuid', str(binary_path), str(dwarf)], text=True)
identifiers = re.findall(r'UUID: ([0-9A-Fa-f-]+) \(arm64\)', uuids)
assert len(identifiers) == 2 and identifiers[0] == identifiers[1]
(out / 'archive-uuid.txt').write_text(uuids)
ipa = out / ('Socks5-' + name + '-unsigned.ipa')
with zipfile.ZipFile(ipa) as zipped:
    assert zipped.testzip() is None
    entries = zipped.infolist()
    assert len({entry.filename for entry in entries}) == len(entries), 'Duplicate IPA member'
    members = {value.filename: value for value in entries if not value.is_dir()}
    app_members = {'Payload/Socks5.app/' + str(value.relative_to(app)): value
                   for value in app.rglob('*') if value.is_file() or value.is_symlink()}
    assert set(members) == set(app_members)
    for member, path in app_members.items():
        assert not path.is_symlink(), 'Unexpected embedded symlink: ' + member
        mode = members[member].external_attr >> 16
        assert stat.S_IFMT(mode) == stat.S_IFREG and stat.S_IMODE(mode) == stat.S_IMODE(path.stat().st_mode), member
        assert zipped.read(members[member]) == path.read_bytes(), member
    assert zipped.read('Payload/Socks5.app/Socks5') == binary
    assert zipped.read('Payload/Socks5.app/Info.plist') == info_bytes
    assert not any(value.endswith(('.swift', '.py', '.c', '.patch')) for value in members)
dsym_zip = out / 'Socks5-dSYMs.zip'
with zipfile.ZipFile(dsym_zip) as zipped:
    assert zipped.testzip() is None
    entries = zipped.infolist()
    assert len({entry.filename for entry in entries}) == len(entries), 'Duplicate dSYM member'
    members = {value.filename: value for value in entries if not value.is_dir()}
    expected_members = {'dSYMs/' + str(value.relative_to(archive / 'dSYMs')): value
                        for value in (archive / 'dSYMs').rglob('*') if value.is_file() or value.is_symlink()}
    assert set(members) == set(expected_members)
    for member, path in expected_members.items():
        assert not path.is_symlink(), 'Unexpected dSYM symlink: ' + member
        mode = members[member].external_attr >> 16
        assert stat.S_IFMT(mode) == stat.S_IFREG and stat.S_IMODE(mode) == stat.S_IMODE(path.stat().st_mode), member
        assert zipped.read(members[member]) == path.read_bytes(), member
source_zip = out / ('Socks5-' + name + '-source.zip')
with zipfile.ZipFile(source_zip) as delivered, zipfile.ZipFile(io.BytesIO(git('archive', '--format=zip', head))) as expected:
    assert delivered.testzip() is None
    assert delivered.namelist() == expected.namelist()
    for member in expected.infolist():
        assert delivered.getinfo(member.filename).external_attr == member.external_attr
        assert delivered.read(member.filename) == expected.read(member.filename)

result = {'result': 'PASS', 'profile': profile, 'source_commit': head,
          'source_tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
          'bundle_id': info['CFBundleIdentifier'], 'version': info['CFBundleShortVersionString'],
          'build': info['CFBundleVersion'], 'minimum_os': info['MinimumOSVersion'],
          'sdk': info['DTSDKName'], 'macho': build, 'dylibs': libraries,
          'archive_uuid': identifiers[0], 'signature_load_command': signed,
          'files': {value.name: {'sha256': hashlib.sha256(value.read_bytes()).hexdigest(),
                                'bytes': value.stat().st_size} for value in (ipa, dsym_zip, source_zip)},
          'scope': 'Actual unsigned ARM64 archive, IPA, matching dSYM and exact source; physical installation is not exercised.'}
result_path.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
