#!/usr/bin/env python3
"""Real child-only FD pressure: established UDP, admission recovery and Stop."""
import argparse
import contextlib
import json
from pathlib import Path
import resource
import signal
import socket
import subprocess
import tempfile
import time

from udp_sockaddr_regression import association, encode

NOFILE_LIMIT = 48


def restrict_descriptors():
    resource.setrlimit(resource.RLIMIT_NOFILE, (NOFILE_LIMIT, NOFILE_LIMIT))
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == (NOFILE_LIMIT, NOFILE_LIMIT)


def exchange(udp, destination, payload):
    wire = b'\0\0\0' + encode(*destination.getsockname()[:2]) + payload
    udp.send(wire)
    try:
        actual, peer = destination.recvfrom(65535)
        assert actual == payload
        destination.sendto(actual, peer)
        assert udp.recv(65535) == wire
    except TimeoutError:
        return False
    return True


def exercise(binary, directory, release):
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
        reserve.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        reserve.bind(('::', 0))
        port = reserve.getsockname()[1]
    conf = directory / 'server.yml'
    conf.write_text(f'''main:
  workers: 1
  port: {port}
  listen-address: '::'
  listen-ipv6-only: false
misc:
  limit-nofile: {NOFILE_LIMIT}
  task-stack-size: 8192
  tcp-read-write-timeout: 300000
  udp-read-write-timeout: 300000
  log-file: null
''')
    row = dict(case='recover-after-pressure' if release else 'stop-under-pressure',
               child_limit_nofile=NOFILE_LIMIT, limit_enforced_before_exec=True,
               workers=1, stop_timed_out=False, watchdog_killed=False)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    with (directory / 'server.log').open('wb') as log:
        proc = subprocess.Popen([str(binary), str(conf)], stdout=log, stderr=log,
                                preexec_fn=restrict_descriptors)
    try:
        for _ in range(100):
            assert proc.poll() is None, 'Server exited during startup'
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    break
            except ConnectionRefusedError:
                time.sleep(.02)
        else:
            raise AssertionError('Server startup timed out')
        with contextlib.ExitStack() as stack:
            destination = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
            destination.bind(('127.0.0.1', 0))
            destination.settimeout(1.5)
            _, udp = stack.enter_context(association(('127.0.0.1', port), 'known'))
            assert exchange(udp, destination, b'before-pressure')
            pressure = [stack.enter_context(socket.create_connection(('127.0.0.1', port), timeout=1.5))
                        for _ in range(72)]
            row['pressure_connections'] = len(pressure)
            # More connected clients than the child's total descriptor limit;
            # pending handshakes retain accepted descriptors for this interval.
            time.sleep(.05)
            row['udp_during_pressure'] = exchange(udp, destination, b'during-pressure')
            if row['udp_during_pressure']:
                time.sleep(.25)
                row['udp_during_pressure'] = exchange(udp, destination, b'still-under-pressure')
            if release:
                assert row['udp_during_pressure'], row
                for client in pressure:
                    client.close()
                with association(('127.0.0.1', port), 'known') as (_, admitted):
                    assert exchange(admitted, destination, b'new-admission')
                assert exchange(udp, destination, b'after-release')
                row['admission_recovered'] = True
            row['alive_before_stop'] = proc.poll() is None
            assert row['alive_before_stop'], 'Server exited under descriptor pressure'
            stop_started = time.monotonic()
            proc.send_signal(signal.SIGINT)
            try:
                row['exit_code'] = proc.wait(timeout=2)
                row['stop_completed'] = row['exit_code'] == 0
            except subprocess.TimeoutExpired:
                row['stop_completed'] = False
                row['stop_timed_out'] = True
            row['stop_seconds'] = time.monotonic() - stop_started
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
            row['watchdog_killed'] = True
        current = resource.getrusage(resource.RUSAGE_CHILDREN)
        row['wall_seconds'] = time.monotonic() - started
        row['child_cpu_seconds'] = (current.ru_utime + current.ru_stime -
                                    usage.ru_utime - usage.ru_stime)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--old-control', action='store_true')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Assertions are mandatory')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        with tempfile.TemporaryDirectory() as temp:
            for release in ((False,) if args.old_control else (False, True)):
                row = exercise(args.binary.resolve(), Path(temp), release)
                row['negative_control'] = args.old_control
                rows.append(row)
                if args.old_control:
                    assert (not row['udp_during_pressure'] and not row['stop_completed'] and
                            row['alive_before_stop'] and row['stop_timed_out'] and
                            row['watchdog_killed']), row
                else:
                    assert row['udp_during_pressure'] and row['stop_completed'], row
    finally:
        args.output.write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(dict(passed=True, cases=len(rows), old_control=args.old_control)))


if __name__ == '__main__':
    main()
