#!/usr/bin/env python3
"""UDP audit failure evidence and real-socket startup reservation regressions."""
import ast
import errno
import hashlib
import socket
from types import SimpleNamespace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import udp_compat_audit as audit


class AuditDriverTests(unittest.TestCase):
    def check_failure(self, *, existing_core=False, wrong_composition=False,
                      previous_success=True):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'artifacts'
            core = Path(directory) / 'core'
            if previous_success:
                out.mkdir()
                (out / 'SUCCESS.txt').write_text('Previous successful run\n')
                (out / 'previous.log').write_text('Preserve diagnostic evidence\n')
            if existing_core:
                core.mkdir()
            config = dict(audit.CONFIG)
            if wrong_composition:
                config['features'] = ['udp', 'statistics']
            with patch.multiple(audit, OUT=out, CORE=core, CONFIG=config), patch.object(
                    audit, 'run', side_effect=RuntimeError('source command failed')) as run:
                rejected = existing_core or wrong_composition
                with self.assertRaises(SystemExit if rejected else RuntimeError):
                    audit.main()
                self.assertEqual(run.call_count, 0 if rejected else 1)
            self.assertFalse((out / 'SUCCESS.txt').exists())
            if previous_success:
                self.assertEqual((out / 'previous.log').read_text(), 'Preserve diagnostic evidence\n')

    def test_existing_checkout_invalidates_success(self):
        self.check_failure(existing_core=True)

    def test_wrong_composition_invalidates_success(self):
        self.check_failure(wrong_composition=True)

    def test_failed_command_invalidates_success(self):
        self.check_failure()

    def test_fresh_failure_does_not_publish_success(self):
        self.check_failure(previous_success=False)

    def test_optimized_python_invalidates_success(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'SUCCESS.txt'
            marker.write_text('Previous successful run\n')
            code = ('from pathlib import Path; import udp_compat_audit as audit; '
                    'audit.OUT = Path(' + repr(directory) + '); audit.main()')
            result = subprocess.run([sys.executable, '-O', '-c', code],
                                    cwd=Path(__file__).resolve().parent,
                                    capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Assertions are required', result.stderr)
            self.assertFalse(marker.exists())


class PortReservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).with_name('udp_sockaddr_regression.py')
        cls.current = path.read_bytes()
        blob = 'b91411242c948308c7067fd2aab21ae8b7051513'
        cls.original = subprocess.check_output(['git', '-C', str(path.parent), 'show', blob])
        if hashlib.sha1(b'blob ' + str(len(cls.original)).encode() + b'\0' + cls.original).hexdigest() != blob:
            raise RuntimeError('Wrong original network-test source')

    def reserve(self, source, forced_port=0):
        # Execute the actual first reservation statement, not a rewritten allocator.
        definition = next(n for n in ast.parse(source).body
                          if isinstance(n, ast.FunctionDef) and n.name == 'proxy_server')
        self.assertIsInstance(definition.body[0], ast.With)
        module = ast.parse('def reserve_port():\n    return port\n')
        module.body[0].body.insert(0, definition.body[0])
        observed = {}

        class ProbeSocket:
            def __init__(self, *args):
                self.actual = socket.socket(*args)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.actual.close()

            def __getattr__(self, name):
                return getattr(self.actual, name)

            def bind(self, address):
                observed['address'] = address
                observed['v6only'] = self.actual.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY)
                # Force only the ephemeral port choice to the occupied-port control.
                self.actual.bind((address[0], forced_port or address[1]))

        constants = {name: getattr(socket, name) for name in
                     ('AF_INET6', 'SOCK_STREAM', 'IPPROTO_IPV6', 'IPV6_V6ONLY')}
        scope = {'socket': SimpleNamespace(socket=ProbeSocket, **constants)}
        exec(compile(ast.fix_missing_locations(module), '<actual-reservation>', 'exec'), scope)
        return scope['reserve_port'](), observed

    def test_ipv4_conflict_is_not_a_free_dual_stack_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            self.assertEqual(self.reserve(self.original, port)[0], port)
            with self.assertRaises(OSError) as caught:
                self.reserve(self.current, port)
            self.assertEqual(caught.exception.errno, errno.EADDRINUSE)
        print('PASS: exact old IPv6-loopback reservation accepts an occupied IPv4 port; current wildcard rejects it')

    def test_free_reservation_uses_server_scope(self):
        port, observed = self.reserve(self.current)
        self.assertGreater(port, 0)
        self.assertEqual(observed, {'address': ('::', 0), 'v6only': 0})
        print('PASS: current reservation uses the actual dual-stack wildcard listener scope')


if __name__ == '__main__':
    unittest.main()
