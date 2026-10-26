#!/usr/bin/env python3
"""Audit the ICMP owner against exact native inputs; no IPA is packaged."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/icmp-native-audit'
SOURCE = ROOT / '.build/icmp-native-audit/source'
CONFIG = json.loads((ROOT / 'Build/features.json').read_text())


def run(args, log, cwd=ROOT, timeout=180):
    with (OUT / log).open('a') as output:
        output.write(json.dumps([str(arg) for arg in args]) + '\n')
        output.flush()
        subprocess.run([str(arg) for arg in args], cwd=cwd, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def prepare(publish=False):
    for path in (ROOT / 'artifacts', OUT, ROOT / '.build', SOURCE.parent, SOURCE):
        if path.is_symlink():
            raise RuntimeError('Linked audit path: ' + str(path))
    if OUT.exists() and any(path.is_symlink() for path in OUT.rglob('*')):
        raise RuntimeError('Linked audit output')
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ('SUCCESS.txt', 'source.zip', 'tested-commit.txt'):
        (OUT / name).unlink(missing_ok=True)
    if publish and os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('artifact_path=artifacts/icmp-native-audit\n')


def main():
    prepare()
    if not __debug__:
        raise RuntimeError('Assertions must be enabled')
    if CONFIG['name'] != 'icmp-relay' or CONFIG['features'] != ['udp', 'icmp']:
        raise RuntimeError('This audit is only for the ICMP feature owner')
    if SOURCE.exists():
        raise RuntimeError('Use a fresh checkout or remove .build/icmp-native-audit first')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    run(['git', 'diff', '--exit-code', 'HEAD', '--'], 'input-worktree.log')
    run(['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 'input-index.log')
    run([sys.executable, 'Build/check.py', 'worktree', commit], 'input-identity.log')
    (OUT / 'tested-commit.txt').write_text(commit + '\n')
    run(['git', 'archive', '--format=zip', commit, '-o', OUT / 'source.zip'], 'archive.log')
    run([sys.executable, 'Build/check.py', 'archive', OUT / 'source.zip', commit], 'archive.log')
    run([sys.executable, 'Build/check.py', 'baseline'], 'baseline.log')
    run([sys.executable, 'Tests/check_baseline_owner.py'], 'baseline-owner.log')
    run([sys.executable, 'Tests/documentation_contract.py'], 'documentation.log')
    run([sys.executable, 'Build/check.py', 'composition'], 'composition.log')
    run(['git', 'diff', '--check', CONFIG['base_commit'], 'HEAD', '--', '.',
         ':(exclude)Patches/*.patch'], 'whitespace.log')
    run([sys.executable, 'Build/native_sources.py', 'checkout', 'server', SOURCE], 'native-inputs.log')
    run([sys.executable, 'Build/check.py', 'apply', SOURCE], 'patches.log')
    formatter = shutil.which('clang-format-18') or shutil.which('clang-format')
    if not formatter or 'version 18.' not in subprocess.check_output([formatter, '--version'], text=True):
        raise RuntimeError('The upstream clang-format 18 is required')
    run([sys.executable, 'Build/check.py', 'format', SOURCE, formatter], 'format.log')
    for name in ('native.c', 'faults.c', 'engine.c'):
        path = ROOT / 'Tests/ICMP' / name
        expected = subprocess.check_output([formatter, '--style=file:' + str(SOURCE / '.clang-format'), str(path)])
        if expected != path.read_bytes():
            raise RuntimeError('Test C formatting differs: ' + name)
    run(['make', '-j3', 'static', 'exec'], 'native-build.log', SOURCE)
    run([sys.executable, 'Tests/ICMP/run.py', SOURCE], 'native-icmp.log')
    run([sys.executable, 'Tests/tcp_smoke.py', SOURCE / 'bin/hev-socks5-server'], 'tcp.log')
    run([sys.executable, 'Tests/udp_sockaddr_regression.py', SOURCE / 'bin/hev-socks5-server',
         '--output', OUT / 'udp.json'], 'udp.log', timeout=90)
    if sys.platform == 'darwin':
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        includes = ['-I' + str(SOURCE / path) for path in (
            'src', 'src/misc', 'src/core/include', 'src/core/src',
            'third-part/yaml/src', 'third-part/hev-task-system/include',
            'third-part/hev-task-system/src')]
        changed = {SOURCE / item['repository'] / name for item in CONFIG['patches']
                   for name in re.findall(r'^\+\+\+ b/(.+\.c)$',
                                          (ROOT / 'Patches' / item['file']).read_text(), re.M)}
        run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios17.2',
             '-isysroot', sdk, '-std=gnu11', '-Wall', '-Werror', '-fsyntax-only',
             *includes, *sorted(changed)], 'ios-sdk-syntax.log')
    run([sys.executable, 'Build/check.py', 'reverse', SOURCE], 'reverse.log')
    run([sys.executable, 'Build/check.py', 'worktree', commit], 'final-identity.log')
    (OUT / 'SUCCESS.txt').write_text('PASS: exact source, native Echo, bounded lifecycle, TCP/UDP and applicable SDK gates\n')
    print('PASS: ICMP native audit')


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--prepare':
        prepare(True)
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit('Usage: audit.py [--prepare]')
