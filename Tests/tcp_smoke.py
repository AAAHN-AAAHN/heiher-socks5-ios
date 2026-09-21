#!/usr/bin/env python3
"""A small real SOCKS5/TCP round trip for every composition, with bounded waits."""
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time


def read(sock, count):
    data = b''
    while len(data) < count:
        part = sock.recv(count - len(data))
        if not part:
            raise EOFError('SOCKS connection closed')
        data += part
    return data


with tempfile.TemporaryDirectory() as directory, socket.socket() as echo:
    echo.bind(('127.0.0.1', 0))
    echo.listen()
    echo.settimeout(8)
    def serve():
        client, _ = echo.accept()
        with client:
            client.settimeout(5)
            client.sendall(read(client, 12))
    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    config = Path(directory) / 'main.yml'
    config.write_text(f'main:\n  workers: 2\n  listen-address: "127.0.0.1"\n  port: {port}\n')
    process = subprocess.Popen([str(Path(sys.argv[1]).resolve()), str(config)], stdout=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                client = socket.create_connection(('127.0.0.1', port), .1)
                break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError('Server exited at startup')
                time.sleep(.02)
        else:
            raise TimeoutError('Server startup deadline')
        with client:
            client.settimeout(5)
            client.sendall(b'\x05\x01\x00')
            assert read(client, 2) == b'\x05\x00'
            client.sendall(b'\x05\x01\x00\x01' + socket.inet_aton('127.0.0.1') + struct.pack('!H', echo.getsockname()[1]))
            response = read(client, 4)
            assert response[:3] == b'\x05\x00\x00'
            read(client, (4 if response[3] == 1 else 16) + 2)
            client.sendall(b'socks5-audit')
            assert read(client, 12) == b'socks5-audit'
        worker.join(timeout=6)
        assert not worker.is_alive()
        print('PASS: actual native SOCKS5 TCP echo')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
