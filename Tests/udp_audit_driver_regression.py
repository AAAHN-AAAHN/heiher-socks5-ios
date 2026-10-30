#!/usr/bin/env python3
"""UDP audit failure evidence and real-socket startup reservation regressions."""
import ast
import errno
import hashlib
import json
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
    def test_repeated_stage_logs_preserve_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch.object(audit, 'OUT', out):
                audit.run([sys.executable, '-c', 'print("earlier-stage")'], 'build.log')
                with self.assertRaises(subprocess.CalledProcessError) as failure:
                    audit.run([sys.executable, '-c',
                               'print("failed-stage"); raise SystemExit(7)'], 'build.log')
            self.assertEqual(failure.exception.returncode, 7)
            text = (out / 'build.log').read_text()
            self.assertIn('\nearlier-stage\n', text)
            self.assertIn('\nfailed-stage\n', text)

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


    def test_actual_single_unknown_ipv6_failure_is_not_an_observation(self):
        # Actual run40970758829/attempt1, Integrated94c24d1, helperfae8d91.
        # Artifact12942504617 SHA256:
        # 73000e1238c591c89ce651ac26d9c169b2a11c274e308bee4f76b714e927f360
        # Member: integrated/native/udp-buffered/limit-fixed-unknown-1.json
        rows = [{'test': 'UDP 127.0.0.1 hint=0.0.0.0, six payloads', 'passed': True},
         {'test': 'UDP 127.0.0.1 hint=::1, six payloads', 'passed': True},
         {'test': 'UDP 127.0.0.1 hint=known, six payloads', 'passed': True},
         {'test': 'UDP ::1 hint=::, six payloads',
          'passed': False,
          'error': 'AssertionError: UDP/TCP setup REP=0x01'},
         {'test': 'UDP ::1 hint=known, six payloads', 'passed': True},
         {'test': 'UDP 127.0.0.1 closed destination preserves association', 'passed': True},
         {'test': 'UDP ::1 closed destination preserves association', 'passed': True},
         {'test': 'UDP three associations and one closed',
          'passed': False,
          'error': 'TimeoutError: timed out'},
         {'test': 'UDP three 24-datagram bursts, unordered replies', 'passed': True},
         {'test': 'TCP echo 127.0.0.1', 'passed': True},
         {'test': 'TCP echo ::1', 'passed': True}]
        recorded = (json.dumps(rows, indent=2) + '\n').encode()
        self.assertEqual(hashlib.sha256(recorded).hexdigest(),
                         'a66743e97bc6ac3a3f634704083b55c610442cbda5a8f5f5a3e9ac2901c12c3f')
        blob = '7a11d2e4d83f7057ddc509c8ccc06e6bbe7a7ee4'
        source = subprocess.check_output(['git', '-C', str(audit.ROOT), 'show', blob])
        self.assertEqual(hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest(), blob)
        old = SimpleNamespace(__file__=audit.__file__, __name__='udp_audit_before_observation_scope')
        exec(compile(source, audit.__file__, 'exec'), old.__dict__)
        for label, module in [('old', old), ('current', audit)]:
            with self.subTest(version=label), tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                def replay(args, name, cwd=None, timeout=180):
                    self.assertEqual(timeout, 90)
                    self.assertIn('--allow-failures', args)
                    Path(args[args.index('--output') + 1]).write_bytes(recorded)
                with patch.multiple(module, OUT=out, CORE=out / 'unused-core', SUMMARY=[]), patch.object(
                        module, 'run', side_effect=replay) as run:
                    options = ('--fixed-udp-port', '--workers', '1')
                    if label == 'old':
                        self.assertEqual(module.network('limit-fixed-unknown-1', *options, observation=True), rows)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'outside the fixed-unknown') as failure:
                            module.network('limit-fixed-unknown-1', *options, observation=True)
                        self.assertIn('UDP ::1 hint=::, six payloads', str(failure.exception))
                        self.assertIn('AssertionError: UDP/TCP setup REP=0x01', str(failure.exception))
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(module.SUMMARY[-1]['failed'], [row for row in rows if not row['passed']])
                    self.assertEqual((out / 'limit-fixed-unknown-1.json').read_bytes(), recorded)


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
                          if isinstance(n, ast.FunctionDef) and n.name == getattr(self, 'function_name', 'proxy_server'))
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


class InputIdentityTests(unittest.TestCase):
    def test_actual_old_and_current_input_boundaries(self):
        blob = 'a55059641f821e62adb19f4a30ec31fa2f337a9d'
        source = subprocess.check_output(['git', '-C', str(audit.ROOT), 'show', blob])
        self.assertEqual(hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest(), blob)
        old = SimpleNamespace(__file__=audit.__file__, __name__='old_udp_audit')
        exec(compile(source, audit.__file__, 'exec'), old.__dict__)
        for label, module in [('old', old), ('current', audit)]:
            for state in ('clean', 'unstaged', 'staged', 'index-only'):
                with self.subTest(version=label, state=state), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    def git(*args):
                        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT)
                    git('init', '-q')
                    tracked = root / 'tracked.txt'
                    tracked.write_text('original\n')
                    git('add', '.')
                    git('-c', 'user.name=Audit fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '-qm', 'isolated input fixture')
                    if state != 'clean':
                        tracked.write_text('changed\n')
                        if state in ('staged', 'index-only'):
                            git('add', '.')
                        if state == 'index-only':
                            tracked.write_text('original\n')
                    out = root / 'artifacts'
                    out.mkdir()
                    (out / 'SUCCESS.txt').write_text('old success\n')
                    (out / 'previous.log').write_text('retain\n')
                    entered = []
                    def run(args, name, cwd=None, timeout=180):
                        if args[0] == 'git' and '--exit-code' in args:
                            git(*args[1:])
                        else:
                            entered.append(name)
                            raise RuntimeError('stop at first downstream source command')
                    with patch.multiple(module, ROOT=root, OUT=out, CORE=root / 'missing-core', run=run):
                        with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                            module.main()
                    self.assertEqual(bool(entered), label == 'old' or state == 'clean')
                    self.assertFalse((out / 'SUCCESS.txt').exists())
                    self.assertEqual((out / 'previous.log').read_text(), 'retain\n')
        print('PASS: 8 actual old/current input boundaries; real Git rejects working/index drift before downstream checks')


class PeerPortReservationTests(PortReservationTests):
    function_name = 'proxy'

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).with_name('udp_peer_regression.py')
        cls.current = path.read_bytes()
        blob = '81453ee580930a91ec926c99c852d31e888e7661'
        cls.original = subprocess.check_output(['git', '-C', str(path.parent), 'show', blob])
        if hashlib.sha1(b'blob ' + str(len(cls.original)).encode() + b'\0' + cls.original).hexdigest() != blob:
            raise RuntimeError('Wrong original peer-test source')


if __name__ == '__main__':
    unittest.main()
