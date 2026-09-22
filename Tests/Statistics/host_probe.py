#!/usr/bin/env python3
"""Check real pipe framing and deadlines without starting the SOCKS5 engine."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from traffic_stats_regression import Host


def check(program, expected):
    host = Host.__new__(Host)
    host.output = b''
    host.proc = subprocess.Popen([sys.executable, '-S', '-u', '-c', program],
                                 stdout=subprocess.PIPE)
    try:
        if isinstance(expected, list):
            assert [host.readline(2) for _ in expected] == expected
        else:
            try:
                host.readline(2)
            except expected:
                pass
            else:
                raise AssertionError('Expected ' + expected.__name__)
    finally:
        if host.proc.poll() is None:
            host.proc.kill()
        host.proc.wait(timeout=5)
        host.proc.stdout.close()


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions are required.')
    check(r"import os; os.write(1, b'FIRST\nSECOND\n')", ['FIRST', 'SECOND'])
    check(r"import os,time; os.write(1, b'PAR'); time.sleep(.05); os.write(1, b'TIAL\n')", ['PARTIAL'])
    check("import time; time.sleep(60)", TimeoutError)
    check(r"import os,time; os.write(1, b'NO_NEWLINE'); time.sleep(60)", TimeoutError)
    check("pass", EOFError)
    check(r"import os; os.write(1, b'x' * 4096)", ValueError)
    print('PASS: six host-response cases: framing, fragmented line, silence, partial-line deadline, EOF and size bound')
