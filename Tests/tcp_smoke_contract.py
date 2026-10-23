#!/usr/bin/env python3
"""Exercise the real smoke script against controlled local SOCKS replies."""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = 'd28fb652d0e4c6a9c96199908b21f5b1cc668a1f'
PASS = 'PASS: actual native SOCKS5 TCP echo'


def read(sock, length):
    data = b''
    while len(data) < length:
        part = sock.recv(length - len(data))
        if not part:
            raise EOFError('Peer closed')
        data += part
    return data


def server(config, case):
    # Invoked as the executable that the smoke script launches and owns.
    Path('server.pid').write_text(str(os.getpid()))
    port = int(config.read_text().split('port: ')[1].strip())
    replies = {'ipv4': b'\x01' + bytes(4), 'ipv6': b'\x04' + bytes(16),
               'domain': b'\x03\x09localhost', 'invalid': b'\xff' + bytes(16),
               'empty-domain': b'\x03\x00'}
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', port))
        listener.listen()
        listener.settimeout(8)
        with listener.accept()[0] as client:
            client.settimeout(5)
            assert read(client, 3) == b'\x05\x01\x00'
            client.sendall(b'\x05\x00')
            request = read(client, 10)
            address = socket.inet_ntoa(request[4:8]), struct.unpack('!H', request[8:])[0]
            client.sendall(b'\x05\x00\x00' + replies.get(case, replies['ipv4']) + bytes(2))
            payload = read(client, 12)
            with socket.create_connection(address, 3) as echo:
                echo.settimeout(5)
                if case == 'worker-eof':
                    echo.sendall(b'bad')
                    echo.shutdown(socket.SHUT_WR)
                    assert echo.recv(12) == b''
                else:
                    echo.sendall(payload)
                    assert read(echo, 12) == payload
            client.sendall(bytes(12) if case == 'wrong-payload' else payload)


def main():
    previous = subprocess.check_output(['git', '-C', str(ROOT), 'show', PREVIOUS + ':Tests/tcp_smoke.py'])
    current = (ROOT / 'Tests/tcp_smoke.py').read_bytes()
    rows = []
    for label, source in (('previous', previous), ('current', current)):
        for case in ('ipv4', 'ipv6', 'domain', 'invalid', 'worker-eof', 'wrong-payload', 'empty-domain'):
            with tempfile.TemporaryDirectory(prefix='tcp-smoke-contract-') as directory:
                root = Path(directory)
                (root / 'smoke.py').write_bytes(source)
                executable = root / 'server'
                executable.write_text('#!' + sys.executable + '\n' + Path(__file__).read_text())
                executable.chmod(0o755)
                result = subprocess.run([sys.executable, str(root / 'smoke.py'), str(executable)],
                                        cwd=root, env=dict(os.environ, SOCKS_SMOKE_CASE=case),
                                        capture_output=True, text=True, timeout=20)
                expected = case in (('ipv4', 'ipv6', 'invalid', 'worker-eof') if label == 'previous'
                                    else ('ipv4', 'ipv6', 'domain'))
                if (result.returncode == 0) != expected or (PASS in result.stdout) != expected:
                    raise RuntimeError((label, case, result.returncode, result.stdout, result.stderr))
                if label == 'current' and not expected:
                    reason = {'invalid': 'Invalid SOCKS reply address type',
                              'worker-eof': 'Echo worker did not complete the round trip',
                              'empty-domain': 'Empty SOCKS reply domain',
                              'wrong-payload': 'AssertionError'}[case]
                    if reason not in result.stderr:
                        raise RuntimeError(('Wrong rejection', case, result.stderr))
                pid = int((root / 'server.pid').read_text())
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise RuntimeError('Smoke left its server alive')
                rows.append({'source': label, 'source_sha256': hashlib.sha256(source).hexdigest(),
                             'case': case, 'accepted': expected, 'returncode': result.returncode,
                             'stdout': result.stdout, 'stderr': result.stderr, 'child_reaped': True})
    print(json.dumps({'result': 'PASS', 'cases': rows,
                      'scope': 'Controlled local sockets; not a native-engine or iOS execution'}, indent=2))


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    if len(sys.argv) == 2:
        server(Path(sys.argv[1]), os.environ['SOCKS_SMOKE_CASE'])
    else:
        main()
