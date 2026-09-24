#!/usr/bin/env python3
"""Enforce one-way feature ownership and exact, pinned source composition."""
import hashlib
import json
from pathlib import Path
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
    expected = expected.replace('            current = desired\n',
        '            // The prior native call has returned before this new intent begins.\n'
        '            hev_socks5_server_prepare()\n            current = desired\n', 1)
    assert controller == expected, 'Unexpected server lifecycle change outside the idle prepare boundary'
    lifecycle_patch = (ROOT / 'Patches/hev-server-startup-stop.patch').read_bytes()
    original_patch = show(INPUT, 'Patches/hev-server-startup-stop.patch')
    assert lifecycle_patch.startswith(original_patch), 'Original pre-start cancellation fix changed'
    extra = lifecycle_patch[len(original_patch):]
    assert extra.startswith(b'diff --git a/src/hev-socks5-worker.c b/src/hev-socks5-worker.c\n')
    assert re.findall(rb'^diff --git a/(\S+) b/', extra, re.M) == [
        b'src/hev-socks5-worker.c', b'src/hev-socks5-proxy.c',
        b'src/hev-socks5-proxy.h', b'src/hev-main.c', b'src/hev-main.h']
    # The native probe also reconstructs the exact upstream worker blob and checks
    # that this adds only the pre-yield Stop guard before compiling both versions.
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
    for path, digest in manifest.get('files', {}).items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    own_doc = {'server-control': 'server-control', 'settings-persistence': 'settings-persistence', 'integrated': 'integrated'}[CONFIG['name']]
    assert (ROOT / 'README.md').read_bytes() == (ROOT / 'docs/features' / (own_doc + '.md')).read_bytes()
    print(f'PASS: server independent of storage; audited behavior preserved; {checked} exact owner files and pinned ancestors')


if __name__ == '__main__':
    main()
