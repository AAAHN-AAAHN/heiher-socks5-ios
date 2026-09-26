#!/usr/bin/env python3
"""Audit the Background delta without re-auditing or modifying the main engine.

This checks source/configuration contracts, not an installed app or OS permission.
Run against a complete Git checkout; source archives do not prove ancestry.
"""
import ast
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / 'Build/features.json').read_bytes())
BASE = CONFIG['base_commit']
assert BASE == '75335d201cb1e541bb153e9899badbc11ccf1973'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def data(path):
    return (ROOT / path).read_bytes()


def text(path):
    return data(path).decode('utf-8')


def original(path):
    return git('show', BASE + ':' + path)


def fields(project, name):
    return re.findall(r'^\s*' + re.escape(name) + r' = (.*);$', project, re.M)


def main():
    git('merge-base', '--is-ancestor', BASE, 'HEAD')
    base_paths = git('ls-tree', '-r', '--name-only', BASE).decode().splitlines()
    current_paths = git('ls-files').decode().splitlines()
    allowed = {'.github/workflows/verify-build.yml', 'Build/check.py',
               'Build/features.json', 'README.md', 'Socks5/Socks5App.swift',
               'Socks5.xcodeproj/project.pbxproj'}
    additions = {'Socks5/AppRoot.swift', 'Socks5/Info.plist',
                 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift',
                 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift',
                 'Socks5/BackgroundKeepAlive/Silence.wav', 'docs/features/background.md',
                 'docs/history/background-before-async-20260925.md',
                 'docs/history/background-before-final-audit-20260926.md'}
    assert set(base_paths) <= set(current_paths), 'A main file was removed'
    for path in set(current_paths) - set(base_paths):
        assert path in additions or path.startswith('Tests/Background/'), path
    preserved = []
    for path in base_paths:
        if path not in allowed:
            assert data(path) == original(path), 'Main implementation changed: ' + path
            preserved.append(path)
    assert data('Socks5/Socks5App.swift') == original('Socks5/Socks5App.swift').replace(
        b'ContentView()', b'AppRoot()', 1), 'Unexpected app entry-point change'
    baseline_config = json.loads(original('Build/features.json'))
    assert CONFIG['features'] == ['background'] and CONFIG['patches'] == []
    for key in ('sources', 'upstream_app'):
        assert CONFIG[key] == baseline_config[key]
    # Feature validation may evolve; native patch/format/reverse/package logic may not.
    old_checks = ast.parse(original('Build/check.py'))
    new_checks = ast.parse(data('Build/check.py'))
    old_functions = {n.name: n for n in old_checks.body if isinstance(n, ast.FunctionDef)}
    new_functions = {n.name: n for n in new_checks.body if isinstance(n, ast.FunctionDef)}
    for name, function in old_functions.items():
        if name not in {'baseline', 'composition'}:
            assert ast.dump(function) == ast.dump(new_functions[name]), name
    project = text('Socks5.xcodeproj/project.pbxproj')
    old_project = original('Socks5.xcodeproj/project.pbxproj').decode()
    for key in ('IPHONEOS_DEPLOYMENT_TARGET', 'PRODUCT_BUNDLE_IDENTIFIER',
                'SWIFT_VERSION', 'TARGETED_DEVICE_FAMILY', 'CODE_SIGN_STYLE'):
        assert fields(project, key) == fields(old_project, key), key
    assert fields(project, 'INFOPLIST_FILE') == ['Socks5/Info.plist'] * 2
    assert fields(project, 'INFOPLIST_KEY_UIApplicationSceneManifest_Generation') == ['NO'] * 2
    assert not fields(project, 'CODE_SIGN_ENTITLEMENTS')
    info = plistlib.loads(data('Socks5/Info.plist'))
    assert set(info['UIBackgroundModes']) == {'audio', 'location'}
    assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
    for key in ('NSLocationWhenInUseUsageDescription',
                'NSLocationAlwaysAndWhenInUseUsageDescription', 'NSLocalNetworkUsageDescription'):
        assert isinstance(info[key], str) and info[key].strip(), key
    assert not any(key.startswith('BGTask') for key in info)
    assert not list((ROOT / 'Socks5').rglob('*.entitlements'))
    root = text('Socks5/AppRoot.swift')
    assert re.findall(r'@AppStorage\("([^"]+)"\)', root) == [
        'background.continuousLocation', 'background.silentAudio']
    assert root.count('@StateObject private var keepAlive = BackgroundKeepAlive()') == 1
    assert root.count('.modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))') == 1
    assert 'ScrollView { ContentView() }' in root
    for name in ('location', 'audio'):
        assert '.onChange(of: ' + name + 'Enabled, initial: true)' in root
        assert 'keepAlive.set' + name.title() + '(value)' in root
        assert name + 'Enabled: $' + name + 'Enabled' in root
    controller = text('Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift')
    assert all(token not in controller for token in ('UserDefaults', 'AppStorage', 'HevSocks5Server',
                                                    'BGTaskScheduler', 'MPRemoteCommandCenter'))
    assert controller.count('Timer(timeInterval:') == 1
    assert 'scheduleAudioCheck(after: 2)' not in controller
    view = text('Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift')
    assert view.index('Text("Audio")') < view.index('Text("Location")')
    assert 'BackgroundKeepAlive.audioNotifications.map' in view
    assert data('README.md') == data('docs/features/background.md')
    assert hashlib.sha256(data('Socks5/BackgroundKeepAlive/Silence.wav')).hexdigest() == (
        '26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e')
    print(json.dumps({
        'base_main': BASE, 'tested_commit': git('rev-parse', 'HEAD').decode().strip(),
        'main_files_byte_preserved': preserved,
        'main_modified_paths_reviewed': sorted(allowed),
        'background_additions': sorted(set(current_paths) - set(base_paths)),
        'result': 'PASS: main boundary, source pins, entry/root/settings, project, plist, assets and README',
        'scope': 'Source contracts only; no IPA, installed signing, LiveContainer runtime, or device permissions.'
    }, indent=2))


if __name__ == '__main__':
    main()
