#!/usr/bin/env python3
"""Exact Total/IP deltas across invalid input, large mixed queues and restart.

Runs the real composed host; all peers are loopback. No production counter or
socket outcome is replaced. Non-delivery checks are bounded observations.
"""
import concurrent.futures
import contextlib
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from traffic_stats_regression import Host, wait_server, check_delta
from udp_sockaddr_regression import association, decode_bytes, encode
from udp_buffer_network import datagram, payload


def main():
    with contextlib.ExitStack() as stack:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
            reserve.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            reserve.bind(('::', 0))
            port = reserve.getsockname()[1]
        config = directory / 'server.yml'
        config.write_text(f'''main:
  workers: 4
  port: {port}
  listen-address: '::'
  listen-ipv6-only: false
  udp-port: 0
  bind-address-v4: '0.0.0.0'
  bind-address-v6: '::'
misc:
  log-level: error
''')
        host = Host(str(Path(sys.argv[1]).resolve()), config)
        stack.callback(host.close)
        wait_server(port)
        expected = {'Unattributed': (0, 0)}

        def add(ip, incoming, outgoing):
            previous = expected.get(ip, (0, 0))
            expected[ip] = (previous[0] + incoming, previous[1] + outgoing)

        def verify():
            check_delta(host, (0, 0), sum(x[0] for x in expected.values()),
                        sum(x[1] for x in expected.values()))
            for _ in range(100):
                actual = host.clients()
                if actual == expected:
                    return
                time.sleep(.01)
            raise AssertionError((actual, expected))

        for ip in ['127.0.0.1', '::1']:
            family = socket.AF_INET6 if ':' in ip else socket.AF_INET
            with datagram(family) as dest, association((ip, port), 'known') as (_, udp):
                dest.bind((ip, 0))
                address = encode(*dest.getsockname()[:2])
                add(ip, 0, 0)
                for prefix in [b'\1\0\0', b'\0\1\0', b'\0\0\1', b'\0\0\x82']:
                    udp.send(prefix + address + b'invalid-not-an-external-write')
                    dest.settimeout(.05)
                    try:
                        dest.recvfrom(70000)
                    except socket.timeout:
                        pass
                    else:
                        raise AssertionError('Invalid header reached destination')
                    verify()
                dest.settimeout(2)
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
                udp.send(b'\0\0\0' + address + payload(2048))
                data, peer = dest.recvfrom(70000)
                assert data == payload(2048)
                dest.sendto(payload(48001), peer)
                reply = udp.recv(70000)
                endpoint, offset = decode_bytes(reply[3:])
                assert endpoint == dest.getsockname()[:2]
                assert reply[3 + offset:] == payload(48001)
                add(ip, 48001, 2048)
                verify()
        print('PASS: invalid RSV/FRAG adds no external bytes; asymmetric large valid replies update the right IP', flush=True)

        def exchange_batch(index):
            ip = '::1' if index % 2 else '127.0.0.1'
            family = socket.AF_INET6 if ':' in ip else socket.AF_INET
            sizes = [0, 7, 2048, 48001, 19, 65000, 4096]
            with datagram(family) as dest, association((ip, port), 'known') as (_, udp):
                dest.bind((ip, 0))
                endpoint = dest.getsockname()[:2]
                address = encode(*endpoint)
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
                original = [payload(n, index + k) for k, n in enumerate(sizes)]
                for data in original:
                    udp.send(b'\0\0\0' + address + data)
                received = []
                for _ in original:
                    data, peer = dest.recvfrom(70000)
                    received.append(data)
                    dest.sendto(data, peer)
                assert sorted(received) == sorted(original)
                returned = []
                for _ in original:
                    reply = udp.recv(70000)
                    source, offset = decode_bytes(reply[3:])
                    assert reply[:3] == b'\0\0\0' and source == endpoint
                    returned.append(reply[3 + offset:])
                assert sorted(returned) == sorted(original)
                udp.settimeout(.02)
                try:
                    udp.recv(70000)
                except socket.timeout:
                    pass
                else:
                    raise AssertionError('Duplicate reply')
            return ip, sum(sizes)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for ip, size in pool.map(exchange_batch, range(16)):
                add(ip, size, size)
        verify()
        before = host.clients()
        host.stats('restart')
        wait_server(port)
        assert host.clients() == before
        for index in (0, 1):
            ip, size = exchange_batch(index)
            add(ip, size, size)
        verify()
        print('PASS: 18 mixed-size associations / 126 complete echoes, concurrent IPv4/IPv6, exact per-IP sums and native Stop/Start accumulation', flush=True)


if __name__ == '__main__':
    if not __debug__ or len(sys.argv) != 2:
        raise SystemExit('Assertions and a compiled statistics host are required')
    main()
