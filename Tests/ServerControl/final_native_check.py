#!/usr/bin/env python3
"""Additional final-review controls with the unchanged Swift controller and Hev.

Allocation-failure probes supplement real bind failure, retry suppression,
quoted UTF-8 authentication, listener release and current-owner lifetime are used.
"""
import json
import os
import subprocess
from pathlib import Path
import socket
import sys
import tempfile
import time

from native_controller_check import Host, authenticate, compile_host, receive, stop, wait_auth


def settled(host, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = host.request('state')
        if predicate(state):
            return state
        time.sleep(.01)
    raise AssertionError('Controller state did not settle')


def refused(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.2):
            return False
    except ConnectionRefusedError:
        return True


def authentication_startup(core, output, folder):
    """Exercise real initialization/cleanup with only allocation outcomes injected."""
    libraries = [core / 'bin/libhev-socks5-server.a', core / 'third-part/yaml/bin/libyaml.a',
                 core / 'third-part/hev-task-system/bin/libhev-task-system.a']
    includes = [core / 'src', core / 'src/misc', core / 'src/core/include',
                core / 'third-part/hev-task-system/include']
    for label, flags in [('sanitized', ['-O1', '-g', '-fsanitize=address,undefined',
                                       '-fno-sanitize-recover=all']), ('optimized', ['-O3'])]:
        executable = folder / ('auth-startup-' + label)
        with (output / (label + '-auth-build.log')).open('wb') as log:
            subprocess.run(['clang', '-std=gnu11', '-Wall', '-Werror', '-pthread', *flags,
                            *['-I' + str(p) for p in includes],
                            str(Path(__file__).with_name('auth_startup_probe.c')),
                            *map(str, libraries), '-o', str(executable)],
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        for workers in (1, 4, 64):
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
            result = subprocess.run([str(executable), str(workers), str(port)],
                                    capture_output=True, text=True, timeout=15,
                                    env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0',
                                             UBSAN_OPTIONS='halt_on_error=1'))
            (output / f'{label}-auth-workers{workers}.log').write_text(result.stdout + result.stderr)
            result.check_returncode()
    print('PASS: 42 authentication startup checks, sanitized/optimized workers1/4/64; allocation faults are injected.')


def main():
    if not __debug__:
        raise SystemExit('Assertions required')
    if len(sys.argv) != 3:
        raise SystemExit('usage: final_native_check.py CORE OUTPUT')
    core, output = (Path(p).resolve() for p in sys.argv[1:])
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        authentication_startup(core, output, folder)
        with (output / 'build.log').open('wb') as log:
            executable = compile_host(core, folder, False, log)
        for workers in (1, 4, 64):
            with socket.socket() as occupied, (output / f'workers-{workers}.log').open('wb') as log:
                occupied.bind(('127.0.0.1', 0)); occupied.listen()
                port = occupied.getsockname()[1]
                options = dict(workers=str(workers), listenAddress='127.0.0.1', listenPort=str(port),
                    udpListenAddress='', udpListenPort='0', bindIPv4Address='0.0.0.0',
                    bindIPv6Address='::', bindInterface='', authUsername="u' :#[]{}/\\\u00e9",
                    authPassword="p' :#[]{}/\\\uac00", listenIPv6Only=False)
                host = Host(executable, log)
                try:
                    host.request('apply', settings=options, running=True)
                    state = settled(host, lambda s: not s['running'] and s['status'].startswith('Server exited ('))
                    occupied.close()
                    # Do not infer no-retry merely from an occupied listener.
                    # Release it, reapply unchanged intent, and probe the real port.
                    for _ in range(40):
                        host.request('apply', settings=options, running=True)
                    assert refused(port) and not host.request('state')['running']
                    rows.append(dict(workers=workers, case='real bind failure and unchanged-intent suppression', state=state))
                    host.request('apply', settings=options, running=True, retry=True)
                    wait_auth(port, options['authUsername'], options['authPassword'])
                    assert not authenticate(port, options['authUsername'], options['authPassword'] + 'x')
                    rows.append(dict(workers=workers, case='explicit retry and exact quoted UTF-8 credentials'))
                    with socket.create_connection(('127.0.0.1', port), timeout=1) as client:
                        client.sendall(b'\x05\x01\x02')
                        assert receive(client, 2) == b'\x05\x02'
                        for _ in range(100):
                            reply = host.request('apply', settings=options, running=True, retry=True)
                            assert reply['running']
                        user, secret = options['authUsername'].encode(), options['authPassword'].encode()
                        client.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(secret)]) + secret)
                        assert receive(client, 2) == b'\x01\x00', 'No-op retry replaced an existing native session'
                    rows.append(dict(workers=workers, case='100 unchanged explicit retries preserve live session'))
                    invalid = dict(options, workers='0')
                    host.request('apply', settings=invalid, running=True)
                    settled(host, lambda s: not s['running'] and s['status'].startswith('Use 1-64'))
                    assert refused(port)
                    for _ in range(40):
                        host.request('apply', settings=invalid, running=True, retry=True)
                    assert refused(port)
                    rows.append(dict(workers=workers, case='invalid replacement closes prior listener and never executes'))
                    noauth = dict(options, authUsername='', authPassword='')
                    host.request('apply', settings=noauth, running=True)
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            with socket.create_connection(('127.0.0.1', port), timeout=.2) as client:
                                client.sendall(b'\x05\x01\x00')
                                assert receive(client, 2) == b'\x05\x00'
                            break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(.01)
                    rows.append(dict(workers=workers, case='clearing credentials restores genuine no-auth listener'))
                    stop(host, noauth, port)
                    for _ in range(100):
                        reply = host.request('apply', settings=invalid, running=False, retry=True)
                        assert not reply['running'] and reply['status'] == 'Stopped'
                    assert refused(port)
                    rows.append(dict(workers=workers, case='100 stopped-invalid intents remain stopped; port released'))
                finally:
                    host.close()
                (output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
    assert len(rows) == 18
    print('PASS: 18 genuine native/controller final-review records, workers1/4/64; no engine substitutions. No physical-install, load benchmark or maximum-throughput claim.')


if __name__ == '__main__':
    main()
