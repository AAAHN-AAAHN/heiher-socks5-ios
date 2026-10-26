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
INPUT = '8577bb1f9b24593de011076aa3a6cafcebd50240'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def native_io_contract(root):
    """Bind the optional native observer once before root actions can start work."""
    registration = 'hev_socks5_server_icmp_set_io_observer'
    adapter = 'hev_socks5_server_record_socket_io'
    assert root.count(registration) == root.count(adapter) == 1, 'Native meter registration count'
    setup = re.search(r'private static let configureNativeIO: Void = \{(.*?)\n    \}\(\)', root, re.S)
    assert setup is not None, 'Native observer must have one process initialization'
    assert re.search(r'precondition\(\s*' + registration + r'\(\s*' + adapter +
                     r'\s*,\s*nil\s*\)\s*==\s*0\s*,', setup.group(1)), 'Native observer adapter or failure gate'
    assert re.search(r'\binit\(\)\s*\{\s*_ = Self\.configureNativeIO\s*\}', root), 'Native observer must precede root service actions'
    assert root.count('Self.configureNativeIO') == 1


def inherited_tree(ref, prefixes, members, *, workflows=False, exceptions=()):
    """Require every selected owner input, including its executable mode and index."""
    for record in git('ls-tree', '-rz', ref).split(b'\0'):
        if not record:
            continue
        meta, source = record.split(b'\t', 1)
        source = source.decode()
        if not source.startswith(prefixes) or source in exceptions:
            continue
        target = ('Build/inherited-workflows/traffic-statistics-' + Path(source).name
                  if workflows and source.startswith('.github/workflows/') else source)
        mode, kind, blob = meta.decode().split()
        path = ROOT / target
        assert kind == 'blob' and path.is_file() and not path.is_symlink(), target
        actual_mode = '100755' if path.stat().st_mode & 0o111 else '100644'
        assert actual_mode == mode and git('hash-object', str(path)).decode().strip() == blob, target
        assert git('ls-files', '--stage', '--', target).decode().split()[:3] == [mode, blob, '0'], target
        entry = members['sources'][target]
        assert entry['commit'] == ref and entry.get('path', target) == source, ('Owner membership', target)


