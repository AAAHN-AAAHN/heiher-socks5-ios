#!/usr/bin/env python3
"""Enforce one-way feature ownership and exact, pinned source composition."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess

if not __debug__:
    raise SystemExit('Assertions must be enabled')
ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'Build/features.json').read_bytes())
FEATURES = set(CONFIG['features'])
INPUT = '16689f780f3e0e0c9344397273528697f197c9e5'


def show(ref, path):
    return subprocess.check_output(['git', '-C', str(ROOT), 'show', ref + ':' + path])


def content(path):
    return (ROOT / path).read_text()


def main():
    assert 'server' in FEATURES
    assert 'settings' not in FEATURES or 'server' in FEATURES
    base = CONFIG['base_commit']
    subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', base, 'HEAD'], check=True)
    model = content('Socks5/Server/ServerSettings.swift')
    controller = content('Socks5/Server/ServerController.swift')
    editor = content('Socks5/ContentView.swift')
    for forbidden in ('AppSettings', 'SettingsStore', 'UserDefaults', 'FileManager', 'BGTaskScheduler'):
        assert forbidden not in model + controller + editor, forbidden
    original = show(INPUT, 'Socks5/Settings/AppSettings.swift').decode()
    before = original[original.index('struct ServerSettings:'):original.index('\nenum SettingsError:')]
    after = model[model.index('struct ServerSettings:'):model.index('\nenum ServerConfigurationError:')]
    assert after.replace('ServerConfigurationError', 'SettingsError') == before
    original_controller = show(INPUT, 'Socks5/Server/ServerController.swift').decode()
    expected = original_controller.replace('func apply(_ settings: AppSettings, retry: Bool = false)',
        'func apply(_ settings: ServerSettings, running: Bool, retry: Bool = false)').replace(
        'desired = settings.serverRunning ? settings.server : nil', 'desired = running ? settings : nil')
    assert controller == expected, 'Server execution algorithm changed during extraction'
    assert (ROOT / 'Patches/hev-server-startup-stop.patch').read_bytes() == show(INPUT, 'Patches/hev-server-startup-stop.patch')
    root = content('Socks5/AppRoot.swift')
    assert root.count('@StateObject private var server = ServerController()') == 1
    if 'settings' in FEATURES:
        assert (ROOT / 'Socks5/Settings/SettingsStore.swift').read_bytes() == show(INPUT, 'Socks5/Settings/SettingsStore.swift')
        assert (ROOT / 'Socks5/Settings/SettingsView.swift').read_bytes() == show(INPUT, 'Socks5/Settings/SettingsView.swift')
        model_without_server = original[:original.index('struct ServerSettings:')] + original[original.index('enum SettingsError:'):]
        assert content('Socks5/Settings/AppSettings.swift') == model_without_server
        assert 'server.apply(value.server, running: value.serverRunning)' in root
        assert 'settings.binding(\\.server)' in root
    else:
        assert not (ROOT / 'Socks5/Settings').exists()
        assert 'requestedRunning = false' in root and '@State private var configuration = ServerSettings()' in root
    if 'background' in FEATURES:
        assert root.count('.modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))') == 1
        assert 'keepAlive.setAudio(value.background.silentAudio)' in root
        assert 'keepAlive.setLocation(value.background.continuousLocation)' in root
    # Complement owner hashes with the duplicate review's deployment/permission
    # contracts. These are source declarations, not granted device permissions.
    info = plistlib.loads((ROOT / 'Socks5/Info.plist').read_bytes())
    assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
    assert not any(key.startswith('BGTask') for key in info)
    assert set(info.get('UIBackgroundModes', [])) == ({'audio', 'location'} if 'background' in FEATURES else set())
    project = content('Socks5.xcodeproj/project.pbxproj')
    for key in ('IPHONEOS_DEPLOYMENT_TARGET', 'PRODUCT_BUNDLE_IDENTIFIER', 'CODE_SIGN_STYLE'):
        pattern = r'^\s*' + key + r' = (.*);$'
        assert re.findall(pattern, project, re.M) == re.findall(pattern, show(base, 'Socks5.xcodeproj/project.pbxproj').decode(), re.M), key
    assert 'CODE_SIGN_ENTITLEMENTS' not in project
    for path in ('Tests/server_lifecycle_host.c', 'Tests/server_lifecycle_regression.py'):
        assert (ROOT / path).read_bytes() == show(INPUT, path), path
    manifest = json.loads((ROOT / 'docs/feature-membership.json').read_bytes())
    checked = 0
    for ref in manifest.get('branches', {}).values():
        subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', ref, 'HEAD'], check=True)
    for path, entry in manifest.get('sources', {}).items():
        actual = (ROOT / path).read_bytes()
        expected = show(entry['commit'], entry.get('path', path))
        assert actual == expected, path
        assert hashlib.sha256(actual).hexdigest() == entry['sha256'], path
        checked += 1
    own_doc = {'server-control': 'server-control', 'settings-persistence': 'settings-persistence', 'integrated': 'integrated'}[CONFIG['name']]
    assert (ROOT / 'README.md').read_bytes() == (ROOT / 'docs/features' / (own_doc + '.md')).read_bytes()
    print(f'PASS: server independent of storage; audited behavior preserved; {checked} exact owner files and pinned ancestors')


if __name__ == '__main__':
    main()
