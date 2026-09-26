#!/usr/bin/env python3
"""Exact patch application, feature boundaries and packaged-resource checks."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import sys
import wave

if not __debug__:
    raise SystemExit('Assertions must be enabled')

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'Build/features.json').read_text())
FEATURES = set(CONFIG['features'])


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])



def baseline():
    lock = json.loads((ROOT / 'Build/upstream.json').read_text())
    manifest = json.loads((ROOT / 'Build/baseline-framework.json').read_text())
    assert CONFIG['sources'] == lock['sources'] == manifest['sources']
    assert CONFIG['upstream_app'] == lock['upstream_app'] == manifest['upstream_app']
    prefix = 'HevSocks5Server.xcframework/'
    names = git(ROOT, 'ls-tree', '-r', '--name-only', 'HEAD', prefix).decode().splitlines()
    actual = {name[len(prefix):]: hashlib.sha256(git(ROOT, 'show', 'HEAD:' + name)).hexdigest() for name in names}
    assert actual == manifest['files'], 'Committed framework differs from shared baseline'
    if CONFIG['name'] == 'baseline':
        assert not CONFIG['features'] and not CONFIG['patches']
        for path in ('Socks5', 'Socks5.xcodeproj', 'LICENSE'):
            assert git(ROOT, 'rev-parse', 'HEAD:' + path) == git(ROOT, 'rev-parse', lock['upstream_app'] + ':' + path)
    else:
        base = CONFIG['base_commit']
        git(ROOT, 'merge-base', '--is-ancestor', base, 'HEAD')
        for path in ('Build/upstream.json', 'Build/baseline-framework.json', 'Build/build.sh',
                     'Build/check.py', 'docs/main-baseline.md', 'HevSocks5Server.xcframework'):
            assert git(ROOT, 'rev-parse', 'HEAD:' + path) == git(ROOT, 'rev-parse', base + ':' + path), path
    print('PASS: shared source pins, baseline framework, app identity and main ancestry')


def patches():
    for item in CONFIG['patches']:
        yield item['repository'], ROOT / 'Patches' / item['file']


def apply(core):
    for relative, sha in CONFIG['sources'].items():
        repo = core / relative
        assert git(repo, 'rev-parse', 'HEAD').decode().strip() == sha, relative
        # Build scripts and the index are source inputs too, not only C/H files.
        git(repo, 'diff', '--exit-code', 'HEAD', '--')
        git(repo, 'diff', '--cached', '--exit-code', 'HEAD', '--')
    for relative, patch in patches():
        git(core / relative, 'apply', '--check', '--whitespace=error-all', str(patch))
        git(core / relative, 'apply', '--whitespace=error-all', str(patch))
        print(hashlib.sha256(patch.read_bytes()).hexdigest(), patch.name)


def formatting(core, formatter):
    for relative in CONFIG['sources']:
        repo = core / relative
        for name in git(repo, 'diff', '--name-only', '--', '*.c', '*.h').decode().splitlines():
            path = repo / name
            formatted = subprocess.check_output([formatter, str(path)])
            assert formatted == path.read_bytes(), f'Upstream formatting: {relative}/{name}'
            print('FORMAT PASS:', relative, name)


def reverse(core):
    for relative, patch in reversed(list(patches())):
        git(core / relative, 'apply', '-R', '--check', str(patch))
        git(core / relative, 'apply', '-R', str(patch))
    for relative in CONFIG['sources']:
        git(core / relative, 'diff', '--exit-code', 'HEAD', '--')
        git(core / relative, 'diff', '--cached', '--exit-code', 'HEAD', '--')
    git(core, 'submodule', 'foreach', '--recursive',
        'git diff --exit-code HEAD -- && git diff --cached --exit-code HEAD --')
    print('PASS: reverse patches restore exact upstream source')


def silence(path):
    with wave.open(str(path), 'rb') as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) == (1, 2, 8000, 400)
        assert wav.readframes(400) == bytes(800)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == '26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e'


def composition():
    actual = {p.name for p in (ROOT / 'Patches').glob('*.patch')}
    assert actual == {p.name for _, p in patches()}, 'Undeclared or missing patch'
    project = (ROOT / 'Socks5.xcodeproj/project.pbxproj').read_text()
    ids = re.findall(r'^\s*([A-F0-9]{24}) /\*.*?\*/ = \{', project, re.M)
    assert len(ids) == len(set(ids)), 'Duplicate Xcode object'
    for path in (ROOT / 'Socks5').rglob('*.swift'):
        data = path.read_bytes()
        assert data.isascii() and b'\t' not in data and b'\r' not in data, path
        assert path.name + ' in Sources' in project, path
        assert all(not line.endswith(b' ') for line in data.splitlines()), path
    for name, feature in [('Statistics', 'statistics'), ('Settings', 'settings'), ('BackgroundKeepAlive', 'background')]:
        assert (ROOT / 'Socks5' / name).exists() == (feature in FEATURES), name
    if 'background' in FEATURES:
        silence(ROOT / 'Socks5/BackgroundKeepAlive/Silence.wav')
        view = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift').read_text()
        for event in ('interruptionNotification', 'routeChangeNotification', 'mediaServicesWereLostNotification', 'mediaServicesWereResetNotification'):
            assert event in view
        source = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_text()
        assert 'scheduleAudioCheck(after: 2)' in source and 'scheduleAudioCheck(after: 1)' in source
        assert 'retryDelay' not in source and 'UserDefaults' not in source
    if 'settings' in FEATURES:
        content = (ROOT / 'Socks5/ContentView.swift').read_text()
        for field in ('workers', 'listenAddress', 'listenPort', 'udpListenAddress', 'udpListenPort',
                      'bindIPv4Address', 'bindIPv6Address', 'bindInterface', 'authUsername', 'authPassword', 'listenIPv6Only'):
            assert f'settings.binding(\\.server.{field})' in content, field
    if 'icon' in FEATURES:
        data = (ROOT / 'Socks5/Assets.xcassets/AppIcon.appiconset/AppIcon.png').read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n' and struct.unpack('>II', data[16:24]) == (1024, 1024)
        assert data[25] in (2, 3) and b'tRNS' not in data
    if CONFIG['name'] == 'integrated':
        root = (ROOT / 'Socks5/AppRoot.swift').read_text()
        assert re.findall(r'\.tag\(AppSettings.Tab\.(\w+)\)', root) == ['statistics', 'server', 'background', 'settings']
        members = json.loads((ROOT / 'docs/feature-membership.json').read_text())
        for name, expected in members['files'].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    print('PASS: declared patches, isolated modules, source format, wiring and assets')


def package(app):
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    if CONFIG['name'] != 'baseline':
        assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
        assert info.get('NSLocalNetworkUsageDescription')
    if 'background' in FEATURES:
        assert set(info['UIBackgroundModes']) == {'location', 'audio'}
        for key in ('NSLocationWhenInUseUsageDescription', 'NSLocationAlwaysAndWhenInUseUsageDescription'):
            assert info.get(key)
        silence(app / 'Silence.wav')
    else:
        assert not info.get('UIBackgroundModes')
    if 'icon' in FEATURES:
        assert info['CFBundleIcons']['CFBundlePrimaryIcon']['CFBundleIconName'] == 'AppIcon'
        assert (app / 'Assets.car').exists()
    print('PASS: final Info.plist, single scene, feature-specific resources and permissions')


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'baseline':
        baseline()
    elif command == 'apply':
        apply(Path(sys.argv[2]))
    elif command == 'format':
        formatting(Path(sys.argv[2]), sys.argv[3])
    elif command == 'reverse':
        reverse(Path(sys.argv[2]))
    elif command == 'composition':
        composition()
    elif command == 'package':
        package(Path(sys.argv[2]))
    else:
        raise SystemExit('Unknown audit command')
