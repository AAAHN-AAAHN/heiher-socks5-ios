#!/usr/bin/env python3
"""Verify single ownership, mechanical extraction and immutable source dependencies."""
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[1]
MAIN = 'd2534cd6bce7389fdf8f362bd8f681c0bd583eb1'
OLD = '16689f780f3e0e0c9344397273528697f197c9e5'
CONFIG = json.loads((ROOT / 'Build/features.json').read_bytes())
FEATURES = set(CONFIG['features'])


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def data(path):
    return (ROOT / path).read_bytes()


def old(path):
    return git('show', OLD + ':' + path)


def main():
    git('merge-base', '--is-ancestor', MAIN, 'HEAD')
    assert CONFIG['base_commit'] == MAIN
    model = old('Socks5/Settings/AppSettings.swift').decode()
    expected_server = 'import Foundation\n\n' + model[model.index('struct ServerSettings:'):].replace('SettingsError', 'ServerConfigurationError')
    assert data('Socks5/Server/ServerSettings.swift').decode() == expected_server
    expected_runtime = old('Socks5/Server/ServerController.swift').decode().replace(
        'func apply(_ settings: AppSettings, retry: Bool = false)',
        'func apply(_ configuration: ServerSettings, running: Bool, retry: Bool = false)').replace(
        'desired = settings.serverRunning ? settings.server : nil', 'desired = running ? configuration : nil')
    assert data('Socks5/Server/ServerController.swift').decode() == expected_runtime
    for path in ('Patches/hev-server-startup-stop.patch', 'Tests/server_lifecycle_host.c', 'Tests/server_lifecycle_regression.py'):
        assert data(path) == old(path), path
    runtime = data('Socks5/Server/ServerController.swift').decode()
    form = data('Socks5/ContentView.swift').decode()
    for text in (runtime, form):
        assert all(name not in text for name in ('AppSettings', 'SettingsStore', 'AppStorage', 'UserDefaults', 'JSONEncoder'))
    for field in ('workers', 'listenAddress', 'listenPort', 'udpListenAddress', 'udpListenPort',
                  'bindIPv4Address', 'bindIPv6Address', 'bindInterface', 'authUsername', 'authPassword', 'listenIPv6Only'):
        assert '$configuration.' + field in form, field
    assert 'server.apply(configuration, running: true, retry: true)' in form
    assert 'server.apply(configuration, running: false)' in form
    if 'config-persistence' in FEATURES:
        expected_app = model[:model.index('struct ServerSettings:')] + model[model.index('enum SettingsError:'):]
        assert data('Socks5/Settings/AppSettings.swift').decode() == expected_app
        for path in ('Socks5/Settings/SettingsStore.swift', 'Socks5/Settings/SettingsView.swift'):
            assert data(path) == old(path), path
        assert 'SettingsStore()' in data('Socks5/AppRoot.swift').decode()
    else:
        assert not (ROOT / 'Socks5/Settings').exists()
        assert CONFIG['features'] == ['server-runtime']
        assert '@State private var running = false' in data('Socks5/AppRoot.swift').decode()
    # Named dependencies must be real ancestors, not merely mentioned in a README.
    members_path = ROOT / 'docs/feature-membership.json'
    owners_checked = {}
    if members_path.exists():
        members = json.loads(members_path.read_bytes())
        for name, sha in members['branches'].items():
            git('merge-base', '--is-ancestor', sha, 'HEAD')
        for path, owner in members['owners'].items():
            sha = members['branches'][owner]
            assert data(path) == git('show', sha + ':' + path), path
            assert hashlib.sha256(data(path)).hexdigest() == members['files'][path], path
            owners_checked[path] = owner
    if CONFIG['name'] != 'integrated':
        spec = 'docs/features/' + CONFIG['name'] + '.md'
        assert data('README.md') == data(spec)
    info = plistlib.loads(data('Socks5/Info.plist'))
    assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
    assert not any(k.startswith('BGTask') for k in info)
    assert set(info.get('UIBackgroundModes', [])) == ({'audio', 'location'} if 'background' in FEATURES else set())
    project = data('Socks5.xcodeproj/project.pbxproj').decode()
    assert re.findall(r'IPHONEOS_DEPLOYMENT_TARGET = (.*);', project) == ['17.2', '17.2']
    assert re.findall(r'PRODUCT_BUNDLE_IDENTIFIER = (.*);', project) == ['hev.Socks5', 'hev.Socks5']
    assert 'CODE_SIGN_ENTITLEMENTS' not in project
    assert data('Build/upstream.json') == git('show', MAIN + ':Build/upstream.json')
    assert data('Build/baseline-framework.json') == git('show', MAIN + ':Build/baseline-framework.json')
    if CONFIG['name'] == 'integrated':
        root = data('Socks5/AppRoot.swift').decode()
        assert re.findall(r'\.tag\(AppSettings.Tab\.(\w+)\)', root) == ['statistics', 'server', 'background', 'settings']
        assert 'server.apply(value.server, running: value.serverRunning)' in root
        assert root.count('BackgroundKeepAlive()') == 1 and root.count('SettingsStore()') == 1
    print(json.dumps({'result': 'PASS', 'main': MAIN, 'extracted_from': OLD,
                      'configuration': CONFIG['name'], 'owner_files': owners_checked,
                      'scope': 'Source identity, extraction, defaults and wiring, not device execution.'}, indent=2))


if __name__ == '__main__':
    main()
