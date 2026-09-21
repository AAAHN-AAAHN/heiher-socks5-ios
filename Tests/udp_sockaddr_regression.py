#!/usr/bin/env python3
"""Loopback TCP/UDP regression tests for the compiled Hev server.

No Internet access is used. This is a CI test, not code included in the app.
Checks both payload integrity and the SOCKS5 response's source address.
"""

import argparse
import contextlib
import ipaddress
import json
import pathlib
import secrets
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time


class DatagramEcho(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        sock.sendto(data, self.client_address)


class StreamEcho(socketserver.BaseRequestHandler):
    def handle(self):
        while True:
            data = self.request.recv(65536)
            if not data:
                return
            self.request.sendall(data)


class UDP6Server(socketserver.ThreadingUDPServer):
    address_family = socket.AF_INET6


class TCP6Server(socketserver.ThreadingTCPServer):
    address_family = socket.AF_INET6


@contextlib.contextmanager
def echo_server(host, udp=True):
    ipv6 = ':' in host
    cls = (UDP6Server if ipv6 else socketserver.ThreadingUDPServer) if udp else (
        TCP6Server if ipv6 else socketserver.ThreadingTCPServer)
    server = cls((host, 0), DatagramEcho if udp else StreamEcho)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[:2]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def exact(sock, count):
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError('SOCKS connection closed')
        data.extend(chunk)
    return bytes(data)


def encode(host, port):
    ip = ipaddress.ip_address(host)
    return bytes([1 if ip.version == 4 else 4]) + ip.packed + struct.pack('!H', port)


def decode_bytes(data):
    size = {1: 4, 4: 16}.get(data[0])
    if size is None or len(data) < size + 3:
        raise ValueError('Invalid address header')
    return (str(ipaddress.ip_address(data[1:1 + size])),
            struct.unpack('!H', data[1 + size:3 + size])[0]), 3 + size


def handshake(tcp, command, address):
    tcp.sendall(b'\x05\x01\x00')
    assert exact(tcp, 2) == b'\x05\x00', 'Authentication failed'
    tcp.sendall(bytes([5, command, 0]) + encode(*address))
    ver, rep, reserved, kind = exact(tcp, 4)
    assert (ver, reserved) == (5, 0), 'Invalid response header'
    assert rep == 0, 'UDP/TCP setup REP=0x%02x' % rep
    size = {1: 4, 4: 16}[kind]
    return decode_bytes(bytes([kind]) + exact(tcp, size + 2))[0]


@contextlib.contextmanager
def association(proxy, hint):
    with socket.create_connection(proxy, timeout=1.5) as tcp:
        family = socket.AF_INET6 if ':' in proxy[0] else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as udp:
            udp.bind((tcp.getsockname()[0], 0))
            requested = udp.getsockname()[:2] if hint == 'known' else (hint, 0)
            relay = handshake(tcp, 3, requested)
            host = ipaddress.ip_address(relay[0])
            if host.version == 6 and host.ipv4_mapped:
                host = host.ipv4_mapped
            assert not host.is_unspecified and relay[1], 'Unusable relay: %r' % (relay,)
            udp.connect((str(host), relay[1]))
            udp.settimeout(1.5)
            yield tcp, udp


def exchange(udp, destination, size):
    payload = secrets.token_bytes(size)
    udp.send(b'\x00\x00\x00' + encode(*destination) + payload)
    reply = udp.recv(65535)
    assert reply[:3] == b'\x00\x00\x00', 'Invalid SOCKS5 UDP prefix'
    source, offset = decode_bytes(reply[3:])
    assert source == destination, 'Wrong source: %r, expected %r' % (source, destination)
    assert reply[3 + offset:] == payload, 'Payload mismatch'


@contextlib.contextmanager
def proxy_server(binary, log_path):
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
        reserve.bind(('::1', 0))
        port = reserve.getsockname()[1]
    with tempfile.TemporaryDirectory() as temp, open(log_path, 'wb') as log:
        conf = pathlib.Path(temp) / 'test.yml'
        conf.write_text('''main:
  workers: 1
  port: %d
  listen-address: '::'
  listen-ipv6-only: false
  udp-port: 0
  bind-address-v4: '0.0.0.0'
  bind-address-v6: '::'
misc:
  log-level: debug
''' % port)
        proc = subprocess.Popen([binary, str(conf)], stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise RuntimeError('Proxy exited: %s' % proc.returncode)
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError('Proxy startup timed out')
            yield port
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('--output', required=True)
    parser.add_argument('--allow-failures', action='store_true')
    args = parser.parse_args()
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []

    def check(name, action):
        try:
            action()
            row = {'test': name, 'passed': True}
        except Exception as exc:
            row = {'test': name, 'passed': False, 'error': '%s: %s' % (type(exc).__name__, exc)}
        results.append(row)
        print(json.dumps(row), flush=True)

    with contextlib.ExitStack() as stack:
        udp4 = stack.enter_context(echo_server('127.0.0.1'))
        udp6 = stack.enter_context(echo_server('::1'))
        tcp4 = stack.enter_context(echo_server('127.0.0.1', udp=False))
        tcp6 = stack.enter_context(echo_server('::1', udp=False))
        port = stack.enter_context(proxy_server(str(pathlib.Path(args.binary).resolve()),
                                                output.with_suffix('.server.log')))
        for host, hint in [('127.0.0.1', '0.0.0.0'), ('127.0.0.1', '::1'),
                           ('127.0.0.1', 'known'), ('::1', '::'), ('::1', 'known')]:
            destination = udp6 if ':' in host else udp4

            def single(host=host, hint=hint, destination=destination):
                with association((host, port), hint) as (_, udp):
                    for size in (1, 64, 512, 1200, 1400, 64):
                        exchange(udp, destination, size)
            check('UDP %s hint=%s, six payloads' % (host, hint), single)

        def concurrent():
            with contextlib.ExitStack() as associations:
                items = [associations.enter_context(association(('127.0.0.1', port), '0.0.0.0'))
                         for _ in range(3)]
                payloads = [secrets.token_bytes(64) for _ in items]
                for (_, udp), payload in zip(items, payloads):
                    udp.send(b'\x00\x00\x00' + encode(*udp4) + payload)
                for (_, udp), payload in zip(items, payloads):
                    reply = udp.recv(65535)
                    source, offset = decode_bytes(reply[3:])
                    assert reply[:3] == b'\x00\x00\x00' and source == udp4
                    assert reply[3 + offset:] == payload
                items[0][0].close()
                items[0][1].close()
                time.sleep(0.1)
                for _, udp in items[1:]:
                    exchange(udp, udp4, 1200)
        check('UDP three associations and one closed', concurrent)

        for destination in (tcp4, tcp6):
            def tcp_test(destination=destination):
                with socket.create_connection(('127.0.0.1', port), timeout=1.5) as tcp:
                    handshake(tcp, 1, destination)
                    data = secrets.token_bytes(16384)
                    tcp.sendall(data)
                    assert exact(tcp, len(data)) == data
            check('TCP echo %s' % destination[0], tcp_test)

    output.write_text(json.dumps(results, indent=2) + '\n')
    failed = sum(not row['passed'] for row in results)
    print('SUMMARY: %d passed, %d failed' % (len(results) - failed, failed), flush=True)
    if failed and not args.allow_failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
