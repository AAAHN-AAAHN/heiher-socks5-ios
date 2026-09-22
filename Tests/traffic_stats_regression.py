#!/usr/bin/env python3
"""Native socket tests for external-side totals; no Internet or UI is used."""
import concurrent.futures
import contextlib
import json
import pathlib
import select
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

from udp_sockaddr_regression import association, echo_server, encode, exact, exchange, handshake


class Asymmetric(socketserver.BaseRequestHandler):
    def handle(self):
        received = bytearray()
        while True:
            chunk = self.request.recv(1021)
            if not chunk:
                break
            received.extend(chunk)
        self.server.actual = bytes(received)
        self.request.sendall(self.server.reply)


class Sink(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.arrived.set()


class Host:
    def __init__(self, binary, config):
        self.proc = subprocess.Popen([binary, str(config)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=sys.stderr, text=True,
                                     bufsize=1)
        assert self.proc.stdout.readline().strip() == 'LOCK_FREE 1'

    def stats(self, command='stats'):
        self.proc.stdin.write(command + '\n')
        self.proc.stdin.flush()
        if not select.select([self.proc.stdout], [], [], 5)[0]:
            raise TimeoutError('Native statistics API timed out')
        row = self.proc.stdout.readline().split()
        assert row[0] == 'STATS', row
        return tuple(map(int, row[1:]))

    def close(self):
        try:
            self.proc.communicate('quit\n', timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def wait_server(port):
    for _ in range(100):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1):
                return
        except OSError:
            time.sleep(.02)
    raise TimeoutError('Server did not start')


def check_delta(host, before, received, sent):
    expected = before[0] + received, before[1] + sent
    for _ in range(100):
        actual = host.stats()
        if actual == expected:
            return
        assert actual[0] <= expected[0] and actual[1] <= expected[1], (actual, expected)
        time.sleep(.01)
    raise AssertionError((actual, expected))


def main():
    results = []
    def passed(name):
        results.append({'test': name, 'passed': True})
        print(json.dumps(results[-1]), flush=True)

    with contextlib.ExitStack() as stack:
        temp = stack.enter_context(tempfile.TemporaryDirectory())
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        config = pathlib.Path(temp) / 'test.yml'
        config.write_text("""main:
  workers: 4
  port: %d
  listen-address: '::'
  listen-ipv6-only: false
  udp-port: 0
  bind-address-v4: '0.0.0.0'
  bind-address-v6: '::'
misc:
  log-level: error
""" % port)
        host = Host(str(pathlib.Path(sys.argv[1]).resolve()), config)
        stack.callback(host.close)
        wait_server(port)
        assert host.stats() == (0, 0)
        passed('Lock-free 64-bit counters; zero before payload')
        for address, hint in [('127.0.0.1', '0.0.0.0'), ('127.0.0.1', 'known'),
                              ('::1', '::'), ('::1', 'known')]:
            destination = stack.enter_context(echo_server(address))
            before = host.stats()
            with association((address, port), hint) as (_, udp):
                assert host.stats() == before, 'SOCKS handshake was counted'
                for size in (1, 64, 512, 1200, 1400, 64):
                    exchange(udp, destination, size)
            check_delta(host, before, 3241, 3241)
            passed('UDP exact payload, header exclusion and source: ' + address + ' / ' + hint)

        # Distinct directions: IN must not merely mirror OUT or the client-side read.
        with socketserver.ThreadingTCPServer(('127.0.0.1', 0), Asymmetric) as server:
            server.reply = b'R' * 17003
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            before = host.stats()
            upload = b'U' * 98317
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=5) as tcp:
                    handshake(tcp, 1, server.server_address)
                    tcp.sendall(upload)
                    tcp.shutdown(socket.SHUT_WR)
                    assert exact(tcp, len(server.reply)) == server.reply
                assert server.actual == upload
                check_delta(host, before, len(server.reply), len(upload))
                passed('TCP asymmetric directions, multi-buffer transfer and half-close')
            finally:
                server.shutdown()
                thread.join()

        # UDP transmit accepted by the external socket, even with no reply.
        with socketserver.UDPServer(('127.0.0.1', 0), Sink) as server:
            server.arrived = threading.Event()
            thread = threading.Thread(target=server.handle_request, daemon=True)
            server.timeout = 2
            thread.start()
            before = host.stats()
            with association(('127.0.0.1', port), '0.0.0.0') as (_, udp):
                udp.send(b'\0\0\0' + encode(*server.server_address) + b'x' * 137)
                assert server.arrived.wait(2)
                check_delta(host, before, 0, 137)
            thread.join()
            passed('UDP one-way OUT without artificial IN or delivery acknowledgement')

        udp_echo = stack.enter_context(echo_server('127.0.0.1'))
        tcp_echo = stack.enter_context(echo_server('::1', udp=False))
        before = host.stats()
        def transfer(index):
            if index % 2:
                with association(('127.0.0.1', port), '0.0.0.0') as (_, udp):
                    for _ in range(20):
                        exchange(udp, udp_echo, 1000)
                return 20000
            with socket.create_connection(('127.0.0.1', port), timeout=5) as tcp:
                handshake(tcp, 1, tcp_echo)
                payload = bytes([index]) * 65539
                tcp.sendall(payload)
                assert exact(tcp, len(payload)) == payload
                return len(payload)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            amounts = list(pool.map(transfer, range(8)))
        check_delta(host, before, sum(amounts), sum(amounts))
        passed('Concurrent TCP/UDP across four native workers: no lost or doubled bytes')
        before = host.stats()
        time.sleep(.1)
        assert host.stats() == before
        passed('Idle and statistics queries do not add network bytes')
        assert host.stats('restart') == before
        wait_server(port)
        with association(('127.0.0.1', port), '0.0.0.0') as (_, udp):
            exchange(udp, udp_echo, 73)
        check_delta(host, before, 73, 73)
        passed('Process-lifetime totals survive server stop/start without reset races')
    print('SUMMARY: %d passed, 0 failed' % len(results), flush=True)


if __name__ == '__main__':
    main()
