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
import select
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import traceback


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
    size = {1: 4, 4: 16}.get(data[0]) if data else None
    if size is None or len(data) < size + 3:
        raise ValueError('Invalid address header')
    return (str(ipaddress.ip_address(data[1:1 + size])),
            struct.unpack('!H', data[1 + size:3 + size])[0]), 3 + size


def record(trace, phase, **values):
    if trace is not None:
        trace(phase, **values)


def handshake(tcp, command, address, trace=None):
    endpoint = {'tcp_local': tcp.getsockname()[:2], 'tcp_peer': tcp.getpeername()[:2]}
    record(trace, 'greeting-send', **endpoint)
    tcp.sendall(b'\x05\x01\x00')
    greeting = exact(tcp, 2)
    record(trace, 'greeting-reply', reply_hex=greeting.hex(), **endpoint)
    assert greeting == b'\x05\x00', 'Authentication failed'
    request = bytes([5, command, 0]) + encode(*address)
    record(trace, 'request-send', command=command, requested=address,
           request_hex=request.hex(), **endpoint)
    tcp.sendall(request)
    header = exact(tcp, 4)
    record(trace, 'reply-header', reply_hex=header.hex(), **endpoint)
    ver, rep, reserved, kind = header
    assert (ver, reserved) == (5, 0), 'Invalid response header'
    assert rep == 0, 'UDP/TCP setup REP=0x%02x' % rep
    size = {1: 4, 4: 16}[kind]
    encoded = bytes([kind]) + exact(tcp, size + 2)
    relay = decode_bytes(encoded)[0]
    record(trace, 'reply-address', reply_hex=(header[:3] + encoded).hex(),
           address=relay, **endpoint)
    return relay


@contextlib.contextmanager
def association(proxy, hint, fixed_udp_port=False, trace=None):
    record(trace, 'tcp-connect', proxy=proxy, hint=hint)
    with socket.create_connection(proxy, timeout=1.5) as tcp:
        family = socket.AF_INET6 if ':' in proxy[0] else socket.AF_INET
        endpoint = {'tcp_local': tcp.getsockname()[:2], 'tcp_peer': tcp.getpeername()[:2]}
        record(trace, 'tcp-connected', **endpoint)
        with contextlib.ExitStack() as sockets:
            # Only repeat a local ephemeral choice equal to the fixed relay port.
            # No handshake, REP failure, I/O failure or test case is retried.
            for attempt in range(8):
                udp = sockets.enter_context(socket.socket(family, socket.SOCK_DGRAM))
                udp.bind((tcp.getsockname()[0], 0))
                local = udp.getsockname()[:2]
                record(trace, 'udp-source-bound', attempt=attempt + 1, udp_local=local,
                       excluded_fixed_port=proxy[1] if fixed_udp_port else None, **endpoint)
                if not fixed_udp_port or local[1] != proxy[1]:
                    break
                udp.close()
                record(trace, 'udp-source-port-collision-released', udp_local=local, **endpoint)
            else:
                raise RuntimeError('Client UDP ephemeral selection repeatedly chose the fixed relay port')
            requested = udp.getsockname()[:2] if hint == 'known' else (hint, 0)
            relay = handshake(tcp, 3, requested, trace)
            host = ipaddress.ip_address(relay[0])
            if host.version == 6 and host.ipv4_mapped:
                host = host.ipv4_mapped
            assert not host.is_unspecified and relay[1], 'Unusable relay: %r' % (relay,)
            udp.connect((str(host), relay[1]))
            udp.settimeout(1.5)
            record(trace, 'association-ready', udp_local=local, requested=requested,
                   relay=udp.getpeername()[:2], **endpoint)
            try:
                yield tcp, udp
            finally:
                record(trace, 'association-release', udp_local=local, **endpoint)


def exchange(udp, destination, size, trace=None):
    payload = secrets.token_bytes(size)
    record(trace, 'udp-send', destination=destination, payload_size=size)
    udp.send(b'\x00\x00\x00' + encode(*destination) + payload)
    record(trace, 'udp-receive', destination=destination, payload_size=size)
    reply = udp.recv(65535)
    record(trace, 'udp-reply-check', reply_size=len(reply))
    assert reply[:3] == b'\x00\x00\x00', 'Invalid SOCKS5 UDP prefix'
    source, offset = decode_bytes(reply[3:])
    assert source == destination, 'Wrong source: %r, expected %r' % (source, destination)
    assert reply[3 + offset:] == payload, 'Payload mismatch'


