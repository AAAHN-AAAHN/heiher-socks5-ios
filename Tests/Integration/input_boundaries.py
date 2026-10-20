#!/usr/bin/env python3
"""Exercise release shell guards and generated-input identity using local fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Build'))
import release_source as product


def load(path):
    spec = importlib.util.spec_from_file_location('server_input_cases', ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    driver = load('Tests/ServerControl/input_integrity_check.py')
    originals = {
        'Build/build.sh': '4a6d2809a52ad7e71a71a68332147122cabf4e5e',
        'Build/check_swift_sdk.sh': 'f866730b0de75f9d2aaf17800b8fed9c2619ae79'}
    count = 0
    for entry in ('Build/build.sh', 'Build/check_swift_sdk.sh'):
        old = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                       originals[entry]])
        if hashlib.sha1(b'blob ' + str(len(old)).encode() + b'\0' + old).hexdigest() != originals[entry]:
            raise RuntimeError('Incorrect exact old release entry')
        for label, source in [('old', old), ('current', (ROOT / entry).read_bytes())]:
            cases = ['clean', 'unstaged', 'staged', 'index-only']
            if entry.endswith('check_swift_sdk.sh'):
                cases += ['stale-headers', 'changed-header', 'changed-module',
                          'missing-native-success', 'missing-header-identity']
            for case in cases:
                driver.exercise(entry, source, label, case, 'integrated')
                count += 1
    # These are synthetic output/phase fixtures, not native builds or certificates.
    for case in ('clean', 'unstaged', 'staged', 'index-only', 'stale-commit', 'stale-tree',
                 'changed-library', 'changed-source-copy', 'changed-source-mode',
                 'missing-native', 'missing-sdk'):
        with tempfile.TemporaryDirectory(prefix='release-product-input-') as folder:
            root = Path(folder)
            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
            (root / '.gitignore').write_text('.build/\nartifacts/\n')
            (root / 'code.swift').write_text('// synthetic fixture\n')
            git('init', '-q');git('add', '.')
            git('-c', 'user.name=Input fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'Synthetic product input')
            out = root / 'artifacts/integrated';out.mkdir(parents=True)
            copied = root / '.build/integrated-product-source';copied.mkdir(parents=True)
            for name in ('.gitignore', 'code.swift'):
                (copied / name).write_bytes((root / name).read_bytes())
            framework = copied / 'HevSocks5Server.xcframework';framework.mkdir()
            (framework / 'fixture.a').write_bytes(b'not an actual archive')
            for name in ('SUCCESS.txt', 'sdk-success.txt'):
                (out / name).write_text('Fixture marker; not native execution.\n')
            with mock.patch.multiple(product, ROOT=root, OUT=out, PRODUCT=copied):
                product.record_product()
                if case in ('unstaged', 'staged', 'index-only'):
                    (root / 'code.swift').write_text('// changed\n')
                    if case != 'unstaged': git('add', 'code.swift')
                    if case == 'index-only': (root / 'code.swift').write_text('// synthetic fixture\n')
                elif case in ('stale-commit', 'stale-tree'):
                    value = json.loads((out / 'built-framework.json').read_text())
                    value['commit' if case == 'stale-commit' else 'tree'] = '0' * 40
                    (out / 'built-framework.json').write_text(json.dumps(value))
                elif case == 'changed-library': (framework / 'fixture.a').write_bytes(b'changed')
                elif case == 'changed-source-copy': (copied / 'code.swift').write_text('// changed\n')
                elif case == 'changed-source-mode': (copied / 'code.swift').chmod(0o755)
                elif case == 'missing-native': (out / 'SUCCESS.txt').unlink()
                elif case == 'missing-sdk': (out / 'sdk-success.txt').unlink()
                accepted = True
                try:
                    product.check_product()
                except (RuntimeError, subprocess.CalledProcessError):
                    accepted = False
                if accepted != (case == 'clean'):
                    raise RuntimeError(('wrong generated-input verdict', case, accepted))
                print('PASS: generated-input fixture', case, 'accepted=', accepted)
                count += 1
    print(f'PASS: {count} release input/header/generated-output boundary cases; no native/Apple fixture execution.')


if __name__ == '__main__':
    main()
