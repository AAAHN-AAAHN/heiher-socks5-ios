#!/usr/bin/env python3
"""Statistics-only review: native tests and iOS type checking, never an IPA build."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/statistics-final-audit'
CORE = ROOT / '.build/statistics-final-audit/core'
START = 'd34e49478d7e061b8824e9f431b40998db25f8b2'
UDP = '05524e3fb917f2a0e5264bc9919118fcc484cb11'
CONFIG = json.loads((ROOT / 'Build/features.json').read_text())
UDP_FILES = {
    '.github/workflows/udp-compat-audit.yml': '.github/workflows/verify-build.yml',
    'docs/branches/feature-udp-compat.md': 'README.md',
    **{p: p for p in ('Patches/hev-udp-port-zero.patch', 'Patches/hev-udp-sockaddr.patch',
                     'Tests/udp_compat_audit.py', 'Tests/udp_sockaddr_regression.py',
                     'Tests/udp_sockaddr_unit.c', 'Tests/udp_audit_driver_regression.py',
                     'docs/reviews/udp-compat-20260923.md', 'docs/features/udp-compatibility.md',
                     'docs/reviews/udp-compat-20260922.md', 'Socks5/Info.plist')}
}


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', '-C', str(cwd), *args])


def run(args, log, cwd=ROOT, timeout=180, env=None):
    with (OUT / log).open('w') as output:
        subprocess.run([str(arg) for arg in args], cwd=cwd, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout, env=env)


def inspect_sources():
    if CONFIG['name'] != 'traffic-statistics' or CONFIG['features'] != ['udp', 'statistics']:
        raise RuntimeError('This review is for the statistics composition only.')
    inventory = git('diff', '--name-only', CONFIG['base_commit'], 'HEAD').decode().splitlines()
    udp_config = json.loads(git('show', UDP + ':Build/features.json'))
    for key in ('base_commit', 'sources', 'upstream_app'):
        assert CONFIG[key] == udp_config[key], key
    assert CONFIG['patches'][:len(udp_config['patches'])] == udp_config['patches']
    workflow = (ROOT / '.github/workflows/verify-build.yml').read_text()
    assert ('    uses: ./.github/workflows/udp-compat-audit.yml\n'
            f'    with:\n      ref: {UDP}\n') in workflow
    assert '    needs: udp-prerequisite\n' in workflow
    preserved = {}
    for target, source in UDP_FILES.items():
        data = (ROOT / target).read_bytes()
        assert data == git('show', UDP + ':' + source), target
        preserved[target] = hashlib.sha256(data).hexdigest()
    # Read-only dependencies and production implementation remain at their reviewed state.
    git('diff', '--exit-code', START, 'HEAD', '--', 'Socks5', 'Socks5.xcodeproj', 'Patches', 'Build')
    git('merge-base', '--is-ancestor', UDP, 'HEAD')
    run([sys.executable, 'Build/check.py', 'baseline'], 'baseline.log')
    run([sys.executable, 'Build/check.py', 'composition'], 'composition.log')
    run(['git', 'diff', '--check', CONFIG['base_commit'], 'HEAD', '--', '.',
         ':(exclude)Patches/*.patch'], 'whitespace.log')
    assert (ROOT / 'README.md').read_bytes() == (ROOT / 'docs/features/traffic-statistics.md').read_bytes()
    view = (ROOT / 'Socks5/Statistics/TrafficStatisticsView.swift').read_text()
    for text in ('.task(id: isVisible && scenePhase == .active)', 'while !Task.isCancelled',
                 'Task.sleep(for: .seconds(1))', 'guard !Task.isCancelled else { return }',
                 'ProcessInfo.processInfo.systemUptime', 'Double(statistics.received) + Double(statistics.sent)'):
        assert text in view, text
    root = (ROOT / 'Socks5/AppRoot.swift').read_text()
    assert re.findall(r'\.tag\("(\w+)"\)', root) == ['statistics', 'server']
    (OUT / 'inventory.json').write_text(json.dumps({
        'base': CONFIG['base_commit'], 'start': START, 'udp': UDP,
        'files_vs_main': inventory, 'excluded_udp_files': preserved,
        'statistics_owned_paths': [p for p in inventory if p not in UDP_FILES],
        'production_unchanged': True}, indent=2) + '\n')
    run(['git', 'diff', CONFIG['base_commit'], 'HEAD'], 'main-to-feature.diff')
    run(['git', 'diff', UDP, 'HEAD'], 'udp-to-statistics.diff')
    run(['git', 'rev-parse', 'HEAD'], 'tested-commit.txt')
    run(['git', 'archive', '--format=zip', 'HEAD', '-o', OUT / 'source.zip'], 'archive.log')
    for name in ('README.md', 'docs/features/traffic-statistics.md'):
        for target in re.findall(r'\]\(([^)]+)\)', (ROOT / name).read_text()):
            if '://' not in target and not target.startswith('#'):
                assert (ROOT / name).parent.joinpath(target.split('#')[0]).is_file(), (name, target)


def native_checks(mode):
    splice = mode == 'splice'
    run(['make', 'clean'], mode + '-clean.log', CORE)
    # CFLAGS alone cannot disable a default-enabled Makefile option.
    run(['make', '-j3', 'ECHO_PREFIX=', 'ENABLE_IO_SPLICE_SYSCALL=' + str(int(splice)),
         'static', 'exec'], mode + '-build.log', CORE, timeout=300)
    task = CORE / 'third-part/hev-task-system'
    symbols = subprocess.check_output(['nm', '-u', task / 'build/lib/io/basic/hev-task-io.o'], text=True)
    (OUT / (mode + '-io-symbols.txt')).write_text(symbols)
    assert bool(re.search(r'\b_?splice\s*$', symbols, re.M)) == splice
    # Generic readv/writev wrappers are always part of this object.
    assert bool(re.search(r'\b_?hev_circular_buffer_new\s*$', symbols, re.M)) != splice
    libs = [CORE / 'bin/libhev-socks5-server.a', CORE / 'third-part/yaml/bin/libyaml.a',
            task / 'bin/libhev-task-system.a']
    common = ['clang', '-std=gnu11', '-O2', '-Wall', '-Werror', '-pthread']
    host = OUT / 'host'
    run([*common, '-I' + str(CORE / 'src'), 'Tests/traffic_stats_host.c', *libs,
         '-o', host], mode + '-host-build.log')
    for repeat in (1, 2):
        run([sys.executable, '-u', 'Tests/traffic_stats_regression.py', host],
            mode + '-network-' + str(repeat) + '.log', timeout=120)
    run([*common, '-I' + str(CORE / 'src'), 'Tests/Statistics/counter_probe.c',
         *libs, '-o', OUT / 'counter'], mode + '-counter-build.log')
    run([OUT / 'counter'], mode + '-counter.log')
    sanitize = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-fno-omit-frame-pointer']
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0', UBSAN_OPTIONS='halt_on_error=1')
    for kind in ('tcp', 'udp'):
        includes = (['-I' + str(task / 'src'), '-I' + str(task / 'include')]
                    if kind == 'tcp' else ['-I' + str(CORE / 'src/core/src'), '-I' + str(task / 'include')])
        flags = ['-DENABLE_IO_SPLICE_SYSCALL'] if splice and kind == 'tcp' else []
        run([*common, '-Wno-unused-function', '-Wno-unused-variable', *sanitize,
             *flags, *includes, 'Tests/Statistics/' + kind + '_probe.c',
             *(libs if kind == 'udp' else [libs[-1]]), '-o', OUT / kind],
            mode + '-' + kind + '-build.log')
        run([OUT / kind], mode + '-' + kind + '.log', env=env)
    if sys.platform == 'darwin':
        # Instrument the real counter implementation, not merely an external mock.
        run([*common, '-O1', '-g', '-fsanitize=thread', '-I' + str(CORE / 'src'),
             '-I' + str(task / 'include'), 'Tests/Statistics/counter_probe.c',
             CORE / 'src/core/src/hev-socks5-misc.c', *libs, '-o', OUT / 'counter-tsan'],
            'counter-tsan-build.log')
        run([OUT / 'counter-tsan'], 'counter-tsan.log',
            env=dict(os.environ, TSAN_OPTIONS='halt_on_error=1'))


def ios_checks(changed):
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    task = CORE / 'third-part/hev-task-system'
    includes = ['-I' + str(p) for p in (CORE / 'src', CORE / 'src/misc',
                CORE / 'src/core/include', CORE / 'src/core/src', CORE / 'third-part/yaml/src',
                task / 'include', task / 'src')]
    # Upstream task-io.h expects hev-task.h first; C sources keep their own includes.
    headers = OUT / 'statistics-headers.c'
    headers.write_text('#include <hev-task.h>\n' + ''.join(
        '#include "' + str(p) + '"\n' for p in changed if p.suffix == '.h'))
    run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios17.2',
         '-isysroot', sdk, '-std=gnu11', '-Wall', '-Werror', '-fsyntax-only',
         '-DCOMMIT_ID="' + CONFIG['sources']['.'] + '"', '-x', 'c', *includes,
         *[p for p in changed if p.suffix == '.c'], headers], 'ios-c-syntax.log')
    module = OUT / 'swift-module'
    module.mkdir()
    shutil.copyfile(CORE / 'src/hev-main.h', module / 'hev-main.h')
    (module / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
    run(['xcrun', 'swiftc', '-swift-version', '5', '-warnings-as-errors', '-typecheck',
         '-sdk', sdk, '-target', 'arm64-apple-ios17.2', '-I', module,
         *sorted((ROOT / 'Socks5').rglob('*.swift'))], 'ios-swift-typecheck.log')
    run(['plutil', '-lint', 'Socks5/Info.plist', 'Socks5.xcodeproj/project.pbxproj'], 'project.log')
    shutil.rmtree(module)


def main():
    # A rejected or failed retry must not reuse an earlier success marker.
    (OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    if not __debug__:
        raise SystemExit('Assertions must be enabled; do not use Python -O.')
    OUT.mkdir(parents=True, exist_ok=True)
    if CORE.exists():
        raise SystemExit('Use a clean checkout or remove .build/statistics-final-audit.')
    inspect_sources()
    run([sys.executable, 'Tests/Statistics/audit_driver_probe.py'], 'audit-driver.log')
    run([sys.executable, 'Tests/Statistics/host_probe.py'], 'host-reader.log')
    run(['git', 'clone', '--no-checkout', 'https://github.com/heiher/hev-socks5-server.git', CORE], 'clone.log')
    run(['git', 'checkout', '--detach', CONFIG['sources']['.']], 'checkout.log', CORE)
    run(['git', 'submodule', 'update', '--init', '--recursive'], 'submodules.log', CORE)
    run([sys.executable, 'Build/check.py', 'apply', CORE], 'apply.log')
    # Only statistics-owned hunks are reviewed; UDP prerequisite contents are frozen.
    changed = []
    for item in CONFIG['patches']:
        if item['file'].startswith('hev-stats-'):
            text = (ROOT / 'Patches' / item['file']).read_text()
            changed += [CORE / item['repository'] / p for p in re.findall(r'^\+\+\+ b/(.+)$', text, re.M)]
    formatter = shutil.which('clang-format-18') or shutil.which('clang-format')
    if not formatter or 'version 18.' not in subprocess.check_output([formatter, '--version'], text=True):
        raise RuntimeError('clang-format 18 is required.')
    hashes = {}
    for path in changed:
        assert subprocess.check_output([formatter, str(path)]) == path.read_bytes(), path
        hashes[str(path.relative_to(CORE))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(hashes) == 9
    (OUT / 'statistics-source-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    # Test-only C follows the same formatter; never silently rewrite reviewed files.
    for path in (ROOT / 'Tests/Statistics').glob('*.c'):
        target = OUT / ('formatted-' + path.name)
        formatted = subprocess.check_output([formatter, '--style=file:' + str(CORE / '.clang-format'), str(path)])
        target.write_bytes(formatted)
        assert formatted == path.read_bytes(), path
    for mode in (('buffered', 'splice') if sys.platform == 'linux' else ('buffered',)):
        native_checks(mode)
    run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
         'Socks5/Statistics/TrafficStatistics.swift', 'Tests/traffic_statistics_model.swift',
         '-o', OUT / 'model'], 'model-build.log')
    run([OUT / 'model'], 'model.log')
    if sys.platform == 'darwin':
        ios_checks(changed)
    for name, expected in hashes.items():
        assert hashlib.sha256((CORE / name).read_bytes()).hexdigest() == expected
    run([sys.executable, 'Build/check.py', 'reverse', CORE], 'reverse.log')
    for name in ('host', 'counter', 'tcp', 'udp', 'counter-tsan', 'model'):
        (OUT / name).unlink(missing_ok=True)
    (OUT / 'SUCCESS.txt').write_text('PASS: statistics-scoped native audit and applicable type checks.\n'
                                    'UDP contents preserved. No IPA or XCFramework build.\n')


if __name__ == '__main__':
    main()
