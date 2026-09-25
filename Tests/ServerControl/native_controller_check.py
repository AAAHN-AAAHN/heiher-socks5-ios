#!/usr/bin/env python3
"""Link the actual Swift controller to Hev and exercise real loopback authentication.

No sockets or engine functions are mocked. The command transport and clients are
CI-only. This is native-host execution, not an iPhone/SideStore/LiveContainer test.
"""
import json
import hashlib
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
BASE = '68599f96331f3f45e3fa271db02e6ede0fc35d73'


class Host:
    def __init__(self, executable, log):
        self.log = log
        self.buffer = b''
        self.sequence = 0
        self.process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=log)

    def request(self, operation, **values):
        self.sequence += 1
        request = dict(id=self.sequence, operation=operation, **values)
        self.process.stdin.write((json.dumps(request) + '\n').encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                self.log.write(line + b'\n'); self.log.flush()
                if line.startswith(b'SERVER_CONTROL_RESULT '):
                    result = json.loads(line.split(b' ', 1)[1])
                    if result['id'] != self.sequence:
                        raise RuntimeError('Out-of-order test command result')
                    return result
            if self.process.poll() is not None:
                raise RuntimeError('Native controller host exited: ' + str(self.process.returncode))
            if select.select([self.process.stdout], [], [], .05)[0]:
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError('Native controller stdout closed')
                self.buffer += chunk
        raise TimeoutError('Native controller command exceeded six seconds')

    def close(self):
        try:
            if self.process.poll() is None:
                self.request('exit')
                self.process.wait(timeout=6)
            if self.process.returncode != 0:
                raise RuntimeError('Native host failed: ' + str(self.process.returncode))
        finally:
            if self.process.poll() is None:
                self.process.kill(); self.process.wait(timeout=6)
            for stream in (self.process.stdin, self.process.stdout):
                stream.close()


def receive(sock, size):
    result = b''
    while len(result) < size:
        data = sock.recv(size - len(result))
        if not data:
            raise RuntimeError('SOCKS authentication reply truncated')
        result += data
    return result


def authenticate(port, username, password):
    user, secret = username.encode(), password.encode()
    with socket.create_connection(('127.0.0.1', port), timeout=.4) as sock:
        sock.sendall(b'\x05\x01\x02')
        if receive(sock, 2) != b'\x05\x02':
            raise RuntimeError('Native server did not select username/password authentication')
        sock.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(secret)]) + secret)
        reply = receive(sock, 2)
        if reply[0] != 1:
            raise RuntimeError('Invalid authentication version')
        return reply[1] == 0


def wait_auth(port, username, password):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if authenticate(port, username, password):
                return
        except (OSError, RuntimeError):
            pass
        time.sleep(.02)
    raise TimeoutError('Native authentication never accepted expected raw credential bytes')


def stop(host, value, port):
    host.request('apply', settings=value, running=False)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not host.request('state')['running']:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2):
                    raise RuntimeError('Controller stopped but its listen socket is still open')
            except ConnectionRefusedError:
                return
        time.sleep(.02)
    raise TimeoutError('Native controller did not complete Stop')


def compile_host(core, folder, old, log):
    include = folder / 'include'; include.mkdir()
    shutil.copyfile(core / 'src/hev-main.h', include / 'hev-main.h')
    (include / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
    model = folder / 'ServerSettings.swift'
    raw = (subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':Socks5/Server/ServerSettings.swift'])
           if old else (ROOT / 'Socks5/Server/ServerSettings.swift').read_bytes())
    model.write_bytes(raw)
    controller = folder / 'ServerController.swift'
    code = (ROOT / 'Socks5/Server/ServerController.swift').read_text()
    sources = [str(model), str(controller), str(Path(__file__).with_name('NativeControllerHost.swift'))]
    if sys.platform != 'darwin':
        code = code.replace('import SwiftUI\n', 'import Foundation\n', 1)
        ui = folder / 'UI.swift'
        ui.write_text('protocol ObservableObject {}\n@propertyWrapper struct Published<T> { var wrappedValue: T }\n')
        sources.append(str(ui))
    controller.write_text(code)
    libraries = [core / 'bin/libhev-socks5-server.a', core / 'third-part/yaml/bin/libyaml.a',
                 core / 'third-part/hev-task-system/bin/libhev-task-system.a']
    executable = folder / 'controller-host'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', '-I', str(include),
                    *sources, *map(str, libraries), '-Xlinker', '-lpthread', '-o', str(executable)],
                   stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    return executable


