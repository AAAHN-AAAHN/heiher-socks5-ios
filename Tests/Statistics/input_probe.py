#!/usr/bin/env python3
"""Actual driver entry boundaries with isolated Git and failing downstream tools.

These fixtures never claim native, SDK or Simulator execution. Exact old blobs
show the formerly accepted input/marker cases; the current source must reject them.
"""
import ast
import errno
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import audit
import ui_audit


def original(module, blob, optimize=0):
    source = subprocess.check_output(['git', '-C', str(audit.ROOT), 'show', blob])
    digest = hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
    if digest != blob:
        raise RuntimeError('Incorrect old driver blob')
    result = SimpleNamespace(__file__=module.__file__, __name__='old_audit_fixture')
    exec(compile(source, module.__file__, 'exec', optimize=optimize), result.__dict__)
    return result


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT)


def repository(root, content='original\n'):
    root.mkdir(parents=True, exist_ok=True)
    git(root, 'init', '-q')
    tracked = root / 'tracked.txt'
    tracked.write_text(content)
    git(root, 'add', '.')
    git(root, '-c', 'user.name=Audit fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '-qm', 'isolated input fixture')
    return tracked


class InputTests(unittest.TestCase):
    def test_statistics_listener_reservation(self):
        blob = 'a5f4f9f58db0fd523956af5f68d626985efcb81e'
        source = subprocess.check_output(['git', '-C', str(audit.ROOT), 'show', blob])
        self.assertEqual(hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest(), blob)
        current = (audit.ROOT / 'Tests/traffic_stats_regression.py').read_bytes()
        for label, content in [('old', source), ('current', current)]:
            definition = next(n for n in ast.parse(content).body
                              if isinstance(n, ast.FunctionDef) and n.name == 'main')
            reservations = [n for n in ast.walk(definition) if isinstance(n, ast.With)
                            and any(isinstance(i.context_expr, ast.Call)
                                    and isinstance(i.context_expr.func, ast.Attribute)
                                    and isinstance(i.context_expr.func.value, ast.Name)
                                    and i.context_expr.func.value.id == 'socket'
                                    and i.context_expr.func.attr == 'socket' for i in n.items)]
            self.assertEqual(len(reservations), 1)
            code = ast.parse('def reserve_port():\n    return port\n')
            code.body[0].body.insert(0, reservations[0])
            for conflict in (False, True):
                with self.subTest(version=label, conflict=conflict), socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as occupied:
                    occupied.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    occupied.bind(('::1', 0))
                    occupied.listen()
                    port = occupied.getsockname()[1]
                    observed = {}
                    class ProbeSocket(socket.socket):
                        def bind(self, address):
                            observed['address'] = address[0]
                            observed['v6only'] = (self.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY)
                                                  if self.family == socket.AF_INET6 else None)
                            return super().bind((address[0], port if conflict else address[1]))
                    scope = {'socket': SimpleNamespace(socket=ProbeSocket, **{
                        name: getattr(socket, name) for name in
                        ('AF_INET6', 'SOCK_STREAM', 'IPPROTO_IPV6', 'IPV6_V6ONLY')})}
                    exec(compile(ast.fix_missing_locations(code), '<actual-statistics-reservation>', 'exec'), scope)
                    if conflict and label == 'current':
                        with self.assertRaises(OSError) as caught:
                            scope['reserve_port']()
                        self.assertEqual(caught.exception.errno, errno.EADDRINUSE)
                    else:
                        selected = scope['reserve_port']()
                        self.assertGreater(selected, 0)
                        if conflict:
                            self.assertEqual(selected, port)
                    expected = {'address': '::', 'v6only': 0} if label == 'current' else {'address': '127.0.0.1', 'v6only': None}
                    self.assertEqual(observed, expected)
        print('PASS: four actual statistics reservation controls; old IPv4-only accepts occupied IPv6 port, current wildcard rejects it')

    def test_native_and_ui_old_current_input(self):
        pairs = [(audit, 'b7e7d7561ea4bd0dd8f4e4858eadf1f1e6a05949', False),
                 (ui_audit, '704462ffeef39df9da7408caacedf2eb3a7cba16', True)]
        for current, blob, ui in pairs:
            for label, module in [('old', original(current, blob)), ('current', current)]:
                for state in ('clean', 'unstaged', 'staged', 'index-only'):
                    with self.subTest(ui=ui, version=label, state=state), tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        tracked = repository(root)
                        if state != 'clean':
                            tracked.write_text('changed\n')
                            if state in ('staged', 'index-only'):
                                git(root, 'add', '.')
                            if state == 'index-only':
                                tracked.write_text('original\n')
                        out = root / 'artifacts'
                        out.mkdir()
                        (out / 'SUCCESS.txt').write_text('old success\n')
                        (out / 'previous.log').write_text('retain\n')
                        entered = []
                        def boundary(*args):
                            entered.append(args)
                            raise RuntimeError('intentionally stop at downstream source/SDK boundary')
                        def run(args, log, *unused, **kwargs):
                            if args[0] != 'git' or '--exit-code' not in args:
                                raise AssertionError('Unexpected command before controlled boundary')
                            git(root, *args[1:])
                        replacements = dict(ROOT=root, OUT=out, CORE=root / 'missing-core', run=run)
                        replacements.update(dict(WORK=root / 'missing-work', output=boundary) if ui else
                                            dict(inspect_sources=boundary))
                        with patch.multiple(module, **replacements), patch.object(module.sys, 'platform', 'darwin'):
                            with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                                module.main()
                        self.assertEqual(bool(entered), label == 'old' or state == 'clean')
                        self.assertFalse((out / 'SUCCESS.txt').exists())
                        self.assertEqual((out / 'previous.log').read_text(), 'retain\n')
        print('PASS: 16 actual native/UI old/current entry cases; dirty tracked input cannot reach downstream checks')

    def test_ui_git_queries_use_source_root(self):
        old = original(ui_audit, '704462ffeef39df9da7408caacedf2eb3a7cba16')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            decoy = Path(directory) / 'unrelated'
            repository(root)
            repository(decoy, 'not the source repository\n')
            for label, module in [('old', old), ('current', ui_audit)]:
                with self.subTest(version=label), patch.object(module, 'ROOT', root):
                    previous = Path.cwd()
                    try:
                        os.chdir(decoy)
                        actual = module.output('git', 'rev-parse', 'HEAD').strip()
                    finally:
                        os.chdir(previous)
                    expected = git(root if label == 'current' else decoy, 'rev-parse', 'HEAD').decode().strip()
                    self.assertEqual(actual, expected)
        print('PASS: two real Git cwd controls; UI output is bound to its source root')

    def test_ui_failed_retry_invalidates_product_markers(self):
        for label in ('old', 'current'):
            for reason in ('workspace', 'optimized'):
                with self.subTest(version=label, reason=reason), tempfile.TemporaryDirectory() as directory:
                    if label == 'old':
                        module = original(ui_audit, '704462ffeef39df9da7408caacedf2eb3a7cba16', int(reason == 'optimized'))
                    else:
                        module = SimpleNamespace(__file__=ui_audit.__file__, __name__='current_ui_fixture')
                        exec(compile(Path(ui_audit.__file__).read_bytes(), ui_audit.__file__, 'exec',
                                     optimize=int(reason == 'optimized')), module.__dict__)
                    out = Path(directory)
                    for name in ('SUCCESS.txt', 'simulator-app-sha256.txt', 'simulator-library-sha256.txt', 'previous.log'):
                        (out / name).write_text('retained prior bytes\n')
                    with patch.multiple(module, OUT=out, WORK=out), patch.object(module.sys, 'platform', 'darwin'):
                        with self.assertRaises(SystemExit):
                            module.main()
                    self.assertFalse((out / 'SUCCESS.txt').exists())
                    for name in ('simulator-app-sha256.txt', 'simulator-library-sha256.txt'):
                        self.assertEqual((out / name).exists(), label == 'old')
                    self.assertEqual((out / 'previous.log').read_text(), 'retained prior bytes\n')
        print('PASS: four actual workspace/optimized old/current marker cases; diagnostic logs preserved')


if __name__ == '__main__':
    unittest.main()
