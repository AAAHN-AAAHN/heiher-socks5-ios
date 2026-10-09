#!/usr/bin/env python3
"""Statistics-owned socket I/O audit and iOS type checks; no IPA packaging."""
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
SOCKET_BASE = 'cfcda5795b833b3ba8768fa4453f6f92606d3be1'
UDP = 'c42a610cd02403b2930c2b8160adcbdad837a77f'
CONFIG = json.loads((ROOT / 'Build/features.json').read_text())
SOCKET_PATCHES = [
    {'file': 'hev-socket-meter-task.patch', 'repository': 'third-part/hev-task-system'},
    {'file': 'hev-socket-meter-core.patch', 'repository': 'src/core'},
    {'file': 'hev-socket-meter-server.patch', 'repository': '.'},
]
UDP_COMPOSED_SOURCES = ('udp_sockaddr_unit.c', 'udp_buffer_unit.c', 'udp_buffer_io.c',
                        'udp_buffer_send.c', 'udp_stream_boundaries.c')
# Keep inherited fixtures' substituted I/O boundaries; real meter tests use no aliases.
UDP_FIXTURE_INIT = ['-include', str(ROOT / 'Tests/SocketIO/udp_fixture_main.h')]
UDP_FIXTURE_FLAGS = UDP_FIXTURE_INIT + [
    '-Dhev_meter_' + op + '=hev_task_io_socket_' + op
    for op in ('recv', 'send', 'recvmsg', 'sendmsg', 'recvmmsg', 'sendmmsg')]
UDP_FILES = {
    '.github/workflows/udp-compat-audit.yml': '.github/workflows/verify-build.yml',
    **{p: p for p in ('Patches/hev-udp-port-zero.patch', 'Patches/hev-udp-sockaddr.patch',
                     'Patches/hev-udp-peer-filter.patch', 'Patches/hev-udp-dynamic-buffer.patch',
                     'Tests/udp_peer_regression.py',
                     'Tests/udp_queue_observation.py',
                     'Tests/udp_compat_audit.py', 'Tests/udp_sockaddr_regression.py',
                     'Tests/udp_sockaddr_unit.c', 'Tests/udp_audit_driver_regression.py',
                     'Socks5/Info.plist',
                     'Tests/udp_buffer_benchmark.py',
                     'Tests/udp_buffer_io.c',
                     'Tests/udp_buffer_live_hold.c',
                     'Tests/udp_buffer_network.py',
                     'Tests/udp_buffer_send.c',
                     'Tests/udp_buffer_timer.c',
                     'Tests/udp_buffer_unit.c',
                     'Tests/udp_header_regression.py')}
}


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', '-C', str(cwd), *args])


def run(args, log, cwd=ROOT, timeout=180, env=None):
    with (OUT / log).open('w') as output:
        subprocess.run([str(arg) for arg in args], cwd=cwd, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout, env=env)


def worker_baseline_sha256():
    """Supply this owner's reviewed worker input to composed lifecycle checks."""
    manifest = json.loads((ROOT / 'Tests/SocketIO/worker-native.json').read_text())
    digest = manifest['compositions']['statistics']['src/hev-socks5-worker.c']
    assert re.fullmatch(r'[0-9a-f]{64}', digest), 'Invalid Statistics worker digest'
    return digest


