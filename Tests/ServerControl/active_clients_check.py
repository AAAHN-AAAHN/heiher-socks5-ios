#!/usr/bin/env python3
"""Stop/reconfigure the real controller and Hev with unfinished/blocked clients.

This complements idle start/stop tests. Only the command transport and network
peers are fixtures; neither server state transitions nor engine calls are mocked.
"""
import contextlib
import json
from pathlib import Path
import socket
import socketserver
import struct
import sys
import tempfile
import threading
import time

from native_controller_check import Host, compile_host, receive, stop, wait_auth, authenticate


class Blocked(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.server.accepted.set()
        self.server.release.wait(12)


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try:
            while True:
                data = self.request.recv(8192)
                if not data: return
                self.request.sendall(data)
        except OSError: pass


@contextlib.contextmanager
def destination(handler):
    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler) as server:
        server.daemon_threads = True
        server.accepted, server.release = threading.Event(), threading.Event()
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        thread.start()
        try: yield server
        finally:
            server.release.set(); server.shutdown(); thread.join(timeout=2)


def greeting(sock, user, password):
    sock.sendall(b'\x05\x01\x02'); assert receive(sock, 2) == b'\x05\x02'
    user, password = user.encode(), password.encode()
    sock.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(password)]) + password)
    assert receive(sock, 2) == b'\x01\x00'


def connect_request(sock, port):
    sock.sendall(b'\x05\x01\0\x01\x7f\0\0\x01' + struct.pack('!H', port))
    head = receive(sock, 4); assert head[:3] == b'\x05\0\0'
    assert head[3] in (1, 4)
    receive(sock, 6 if head[3] == 1 else 18)


def expect_closed(sock):
    deadline = time.monotonic() + 3
    sock.settimeout(.2)
    while time.monotonic() < deadline:
        try:
            if not sock.recv(65536): return
        except (ConnectionResetError, BrokenPipeError): return
        except socket.timeout: pass
    raise AssertionError('Old client remained open after controller completed Stop')


def scenario(host, options, reconfigure):
    port = int(options['listenPort'])
    host.request('apply', settings=options, running=True)
    wait_auth(port, options['authUsername'], options['authPassword'])
    with contextlib.ExitStack() as stack:
        echo = stack.enter_context(destination(Echo))
        blocked = stack.enter_context(destination(Blocked))
        clients = []
        def client():
            sock = stack.enter_context(socket.create_connection(('127.0.0.1', port), timeout=1))
            clients.append(sock); return sock
        client()  # No SOCKS greeting yet.
        client().sendall(b'\x05')  # Partial greeting.
        auth = client(); auth.sendall(b'\x05\x01\x02')
        assert receive(auth, 2) == b'\x05\x02'; auth.sendall(b'\x01')
        ready = client(); greeting(ready, 'user', options['authPassword'])
        active = client(); greeting(active, 'user', options['authPassword'])
        connect_request(active, echo.server_address[1]); active.sendall(b'A' * 1024)
        assert receive(active, 1024) == b'A' * 1024
        stalled = client(); greeting(stalled, 'user', options['authPassword'])
        connect_request(stalled, blocked.server_address[1]); assert blocked.accepted.wait(2)
        stalled.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        stalled.settimeout(.1)
        try: stalled.sendall(b'B' * (4 * 1024 * 1024))
        except socket.timeout: pass  # Deliberate backpressure; not a passed write.
        reset = stack.enter_context(socket.create_connection(('127.0.0.1', port), timeout=1))
        reset.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        reset.close()
        started = time.monotonic()
        if reconfigure:
            changed = dict(options, authPassword=options['authPassword'] + 'x')
            host.request('apply', settings=changed, running=True)
            wait_auth(port, 'user', changed['authPassword'])
            assert not authenticate(port, 'user', options['authPassword'])
        else:
            changed = options
            stop(host, options, port)
        for sock in clients: expect_closed(sock)
        elapsed = time.monotonic() - started
        stop(host, changed, port)
        return dict(mode='reconfigure' if reconfigure else 'stop', oldClientsClosed=len(clients),
                    resetClient=True, blockedDestination=True, seconds=round(elapsed, 4))


def main():
    if not __debug__: raise SystemExit('Assertions required')
    core, output = (Path(p).resolve() for p in sys.argv[1:3])
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        with (output / 'build.log').open('wb') as log: executable = compile_host(core, folder, False, log)
        for workers in (1, 4):
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
            options = dict(workers=str(workers), listenAddress='127.0.0.1', listenPort=str(port),
                udpListenAddress='', udpListenPort='0', bindIPv4Address='0.0.0.0', bindIPv6Address='::',
                bindInterface='', authUsername='user', authPassword='password', listenIPv6Only=False)
            with (output / f'workers-{workers}.log').open('wb') as log:
                host = Host(executable, log)
                try:
                    for cycle in range(3):
                        for reconfigure in (False, True):
                            row = scenario(host, options, reconfigure)
                            row.update(workers=workers, cycle=cycle)
                            results.append(row); print(json.dumps(row), flush=True)
                finally: host.close()
    assert len(results) == 12
    (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print('PASS: 12 real active-client termination/reconfiguration scenarios; native-host test, not physical iOS.')


if __name__ == '__main__': main()
