#!/usr/bin/env python3
"""Real patched server: per-control-peer payload attribution, no Internet."""
import concurrent.futures
import contextlib
from pathlib import Path
import socket
import socketserver
import statistics
import struct
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from traffic_stats_regression import Host, Asymmetric, wait_server, check_delta
from udp_sockaddr_regression import association, echo_server, encode, exact, exchange, handshake


def main():
    with contextlib.ExitStack() as stack:
        temp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
            reserve.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            reserve.bind(('::', 0))
            port = reserve.getsockname()[1]
        config = temp / 'config.yml'
        config.write_text(f"""main:
  workers: 4
  port: {port}
  listen-address: '::'
  listen-ipv6-only: false
  udp-port: 0
  bind-address-v4: '0.0.0.0'
  bind-address-v6: '::'
misc:
  log-level: error
""")
        host = Host(str(Path(sys.argv[1]).resolve()), config)
        stack.callback(host.close)
        wait_server(port)
        assert host.clients() == {'Unattributed': (0, 0)}
        expected = {'Unattributed': (0, 0)}

        def verify():
            incoming = sum(v[0] for v in expected.values())
            outgoing = sum(v[1] for v in expected.values())
            check_delta(host, (0, 0), incoming, outgoing)
            for _ in range(100):
                rows = host.clients()
                if rows == expected:
                    return
                time.sleep(.01)
            raise AssertionError((rows, expected))

        def add(ip, incoming, outgoing):
            a, b = expected.get(ip, (0, 0))
            expected[ip] = (a + incoming, b + outgoing)

        echo = stack.enter_context(echo_server('127.0.0.1'))
        for ip, unknown in [('127.0.0.1', '0.0.0.0'), ('::1', '::')]:
            for hint in [unknown, 'known']:
                with association((ip, port), hint) as (_, udp):
                    for size in [1, 73, 1200]:
                        exchange(udp, echo, size)
                        add(ip, size, size)
                verify()
        print('PASS: dual-stack control peers, mapped IPv4, unknown/known UDP endpoint, same-IP association accumulation', flush=True)
        with socketserver.ThreadingTCPServer(('127.0.0.1', 0), Asymmetric) as server:
            server.reply = b'R' * 17003
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for ip in ['127.0.0.1', '::1']:
                    with socket.create_connection((ip, port), timeout=5) as tcp:
                        handshake(tcp, 1, server.server_address)
                        payload = b'U' * 98317
                        tcp.sendall(payload)
                        tcp.shutdown(socket.SHUT_WR)
                        assert exact(tcp, len(server.reply)) == server.reply
                        add(ip, len(server.reply), len(payload))
                    verify()
            finally:
                server.shutdown()
                thread.join()
        print('PASS: asymmetric TCP and half-close share the same IP bucket as UDP', flush=True)
        for ip in ['127.0.0.1', '::1']:
            with socket.create_connection((ip, port), timeout=5) as tcp:
                handshake(tcp, 5, ('0.0.0.0', 0))
                payload = b'udp-in-tcp' * 17
                address = encode(*echo)
                tcp.sendall(struct.pack('!HB', len(payload), 3 + len(address)) + address + payload)
                data_length, header_length = struct.unpack('!HB', exact(tcp, 3))
                assert header_length >= 4
                exact(tcp, header_length - 3)
                assert exact(tcp, data_length) == payload
                add(ip, len(payload), len(payload))
            verify()
        print('PASS: UDP-over-TCP extension retains control-peer attribution and excludes its framing', flush=True)
        durations = []
        with association(('127.0.0.1', port), '0.0.0.0') as (_, udp):
            for _ in range(2000):
                start = time.perf_counter()
                exchange(udp, echo, 64)
                durations.append(time.perf_counter() - start)
        add('127.0.0.1', 2000 * 64, 2000 * 64)
        verify()
        print('OBSERVATION: 2000 sequential local 64-byte UDP echoes; median_ms=%.3f p95_ms=%.3f; not a device or comparative benchmark' %
              (statistics.median(durations) * 1000, sorted(durations)[1899] * 1000), flush=True)

        tcp_echo = stack.enter_context(echo_server('127.0.0.1', udp=False))
        def transfer(n):
            ip = '::1' if n % 2 else '127.0.0.1'
            size = 7001 + n
            if n % 3:
                with socket.create_connection((ip, port), timeout=5) as tcp:
                    handshake(tcp, 1, tcp_echo)
                    payload = bytes([n]) * size
                    tcp.sendall(payload)
                    assert exact(tcp, size) == payload
            else:
                with association((ip, port), '::' if n % 2 else '0.0.0.0') as (_, udp):
                    exchange(udp, echo, 1000)
                    size = 1000
            return ip, size
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for ip, size in pool.map(transfer, range(24)):
                add(ip, size, size)
        verify()
        before = host.clients()
        host.stats('restart')
        wait_server(port)
        assert host.clients() == before
        with association(('127.0.0.1', port), '0.0.0.0') as (_, udp):
            exchange(udp, echo, 31)
        add('127.0.0.1', 31, 31)
        verify()
        print('PASS: concurrent TCP/UDP, stable peer rows after fd churn and native Stop/Start, per-IP sum equals original aggregate', flush=True)

if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions must be enabled.')
    main()
