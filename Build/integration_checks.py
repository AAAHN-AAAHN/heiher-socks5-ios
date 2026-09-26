#!/usr/bin/env python3
"""Verify the integration boundary and reuse owner checks without rewriting owners.

Source composition is checked here; real combined native tests, SDK compilation,
packaging and Simulator execution remain separate gates with their own evidence.
"""
import importlib.util
import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INPUT = '2bc8e5a8bfbe6a7d2de74644bec9955513f8f8df'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    config = json.loads((ROOT / 'Build/features.json').read_bytes())
    members = json.loads((ROOT / 'docs/feature-membership.json').read_bytes())
    refs = members['branches']
    assert config['name'] == 'integrated'
    assert config['features'] == ['udp', 'statistics', 'background', 'server', 'settings', 'icon']
    assert len(refs) == 6
    assert members['base_commit'] == config['base_commit'], 'Membership baseline differs'
    git('merge-base', '--is-ancestor', INPUT, 'HEAD')
    git('merge-base', '--is-ancestor', config['base_commit'], 'HEAD')
    subprocess.run([sys.executable, 'Build/check_ownership.py'], check=True)
    for path in members['sources']:
        owner = members['sources'][path]
        source = owner.get('path', path)
        entry = git('ls-tree', owner['commit'], '--', source).split()[0]
        mode = b'100755' if (ROOT / path).stat().st_mode & 0o111 else b'100644'
        assert entry == mode, ('executable mode', path)
    # Preserve the former release's composition and platform declarations.
    for path in ('Socks5/AppRoot.swift', 'Socks5/Socks5App.swift', 'Socks5/Info.plist',
                 'Socks5.xcodeproj/project.pbxproj'):
        assert (ROOT / path).read_bytes() == git('show', INPUT + ':' + path), path
    root = (ROOT / 'Socks5/AppRoot.swift').read_text()
    for name, kind in (('settings', 'SettingsStore'), ('server', 'ServerController'), ('keepAlive', 'BackgroundKeepAlive')):
        assert root.count('@StateObject private var ' + name + ' = ' + kind + '()') == 1
    info = plistlib.loads((ROOT / 'Socks5/Info.plist').read_bytes())
    assert set(info['UIBackgroundModes']) == {'audio', 'location'}
    assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
    assert not any(k.startswith('BGTask') for k in info)
    project = (ROOT / 'Socks5.xcodeproj/project.pbxproj').read_text()
    assert 'CODE_SIGN_ENTITLEMENTS' not in project and 'Tests/' not in project
    assert set(re.findall(r'IPHONEOS_DEPLOYMENT_TARGET = ([^;]+)', project)) == {'17.2'}
    assert set(re.findall(r'PRODUCT_BUNDLE_IDENTIFIER = ([^;]+)', project)) == {'hev.Socks5'}
    statistics = json.loads(git('show', refs['feature/traffic-statistics'] + ':Build/features.json'))
    server = json.loads(git('show', refs['feature/server-control'] + ':Build/features.json'))
    assert config['patches'] == statistics['patches'] + server['patches']
    assert len(config['patches']) == len({p['file'] for p in config['patches']}) == 7
    for ref in refs.values():
        owner = json.loads(git('show', ref + ':Build/features.json'))
        assert owner['sources'] == config['sources'] and owner['upstream_app'] == config['upstream_app']
        assert owner['base_commit'] == config['base_commit'], 'Owner baseline differs'
        git('merge-base', '--is-ancestor', config['base_commit'], ref)
    assert refs['feature/udp-compat'].encode() in git('show', refs['feature/traffic-statistics'] + ':Tests/Statistics/audit.py')
    parent = json.loads(git('show', refs['feature/settings-persistence'] + ':docs/feature-membership.json'))
    assert parent['branches']['feature/server-control'] == refs['feature/server-control']
    assert parent['base_commit'] == config['base_commit']
    git('merge-base', '--is-ancestor', refs['feature/server-control'], refs['feature/settings-persistence'])
    git('merge-base', '--is-ancestor', refs['feature/udp-compat'], refs['feature/traffic-statistics'])
    # Check the actual integrated resources, independent of icon-only source gates.
    icon = load('integration_icon', 'Tests/AppIcon/check_icon.py')
    print(json.dumps(icon.catalog(ROOT / icon.CATALOG), indent=2))
    # Reuse the exact shell-boundary regression with this composition's old entry.
    driver = load('integration_driver', 'Tests/ServerControl/audit_driver_check.py')
    for entry, markers in [('Build/build.sh', ['SUCCESS.txt', 'sdk-success.txt']),
                           ('Build/check_swift_sdk.sh', ['sdk-success.txt'])]:
        blob = git('rev-parse', '2dcfce074e288c942bd6582b3b77d4763c516a25:' + entry).decode().strip()
        driver.check(entry, markers, blob, 'integrated')
    print(f'PASS: {len(members["sources"])} exact owner files, seven ordered patches, preserved root/platform and failure-marker controls')


if __name__ == '__main__':
    main()
