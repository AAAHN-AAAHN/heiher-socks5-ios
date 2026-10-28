#!/usr/bin/env python3
"""Real same-process Hev + Swift service + explicit writer against UDP Echo port 7."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    native, output = args.native.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture_path = ROOT / 'Tests/Background/check_udp_echo_native.py'
    spec = importlib.util.spec_from_file_location('udp_echo_fixture', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    module = output / 'include'
    module.mkdir(exist_ok=True)
    shutil.copyfile(native / 'src/hev-main.h', module / 'hev-main.h')
    (module / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
    sources = [ROOT / 'Socks5/BackgroundKeepAlive' / name for name in (
        'Socks5UDPClient.swift', 'Socks5ServerEndpoint.swift',
        'PeriodicUDPEchoService.swift', 'PeriodicUDPEchoStore.swift')]
    sources += [ROOT / 'Socks5/Statistics/SocketIOWriter.swift',
                ROOT / 'Tests/Statistics/PeriodicEchoMeter.swift']
    libraries = [native / path for path in (
        'bin/libhev-socks5-server.a', 'third-part/yaml/bin/libyaml.a',
        'third-part/hev-task-system/bin/libhev-task-system.a')]
    executable = output / 'periodic-echo-meter'
    command = ['swiftc', '-swift-version', '5', '-strict-concurrency=complete',
               '-warnings-as-errors', '-I', str(module), *map(str, sources),
               *map(str, libraries), '-Xlinker', '-lpthread', '-o', str(executable)]
    (output / 'source-sha256.json').write_text(json.dumps({
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sources}, indent=2) + '\n')
    with (output / 'build.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    records = []
    echo = fixture.Echo(replies=True)
    process = None
    try:
        with (output / 'native.log').open('w') as log:
            process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)

            def request(value):
                result = fixture.command(process, value)
                records.append(dict(command=value, result=result))
                (output / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
                return result

            def accounting(rounds):
                # All replies are consumed before Off; no later round is due for 60s.
                # Wait only for the native post-syscall counters to be published.
                deadline = time.monotonic() + 3
                while True:
                    result = request('snapshot')
                    client, native_value = result['client'], result['native']
                    observed = echo.snapshot()
                    assert len(observed[4]) == len(observed[6]) == rounds
                    assert all(row[0] == '00' for values in observed.values() for row in values)
                    assert all(client[key] == rounds for key in (
                        'udpSent4', 'udpSent6', 'udpReceived4', 'udpReceived6'))
                    # Two ordinary authenticated UDP associations per round.
                    assert client['tcpSent'] >= rounds * 2 * (3 + 25 + 10)
                    assert client['tcpReceived'] >= rounds * 2 * (2 + 2 + 10)
                    assert len(client['peers']) >= 2
                    client_wire = client['clientSent'] + client['clientReceived']
                    expected = client_wire + 2 * rounds
                    if native_value['received'] == native_value['sent'] == expected:
                        break
                    assert time.monotonic() < deadline, (result, expected)
                    time.sleep(.01)
                peers = {row['address']: row for row in native_value['rows']}
                assert set(peers) == {'Unattributed', '127.0.0.1', '::1'}, peers
                for address, amount in [('Unattributed', 0), ('127.0.0.1', client_wire + rounds), ('::1', rounds)]:
                    assert peers[address]['received'] == peers[address]['sent'] == amount, peers
                assert result['factoryCalls'] == 1
                return result

            initial = request('snapshot')
            assert initial['factoryCalls'] == 0 and initial['writerAlive']
            assert initial['native']['received'] == initial['native']['sent'] == 0
            request('start1')
            for round_number in (1, 2):
                request('on')
                stopped = request('off')
                assert stopped['writerAlive'] and stopped['factoryCalls'] == 1
                accounting(round_number)
            before_restart = request('stop')
            assert before_restart['writerAlive']
            request('start4')
            request('on')
            request('off')
            final = accounting(3)
            released = request('release')
            assert not released['writerAlive'] and released['factoryCalls'] == 1
            assert released['native'] == final['native']
            stopped = request('stop')
            assert stopped['native'] == final['native']
            request('exit')
            assert process.wait(timeout=5) == 0
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
        echo.finish()
    print('PASS: same-process real Hev + Swift SOCKS5 service + explicit writer; exact TCP/auth/UDP wire bytes and peer rows; one producer survives Off/native restart and releases after shutdown; cumulative totals retained')


if __name__ == '__main__':
    main()
