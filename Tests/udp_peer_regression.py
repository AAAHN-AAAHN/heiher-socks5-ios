#!/usr/bin/env python3
"""Real loopback sender isolation, including pre-connect queued datagrams.

No network outside loopback, packet spoofing, aliases or system settings are used.
The alternate sender uses the other loopback address family on a dual-stack bind.
Negative mode checks the prior two-patch implementation, not a mock of its logic.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import signal
import socket
import socketserver
import subprocess
import tempfile
import threading
import time

from udp_sockaddr_regression import encode, handshake


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        payload, sock = self.request
        with self.server.lock:
            self.server.payloads.append(payload)
        sock.sendto(payload, self.client_address)


@contextlib.contextmanager
def echo_server(host):
    cls = type('EchoServer', (socketserver.UDPServer,),
               {'address_family': socket.AF_INET6 if ':' in host else socket.AF_INET})
    server = cls((host, 0), Echo)
    server.lock = threading.Lock()
    server.payloads = []
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


@contextlib.contextmanager
def proxy(binary, directory, workers):
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as reserve:
        reserve.bind(('::1', 0)); port = reserve.getsockname()[1]
    config = directory / f'peer-{workers}.yml'
    config.write_text(f"main:\n  workers: {workers}\n  port: {port}\n  listen-address: '::'\n"
                      "  listen-ipv6-only: false\n  udp-listen-address: '::'\n  udp-port: 0\n")
    with (directory / f'peer-{workers}.server.log').open('wb') as log:
        process = subprocess.Popen([binary, str(config)], stdout=log, stderr=log)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Proxy exited before test')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.05): break
                except OSError: time.sleep(.02)
            else: raise TimeoutError('Proxy did not listen')
            yield process, port
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGCONT); process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=2)


def datagram(host):
    sock = socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, 0)); sock.settimeout(1)
    return sock


def send(sock, host, port, destination, payload):
    sock.sendto(b'\0\0\0' + encode(*destination) + payload, (host, port))


def first_sender(process, port, host, foreign, echo, vulnerable):
    with socket.create_connection((host, port), timeout=1) as control, datagram(host) as good, datagram(foreign) as bad:
        relay = handshake(control, 3, ('::' if ':' in host else '0.0.0.0', 0))
        destination = echo.server_address[:2]
        before = len(echo.payloads)
        send(bad, foreign, relay[1], destination, b'foreign-first')
        bad.settimeout(.15)
        try: foreign_received = bad.recv(2048).endswith(b'foreign-first')
        except socket.timeout: foreign_received = False
        assert foreign_received == vulnerable, ('foreign accepted', foreign_received, vulnerable)
        send(good, host, relay[1], destination, b'legitimate-after')
        good.settimeout(.3 if vulnerable else 1)
        try: good_received = good.recv(2048).endswith(b'legitimate-after')
        except socket.timeout: good_received = False
        assert good_received != vulnerable, ('legitimate accepted', good_received, vulnerable)
        with echo.lock: delivered = echo.payloads[before:]
        assert delivered == ([b'foreign-first'] if vulnerable else [b'legitimate-after']), delivered
        return {'case': 'foreign first then legitimate', 'controlIP': host,
                'foreignIP': foreign, 'foreignForwarded': foreign_received,
                'legitimateForwarded': good_received, 'negativeControl': vulnerable}


def queued_senders(process, port, host, foreign, echo):
    with socket.create_connection((host, port), timeout=1) as control, datagram(host) as good, datagram(host) as wrong_port, datagram(foreign) as bad:
        relay = handshake(control, 3, ('::' if ':' in host else '0.0.0.0', 0))
        destination = echo.server_address[:2]
        before = len(echo.payloads)
        process.send_signal(signal.SIGSTOP)
        try:
            # First valid packet chooses a port; later batches must not leak packets
            # queued before connect, including other ports at the legitimate IP.
            send(good, host, relay[1], destination, b'first-valid')
            for n in range(24):
                sender, route = (bad, foreign) if n % 2 else (wrong_port, host)
                send(sender, route, relay[1], destination, f'rejected-{n}'.encode())
            send(good, host, relay[1], destination, b'last-valid')
        finally: process.send_signal(signal.SIGCONT)
        replies = [good.recv(2048), good.recv(2048)]
        assert replies[0].endswith(b'first-valid') and replies[1].endswith(b'last-valid')
        time.sleep(.08)
        with echo.lock: delivered = echo.payloads[before:]
        assert delivered == [b'first-valid', b'last-valid'], delivered
        # The accepted association must remain usable after discarding full batches.
        send(good, host, relay[1], destination, b'continuation')
        assert good.recv(2048).endswith(b'continuation')
        return {'case': '26 pre-connect queued packets across batches', 'controlIP': host,
                'delivered': 2, 'discarded': 24, 'continuation': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary'); parser.add_argument('--output', required=True)
    parser.add_argument('--expect-vulnerable', action='store_true')
    args = parser.parse_args()
    if not __debug__: parser.error('Assertions are required')
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for workers in (1, 4):
                with proxy(str(Path(args.binary).resolve()), directory, workers) as (process, port):
                    for host, foreign in [('127.0.0.1', '::1'), ('::1', '127.0.0.1')]:
                        with echo_server(host) as echo:
                            result = first_sender(process, port, host, foreign, echo, args.expect_vulnerable)
                            result['workers'] = workers; rows.append(result); print(json.dumps(result), flush=True)
                            if not args.expect_vulnerable:
                                result = queued_senders(process, port, host, foreign, echo)
                                result['workers'] = workers; rows.append(result); print(json.dumps(result), flush=True)
            assert len(rows) == (4 if args.expect_vulnerable else 8)
    finally: output.write_text(json.dumps(rows, indent=2) + '\n')
    print('PASS: expected old sender-isolation failure reproduced.' if args.expect_vulnerable else
          'PASS: real sender isolation and queued datagram filtering; no external traffic.')


if __name__ == '__main__': main()