def check_udp_inheritance():
    """Keep the executable UDP prerequisite, inherited tests and prose on one parent."""
    parent = json.loads((ROOT / 'docs/documentation.json').read_bytes())['parents']['feature/udp-compat']
    assert parent == UDP, 'Executable UDP prerequisite differs from document parent'
    workflow = (ROOT / '.github/workflows/verify-build.yml').read_text()
    assert ('    uses: ./.github/workflows/udp-compat-audit.yml\n'
            f'    with:\n      ref: {UDP}\n') in workflow, 'UDP workflow prerequisite differs'
    assert '    needs: udp-prerequisite\n' in workflow
    assert 'udp_stream_boundaries.c' in UDP_COMPOSED_SOURCES, 'Missing composed stream execution'
    entries = {}
    for record in git('ls-tree', '-rz', UDP).split(b'\0'):
        if record:
            meta, path = record.split(b'\t', 1)
            entries[path.decode()] = tuple(meta.decode().split())
    # Discover the whole parent test tree, not a hand-maintained partial inventory.
    paths = dict(UDP_FILES)
    paths.update({p: p for p in entries if p.startswith('Tests/')})
    preserved = {}
    for target, source in paths.items():
        mode, kind, blob = entries[source]
        path = ROOT / target
        assert kind == 'blob' and not path.is_symlink() and path.is_file(), target
        data = path.read_bytes()
        actual_mode = '100755' if path.stat().st_mode & 0o111 else '100644'
        assert data == git('cat-file', 'blob', blob) and actual_mode == mode, target
        index = git('ls-files', '--stage', '--', target).decode().split()
        assert index[:3] == [mode, blob, '0'], ('Inherited UDP index', target)
        preserved[target] = hashlib.sha256(data).hexdigest()
    return preserved


def inspect_sources():
    import runpy
    documents = runpy.run_path(str(ROOT / 'Build/check_documentation.py'))
    documents['check'](ROOT)
    if CONFIG['name'] != 'traffic-statistics' or CONFIG['features'] != ['udp', 'statistics']:
        raise RuntimeError('This review is for the statistics composition only.')
    inventory = git('diff', '--name-only', CONFIG['base_commit'], 'HEAD').decode().splitlines()
    udp_config = json.loads(git('show', UDP + ':Build/features.json'))
    for key in ('base_commit', 'sources', 'upstream_app'):
        assert CONFIG[key] == udp_config[key], key
    assert CONFIG['patches'][:len(udp_config['patches'])] == udp_config['patches']
    preserved = check_udp_inheritance()
    # The UDP prefix remains exact; all metric changes belong to Statistics.
    original = json.loads(git('show', START + ':Build/features.json'))
    assert CONFIG == dict(original, base_commit=udp_config['base_commit'],
                          sources=udp_config['sources'], upstream_app=udp_config['upstream_app'],
                          patches=udp_config['patches'] + SOCKET_PATCHES)
    runtime_changes = set(git('diff', '--name-only', SOCKET_BASE, 'HEAD', '--',
                              'Socks5', 'Socks5.xcodeproj', 'Patches').decode().splitlines())
    allowed = {'Socks5/Statistics/TrafficStatistics.swift',
               'Socks5/Statistics/TrafficStatisticsView.swift',
               'Patches/hev-stats-task-io.patch', 'Patches/hev-stats-core.patch',
               'Patches/hev-stats-server.patch',
               *('Patches/' + p['file'] for p in SOCKET_PATCHES),
               *('Patches/' + p['file'] for p in udp_config['patches'])}
    assert runtime_changes <= allowed, runtime_changes - allowed
    git('merge-base', '--is-ancestor', SOCKET_BASE, 'HEAD')
    git('merge-base', '--is-ancestor', UDP, 'HEAD')
    git('diff', '--exit-code', SOCKET_BASE, 'HEAD', '--', 'Socks5', 'Socks5.xcodeproj',
        ':(exclude)Socks5/Statistics/TrafficStatistics.swift',
        ':(exclude)Socks5/Statistics/TrafficStatisticsView.swift')
    for name in ('hev-stats-task-io.patch', 'hev-stats-core.patch', 'hev-stats-server.patch'):
        assert not (ROOT / 'Patches' / name).exists(), 'Obsolete payload collector: ' + name
    from ui_audit import verify_presentation
    verify_presentation()
    run([sys.executable, 'Build/check.py', 'baseline'], 'baseline.log')
    run([sys.executable, 'Tests/baseline_audit.py'], 'baseline-driver.log')
    run([sys.executable, 'Build/check.py', 'composition'], 'composition.log')
    run(['git', 'diff', '--check', CONFIG['base_commit'], 'HEAD', '--', '.',
         ':(exclude)Patches/*.patch'], 'whitespace.log')
    assert (ROOT / 'README.md').read_bytes() == (ROOT / 'docs/features/traffic-statistics.md').read_bytes()
    view = (ROOT / 'Socks5/Statistics/TrafficStatisticsView.swift').read_text()
    for text in ('.task(id: isVisible && scenePhase == .active)', 'while !Task.isCancelled',
                 'Date().timeIntervalSinceReferenceDate', 'Task.sleep(for: .seconds(delay))',
                 'guard !Task.isCancelled else { return }',
                 'guard isVisible && scenePhase == .active && !Task.isCancelled else { return }',
                 'ProcessInfo.processInfo.systemUptime', 'Double(statistics.received) + Double(statistics.sent)'):
        assert text in view, text
    root = (ROOT / 'Socks5/AppRoot.swift').read_text()
    assert re.findall(r'\.tag\("(\w+)"\)', root) == ['statistics', 'server']
    (OUT / 'inventory.json').write_text(json.dumps({
        'base': CONFIG['base_commit'], 'start': START, 'udp': UDP,
        'files_vs_main': inventory, 'excluded_udp_files': preserved,
        'statistics_owned_paths': [p for p in documents['code_paths'](ROOT, inventory) if p not in UDP_FILES and p not in preserved],
        'statistics_production_unchanged': False,
        'socket_accounting_base': SOCKET_BASE, 'allowed_runtime_changes': sorted(runtime_changes), 'udp_dependency_updated': True}, indent=2) + '\n')
    run(['git', 'diff', CONFIG['base_commit'], 'HEAD'], 'main-to-feature.diff')
    run(['git', 'diff', UDP, 'HEAD'], 'udp-to-statistics.diff')
    run(['git', 'rev-parse', 'HEAD'], 'tested-commit.txt')
    run(['git', 'archive', '--format=zip', 'HEAD', '-o', OUT / 'source.zip'], 'archive.log')
    for name in ('README.md', 'docs/features/traffic-statistics.md'):
        for target in re.findall(r'\]\(([^)]+)\)', (ROOT / name).read_text()):
            if '://' not in target and not target.startswith('#'):
                assert (ROOT / name).parent.joinpath(target.split('#')[0]).is_file(), (name, target)


