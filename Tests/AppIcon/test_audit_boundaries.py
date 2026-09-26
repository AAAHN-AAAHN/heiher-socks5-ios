#!/usr/bin/env python3
"""Exact-old/current audit boundaries; fixtures never stand in for Apple runs."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

import check_compiled as current
import check_icon

ROOT = check_icon.ROOT
OLD_SHELL = 'a4bb1716ecd584ecfcb402f5a4380a6b01a3ddcc'
OLD_COMPILED = 'ce6469ac03826389da0fc28ebe7ca799bc5cc984'


def original(sha):
    data = check_icon.git('show', sha)
    identity = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if identity != sha:
        raise RuntimeError('Wrong exact-old boundary source')
    return data


def old_module():
    module = types.ModuleType('old_icon_compiled')
    exec(compile(original(OLD_COMPILED), '<exact-old-compiled>', 'exec'), module.__dict__)
    return module


class AuditBoundaries(unittest.TestCase):
    def test_input_and_retry_markers(self):
        real_git = shutil.which('git')
        self.assertIsNotNone(real_git)
        for entry, sha in [('run_checks.sh', OLD_SHELL), ('check_compiled.py', OLD_COMPILED)]:
            for version in ('old', 'current'):
                source = original(sha) if version == 'old' else (ROOT / 'Tests/AppIcon' / entry).read_bytes()
                for state in ('clean', 'unstaged', 'staged', 'index-only', 'optimized'):
                    with self.subTest(entry=entry, version=version, state=state), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        path = root / 'Tests/AppIcon' / entry
                        path.parent.mkdir(parents=True)
                        path.write_bytes(source)
                        shutil.copyfile(ROOT / 'Tests/AppIcon/check_icon.py', path.parent / 'check_icon.py')
                        tracked = root / 'tracked.txt'
                        tracked.write_text('original\n')
                        def git(*args):
                            return subprocess.check_output([real_git, '-C', str(root), *args], stderr=subprocess.STDOUT)
                        git('init', '-q')
                        git('add', '.')
                        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '-qm', 'isolated fixture')
                        if state in ('unstaged', 'staged', 'index-only'):
                            tracked.write_text('modified\n')
                            if state != 'unstaged':
                                git('add', 'tracked.txt')
                            if state == 'index-only':
                                tracked.write_text('original\n')
                        out = root / 'artifacts/icon-checks'
                        out.mkdir(parents=True)
                        for name in ('SUCCESS.txt', 'simulator-results.json'):
                            (out / name).write_text('PRIOR SUCCESS\n')
                        (out / 'previous.log').write_text('preserve diagnostics\n')
                        tools = root / 'tools'
                        tools.mkdir()
                        boundary = root / 'boundary'
                        (tools / 'git').write_text('#!/bin/sh\nif [ "$1" = archive ]; then\n'
                            '  printf reached > "$BOUNDARY"\n  exit 23\nfi\nexec ' + real_git + ' "$@"\n')
                        (tools / 'xcrun').write_text('#!/bin/sh\nprintf reached > "$BOUNDARY"\nexit 23\n')
                        for tool in tools.iterdir():
                            tool.chmod(0o755)
                        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                                   BOUNDARY=str(boundary), PYTHONOPTIMIZE='1' if state == 'optimized' else '')
                        command = ['bash' if entry.endswith('.sh') else sys.executable, str(path)]
                        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=15)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(boundary.exists(), version == 'old' or state == 'clean')
                        self.assertEqual((out / 'SUCCESS.txt').exists(), version == 'old' and entry.endswith('.py'))
                        self.assertEqual((out / 'simulator-results.json').exists(), version == 'old')
                        self.assertEqual((out / 'previous.log').read_text(), 'preserve diagnostics\n')
        print('PASS: 20 old/current entry cases; clean/dirty/index/optimization and stale verdicts')

    def test_compiled_reference_names(self):
        old = old_module()
        info = {key: {'CFBundlePrimaryIcon': {'CFBundleIconName': 'AppIcon',
                                            'CFBundleIconFiles': ['AppIcon60x60']}}
                for key in ('CFBundleIcons', 'CFBundleIcons~ipad')}
        cases = [('AppIcon60x60.png', False, False, True),
                 ('AppIcon60x60@2x.png', False, False, True),
                 ('AppIcon60x60@3x~iphone.png', False, False, True),
                 ('AppIcon60x60@2x~ipad.png', False, False, True),
                 ('AppIcon60x60WRONG.png', False, False, False),
                 ('AppIcon60x60@4x.png', False, False, False),
                 ('AppIcon60x60@2x.png', True, False, False),
                 ('AppIcon60x60@2x.png', False, True, False)]
        data = (ROOT / check_icon.CATALOG / 'AppIcon.png').read_bytes()
        for filename, directory, empty, valid in cases:
            with self.subTest(filename=filename, directory=directory, empty=empty), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                (folder / 'Assets.car').write_bytes(b'fixture; not a compiled catalog')
                path = folder / filename
                if directory:
                    path.mkdir()
                else:
                    path.write_bytes(data)
                value = copy.deepcopy(info)
                if empty:
                    value['CFBundleIcons']['CFBundlePrimaryIcon']['CFBundleIconFiles'] = ['']
                old.compiled(folder, value)
                if valid:
                    self.assertTrue(current.compiled(folder, value))
                else:
                    with self.assertRaises(ValueError):
                        current.compiled(folder, value)
        print('PASS: 8 filename cases; four genuine variants and four exact-old false accepts')

    def test_catalog_rendition_contract(self):
        tree = ast.parse(original(OLD_COMPILED))
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and any(isinstance(a, ast.Constant) and a.value == 'CAR missing AppIcon renditions'
                            for a in node.value.args))
        expression = compile(ast.Module(body=[node], type_ignores=[]), '<old-CAR-check>', 'exec')
        good = [{'Name': 'AppIcon', 'AssetType': 'Icon Image', 'Idiom': idiom,
                 'PixelWidth': 1024, 'PixelHeight': 1024, 'Opaque': True} for idiom in ('phone', 'pad')]
        cases = [('good', good, True, True), ('empty', [], False, False),
                 ('name-substring', [dict(x, Name='NotAppIcon') for x in good], True, False),
                 ('not-icon-images', [dict(x, AssetType='MultiSized Image') for x in good], True, False),
                 ('missing-pad', good[:1], True, False),
                 ('wrong-width', [dict(x, PixelWidth=512) for x in good], True, False),
                 ('wrong-height', [dict(x, PixelHeight=512) for x in good], True, False),
                 ('transparency', [dict(x, Opaque=False) for x in good], True, False)]
        for label, value, old_accepts, accepts in cases:
            with self.subTest(label=label):
                def old_check():
                    exec(expression, {'require': check_icon.require, 'json': json, 'assetinfo': json.dumps(value)})
                if old_accepts:
                    old_check()
                else:
                    with self.assertRaises(ValueError):
                        old_check()
                if accepts:
                    current.catalog_renditions(value)
                else:
                    with self.assertRaises(ValueError):
                        current.catalog_renditions(value)
        print('PASS: 8 CAR metadata cases; six exact-old false accepts rejected')

    def test_command_working_directory(self):
        for version in ('old', 'current'):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                module = old_module() if version == 'old' else types.ModuleType('current_fixture')
                if version == 'current':
                    exec(compile((ROOT / 'Tests/AppIcon/check_compiled.py').read_bytes(),
                                 '<current-fixture>', 'exec'), module.__dict__)
                module.OUT = Path(tmp)
                module.ROOT = Path(tmp)
                here = module.run(sys.executable, '-c', 'import os; print(os.getcwd())')
                self.assertEqual(Path(here).resolve(), Path.cwd().resolve() if version == 'old' else Path(tmp).resolve())
        print('PASS: 2 actual command working-directory controls')


if __name__ == '__main__':
    unittest.main(verbosity=2)