def source_contract():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    config = json.loads((ROOT / 'Build/features.json').read_bytes())
    members = json.loads((ROOT / 'docs/feature-membership.json').read_bytes())
    refs = members['branches']
    assert config['name'] == 'integrated'
    assert config['features'] == ['udp', 'icmp', 'statistics', 'background', 'server', 'settings', 'icon']
    assert set(refs) == {'feature/app-icon', 'feature/background', 'feature/udp-compat',
                         'feature/icmp-relay', 'feature/server-control',
                         'feature/traffic-statistics', 'feature/settings-persistence'}
    documents = json.loads((ROOT / 'docs/documentation.json').read_bytes())
    assert refs == documents['parents']
    assert members['base_commit'] == config['base_commit'], 'Membership baseline differs'
    git('merge-base', '--is-ancestor', INPUT, 'HEAD')
    git('merge-base', '--is-ancestor', config['base_commit'], 'HEAD')
    load('integration_ownership', 'Build/check_ownership.py').source_contract()
    for path in members['sources']:
        owner = members['sources'][path]
        source = owner.get('path', path)
        entry = git('ls-tree', owner['commit'], '--', source).split()[0]
        mode = b'100755' if (ROOT / path).stat().st_mode & 0o111 else b'100644'
        assert entry == mode, ('executable mode', path)
    # Entry point and platform declarations retain their exact prior bytes.
    # The root now owns direct intent/load readiness, and the project adds only
    # the five Background-owned files to the existing app source phase.
    for path in ('Socks5/Socks5App.swift', 'Socks5/Info.plist'):
        assert (ROOT / path).read_bytes() == git('show', INPUT + ':' + path), path
    subprocess.run([sys.executable, 'Tests/Integration/intent_boundaries.py', '--source-only'], check=True)
    root = (ROOT / 'Socks5/AppRoot.swift').read_text()
    native_io_contract(root)
    production = '\n'.join(path.read_text() for path in (ROOT / 'Socks5').rglob('*.swift'))
    assert production.count('hev_socks5_server_icmp_set_io_observer') == 1
    assert production.count('hev_socks5_server_record_socket_io') == 1
    for name, kind in (('settings', 'SettingsStore'), ('server', 'ServerController'),
                       ('keepAlive', 'BackgroundKeepAlive'), ('ping', 'PeriodicPingModel')):
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
    icmp = json.loads(git('show', refs['feature/icmp-relay'] + ':Build/features.json'))
    udp = json.loads(git('show', refs['feature/udp-compat'] + ':Build/features.json'))
    assert icmp['features'] == ['udp', 'icmp']
    assert icmp['patches'][:len(udp['patches'])] == udp['patches']
    assert statistics['patches'][:len(udp['patches'])] == udp['patches']
    assert config['patches'] == icmp['patches'] + statistics['patches'][len(udp['patches']):] + server['patches']
    assert len(config['patches']) == 13
    assert len(config['patches']) == len({p['file'] for p in config['patches']})
    for ref in refs.values():
        owner = json.loads(git('show', ref + ':Build/features.json'))
        assert owner['sources'] == config['sources'] and owner['upstream_app'] == config['upstream_app']
        assert owner['base_commit'] == config['base_commit'], 'Owner baseline differs'
        git('merge-base', '--is-ancestor', config['base_commit'], ref)
    # Test inheritance and executable prerequisites use the same current parents;
    # runtime equivalence alone cannot excuse a missing parent verification input.
    stats_audit = git('show', refs['feature/traffic-statistics'] + ':Tests/Statistics/audit.py').decode()
    dependency = re.search(r"^UDP = '([0-9a-f]{40})'$", stats_audit, re.M).group(1)
    assert refs['feature/traffic-statistics'] == documents['parents']['feature/traffic-statistics']
    assert dependency == refs['feature/udp-compat'] == documents['parents']['feature/udp-compat']
    git('merge-base', '--is-ancestor', dependency, refs['feature/traffic-statistics'])
    git('merge-base', '--is-ancestor', dependency, refs['feature/udp-compat'])
    dependency_config = json.loads(git('show', dependency + ':Build/features.json'))
    assert udp == dependency_config, 'New UDP owner requires a new native composition'
    for item in udp['patches']:
        path = 'Patches/' + item['file']
        assert git('show', refs['feature/udp-compat'] + ':' + path) == git('show', dependency + ':' + path)
        assert (ROOT / path).read_bytes() == git('show', refs['feature/traffic-statistics'] + ':' + path)

    # Complete owner trees remain exact. Only the canonical server authentication
    # fixture has the separately verified UDP composition adaptation.
    inherited_tree(refs['feature/traffic-statistics'],
                   ('Socks5/Statistics/', 'Patches/hev-socket-meter-', 'Tests/', '.github/workflows/'),
                   members, workflows=True)
    for branch, prefixes in {
        'feature/app-icon': ('Socks5/Assets.xcassets/AppIcon.appiconset/', 'Tests/AppIcon/'),
        'feature/background': ('Socks5/BackgroundKeepAlive/', 'Tests/Background/'),
        'feature/icmp-relay': ('Patches/hev-icmp-', 'Tests/ICMP/'),
        'feature/server-control': ('Socks5/Server/', 'Socks5/ContentView.swift',
                                  'Tests/ServerControl/', 'Tests/server_lifecycle'),
        'feature/settings-persistence': ('Socks5/Settings/', 'Tests/Settings/'),
    }.items():
        inherited_tree(refs[branch], prefixes, members,
                       exceptions=('Tests/ServerControl/auth_startup_probe.c',))
    icmp_parent = json.loads(git('show', refs['feature/icmp-relay'] + ':docs/documentation.json'))
    background = json.loads(git('show', refs['feature/background'] + ':docs/documentation.json'))
    assert icmp_parent['parents'] == {'feature/udp-compat': refs['feature/udp-compat']}
    assert background['parents'] == {'feature/icmp-relay': refs['feature/icmp-relay']}
    git('merge-base', '--is-ancestor', refs['feature/icmp-relay'], refs['feature/background'])
    background_config = json.loads(git('show', refs['feature/background'] + ':Build/features.json'))
    assert background_config['features'] == icmp['features'] + ['background']
    assert background_config['patches'] == icmp['patches']

    parent = json.loads(git('show', refs['feature/settings-persistence'] + ':docs/feature-membership.json'))
    assert parent['branches']['feature/server-control'] == refs['feature/server-control']
    assert parent['base_commit'] == config['base_commit']
    git('merge-base', '--is-ancestor', refs['feature/server-control'], refs['feature/settings-persistence'])
    # Shared fixture boundary: early malformed-frame rejection may precede
    # client half-close. All no-forwarding/EOF assertions and timeouts remain exact.
    path = 'Tests/udp_buffer_network.py'
    assert (ROOT / path).read_bytes() == git('show', refs['feature/udp-compat'] + ':' + path)
    # Check the actual integrated resources, independent of icon-only source gates.
    icon = load('integration_icon', 'Tests/AppIcon/check_icon.py')
    print(json.dumps(icon.catalog(ROOT / icon.CATALOG), indent=2))
    # Reuse the exact shell-boundary regression with this composition's old entry.
    driver = load('integration_driver', 'Tests/ServerControl/audit_driver_check.py')
    for entry, markers in [('Build/build.sh', ['SUCCESS.txt', 'sdk-success.txt']),
                           ('Build/check_swift_sdk.sh', ['sdk-success.txt'])]:
        blob = git('rev-parse', '2dcfce074e288c942bd6582b3b77d4763c516a25:' + entry).decode().strip()
        driver.check(entry, markers, blob, 'integrated')
    print(f'PASS: {len(members["sources"])} exact owner files, {len(config["patches"])} ordered patches, one native observer, direct root intent, exact 17-source target and preserved platform/failure controls')


def main():
    subprocess.run([sys.executable, 'Build/check_documentation.py'], cwd=ROOT, check=True)
    source_contract()


if __name__ == '__main__':
    main()
