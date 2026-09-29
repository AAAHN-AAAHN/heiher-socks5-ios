#!/usr/bin/env python3
"""Real loopback dynamic-buffer regression; no production counter or payload mocks."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import socket
import struct
import tempfile
import time

from udp_sockaddr_regression import association, decode_bytes, encode, exact, handshake, proxy_server


def payload(size, salt=0):
    return bytes((i + salt) % 251 for i in range(size))


def datagram(family):
    sock = socket.socket(family, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
    sock.settimeout(2)
    return sock


def single(port, ip, domain, hint):
    rows = []
    family = socket.AF_INET6 if ':' in ip else socket.AF_INET
    with datagram(family) as destination:
        destination.bind((ip, 0))
        endpoint = destination.getsockname()[:2]
        addr = (b'\x03' + bytes([len(ip)]) + ip.encode() + struct.pack('!H', endpoint[1])) if domain else encode(*endpoint)
        with association((ip, port), hint) as (_, udp):
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
            sizes = [0, 1, 1477, 1478, 1479, 1489, 1490, 1491, 1499, 1500, 1501,
                     1999, 2000, 2001, 2048, 4096, 30001, 48000, 48001, 65000, 1]
            for size in sizes:
                original = payload(size)
                udp.send(b'\0\0\0' + addr + original)
                actual, peer = destination.recvfrom(70000)
                assert actual == original, ('outbound', ip, domain, size, len(actual))
                destination.sendto(actual, peer)
                reply = udp.recv(70000)
                source, offset = decode_bytes(reply[3:])
                assert reply[:3] == b'\0\0\0' and source == endpoint
                assert reply[3 + offset:] == original, ('reply', ip, size)
                rows.append(dict(case='roundtrip', ip=ip, domain=domain, hint=hint, size=size))
            # A small outbound request must not mask independent large replies.
            for size in [0, 1, 1500, 1501, 2048, 48001, 65000, 1]:
                udp.send(b'\0\0\0' + addr + b'Q')
                actual, peer = destination.recvfrom(70000)
                assert actual == b'Q'
                original = payload(size, 3)
                destination.sendto(original, peer)
                reply = udp.recv(70000)
                source, offset = decode_bytes(reply[3:])
                assert source == endpoint and reply[3 + offset:] == original
                rows.append(dict(case='independent-response', ip=ip, domain=domain, size=size))
            # Same queue: small/large/empty messages must never share or lose tails.
            originals = [payload(n, k) for k, n in enumerate([7, 2048, 19, 48001, 0, 4096, 1])]
            for original in originals:
                udp.send(b'\0\0\0' + addr + original)
            observed = []
            for _ in originals:
                actual, peer = destination.recvfrom(70000)
                observed.append(actual)
                destination.sendto(actual, peer)
            assert sorted(observed) == sorted(originals)
            returned = []
            for _ in originals:
                reply = udp.recv(70000)
                _, offset = decode_bytes(reply[3:])
                returned.append(reply[3 + offset:])
            assert sorted(returned) == sorted(originals)
            udp.settimeout(.05)
            try:
                extra = udp.recv(70000)
            except socket.timeout:
                pass
            else:
                raise AssertionError(('extra datagram', extra))
            rows.append(dict(case='mixed-queue', ip=ip, domain=domain, messages=len(originals)))
        with socket.create_connection((ip, port), timeout=2) as tcp:
            handshake(tcp, 5, ('::' if family == socket.AF_INET6 else '0.0.0.0', 0))
            for size in [0, 1, 1493, 1500, 1501, 2048, 4096, 30001, 48001, 65000, 1]:
                original = payload(size, 11)
                frame = struct.pack('!HB', size, 3 + len(addr)) + addr + original
                # Split the TCP header too: UDP message framing must survive.
                tcp.sendall(frame[:2])
                tcp.sendall(frame[2:5])
                tcp.sendall(frame[5:])
                actual, peer = destination.recvfrom(70000)
                assert actual == original, ('udp-over-tcp', ip, domain, size)
                destination.sendto(actual, peer)
                length, hlen = struct.unpack('!HB', exact(tcp, 3))
                source, offset = decode_bytes(exact(tcp, hlen - 3))
                assert source == endpoint and offset == hlen - 3 and length == size
                assert exact(tcp, length) == original
                rows.append(dict(case='udp-over-tcp', ip=ip, domain=domain, size=size))
    return rows


def malformed_frames(port):
    rows = []
    # Header consistency/short-stream failures must not produce a destination datagram.
    with datagram(socket.AF_INET) as destination:
        destination.bind(('127.0.0.1', 0))
        endpoint = destination.getsockname()[:2]
        addr = encode(*endpoint)
        for label, frame in [
            ('short-header', b'\x00\x08'),
            ('wrong-header-length', struct.pack('!HB', 4, 9) + addr + b'data'),
            ('short-body', struct.pack('!HB', 2048, 10) + addr + b'short'),
            ('invalid-address-type', b'\x00\x01\x05\x7f\x00x')]:
            with socket.create_connection(('127.0.0.1', port), timeout=2) as tcp:
                handshake(tcp, 5, ('0.0.0.0', 0))
                tcp.sendall(frame)
                tcp.shutdown(socket.SHUT_WR)
                destination.settimeout(.08)
                try:
                    data, _ = destination.recvfrom(70000)
                except socket.timeout:
                    pass
                else:
                    raise AssertionError((label, 'unexpected destination payload', data))
                try:
                    closed = tcp.recv(1) == b''
                except ConnectionResetError:
                    closed = True
                assert closed, label
                rows.append(dict(case=label, rejected=True))
    return rows


def prior_control(binary, directory):
    with proxy_server(str(binary), directory / 'old.server.log') as port:
        with datagram(socket.AF_INET) as dest:
            dest.bind(('127.0.0.1', 0))
            endpoint = dest.getsockname()[:2]
            with association(('127.0.0.1', port), 'known') as (_, udp):
                original = payload(2048)
                udp.send(b'\0\0\0' + encode(*endpoint) + original)
                observed, _ = dest.recvfrom(70000)
                assert observed == original[:1490]
    return dict(case='exact-prior-three-patch-control', original=2048, forwarded=1490)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--old-control', action='store_true')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Assertions are mandatory')
    rows = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            if args.old_control:
                rows.append(prior_control(args.binary.resolve(), directory))
            else:
                for workers in (1, 4):
                    with proxy_server(str(args.binary.resolve()), directory / f'new-{workers}.server.log', workers) as port:
                        routes = [('127.0.0.1', False, 'known'), ('127.0.0.1', False, '0.0.0.0'),
                                  ('::1', False, 'known'), ('::1', False, '::'),
                                  ('127.0.0.1', True, 'known')]
                        for ip, domain, hint in routes:
                            batch = single(port, ip, domain, hint)
                            for row in batch:
                                row['workers'] = workers
                            rows.extend(batch)
                        rows.extend(malformed_frames(port))
                        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                            futures = [pool.submit(single, port, ip, False, hint) for ip, _, hint in routes[:4]]
                            for f in futures:
                                result = f.result(timeout=30)
                                rows.append(dict(case='concurrent-association', workers=workers,
                                                 subcases=len(result)))
    finally:
        args.output.write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(dict(passed=True, recorded_cases=len(rows), old_control=args.old_control)))


if __name__ == '__main__':
    main()
