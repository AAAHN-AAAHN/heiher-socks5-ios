#!/usr/bin/env python3
"""Observation-only equal-payload comparison, not an iOS throughput/power claim."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import statistics
import subprocess
import sys
import tempfile
import threading
import time

from udp_sockaddr_regression import association, encode, decode_bytes


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        sock.sendto(data, self.client_address)


def trial(binary, size, count, label):
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
        reserve.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        reserve.bind(('::', 0))
        port = reserve.getsockname()[1]
    echo = socketserver.UDPServer(('127.0.0.1', 0), Echo)
    thread = threading.Thread(target=echo.serve_forever, kwargs={'poll_interval': .01})
    thread.start()
    usage = None
    with tempfile.TemporaryDirectory() as temp:
        config = Path(temp) / 'bench.yml'
        config.write_text(f"main:\n  workers: 1\n  port: {port}\n  listen-address: '::'\n"
                          "  listen-ipv6-only: false\n  udp-port: 0\n"
                          "  bind-address-v4: '0.0.0.0'\n  bind-address-v6: '::'\n"
                          "misc:\n  log-level: error\n")
        with (Path(temp) / 'server.log').open('wb') as log:
            proc = subprocess.Popen([str(binary), str(config)], stdout=log, stderr=log)
            try:
                for _ in range(150):
                    if proc.poll() is not None:
                        raise RuntimeError('Benchmark server exited')
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.05):
                            break
                    except OSError:
                        time.sleep(.01)
                else:
                    raise TimeoutError('Benchmark listen deadline')
                prefix = b'\0\0\0' + encode(*echo.server_address)
                with association(('127.0.0.1', port), 'known') as (_, udp):
                    payloads = [i.to_bytes(4, 'big') + bytes([i % 251]) * (size - 4) for i in range(16)]
                    frames = [prefix + p for p in payloads]
                    rss_before = int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(proc.pid)])) * 1024
                    start = time.monotonic()
                    for _ in range(count // 16):
                        for frame in frames:
                            assert udp.send(frame) == len(frame)
                        received = []
                        for _ in frames:
                            reply = udp.recv(70000)
                            _, offset = decode_bytes(reply[3:])
                            received.append(reply[3 + offset:])
                        assert sorted(received) == payloads
                    wall = time.monotonic() - start
                    rss_after = int(subprocess.check_output(['ps', '-o', 'rss=', '-p', str(proc.pid)])) * 1024
            finally:
                if proc.returncode is None:
                    proc.send_signal(signal.SIGINT)
                    deadline = time.monotonic() + 5
                    while True:
                        pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
                        if pid:
                            proc.returncode = os.waitstatus_to_exitcode(status)
                            break
                        if time.monotonic() > deadline:
                            proc.kill()
                            _, status, usage = os.wait4(proc.pid, 0)
                            proc.returncode = os.waitstatus_to_exitcode(status)
                            raise TimeoutError('Benchmark Stop deadline')
                        time.sleep(.01)
                echo.shutdown()
                echo.server_close()
                thread.join(timeout=2)
    assert usage is not None
    cpu = usage.ru_utime + usage.ru_stime
    return {'variant': label, 'payload_bytes': size, 'roundtrips': count, 'workers': 1,
            'server_cpu_seconds': cpu, 'cpu_us_per_relay_datagram': cpu * 1e6 / (count * 2),
            'wall_seconds': wall, 'post_exec_rss_before_bytes': rss_before, 'live_association_rss_after_bytes': rss_after,
            'raw_child_highwater_not_app_footprint': int(usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)),
            'exit_code': proc.returncode}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('old', type=Path)
    p.add_argument('new', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if not __debug__:
        p.error('Assertions are mandatory')
    rows = []
    try:
        for size in (64, 1200):
            for repeat in range(3):
                variants = [('old-three-patch', a.old), ('dynamic', a.new)]
                if repeat % 2:
                    variants.reverse()
                for label, binary in variants:
                    row = trial(binary.resolve(), size, 12000, label)
                    row['repeat'] = repeat
                    rows.append(row)
                    print(json.dumps(row), flush=True)
    finally:
        a.output.write_text(json.dumps({'observations': rows,
            'scope': 'same 12000 small-payload roundtrips; server child CPU includes startup/Stop; parent client/echo CPU excluded; RSS snapshots are post-exec, not peak; child highwater can include pre-exec parent pages and is not an app footprint; no performance threshold; not physical iOS or maximum throughput'}, indent=2) + '\n')
    for size in (64, 1200):
        medians = {label: statistics.median(r['cpu_us_per_relay_datagram'] for r in rows
                    if r['variant'] == label and r['payload_bytes'] == size)
                   for label in ('old-three-patch', 'dynamic')}
        print(json.dumps({'payload': size, 'median_cpu_us': medians,
                          'ratio': medians['dynamic'] / medians['old-three-patch']}), flush=True)


if __name__ == '__main__':
    main()
