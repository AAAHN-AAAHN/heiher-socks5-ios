#!/usr/bin/env python3
"""Exercise the declared native composition; retain branch audits as separate evidence.

Adapted from 0ab3c33a's dispatcher after duplicate-branch comparison. Updated to the finalized six owners with combined lifecycle/persistence cases. Production modules and standalone audit gates
are preserved; this entry point reuses their real native cases for compositions.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) != 3:
    raise SystemExit('Usage: native_checks.py CORE OUTPUT')
CORE = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
FEATURES = set(json.loads((ROOT / 'Build/features.json').read_text())['features'])
OUT.mkdir(parents=True, exist_ok=True)


def run(args, name, timeout=180, cwd=ROOT, env=None):
    with (OUT / name).open('w') as output:
        subprocess.run([str(a) for a in args], cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout, env=env)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


for mode in (('buffered', 'splice') if sys.platform == 'linux' and 'statistics' in FEATURES else ('buffered',)):
    udp_fixture_flags = []
    worker_baseline = None
    if 'statistics' in FEATURES:
        audit = module('composition_statistics', 'Tests/Statistics/audit.py')
        audit.CORE = CORE
        audit.OUT = OUT / 'statistics'
        audit.OUT.mkdir(exist_ok=True)
        # Execute the existing real native cases, not the standalone-branch identity gate.
        audit.native_checks(mode)
        udp_fixture_flags = audit.UDP_FIXTURE_FLAGS
        worker_baseline = audit.worker_baseline_sha256()
    else:
        run(['make', 'clean'], mode + '-clean.log', cwd=CORE)
        run(['make', '-j3', 'ENABLE_IO_SPLICE_SYSCALL=0', 'static', 'exec'],
            mode + '-build.log', timeout=300, cwd=CORE)
    libraries = [CORE / 'bin/libhev-socks5-server.a', CORE / 'third-part/yaml/bin/libyaml.a',
                 CORE / 'third-part/hev-task-system/bin/libhev-task-system.a']
    run([sys.executable, 'Tests/tcp_smoke.py', CORE / 'bin/hev-socks5-server'], mode + '-tcp.log')
    if 'udp' in FEATURES:
        audit = module('composition_udp', 'Tests/udp_compat_audit.py')
        audit.CORE = CORE
        audit.OUT = OUT / ('udp-' + mode)
        audit.OUT.mkdir(exist_ok=True)
        audit.network('default')
        audit.network('workers4', '--workers', '4')
        audit.network('mixed', '--unbound')
        audit.network('mixed-workers4', '--unbound', '--workers', '4')
        for workers in ('1', '4'):
            audit.network('fixed-known-' + workers, '--fixed-udp-port', '--known-concurrent', '--workers', workers)
            audit.network('limit-fixed-unknown-' + workers, '--fixed-udp-port', '--workers', workers, observation=True)
        (audit.OUT / 'summary.json').write_text(json.dumps(audit.SUMMARY, indent=2) + '\n')
        includes = ['-I' + str(CORE / 'src/core/src'), '-I' + str(CORE / 'third-part/hev-task-system/include')]
        for label, flags in [('sanitized', ['-O2', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']),
                             ('optimized', ['-O3', '-fstrict-aliasing'])]:
            executable = OUT / ('udp-' + label)
            run(['clang', '-std=gnu11', '-Wall', '-Werror', '-pthread', *flags, *udp_fixture_flags, *includes,
                 'Tests/udp_sockaddr_unit.c', *libraries, '-o', executable], mode + '-' + label + '-build.log')
            run([executable], mode + '-' + label + '.log', env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0'))
            stream = OUT / ('udp-stream-' + label)
            run(['clang', '-std=gnu11', '-Wall', '-Werror', '-pthread', *flags, *udp_fixture_flags,
                 '-Wno-unused-function', *includes, 'Tests/udp_stream_boundaries.c',
                 *libraries, '-o', stream], mode + '-stream-' + label + '-build.log')
            run([stream], mode + '-stream-' + label + '.log',
                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=0', UBSAN_OPTIONS='halt_on_error=1'))
    if 'server' in FEATURES:
        executable = OUT / 'lifecycle-host'
        run(['clang', '-std=gnu11', '-O2', '-Wall', '-Werror', '-pthread', '-I' + str(CORE / 'src'),
             'Tests/server_lifecycle_host.c', *libraries, '-o', executable], mode + '-lifecycle-build.log')
        run([sys.executable, 'Tests/server_lifecycle_regression.py', executable], mode + '-lifecycle.log')
        run(['swiftc', '-swift-version', '5', '-warnings-as-errors', 'Socks5/Server/ServerSettings.swift',
             'Tests/ServerControl/EmitConfiguration.swift', '-o', OUT / 'emit'], 'configuration-emit-build.log')
        run([OUT / 'emit', OUT / 'yaml'], 'configuration-emit.log')
        run(['clang', '-std=gnu11', '-O2', '-Wall', '-Werror', '-pthread', '-I' + str(CORE / 'src'),
             'Tests/ServerControl/configuration_probe.c', *libraries, '-o', OUT / 'config-probe'], 'configuration-probe-build.log')
        run([OUT / 'config-probe', OUT / 'yaml/defaults.yml', OUT / 'yaml/quoted.yml'], mode + '-configuration.log')
        for script in ('native_controller_check', 'delayed_completion_check', 'active_clients_check', 'final_native_check'):
            baseline = (['--worker-baseline-sha256', worker_baseline]
                        if script == 'native_controller_check' and worker_baseline else [])
            run([sys.executable, 'Tests/ServerControl/' + script + '.py', CORE, OUT / (mode + '-' + script), *baseline],
                mode + '-' + script + '.log', timeout=300)
        if 'settings' in FEATURES:
            for script in ('native_persistence_check', 'delayed_persistence_check'):
                run([sys.executable, 'Tests/Settings/' + script + '.py', CORE, OUT / (mode + '-' + script)],
                    mode + '-' + script + '.log', timeout=300)

if 'statistics' in FEATURES:
    run([sys.executable, 'Tests/Statistics/audit_driver_probe.py'], 'audit-driver-probe.log')
    statistics = module('composition_statistics_models', 'Tests/Statistics/audit.py')
    statistics.OUT = OUT / 'statistics'
    statistics.model_checks()
print('PASS: declared native tests; fixed-unknown UDP observation failures remain separately recorded.')