def native_checks(mode):
    """Build one composition and reuse the same Statistics-owned metric tests."""
    assert mode in ('buffered', 'splice')
    splice = mode == 'splice'
    run(['make', 'clean'], mode + '-clean.log', CORE)
    # CFLAGS alone cannot disable a default-enabled Makefile option.
    run(['make', '-j3', 'ECHO_PREFIX=', 'ENABLE_IO_SPLICE_SYSCALL=' + str(int(splice)),
         'static', 'exec'], mode + '-build.log', CORE, timeout=300)
    task = CORE / 'third-part/hev-task-system'
    symbols = subprocess.check_output(['nm', '-u', task / 'build/lib/io/basic/hev-task-io.o'], text=True)
    (OUT / (mode + '-io-symbols.txt')).write_text(symbols)
    assert bool(re.search(r'\b_?splice\s*$', symbols, re.M)) == splice
    assert bool(re.search(r'\b_?hev_circular_buffer_new\s*$', symbols, re.M)) != splice
    libs = [CORE / 'bin/libhev-socks5-server.a', CORE / 'third-part/yaml/bin/libyaml.a',
            task / 'bin/libhev-task-system.a']
    common = ['clang', '-std=gnu11', '-O2', '-Wall', '-Werror', '-pthread']
    includes = ['-I' + str(CORE / 'src'), '-I' + str(CORE / 'src/core/src'),
                '-I' + str(task / 'src'), '-I' + str(task / 'include')]
    run([sys.executable, 'Tests/SocketIO/run.py', CORE, '--mode', mode,
         '--output', OUT / ('socket-' + mode)], mode + '-socket-io.log', timeout=600)
    # Preserve the UDP parent's protocol and buffer checks on the composed core.
    for script, label, timeout in [('udp_peer_regression.py', 'peer', 45),
                                    ('udp_header_regression.py', 'header', 120),
                                    ('udp_buffer_network.py', 'dynamic-network', 120)]:
        run([sys.executable, 'Tests/' + script, CORE / 'bin/hev-socks5-server',
             '--output', OUT / (mode + '-' + label + '.json')],
            mode + '-' + label + '.log', timeout=timeout)
    sanitize = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-fno-omit-frame-pointer']
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=0', UBSAN_OPTIONS='halt_on_error=1')
    helpers = [('socket_observer', []), ('socket_observer', ['-DFORCE_FALLBACK']),
               ('stream_matrix', ['-DENABLE_IO_SPLICE_SYSCALL'] if splice else []),
               ('registry', []), ('worker_boundaries', [])]
    for label, extra in [('asan', sanitize), ('optimized', ['-O3', '-fstrict-aliasing'])]:
        # Fixtures include the actual socket helpers/worker registry; only syscall
        # outcomes and allocation failures are substituted at controlled boundaries.
        for name, defines in helpers:
            suffix = '-fallback' if '-DFORCE_FALLBACK' in defines else ''
            executable = OUT / ('socket-' + name + suffix + '-' + label)
            run([*common, *extra, '-Wno-unused-function', *defines, *includes,
                 'Tests/SocketIO/' + name + '.c', libs[-1], '-o', executable],
                mode + '-' + executable.name + '-build.log')
            run([executable], mode + '-' + executable.name + '.log', env=env)
            executable.unlink()
        for source in UDP_COMPOSED_SOURCES:
            executable = OUT / ('composed-' + Path(source).stem + '-' + label)
            run([*common, *extra, '-Wno-unused-function', *UDP_FIXTURE_FLAGS, *includes,
                 ROOT / 'Tests' / source, *libs, '-o', executable],
                mode + '-' + executable.name + '-build.log')
            run([executable], mode + '-' + executable.name + '.log', env=env)
            executable.unlink()
    if not splice:
        executable = OUT / 'udp-live-retention'
        run([*common, *UDP_FIXTURE_INIT, *includes, 'Tests/udp_buffer_live_hold.c', *libs, '-o', executable],
            'udp-live-retention-build.log')
        run([executable], 'udp-live-retention.log', timeout=490)
        executable.unlink()
    if sys.platform == 'darwin':
        for name in ('registry', 'worker_boundaries'):
            executable = OUT / ('socket-' + name + '-tsan')
            run([*common, '-O1', '-g', '-fsanitize=thread', *includes,
                 'Tests/SocketIO/' + name + '.c', libs[-1], '-o', executable],
                mode + '-' + executable.name + '-build.log')
            run([executable], mode + '-' + executable.name + '.log',
                env=dict(os.environ, TSAN_OPTIONS='halt_on_error=1'))
            executable.unlink()
    module = OUT / 'bridge-module'
    module.mkdir(exist_ok=True)
    shutil.copyfile(CORE / 'src/hev-main.h', module / 'hev-main.h')
    (module / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
    executable = OUT / 'socket-abi-bridge'
    run(['swiftc', '-swift-version', '5', '-warnings-as-errors', '-I', module,
         'Tests/SocketIO/BridgeTests.swift', *libs, '-Xlinker', '-lpthread', '-o', executable],
        mode + '-socket-abi-build.log')
    run([executable], mode + '-socket-abi.log')
    executable.unlink()


def model_checks():
    """Pure formatting/model checks and the current sampling lifecycle contract."""
    run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
         'Socks5/Statistics/TrafficStatistics.swift', 'Tests/traffic_statistics_model.swift',
         '-o', OUT / 'model'], 'model-build.log')
    run([OUT / 'model'], 'model.log')
    (OUT / 'model').unlink()
    for optimization in ([], ['-O']):
        label = 'client-model-optimized' if optimization else 'client-model-debug'
        run(['swiftc', '-swift-version', '5', '-warnings-as-errors', *optimization,
             'Socks5/Statistics/TrafficStatistics.swift', 'Tests/Statistics/client_model.swift',
             '-o', OUT / 'client-model'], label + '-build.log')
        run([OUT / 'client-model'], label + '.log')
    (OUT / 'client-model').unlink()
    run([sys.executable, 'Tests/Statistics/sampling_contract.py'], 'sampling-contract.log', timeout=300)


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
    # The working files, index and archived HEAD must describe the same input.
    run(['git', 'diff', '--exit-code', 'HEAD', '--'], 'input-worktree.log')
    run(['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 'input-index.log')
    inspect_sources()
    run([sys.executable, 'Tests/Statistics/audit_driver_probe.py'], 'audit-driver.log')
    run([sys.executable, 'Tests/Statistics/udp_inheritance_regression.py'], 'udp-inheritance.log')
    run([sys.executable, 'Tests/Statistics/input_probe.py'], 'input-probe.log')
    run(['git', 'clone', '--no-checkout', 'https://github.com/heiher/hev-socks5-server.git', CORE], 'clone.log')
    run(['git', 'checkout', '--detach', CONFIG['sources']['.']], 'checkout.log', CORE)
    run(['git', 'submodule', 'update', '--init', '--recursive'], 'submodules.log', CORE)
    run([sys.executable, 'Build/check.py', 'apply', CORE], 'apply.log')
    # Preserve the actual patched native sources for offline inspection; no build
    # product, credentials or .git metadata is included in this source-only archive.
    run(['tar', '-czf', OUT / 'native-patched-source.tar.gz', '--exclude=.git',
         '-C', CORE, '.'], 'native-source-archive.log')
    # Only statistics-owned hunks are reviewed; UDP prerequisite contents are frozen.
    changed = []
    for item in CONFIG['patches']:
        if item['file'].startswith('hev-socket-meter-'):
            text = (ROOT / 'Patches' / item['file']).read_text()
            changed += [CORE / item['repository'] / p for p in re.findall(r'^\+\+\+ b/(.+)$', text, re.M)]
    formatter = shutil.which('clang-format-18') or shutil.which('clang-format')
    if not formatter or 'version 18.' not in subprocess.check_output([formatter, '--version'], text=True):
        raise RuntimeError('clang-format 18 is required.')
    hashes = {}
    formatting_errors = []
    for path in changed:
        formatted = subprocess.check_output([formatter, str(path)])
        if formatted != path.read_bytes():
            target = OUT / 'formatting' / path.relative_to(CORE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(formatted)
            formatting_errors.append(str(path))
        hashes[str(path.relative_to(CORE))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(hashes) == 17
    (OUT / 'statistics-source-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    # Test-only C follows the same formatter; never silently rewrite reviewed files.
    for path in [*(ROOT / 'Tests/SocketIO').glob('*.c'), ROOT / 'Tests/udp_stream_boundaries.c']:
        target = OUT / ('formatted-' + path.name)
        formatted = subprocess.check_output([formatter, '--style=file:' + str(CORE / '.clang-format'), str(path)])
        target.write_bytes(formatted)
        if formatted != path.read_bytes():
            formatting_errors.append(str(path))
    assert not formatting_errors, formatting_errors
    for mode in (('buffered', 'splice') if sys.platform == 'linux' else ('buffered',)):
        native_checks(mode)
    model_checks()
    if sys.platform == 'darwin':
        ios_checks(changed)
    for name, expected in hashes.items():
        assert hashlib.sha256((CORE / name).read_bytes()).hexdigest() == expected
    run([sys.executable, 'Build/check.py', 'reverse', CORE], 'reverse.log')
    run(['git', 'diff', '--exit-code', 'HEAD', '--'], 'final-worktree.log')
    run(['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 'final-index.log')
    (OUT / 'SUCCESS.txt').write_text('PASS: peer socket I/O native audit and applicable type checks.\n'
                                    'UDP contents preserved. No IPA or XCFramework build.\n')


if __name__ == '__main__':
    main()
