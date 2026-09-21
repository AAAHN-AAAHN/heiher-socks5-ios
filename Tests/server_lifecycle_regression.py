#!/usr/bin/env python3
"""Bound the real stop-before-start probe so a blocked worker fails the test."""
from pathlib import Path
import socket
import subprocess
import sys

binary = str(Path(sys.argv[1]).resolve())
for workers in (1, 4):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    result = subprocess.run([binary, str(workers), str(port)], timeout=15, check=True,
                            text=True, capture_output=True)
    print(f'workers={workers}: {result.stdout.strip()}')