def worker_stop_check(core, output, folder):
    """Exercise the actual old/new worker helper with only yield scheduling replaced."""
    patched = (core / 'src/hev-socks5-worker.c').read_bytes()
    guard = (b'    /* A pending Stop can run before this task reaches its first wait. */\n'
             b'    if (!READ_ONCE (self->run))\n        return -1;\n\n')
    if patched.count(guard) != 1:
        raise AssertionError('Missing/duplicated worker Stop guard')
    original = patched.replace(guard, b'', 1)
    identity = hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest()
    if identity != '683a773999569784b2a42d1bab136ef1c44a8101':
        raise AssertionError('Worker changed beyond the reviewed four-line Stop guard')
    old = folder / 'upstream-worker'; old.mkdir()
    (old / 'hev-socks5-worker.c').write_bytes(original)
    libraries = [core / 'bin/libhev-socks5-server.a', core / 'third-part/yaml/bin/libyaml.a',
                 core / 'third-part/hev-task-system/bin/libhev-task-system.a']
    for name, source in [('original', old), ('current', core / 'src')]:
        executable = folder / ('worker-stop-' + name)
        with (output / ('worker-stop-' + name + '-build.log')).open('wb') as log:
            subprocess.run(['clang', '-std=gnu11', '-O2', '-Wall', '-Werror', '-pthread',
                            '-I' + str(source), '-I' + str(core / 'src'),
                            '-I' + str(core / 'src/misc'), '-I' + str(core / 'src/core/include'),
                            '-I' + str(core / 'third-part/hev-task-system/include'),
                            str(Path(__file__).with_name('worker_stop_probe.c')),
                            *map(str, libraries), '-o', str(executable)],
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        (output / ('worker-stop-' + name + '.log')).write_text(result.stdout + result.stderr)
        expected = 1 if name == 'original' else 0
        if result.returncode != expected or f'three worker-yield postconditions; {expected} failed' not in result.stdout:
            raise AssertionError('Worker Stop boundary did not match the old/new contract')
    print('PASS: exact upstream worker attempts a wait after Stop; corrected worker does not. Normal and resumed waits preserved.')


def main():
    core = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve(); output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory() as temp:
        worker_stop_check(core, output, Path(temp))
        for old in (True, False):
            label = 'original' if old else 'current'
            folder = Path(temp) / label; folder.mkdir()
            with (output / (label + '-build.log')).open('wb') as build_log:
                executable = compile_host(core, folder, old, build_log)
            for workers in (1, 4):
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
                options = dict(workers=str(workers), listenAddress='127.0.0.1', listenPort=str(port),
                               udpListenAddress='', udpListenPort='0', bindIPv4Address='0.0.0.0',
                               bindIPv6Address='::', bindInterface='', authUsername='user',
                               authPassword='\u00e9', listenIPv6Only=False)
                with (output / f'{label}-workers{workers}.log').open('wb') as log:
                    host = Host(executable, log)
                    try:
                        host.request('apply', settings=options, running=True)
                        wait_auth(port, options['authUsername'], options['authPassword'])
                        if authenticate(port, 'user', 'wrong'):
                            raise AssertionError('Wrong password accepted')
                        changed = dict(options, authPassword='e\u0301')
                        host.request('apply', settings=changed, running=True)
                        if old:
                            time.sleep(.15)
                            if authenticate(port, 'user', changed['authPassword']) or not authenticate(port, 'user', options['authPassword']):
                                raise AssertionError('Original equality no longer reproduces the missed credential update')
                            results.append(dict(model=label, workers=workers, observed='old password retained despite changed bytes'))
                            stop(host, changed, port)
                            host.request('apply', settings=changed, running=True)
                            wait_auth(port, 'user', changed['authPassword'])
                        else:
                            wait_auth(port, 'user', changed['authPassword'])
                            if authenticate(port, 'user', options['authPassword']):
                                raise AssertionError('Old password remained valid after replacement')
                            results.append(dict(model=label, workers=workers, observed='new password accepted; old bytes rejected'))
                            changed['authUsername'] = '\uac00'
                            host.request('apply', settings=changed, running=True)
                            wait_auth(port, changed['authUsername'], changed['authPassword'])
                            changed['authUsername'] = '\u1100\u1161'
                            host.request('apply', settings=changed, running=True)
                            wait_auth(port, changed['authUsername'], changed['authPassword'])
                            if authenticate(port, '\uac00', changed['authPassword']):
                                raise AssertionError('Old username remained valid after replacement')
                            results.append(dict(model=label, workers=workers, observed='decomposed Korean username applied byte-exactly'))
                            changed.update(authUsername='\uac00' * 85, authPassword='x' * 255)
                            host.request('apply', settings=changed, running=True)
                            wait_auth(port, changed['authUsername'], changed['authPassword'])
                            results.append(dict(model=label, workers=workers, observed='255-byte username and password authenticate'))
                        stop(host, changed, port)
                        host.request('apply', settings=changed, running=True)
                        wait_auth(port, changed['authUsername'], changed['authPassword'])
                        stop(host, changed, port)
                        results.append(dict(model=label, workers=workers, observed='Stop releases socket; same-port restart succeeds'))
                        if not old:
                            for _ in range(20):
                                host.request('apply', settings=changed, running=True)
                                wait_auth(port, changed['authUsername'], changed['authPassword'])
                                stop(host, changed, port)
                            results.append(dict(model=label, workers=workers, observed='20 active Stop/restart cycles complete with real authentication'))
                    finally:
                        # Preserve the first failing condition even when cleanup
                        # independently fails for an already-stuck native engine.
                        if sys.exc_info()[0] is None:
                            host.close()
                        else:
                            try:
                                host.close()
                            except Exception as error:
                                print('Additional native cleanup failure:', error, file=sys.stderr)
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
    print('PASS: actual Swift controller + native Hev. Original missed byte changes reproduced; corrected updates accepted.')
    print('SCOPE: host loopback and test command transport, not iOS UI/installation/background/VPN tests.')


if __name__ == '__main__':
    main()