@contextlib.contextmanager
def proxy_server(binary, log_path, workers=1, fixed_udp_port=False, unbound=False,
                 udp_buffer_count=10, trace=None):
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
        # Reserve the same dual-stack wildcard scope used by the actual server.
        reserve.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        reserve.bind(('::', 0))
        port = reserve.getsockname()[1]
    with tempfile.TemporaryDirectory() as temp, open(log_path, 'wb') as log:
        conf = pathlib.Path(temp) / 'test.yml'
        conf.write_text('''main:
  workers: %d
  port: %d
  listen-address: '::'
  listen-ipv6-only: false
  udp-port: %d
%smisc:
  log-level: debug
  udp-copy-buffer-nums: %d
''' % (workers, port, port if fixed_udp_port else 0,
       '' if unbound else "  bind-address-v4: '0.0.0.0'\n  bind-address-v6: '::'\n",
       udp_buffer_count))
        saved_config = pathlib.Path(log_path).with_suffix('.yml')
        saved_config.write_bytes(conf.read_bytes())
        record(trace, 'proxy-config', path=str(saved_config), tcp_port=port,
               udp_port=port if fixed_udp_port else 0, workers=workers)
        proc = subprocess.Popen([binary, str(conf)], stdout=log, stderr=subprocess.STDOUT)
        try:
            record(trace, 'proxy-started', pid=proc.pid, returncode=proc.poll())
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
            try:
                record(trace, 'proxy-before-cleanup', pid=proc.pid, returncode=proc.poll())
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                finally:
                    record(trace, 'proxy-after-cleanup', pid=proc.pid, returncode=proc.poll())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('--output', required=True)
    parser.add_argument('--allow-failures', action='store_true')
    parser.add_argument('--workers', type=int, choices=(1, 4), default=1)
    parser.add_argument('--fixed-udp-port', action='store_true')
    parser.add_argument('--known-concurrent', action='store_true',
                        help='Advertise the actual ports in the multi-association case')
    parser.add_argument('--unbound', action='store_true',
                        help='Do not bind the outgoing socket to one address family')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Run without -O: assertions are part of this test')
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    current_test = None
    events = []

    def trace(phase, **values):
        event = {'test': current_test, 'phase': phase, 'monotonic_ns': time.monotonic_ns(), **values}
        events.append(event)
        diagnostics.write(json.dumps(event) + '\n')
        diagnostics.flush()

    def check(name, action):
        nonlocal current_test
        current_test = name
        events.clear()
        try:
            action()
            row = {'test': name, 'passed': True}
        except Exception as exc:
            site = traceback.extract_tb(exc.__traceback__)[-1]
            row = {'test': name, 'passed': False, 'error': '%s: %s' % (type(exc).__name__, exc),
                   'exception_type': type(exc).__name__, 'exception_module': type(exc).__module__,
                   'exception_site': {'filename': site.filename, 'function': site.name,
                                      'line_number': site.lineno, 'line': site.line},
                   'traceback': traceback.format_exc(), 'events': list(events)}
        results.append(row)
        print(json.dumps(row), flush=True)
        current_test = None

    with contextlib.ExitStack() as stack:
        diagnostics = stack.enter_context(output.with_suffix('.events.jsonl').open('w'))
        udp4 = stack.enter_context(echo_server('127.0.0.1'))
        udp6 = stack.enter_context(echo_server('::1'))
        tcp4 = stack.enter_context(echo_server('127.0.0.1', udp=False))
        tcp6 = stack.enter_context(echo_server('::1', udp=False))
        port = stack.enter_context(proxy_server(str(pathlib.Path(args.binary).resolve()),
                                                output.with_suffix('.server.log'), args.workers,
                                                args.fixed_udp_port, args.unbound, trace=trace))
        for host, hint in [('127.0.0.1', '0.0.0.0'), ('127.0.0.1', '::1'),
                           ('127.0.0.1', 'known'), ('::1', '::'), ('::1', 'known')]:
            destination = udp6 if ':' in host else udp4

            def single(host=host, hint=hint, destination=destination):
                with association((host, port), hint, args.fixed_udp_port, trace) as (_, udp):
                    for size in (1, 64, 512, 1200, 1400, 64):
                        exchange(udp, destination, size, trace)
            check('UDP %s hint=%s, six payloads' % (host, hint), single)

        for host, destination in [('127.0.0.1', udp4), ('::1', udp6)]:
            def closed_destination(host=host, destination=destination):
                family = socket.AF_INET6 if ':' in host else socket.AF_INET
                with socket.socket(family, socket.SOCK_DGRAM) as reserve:
                    reserve.bind((host, 0))
                    closed = reserve.getsockname()[:2]
                with association((host, port), 'known', args.fixed_udp_port, trace) as (tcp, udp):
                    exchange(udp, destination, 64, trace)
                    for _ in range(3):
                        udp.send(b'\x00\x00\x00' + encode(*closed) + b'\x00')
                        time.sleep(0.02)
                        exchange(udp, destination, 64, trace)
                    assert not select.select([tcp], [], [], 0)[0], (
                        'Destination error changed the UDP control connection')
            check('UDP %s closed destination preserves association' % host,
                  closed_destination)

        def concurrent():
            with contextlib.ExitStack() as associations:
                hint = 'known' if args.known_concurrent else '0.0.0.0'
                items = [associations.enter_context(association(
                    ('127.0.0.1', port), hint, args.fixed_udp_port, trace)) for _ in range(3)]
                payloads = [secrets.token_bytes(64) for _ in items]
                endpoints = [{'tcp_local': tcp.getsockname()[:2], 'tcp_peer': tcp.getpeername()[:2],
                              'udp_local': udp.getsockname()[:2], 'relay': udp.getpeername()[:2],
                              'requested': udp.getsockname()[:2] if hint == 'known' else (hint, 0)}
                             for tcp, udp in items]
                record(trace, 'concurrent-data-ready', associations=endpoints)
                phase = 'initial-send'
                try:
                    for index, ((_, udp), payload) in enumerate(zip(items, payloads)):
                        record(trace, 'concurrent-initial-send', association=index)
                        udp.send(b'\x00\x00\x00' + encode(*udp4) + payload)
                    phase = 'initial-receive'
                    for index, ((_, udp), payload) in enumerate(zip(items, payloads)):
                        record(trace, 'concurrent-initial-receive', association=index)
                        reply = udp.recv(65535)
                        source, offset = decode_bytes(reply[3:])
                        assert reply[:3] == b'\x00\x00\x00' and source == udp4
                        assert reply[3 + offset:] == payload
                    phase = 'close-first'
                    record(trace, 'concurrent-close-first', association=0)
                    items[0][0].close()
                    items[0][1].close()
                    time.sleep(0.1)
                    phase = 'survivor-exchange'
                    for index, (_, udp) in enumerate(items[1:], 1):
                        record(trace, 'concurrent-survivor-exchange', association=index)
                        exchange(udp, udp4, 1200, trace)
                except Exception as exc:
                    site = traceback.extract_tb(exc.__traceback__)[-1]
                    record(trace, 'concurrent-data-failure', data_phase=phase, associations=endpoints,
                           error='%s: %s' % (type(exc).__name__, exc),
                           exception_type=type(exc).__name__, exception_module=type(exc).__module__,
                           exception_site={'filename': site.filename, 'function': site.name,
                                           'line_number': site.lineno, 'line': site.line})
                    raise
        check('UDP three associations and one closed', concurrent)

        def burst():
            with association(('127.0.0.1', port), '0.0.0.0', args.fixed_udp_port, trace) as (_, udp):
                # Establish the peer before queuing a vector-sized burst.
                exchange(udp, udp4, 64, trace)
                for _ in range(3):
                    pending = {secrets.token_bytes(128) for _ in range(24)}
                    for payload in pending:
                        udp.send(b'\x00\x00\x00' + encode(*udp4) + payload)
                    for _ in range(len(pending)):
                        reply = udp.recv(65535)
                        source, offset = decode_bytes(reply[3:])
                        assert reply[:3] == b'\x00\x00\x00' and source == udp4
                        payload = reply[3 + offset:]
                        assert payload in pending, 'Duplicate or foreign burst payload'
                        pending.remove(payload)
                    assert not pending
        check('UDP three 24-datagram bursts, unordered replies', burst)

        if args.unbound:
            for first, second in ((udp4, udp6), (udp6, udp4)):
                def mixed(first=first, second=second):
                    with association(('127.0.0.1', port), '0.0.0.0', args.fixed_udp_port, trace) as (_, udp):
                        for _ in range(6):
                            exchange(udp, first, 64, trace)
                            exchange(udp, second, 512, trace)
                check('UDP mixed external families, first=' + first[0], mixed)

        for destination in (tcp4, tcp6):
            def tcp_test(destination=destination):
                with socket.create_connection(('127.0.0.1', port), timeout=1.5) as tcp:
                    handshake(tcp, 1, destination, trace)
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
