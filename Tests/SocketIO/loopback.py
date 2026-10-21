"""Prepare only the peer addresses used by the real socket-I/O fixtures."""
from contextlib import contextmanager
import re
import socket
import subprocess
import sys

PEERS = ('127.0.0.2', '127.0.0.3', '127.0.0.4')


def command(args):
    print('+', ' '.join(args), flush=True)
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=10)
    if result.stdout:
        print(result.stdout, end='', flush=True)
    result.check_returncode()
    return result.stdout


def aliases():
    return set(re.findall(r'^\s*inet (\S+)', command(['/sbin/ifconfig', 'lo0']), re.M))


def verify_bindings():
    for address in PEERS:
        with socket.socket() as probe:
            probe.bind((address, 0))


@contextmanager
def prepared_loopback():
    """Restore aliases owned by this invocation, including partial setup failure."""
    attempted = []
    primary = None
    try:
        if sys.platform == 'darwin':
            existing = aliases()
            for address in PEERS:
                if address not in existing:
                    # A timed-out command may already have installed the alias.
                    attempted.append(address)
                    command(['sudo', '-n', '/sbin/ifconfig', 'lo0', 'inet',
                             address, 'netmask', '255.255.255.255', 'alias'])
        verify_bindings()
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        if attempted:
            try:
                current = aliases()
            except Exception as error:
                failures.append('cannot inspect lo0 during cleanup: ' + repr(error))
                current = set(attempted)
            for address in reversed(attempted):
                if address in current:
                    try:
                        command(['sudo', '-n', '/sbin/ifconfig', 'lo0', 'inet',
                                 address, '-alias'])
                    except Exception as error:
                        failures.append(address + ': ' + repr(error))
        if failures:
            detail = 'Loopback cleanup failed: ' + '; '.join(failures)
            print(detail, file=sys.stderr, flush=True)
            if primary is None:
                raise RuntimeError(detail)
