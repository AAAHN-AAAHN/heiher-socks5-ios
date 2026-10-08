#!/usr/bin/env python3
"""Observe one exact ServerControl bind-failure case in 100 fresh processes.

This diagnostic does not replace any normal native or UI gate. A successful
series means only that the original macOS crash was not reproduced here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

TARGET = 'b3b770cc59ce9d6746a460e4f89bec424215c7db'


def main():
    if not __debug__:
        raise SystemExit('Assertions required')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('product', type=Path)
    parser.add_argument('native', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    product, native, output = (p.resolve() for p in (args.product, args.native, args.output))
    head = subprocess.check_output(['git', '-C', str(product), 'rev-parse', 'HEAD'], text=True).strip()
    if head != TARGET:
        raise SystemExit('Diagnostic requires exact ServerControl ' + TARGET)
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(product / 'Tests/ServerControl'))
    from final_native_check import compile_host, Host, settled, temporary_with_failure_evidence

    records = []
    context = {}
    libraries = [native / 'bin/libhev-socks5-server.a', native / 'third-part/yaml/bin/libyaml.a',
                 native / 'third-part/hev-task-system/bin/libhev-task-system.a']
    identity = dict(product=head, mode='buffered', trials=100, workers=64,
                    libraries={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in libraries},
                    scope='Original compiler flags and original first bind-failure case; no retries or replacement of normal gates')
    (output / 'identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    with temporary_with_failure_evidence(output, context) as temporary:
        folder = Path(temporary)
        with (output / 'compile-host.log').open('wb') as log:
            executable = compile_host(native, folder, False, log)
        (output / 'compiled-input-sha256.json').write_text(json.dumps({
            str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob('*')) if p.is_file()}, indent=2) + '\n')
        with (output / 'stages.jsonl').open('w') as stages:
            for trial in range(100):
                workers = 64
                with socket.socket() as occupied, (output / f'trial-{trial:03d}.log').open('wb') as log:
                    occupied.bind(('127.0.0.1', 0)); occupied.listen()
                    port = occupied.getsockname()[1]
                    options = dict(workers=str(workers), listenAddress='127.0.0.1', listenPort=str(port),
                        udpListenAddress='', udpListenPort='0', bindIPv4Address='0.0.0.0',
                        bindIPv6Address='::', bindInterface='', authUsername="u' :#[]{}/\\\u00e9",
                        authPassword="p' :#[]{}/\\\uac00", listenIPv6Only=False)
                    context.clear()
                    host = Host(executable, log)
                    context.update(host=host, workers=workers)

                    def stage(name, **values):
                        record = dict(trial=trial, pid=host.process.pid, workers=workers,
                                      port=port, stage=name, monotonic=time.monotonic(), **values)
                        stages.write(json.dumps(record) + '\n'); stages.flush()

                    stage('host-started')
                    try:
                        stage('apply')
                        reply = host.request('apply', settings=options, running=True)
                        stage('apply-returned', reply=reply)
                        stage('settled')
                        state = settled(host, lambda s: not s['running'] and s['status'].startswith('Server exited ('))
                        occupied.close()
                        stage('settled-returned', state=state)
                        records.append(dict(trial=trial, pid=host.process.pid, workers=workers,
                                            port=port, state=state))
                    except BaseException as error:
                        stage('failed', error=repr(error), returncode=host.process.poll())
                        raise
                    finally:
                        stage('close')
                        try:
                            host.close()
                        except BaseException as error:
                            stage('close-failed', error=repr(error), returncode=host.process.poll())
                            raise
                        stage('closed', returncode=host.process.returncode)
                    (output / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
    assert len(records) == 100
    (output / 'NOT-REPRODUCED.txt').write_text(
        'The occupied-port crash was not reproduced in 100 fresh 64-worker hosts. '
        'This does not resolve the earlier crash or establish a normal native/UI gate result.\n')
    print('NOT REPRODUCED: 100 fresh 64-worker hosts completed the original occupied-port case.')


if __name__ == '__main__':
    main()
