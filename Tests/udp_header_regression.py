#!/usr/bin/env python3
"""Real loopback request/UDP headers, first-peer safety and CONNECT replies."""
import argparse
import json
from pathlib import Path
import socket
import struct
import tempfile
import time

from udp_sockaddr_regression import association, decode_bytes, encode, exact, proxy_server


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


def setup_reserved(port, ip):
    """TCP request RSV validation, independently of datagram RSV/FRAG."""
    hint = '::' if ':' in ip else '0.0.0.0'
    responses, closes = [], []
    with destination(ip) as dest:
        address = encode(*dest.getsockname()[:2])
        for reserved in (0, 1, 255):
            with socket.create_connection((ip, port), timeout=2) as control:
                control.sendall(b'\x05\x01\x00')
                assert exact(control, 2) == b'\x05\x00'
                control.sendall(bytes([5, 3, reserved]) + encode(hint, 0))
                head = exact(control, 4)
                assert (head[0], head[2]) == (5, 0), 'Invalid setup reply header'
                assert head[3] in (1, 4), 'Invalid setup reply address type'
                tail = exact(control, {1: 4, 4: 16}[head[3]] + 2)
                relay, _ = decode_bytes(head[3:] + tail)
                responses.append(dict(reserved=reserved, reply=(head + tail).hex()))
                assert head[1] == (1 if reserved else 0), ('setup RSV accepted', reserved, head[1])
                if reserved:
                    try:
                        assert control.recv(1) == b'', 'Rejected setup did not close'
                        closes.append('EOF')
                    except ConnectionResetError:
                        closes.append('RST')
                else:
                    assert relay[0] == ip and relay[1], ('Unusable relay', relay)
                    with destination(ip) as udp:
                        udp.settimeout(2)
                        udp.connect(relay)
                        roundtrip(udp, dest, address, b'setup-RSV-zero')
            if reserved:
                # Each malformed setup is followed by an independent valid one.
                with association((ip, port), hint) as (_, udp):
                    roundtrip(udp, dest, address, b'after-bad-setup-' + bytes([reserved]))
    return dict(case='setup-request-reserved', ip=ip, responses=responses,
                rejected_control_closes=closes, normal_roundtrips=3, passed=True)


def connect_bound(port, control_ip, target_ip, domain):
    """The target's accepted peer is the independent oracle for CONNECT BND."""
    family = socket.AF_INET6 if ':' in target_ip else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as target:
        target.bind((target_ip, 0))
        target.listen(1)
        target.settimeout(2)
        endpoint = target.getsockname()[:2]
        address = (b'\3' + bytes([len(target_ip)]) + target_ip.encode() +
                   struct.pack('!H', endpoint[1]) if domain else encode(*endpoint))
        with socket.create_connection((control_ip, port), timeout=2) as control:
            control.sendall(b'\5\1\0')
            assert exact(control, 2) == b'\5\0'
            control.sendall(b'\5\1\0' + address)
            head = exact(control, 4)
            assert head[:3] == b'\5\0\0' and head[3] in (1, 4), 'Invalid CONNECT reply'
            tail = exact(control, {1: 6, 4: 18}[head[3]])
            bound, _ = decode_bytes(head[3:] + tail)
            accepted, peer = target.accept()
            with accepted:
                accepted.settimeout(2)
                assert bound == peer[:2], ('CONNECT BND differs from actual peer', bound, peer)
                payload = bytes(range(256)) * 16
                control.sendall(payload)
                assert exact(accepted, len(payload)) == payload
                accepted.sendall(payload[::-1])
                assert exact(control, len(payload)) == payload[::-1]
    return dict(case='connect-bound-address', control_ip=control_ip, target_ip=target_ip,
                domain=domain, reported_bound=bound, actual_peer=peer[:2],
                duplex_payload_bytes=len(payload), passed=True)


def first_peer(port, ip, label, prefix, old_control, empty_name=False):
    hint = '::' if ':' in ip else '0.0.0.0'
    with destination(ip) as dest, association((ip, port), hint) as (_, good):
        address = encode(*dest.getsockname()[:2])
        with socket.socket(good.family, socket.SOCK_DGRAM) as other:
            other.bind((ip, 0))
            other.connect(good.getpeername())
            bad_payload = b'invalid-first-' + label.encode()
            bad_address = (b'\3\0' + struct.pack('!H', dest.getsockname()[1])
                           if empty_name else address)
            other.send(prefix + bad_address + bad_payload)
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
                        if not args.old_control:
                            row = setup_reserved(port, ip)
                            row['workers'] = workers
                            rows.append(row)
                        prefixes = (PREFIXES[0], PREFIXES[3]) if args.old_control else PREFIXES
                        for label, prefix in prefixes:
                            row = first_peer(port, ip, label, prefix, args.old_control)
                            row['workers'] = workers
                            rows.append(row)
                        if not args.old_control:
                            row = first_peer(port, ip, 'empty-NAME', b'\0\0\0', False,
                                             empty_name=True)
                            row['workers'] = workers
                            rows.append(row)
                            for target in ('127.0.0.1', '::1'):
                                for domain in (False, True):
                                    row = connect_bound(port, ip, target, domain)
                                    row['workers'] = workers
                                    rows.append(row)
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
