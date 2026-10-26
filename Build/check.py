#!/usr/bin/env python3
"""Exact patch application, feature boundaries and packaged-resource checks."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import sys
import wave
import zipfile

if not __debug__:
    raise SystemExit('Assertions must be enabled')

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'Build/features.json').read_text())
FEATURES = set(CONFIG['features'])


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def baseline():
    from native_sources import validate
    lock = json.loads((ROOT / 'Build/upstream.json').read_text())
    validate(lock)
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
        for path in ('Build/upstream.json', 'Build/baseline-framework.json', 'HevSocks5Server.xcframework'):
            assert git(ROOT, 'rev-parse', 'HEAD:' + path) == git(ROOT, 'rev-parse', base + ':' + path), path
    subprocess.run([sys.executable, str(ROOT / 'Build/check_documentation.py')], check=True)
    print('PASS: shared source pins, baseline framework, app identity and main ancestry')


def patches():
    for item in CONFIG['patches']:
        yield item['repository'], ROOT / 'Patches' / item['file']


def tracked(repo, ref):
    for record in git(repo, 'ls-tree', '-rz', ref).split(b'\0'):
        if record:
            meta, name = record.split(b'\t', 1)
            yield (*meta.decode().split(), os.fsdecode(name))


def clean_tracked(repo, sha):
    assert git(repo, 'rev-parse', 'HEAD').decode().strip() == sha, 'Source HEAD changed: ' + str(repo)
    git(repo, 'diff', '--cached', '--no-ext-diff', '--no-textconv',
        '--ignore-submodules=none', '--exit-code', sha, '--')
    # Compare raw files, not Git's configurable/possibly masked working-tree diff.
    for mode, kind, blob, name in tracked(repo, sha):
        if kind != 'blob':
            continue  # Native submodule HEADs are checked through CONFIG['sources'].
        path = repo / name
        if path.is_symlink():
            data, actual_mode = os.fsencode(os.readlink(path)), '120000'
        else:
            assert path.is_file(), 'Missing source input: ' + str(path)
            data = path.read_bytes()
            actual_mode = '100755' if path.stat().st_mode & 0o100 else '100644'
        digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert (actual_mode, digest) == (mode, blob), 'Changed source input: ' + str(path)


def clean_native(core, sources=None):
    for relative, sha in (CONFIG['sources'] if sources is None else sources).items():
        repo = core / relative
        clean_tracked(repo, sha)
        # Only known generated output roots are exempt, never ignored sources or Makefiles.
        outputs = (b'bin/', b'build/', b'HevSocks5Server.xcframework/',
                   b'HevSocks5Tunnel.xcframework/', b'HevTaskSystem.xcframework/')
        assert all(not name or name.startswith(outputs) for name in
                   git(repo, 'ls-files', '--others', '-z').split(b'\0')), 'Untracked native input: ' + relative


def archive(path, ref):
    entries = list(tracked(ROOT, ref))
    assert all(kind == 'blob' for _, kind, _, _ in entries), 'Unarchived source submodule'
    expected = {name: (mode, blob) for mode, _, blob, name in entries}
    directories = {str(parent) + '/' for name in expected for parent in Path(name).parents
                   if str(parent) != '.'}
    with zipfile.ZipFile(path) as source:
        names = source.namelist()
        assert len(names) == len(set(names)), 'Duplicate source archive entry'
        assert {n for n in names if not n.endswith('/')} == set(expected), 'Source archive inventory differs'
        assert all(n in directories and not source.read(n) for n in names if n.endswith('/')), 'Unexpected source archive directory'
        for name, (mode, blob) in expected.items():
            info = source.getinfo(name)
            # Git ZIP stores ordinary non-executable files with DOS metadata.
            permissions = info.external_attr >> 16
            actual_mode = ('120000' if permissions & 0o170000 == 0o120000 else
                           '100755' if permissions & 0o100 else '100644')
            assert permissions & 0o170000 in (0, 0o100000, 0o120000), 'Invalid source archive type'
            data = source.read(info)  # Also checks the entry's CRC.
            digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            assert (actual_mode, digest) == (mode, blob), 'Source archive differs: ' + name
    print('PASS: source archive inventory, Git modes and raw bytes')


def apply_patch(repo, patch, reverse=False):
    if CONFIG['name'] == 'integrated' and patch.name == 'hev-server-startup-stop.patch':
        from server_patch import apply as apply_server_patch
        apply_server_patch(repo, patch, reverse=reverse)
        return
    options = ['-R'] if reverse else ['--whitespace=error-all']
    git(repo, 'apply', *options, '--check', str(patch))
    git(repo, 'apply', *options, str(patch))


def apply(core):
    clean_native(core)
    for relative, patch in patches():
        apply_patch(core / relative, patch)
        print(hashlib.sha256(patch.read_bytes()).hexdigest(), patch.name)


def formatting(core, formatter):
    for relative in CONFIG['sources']:
        repo = core / relative
        changed = git(repo, 'diff', '--name-only', '--', '*.c', '*.h').decode().splitlines()
        added = git(repo, 'ls-files', '--others', '--exclude-standard', '--', '*.c', '*.h').decode().splitlines()
        for name in sorted(set(changed + added)):
            path = repo / name
            formatted = subprocess.check_output([formatter, str(path)])
            assert formatted == path.read_bytes(), f'Upstream formatting: {relative}/{name}'
            print('FORMAT PASS:', relative, name)


def reverse(core):
    for relative, sha in CONFIG['sources'].items():
        assert git(core / relative, 'rev-parse', 'HEAD').decode().strip() == sha, 'Native HEAD changed: ' + relative
    for relative, patch in reversed(list(patches())):
        apply_patch(core / relative, patch, reverse=True)
    clean_native(core)
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
    for name, feature in [('Statistics', 'statistics'), ('Settings', 'settings'), ('Server', 'server'), ('BackgroundKeepAlive', 'background')]:
        assert (ROOT / 'Socks5' / name).exists() == (feature in FEATURES), name
    if 'background' in FEATURES:
        silence(ROOT / 'Socks5/BackgroundKeepAlive/Silence.wav')
        view = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift').read_text()
        source = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift').read_text()
        for event in ('interruptionNotification', 'routeChangeNotification',
                      'mediaServicesWereLostNotification', 'mediaServicesWereResetNotification',
                      'didBecomeInactiveNotification', 'resumptionRecommendationNotification',
                      'didBecomeActiveNotification', 'silenceSecondaryAudioHintNotification',
                      'spatialPlaybackCapabilitiesChangedNotification', 'renderingModeChangeNotification',
                      'renderingCapabilitiesChangeNotification', 'outputMuteStateChangeNotification',
                      'userIntentToUnmuteOutputNotification'):
            assert event in source, event
        service = (ROOT / 'Socks5/BackgroundKeepAlive/LoopAudioService.swift').read_text()
        assert 'service.observeAudioNotifications(BackgroundKeepAlive.audioNotifications,' in service
        assert 'normalize: { BackgroundKeepAlive.audioEventValue($0) })' in service
        assert 'BackgroundKeepAlive.audioNotifications' not in view
        assert 'var interval = 0.5' in service
        assert service.count('DispatchSource.makeTimerSource(') == 1
        assert service.count('DispatchSource.makeTimerSource(flags: recovery ? .strict : [], queue: control)') == 1
        assert 'precondition(outstanding == 1)' in service
        assert 'if next.stop != current.stop { releaseBarrier = true }' in service
        assert 'Timer(timeInterval:' not in source + service
        assert 'AVAudioPlayer' not in source and 'retryDelay' not in source
        assert 'UserDefaults' not in source + service
        assert 'private let audio: LoopAudioService' in source
    if 'server' in FEATURES:
        content = (ROOT / 'Socks5/ContentView.swift').read_text()
        for field in ('workers', 'listenAddress', 'listenPort', 'udpListenAddress', 'udpListenPort',
                      'bindIPv4Address', 'bindIPv6Address', 'bindInterface', 'authUsername', 'authPassword', 'listenIPv6Only'):
            assert f'$configuration.{field}' in content, field
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
        subprocess.run([sys.executable, str(ROOT / 'Tests/Integration/intent_boundaries.py'), '--source-only'], check=True)
    subprocess.run([sys.executable, str(ROOT / 'Build/check_ownership.py')], check=True)
    print('PASS: declared patches, isolated modules, source format, wiring and assets')


def package(app):
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    assert info['CFBundleShortVersionString'] == '3.0.0' and info['CFBundleVersion'] == '1', 'Unexpected package version'
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
    print('PASS: final Info.plist and applicable feature-specific resources and permissions')


if __name__ == '__main__':
    command = sys.argv[1]
    if command == 'worktree':
        clean_tracked(ROOT, sys.argv[2])
        print('PASS: fixed application HEAD, index, raw bytes and Git modes')
    elif command == 'archive':
        archive(Path(sys.argv[2]), sys.argv[3])
    elif command == 'baseline':
        baseline()
    elif command == 'native':
        from native_sources import sources, validate, verify
        lock = validate(json.loads((ROOT / 'Build/upstream.json').read_text()))
        component, destination = sys.argv[2], Path(sys.argv[3])
        verify(lock, component, destination)
        clean_native(destination, sources(lock, component))
        print('PASS: recorded upstream gitlinks and complete effective native inputs')
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
