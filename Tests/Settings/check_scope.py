#!/usr/bin/env python3
"""Check the Settings-owned delta and preserved main files; not device execution."""
import json
from pathlib import Path
import plistlib
import re
import subprocess

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
BASE = 'd2534cd6bce7389fdf8f362bd8f681c0bd583eb1'
INPUT = '9c2e76afcde7a20ff1bbdcf2a1f7e9092e1a98fd'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def data(path):
    return (ROOT / path).read_bytes()


def original(path):
    return git('show', BASE + ':' + path)


def main():
    git('merge-base', '--is-ancestor', BASE, 'HEAD')
    paths = git('ls-files').decode().splitlines()
    base_paths = git('ls-tree', '-r', '--name-only', BASE).decode().splitlines()
    mutable_main = {'.github/workflows/verify-build.yml', 'Build/features.json', 'README.md',
                    'Socks5/Socks5App.swift', 'Socks5/ContentView.swift', 'Socks5.xcodeproj/project.pbxproj'}
    allowed_new = {'Patches/hev-server-startup-stop.patch', 'Socks5/AppRoot.swift', 'Socks5/Info.plist',
                   'Socks5/Server/ServerController.swift', 'Socks5/Settings/AppSettings.swift',
                   'Socks5/Settings/SettingsStore.swift', 'Socks5/Settings/SettingsView.swift',
                   'Tests/server_lifecycle_host.c', 'Tests/server_lifecycle_regression.py',
                   'docs/features/settings-lifecycle.md'}
    assert set(base_paths) <= set(paths)
    for path in set(paths) - set(base_paths):
        assert path in allowed_new or path.startswith('Tests/Settings/'), path
    preserved = []
    for path in base_paths:
        if path not in mutable_main:
            assert data(path) == original(path), path
            preserved.append(path)
    assert data('Socks5/Socks5App.swift') == original('Socks5/Socks5App.swift').replace(b'ContentView()', b'AppRoot()', 1)
    for path in ('Socks5/AppRoot.swift', 'Socks5/ContentView.swift', 'Socks5/Settings/SettingsView.swift',
                 'Socks5/Server/ServerController.swift', 'Socks5/Info.plist', 'Socks5.xcodeproj/project.pbxproj',
                 'Patches/hev-server-startup-stop.patch', 'Tests/Settings/SettingsTests.swift',
                 'Tests/Settings/ServerTests.swift', 'Tests/Settings/ServerMocks.swift',
                 'Tests/server_lifecycle_host.c', 'Tests/server_lifecycle_regression.py'):
        assert data(path) == git('show', INPUT + ':' + path), 'Unrequested source/test edit: ' + path
    config = json.loads(data('Build/features.json'))
    baseline = json.loads(original('Build/features.json'))
    assert config['base_commit'] == BASE and config['features'] == ['settings']
    assert config['patches'] == [{'file': 'hev-server-startup-stop.patch', 'repository': '.'}]
    assert config['sources'] == baseline['sources'] and config['upstream_app'] == baseline['upstream_app']
    project = data('Socks5.xcodeproj/project.pbxproj').decode()
    old_project = original('Socks5.xcodeproj/project.pbxproj').decode()
    for key in ('IPHONEOS_DEPLOYMENT_TARGET', 'PRODUCT_BUNDLE_IDENTIFIER', 'SWIFT_VERSION',
                'CODE_SIGN_STYLE', 'TARGETED_DEVICE_FAMILY'):
        pattern = r'^\s*' + key + r' = (.*);$'
        assert re.findall(pattern, project, re.M) == re.findall(pattern, old_project, re.M), key
    assert 'CODE_SIGN_ENTITLEMENTS' not in project
    info = plistlib.loads(data('Socks5/Info.plist'))
    assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
    assert info['NSLocalNetworkUsageDescription']
    assert not info.get('UIBackgroundModes') and not any(k.startswith('BGTask') for k in info)
    root = data('Socks5/AppRoot.swift').decode()
    assert root.count('@StateObject private var settings = SettingsStore()') == 1
    assert root.count('@StateObject private var server = ServerController()') == 1
    assert '.onChange(of: settings.value, initial: true)' in root and 'server.apply(value)' in root
    assert 'settings.value.selectedTab == .settings ? .settings : .server' in root
    assert re.findall(r'\.tag\(AppSettings.Tab\.(\w+)\)', root) == ['server', 'settings']
    assert 'ScrollView { ContentView() }' in root
    content = data('Socks5/ContentView.swift').decode()
    model = data('Socks5/Settings/AppSettings.swift').decode()
    old_content = original('Socks5/ContentView.swift').decode()
    fields = [('workers', 'workersText'), ('listenAddress', 'listenAddrText'), ('listenPort', 'listenPortText'),
              ('udpListenAddress', 'udpListenAddrText'), ('udpListenPort', 'udpListenPortText'),
              ('bindIPv4Address', 'bindIpv4AddrText'), ('bindIPv6Address', 'bindIpv6AddrText'),
              ('bindInterface', 'bindIfaceText'), ('authUsername', 'authUserText'),
              ('authPassword', 'authPassText'), ('listenIPv6Only', 'listenIpv6OnlyToggle')]
    for field, old_field in fields:
        assert 'settings.binding(\\.server.' + field + ')' in content
        new_default = re.search(r'var ' + field + r' = ([^\n]+)', model).group(1)
        old_default = re.search(r'var ' + old_field + r': [^=]+ = ([^\n]+)', old_content).group(1)
        assert new_default == old_default, field
    assert 'settings.set(\\.serverRunning, false)' in content and 'server.apply(settings.value)' in content
    assert 'server.apply(settings.value, retry: true)' in content
    store = data('Socks5/Settings/SettingsStore.swift').decode()
    assert '.completeFileProtectionUntilFirstUserAuthentication' in store and '[.atomic]' in store
    assert 'read(upToCount: 65_537)' in store
    assert all(x in store for x in ('startAccessingSecurityScopedResource', 'stopAccessingSecurityScopedResource', 'NSFileCoordinator'))
    assert not any(x in store for x in ('Timer(', 'BGTaskScheduler', 'bundleIdentifier', 'containerURL(forSecurityApplicationGroupIdentifier'))
    assert data('README.md') == data('docs/features/settings-lifecycle.md')
    print(json.dumps({'base_main': BASE, 'input_settings': INPUT,
                      'tested_commit': git('rev-parse', 'HEAD').decode().strip(),
                      'preserved_main_files': preserved, 'reviewed_main_deltas': sorted(mutable_main),
                      'result': 'PASS', 'scope': 'Source/defaults/root/plist/migration/feature boundaries; not installed permissions or UI taps.'}, indent=2))


if __name__ == '__main__':
    main()
