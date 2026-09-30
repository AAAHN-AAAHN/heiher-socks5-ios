#!/usr/bin/env python3
"""Real loopback RSV/FRAG rejection, first-peer safety and queue continuation."""
import argparse
import json
from pathlib import Path
import socket
import struct
import tempfile
import time

from udp_sockaddr_regression import association, decode_bytes, encode, proxy_server


PREFIXES = [('fragment-first', b'\0\0\1'), ('fragment-last', b'\0\0\x82'),
            ('fragment-255', b'\0\0\xff'), ('reserved-first', b'\1\0\0'),
            ('reserved-second', b'\0\1\0'), ('combined', b'\xff\xff\xff')]


def drain(sock, duration=.12):
    """A bounded absence observation, not a proof about arbitrary network delay."""
    found = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        sock.settimeout(max(.001, deadline - time.monotonic()))
        try:
            found.append(sock.recvfrom(70000))
        except socket.timeout:
            break
    return found


def destination(ip):
    sock = socket.socket(socket.AF_INET6 if ':' in ip else socket.AF_INET,
                         socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 512 * 1024)
    sock.bind((ip, 0))
    return sock


def roundtrip(udp, dest, address, payload):
    udp.send(b'\0\0\0' + address + payload)
    dest.settimeout(2)
    actual, peer = dest.recvfrom(70000)
    assert actual == payload, ('unexpected forwarded payload', len(actual))
    dest.sendto(actual, peer)
    reply = udp.recv(70000)
    source, offset = decode_bytes(reply[3:])
    assert reply[:3] == b'\0\0\0' and source == dest.getsockname()[:2]
    assert reply[3 + offset:] == payload


def first_peer(port, ip, label, prefix, old_control):
    hint = '::' if ':' in ip else '0.0.0.0'
    with destination(ip) as dest, association((ip, port), hint) as (_, good):
        address = encode(*dest.getsockname()[:2])
        with socket.socket(good.family, socket.SOCK_DGRAM) as other:
            other.bind((ip, 0))
            other.connect(good.getpeername())
            bad_payload = b'invalid-first-' + label.encode()
            other.send(prefix + address + bad_payload)
            observed = drain(dest)
            if old_control:
                assert len(observed) == 1 and observed[0][0] == bad_payload
                good.send(b'\0\0\0' + address + b'correct-port')
                assert not drain(dest), 'Prior peer poisoning was not reproduced'
            else:
                assert not observed, (label, 'invalid first datagram was forwarded')
                # The intended port must still be able to become the peer.
                for payload in (b'correct-port', b'', bytes(2048)):
                    roundtrip(good, dest, address, payload)
                assert not drain(dest, .03) and not drain(good, .03)
    return dict(case='first-peer', ip=ip, header=label,
                negative_control=old_control, passed=True)


def queued(port, ip, hint, domain):
    with destination(ip) as dest, association((ip, port), hint) as (_, udp):
        endpoint = dest.getsockname()[:2]
        address = (b'\3' + bytes([len(ip)]) + ip.encode() + struct.pack('!H', endpoint[1])
                   if domain else encode(*endpoint))
        roundtrip(udp, dest, address, b'establish')
        # More than one ten-message batch, with empty and enlarged payloads.
        for size in (0, 7, 2048):
            for _, prefix in PREFIXES:
                udp.send(prefix + address + bytes(size))
        assert not drain(dest), 'Rejected-only queue delivered a payload'
        expected = [b'marker-one', b'', bytes(2048), b'marker-last']
        for index, payload in enumerate(expected):
            for _, prefix in PREFIXES:
                udp.send(prefix + address + b'bad-' + bytes([index]))
            udp.send(b'\0\0\0' + address + payload)
        actuals = []
        dest.settimeout(2)
        for _ in expected:
            actual, peer = dest.recvfrom(70000)
            actuals.append(actual)
            dest.sendto(actual, peer)
        assert sorted(actuals) == sorted(expected), 'Mixed queue lost or leaked a message'
        replies = []
        for _ in expected:
            reply = udp.recv(70000)
            source, offset = decode_bytes(reply[3:])
            assert reply[:3] == b'\0\0\0' and source == endpoint
            replies.append(reply[3 + offset:])
        assert sorted(replies) == sorted(expected)
        assert not drain(dest, .03) and not drain(udp, .03), 'Unexpected extra datagram'
    return dict(case='rejected-and-mixed-queues', ip=ip, hint=hint, domain=domain,
                invalid_datagrams=42, valid_mixed_datagrams=4, passed=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--old-control', action='store_true')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Assertions are mandatory')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        with tempfile.TemporaryDirectory() as temp:
            for workers in ((1,) if args.old_control else (1, 4)):
                with proxy_server(str(args.binary.resolve()),
                                  Path(temp) / f'header-{workers}.log', workers) as port:
                    for ip in ('127.0.0.1', '::1'):
                        prefixes = (PREFIXES[0], PREFIXES[3]) if args.old_control else PREFIXES
                        for label, prefix in prefixes:
                            row = first_peer(port, ip, label, prefix, args.old_control)
                            row['workers'] = workers
                            rows.append(row)
                        if not args.old_control:
                            for hint in ('known', '::' if ':' in ip else '0.0.0.0'):
                                row = queued(port, ip, hint, False)
                                row['workers'] = workers
                                rows.append(row)
                    if not args.old_control:
                        row = queued(port, '127.0.0.1', 'known', True)
                        row['workers'] = workers
                        rows.append(row)
    finally:
        args.output.write_text(json.dumps(rows, indent=2) + '\n')
    print(json.dumps(dict(passed=True, cases=len(rows), old_control=args.old_control)))


if __name__ == '__main__':
    main()
