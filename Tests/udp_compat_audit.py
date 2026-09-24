#!/usr/bin/env python3
"""Native-only audit: no Apple framework build, xcodebuild archive, or IPA output."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/udp-final-audit'
CORE = ROOT / '.build/udp-final-audit/core'
CONFIG = json.loads((ROOT / 'Build/features.json').read_text())
SUMMARY = []


def run(args, name, cwd=ROOT, timeout=180):
    with (OUT / name).open('w') as log:
        subprocess.run([str(arg) for arg in args], cwd=cwd, stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def patch(name, repo, reverse=False):
    args = ['git', '-C', repo, 'apply', '--whitespace=error-all']
    if reverse:
        args.append('-R')
    run([*args, '--check', ROOT / 'Patches' / name], name + '.check.log')
    run([*args, ROOT / 'Patches' / name], name + '.apply.log')


def network(name, *options, observation=False):
    args = [sys.executable, ROOT / 'Tests/udp_sockaddr_regression.py',
            CORE / 'bin/hev-socks5-server', '--output', OUT / (name + '.json'),
            *options]
    if observation:
        args.append('--allow-failures')
    run(args, name + '.log', timeout=90)
    rows = json.loads((OUT / (name + '.json')).read_text())
    SUMMARY.append({'profile': name, 'observation_only': observation,
                    'passed': sum(row['passed'] for row in rows),
                    'failed': [row for row in rows if not row['passed']]})
    return rows


def build():
    run(['make', '-j3', 'static', 'exec'], 'native-build.log', CORE)


def main():
    # A rejected or failed retry must not reuse an earlier success marker.
    (OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    if not __debug__:
        raise SystemExit('Assertions are required; do not use Python -O.')
    if CONFIG['name'] != 'udp-compat' or CONFIG['features'] != ['udp']:
        raise SystemExit('This audit is only for the UDP compatibility branch.')
    OUT.mkdir(parents=True, exist_ok=True)
    if CORE.exists():
        raise SystemExit('Use a fresh checkout or remove .build/udp-final-audit first.')
    run(['git', 'rev-parse', 'HEAD'], 'tested-commit.txt')
    run(['git', 'diff', '--name-status', CONFIG['base_commit'], 'HEAD'], 'branch-files.txt')
    run(['git', 'diff', CONFIG['base_commit'], 'HEAD'], 'branch-diff.patch')
    run(['git', 'archive', '--format=zip', 'HEAD', '-o', OUT / 'source.zip'], 'source-archive.log')
    if (ROOT / 'README.md').read_bytes() != (ROOT / 'docs/features/udp-compatibility.md').read_bytes():
        raise RuntimeError('Root README and feature specification differ.')
    # Unified patches require a single space on empty context lines. Their added
    # C code is checked separately by git apply and the upstream formatter.
    run(['git', 'diff', '--check', CONFIG['base_commit'], 'HEAD', '--', '.',
         ':(exclude)Patches/*.patch'], 'whitespace.log')
    run([sys.executable, 'Build/check.py', 'baseline'], 'baseline.log')
    run([sys.executable, 'Build/check.py', 'composition'], 'composition.log')
    run([sys.executable, 'Tests/udp_audit_driver_regression.py'], 'audit-driver.log')
    if sys.platform == 'darwin':
        run(['plutil', '-lint', 'Socks5/Info.plist',
             'Socks5.xcodeproj/project.pbxproj'], 'xcode-metadata.log')
    run(['git', 'clone', '--no-checkout', 'https://github.com/heiher/hev-socks5-server.git', CORE], 'clone.log')
    run(['git', 'checkout', '--detach', CONFIG['sources']['.']], 'checkout.log', CORE)
    run(['git', 'submodule', 'update', '--init', '--recursive'], 'submodules.log', CORE)
    for path, sha in CONFIG['sources'].items():
        actual = subprocess.check_output(['git', '-C', str(CORE / path), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != sha:
            raise RuntimeError('Source mismatch: ' + path)

    # Negative controls distinguish the two repairs; these are not pass claims.
    build()
    baseline = network('control-unpatched', observation=True)
    network('control-unpatched-fixed', '--fixed-udp-port', observation=True)
    run(['make', 'clean'], 'clean.log', CORE)
    patch('hev-udp-port-zero.patch', CORE)
    build()
    port_only = network('control-port-only', observation=True)
    run(['make', 'clean'], 'clean.log', CORE)
    patch('hev-udp-port-zero.patch', CORE, reverse=True)
    patch('hev-udp-sockaddr.patch', CORE / 'src/core')
    build()
    address_only = network('control-address-only', observation=True)
    run(['make', 'clean'], 'clean.log', CORE)
    patch('hev-udp-port-zero.patch', CORE)
    build()
    run([sys.executable, 'Tests/udp_peer_regression.py', CORE / 'bin/hev-socks5-server',
         '--expect-vulnerable', '--output', OUT / 'peer-original.json'],
        'peer-original.log', timeout=45)
    run(['make', 'clean'], 'clean.log', CORE)
    patch('hev-udp-peer-filter.patch', CORE / 'src/core')
    build()
    run([sys.executable, 'Tests/udp_peer_regression.py', CORE / 'bin/hev-socks5-server',
         '--output', OUT / 'peer-filtered.json'], 'peer-filtered.log', timeout=45)

    formatter = shutil.which('clang-format-18') or shutil.which('clang-format')
    if not formatter:
        raise RuntimeError('clang-format 18 is required.')
    version = subprocess.check_output([formatter, '--version'], text=True)
    if 'version 18.' not in version:
        raise RuntimeError(version)
    run([sys.executable, 'Build/check.py', 'format', CORE, formatter], 'core-format.log')
    # The test follows the same project formatting as the C code it exercises.
    formatted = subprocess.check_output([formatter, '--style=file:' + str(CORE / '.clang-format'),
                                         str(ROOT / 'Tests/udp_sockaddr_unit.c')])
    if formatted != (ROOT / 'Tests/udp_sockaddr_unit.c').read_bytes():
        raise RuntimeError('The UDP unit test differs from upstream C formatting.')

    if sys.platform == 'darwin':
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        includes = ['-I' + str(CORE / path) for path in (
            'src/misc', 'src/core/include', 'src/core/src',
            'third-part/yaml/src', 'third-part/hev-task-system/include')]
        run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios17.2',
             '-isysroot', sdk, '-std=gnu11', '-Wall', '-Werror', '-fsyntax-only',
             *includes, CORE / 'src/hev-socks5-session.c',
             CORE / 'src/core/src/hev-socks5-udp.c'], 'ios-arm64-syntax.log')
        if all(row['passed'] for row in baseline):
            raise RuntimeError('Darwin negative control did not reproduce either defect.')
        known = next(row for row in port_only if row['test'].startswith('UDP 127.0.0.1 hint=known'))
        unknown = next(row for row in address_only if row['test'].startswith('UDP 127.0.0.1 hint=0.0.0.0'))
        if not known.get('error', '').startswith('AssertionError: Wrong source:'):
            raise RuntimeError('Missing address repair did not produce a wrong source address.')
        if unknown.get('error') != 'AssertionError: UDP/TCP setup REP=0x01':
            raise RuntimeError('Missing port repair did not produce the expected setup error.')

    network('patched-default')
    network('patched-workers4', '--workers', '4')
    network('patched-mixed', '--unbound')
    network('patched-mixed-workers4', '--unbound', '--workers', '4')
    for workers in ('1', '4'):
        network('patched-fixed-known-' + workers, '--fixed-udp-port', '--known-concurrent', '--workers', workers)
        network('limit-fixed-unknown-' + workers, '--fixed-udp-port', '--workers', workers, observation=True)

    compiler = os.environ.get('CC', 'clang')
    includes = ['-I' + str(CORE / 'src/core/src'), '-I' + str(CORE / 'third-part/hev-task-system/include')]
    libs = [CORE / 'bin/libhev-socks5-server.a', CORE / 'third-part/yaml/bin/libyaml.a',
            CORE / 'third-part/hev-task-system/bin/libhev-task-system.a']
    executable = OUT / 'unit'
    run([compiler, '-std=gnu11', '-O2', '-g', '-Wall', '-Werror', '-pthread',
         '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
         *includes, ROOT / 'Tests/udp_sockaddr_unit.c', *libs, '-o', executable], 'unit-build.log')
    run([executable], 'unit.log')
    executable.unlink()
    run([compiler, '-std=gnu11', '-O3', '-Wall', '-Werror', '-fstrict-aliasing', '-pthread',
         *includes, ROOT / 'Tests/udp_sockaddr_unit.c', *libs, '-o', executable], 'unit-optimized-build.log')
    run([executable], 'unit-optimized.log')
    executable.unlink()
    run([sys.executable, 'Build/check.py', 'reverse', CORE], 'reverse.log')
    (OUT / 'SUCCESS.txt').write_text('Scoped UDP repair audit passed. Read summary.json for observation-only failures. No IPA was built.\n')


if __name__ == '__main__':
    try:
        main()
    finally:
        if OUT.exists():
            (OUT / 'summary.json').write_text(json.dumps(SUMMARY, indent=2) + '\n')
