#!/usr/bin/env python3
"""Launch the actual integrated app with saved tabs/intent on iOS 27 Simulator.

Uses the same patched native framework as the archive. Settings are preseeded by
this harness; no UI tap, actual file picker, audio interruption or installer is claimed.
"""
import json
from pathlib import Path
import plistlib
import socket
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/integrated/simulator'


def run(*args, timeout=120):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout.strip()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def receive(sock, count):
    result = b''
    while len(result) < count:
        chunk = sock.recv(count - len(result))
        if not chunk:
            raise RuntimeError('Unexpected end of SOCKS5 reply')
        result += chunk
    return result


def tcp_echo(proxy_port):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(10)
        destination = listener.getsockname()[1]
        errors = []
        def echo():
            try:
                client, _ = listener.accept()
                with client:
                    client.settimeout(10)
                    while True:
                        data = client.recv(4096)
                        if not data:
                            return
                        client.sendall(data)
            except Exception as error:
                errors.append(repr(error))
        thread = threading.Thread(target=echo, daemon=True)
        thread.start()
        with socket.create_connection(('127.0.0.1', proxy_port), timeout=5) as proxy:
            proxy.settimeout(5)
            proxy.sendall(b'\x05\x01\x00')
            assert receive(proxy, 2) == b'\x05\x00'
            proxy.sendall(b'\x05\x01\x00\x01\x7f\x00\x00\x01' + destination.to_bytes(2, 'big'))
            head = receive(proxy, 4)
            assert head[:3] == b'\x05\x00\x00'
            if head[3] == 1:
                receive(proxy, 6)
            elif head[3] == 4:
                receive(proxy, 18)
            elif head[3] == 3:
                receive(proxy, receive(proxy, 1)[0] + 2)
            else:
                raise RuntimeError('Unexpected SOCKS5 address type')
            payload = b'Integrated-iOS27-persisted-start-echo:' + bytes(range(256)) * 8
            proxy.sendall(payload)
            assert receive(proxy, len(payload)) == payload
        thread.join(12)
        assert not thread.is_alive() and not errors, errors


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'app-build.log').open('w') as log:
        subprocess.run(['xcodebuild', 'build', '-project', 'Socks5.xcodeproj', '-scheme', 'Socks5',
                        '-configuration', 'Release', '-sdk', 'iphonesimulator', '-arch', 'arm64',
                        'CONFIGURATION_BUILD_DIR=' + str(ROOT / '.build/integrated-simulator'),
                        'CODE_SIGNING_ALLOWED=NO', 'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES',
                        'MARKETING_VERSION=1.1.0', 'CURRENT_PROJECT_VERSION=6'],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
    app = ROOT / '.build/integrated-simulator/Socks5.app'
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    assert info['DTSDKName'].startswith('iphonesimulator27.')
    runtimes = json.loads(run('xcrun', 'simctl', 'list', 'runtimes', '-j'))['runtimes']
    runtime = next(r for r in runtimes if r['isAvailable'] and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
    types = json.loads(run('xcrun', 'simctl', 'list', 'devicetypes', '-j'))['devicetypes']
    device_type = next(t['identifier'] for t in types if t['name'] == 'iPhone 16')
    device = run('xcrun', 'simctl', 'create', 'Integrated Eight Branch Review', device_type, runtime['identifier'])
    (OUT / 'environment.json').write_text(json.dumps({'runtime': runtime, 'device_type': device_type,
        'scope': 'Production app on Simulator, preseeded JSON. No physical device, installer, UI tap or background-delivery claim.'}, indent=2))
    outcomes = []
    def record(result):
        outcomes.append(result)
        (OUT / 'results.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    try:
        run('xcrun', 'simctl', 'boot', device)
        (OUT / 'boot.log').write_text(run('xcrun', 'simctl', 'bootstatus', device, '-b', timeout=240))
        for suffix in ('', '.REMAPTEST'):
            bundle = 'hev.Socks5' + suffix
            label = 'original' if not suffix else 'remapped'
            info['CFBundleIdentifier'] = bundle
            (app / 'Info.plist').write_bytes(plistlib.dumps(info))
            run('codesign', '--force', '--sign', '-', app)
            run('xcrun', 'simctl', 'install', device, app)
            container = Path(run('xcrun', 'simctl', 'get_app_container', device, bundle, 'data'))
            settings_file = container / 'Library/Application Support/Socks5/settings.json'
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            port = free_port()
            settings = {'version': 1, 'serverRunning': False, 'background': {'continuousLocation': False, 'silentAudio': False},
                        'selectedTab': 'statistics', 'server': {
                            'workers': '4', 'listenAddress': '127.0.0.1', 'listenPort': str(port),
                            'udpListenAddress': '', 'udpListenPort': '0', 'bindIPv4Address': '0.0.0.0',
                            'bindIPv6Address': '::', 'bindInterface': '', 'authUsername': '',
                            'authPassword': '', 'listenIPv6Only': False}}
            def seed():
                settings_file.write_text(json.dumps(settings))
            def launch():
                value = run('xcrun', 'simctl', 'launch', device, bundle)
                time.sleep(2)
                listing = run('xcrun', 'simctl', 'spawn', device, 'launchctl', 'list')
                assert any(bundle in line and line.split()[0].isdigit() for line in listing.splitlines()), value
                return value
            tabs = ('statistics', 'server', 'background', 'settings') if not suffix else ('settings',)
            for tab in tabs:
                settings['selectedTab'] = tab; seed(); launch()
                assert json.loads(settings_file.read_text()) == settings
                run('xcrun', 'simctl', 'io', device, 'screenshot', OUT / f'{label}-{tab}.png')
                run('xcrun', 'simctl', 'terminate', device, bundle)
                record({'identity': label, 'case': 'saved-tab-' + tab, 'passed': True})
            settings['selectedTab'] = 'server'; settings['serverRunning'] = True; seed()
            for iteration in range(2 if not suffix else 1):
                launch()
                deadline = time.monotonic() + 15
                while True:
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.5):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('Saved Start did not produce a listening socket')
                        time.sleep(.2)
                tcp_echo(port)
                assert json.loads(settings_file.read_text()) == settings
                run('xcrun', 'simctl', 'terminate', device, bundle)
                time.sleep(.3)
                record({'identity': label, 'case': f'saved-start-and-tcp-{iteration}', 'passed': True})
            settings['serverRunning'] = False; seed(); launch()
            stopped = False
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=1):
                    pass
            except OSError:
                stopped = True
            assert stopped, 'Saved Stop unexpectedly opened a server socket'
            assert json.loads(settings_file.read_text()) == settings
            run('xcrun', 'simctl', 'terminate', device, bundle)
            record({'identity': label, 'case': 'saved-stop', 'passed': True})
            run('xcrun', 'simctl', 'uninstall', device, bundle)
        (OUT / 'SUCCESS.txt').write_text('PASS: saved tabs, Start/relaunch/TCP and Stop in original/remapped Simulator installs. Not a physical SideStore/LiveContainer or background audio test.\n')
    finally:
        for action in ('shutdown', 'delete'):
            try:
                subprocess.run(['xcrun', 'simctl', action, device], capture_output=True, timeout=30)
            except subprocess.TimeoutExpired:
                print('Simulator cleanup timeout:', action)


if __name__ == '__main__':
    main()
