#!/usr/bin/env python3
"""Replay the UI sample and task bodies with scripted snapshots/state and sleep.

No SwiftUI body rendering, Apple scheduling or real network traffic occurs here.
The task uses real Swift cancellation; wall time, sleep and native read work are controlled.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
VIEW = ROOT / 'Socks5/Statistics/TrafficStatisticsView.swift'
BASELINE_BLOB = '190950bcb80d7e4449fbdc1f772dcc75d4d7128f'
previous = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASELINE_BLOB])
assert hashlib.sha1(b'blob ' + str(len(previous)).encode() + b'\0' + previous).hexdigest() == BASELINE_BLOB
fixture = (ROOT / 'Tests/Statistics/SamplingContractTests.swift').read_text()
mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
assert mode in ('all', 'debug', 'optimized')
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    for label, text in [('current', VIEW.read_text()), ('prior-per-row-negative', previous.decode())]:
        start = text.index('    private func sample()')
        body = text[start:].rsplit('\n}', 1)[0]
        # The historical negative control keeps its per-row publication and
        # I/O behavior; adapt only renamed API types to the current fixture.
        if label == 'prior-per-row-negative':
            body = body.replace('HevSocks5ClientStats', 'HevSocks5EndpointStats')\
                .replace('hev_socks5_server_client_stats', 'hev_socks5_server_endpoint_rows')\
                .replace('hev_socks5_server_stats', 'hev_socks5_server_endpoint_stats')
        # Import the exact current formatter/model, not a rewritten formula.
        generated = fixture.replace('    // INSERT_EXACT_SAMPLE_METHOD', body)
        assert generated != fixture
        source = folder / 'Replay.swift'
        source.write_text(generated)
        for optimized in (False, True):
            if (mode == 'debug' and optimized) or (mode == 'optimized' and not optimized):
                continue
            executable = folder / 'test'
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimized else []),
                            str(ROOT / 'Socks5/Statistics/TrafficStatistics.swift'),
                            str(source), '-o', str(executable)], check=True, timeout=90)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=45)
            print('TEST:', label, 'optimized=', optimized, flush=True)
            print(result.stdout, end='', flush=True)
            if label == 'current':
                assert result.returncode == 0 and 'PASS:' in result.stdout, result.stderr
            else:
                assert result.returncode == 1 and 'FAIL: one client-state publication' in result.stdout, result.stderr
                print('EXPECTED OLD PUBLICATION-COUNT FAILURE; not incorrect native byte accounting', flush=True)
    current = VIEW.read_text()
    task_start = '        .task(id: isVisible && scenePhase == .active) {\n'
    task_end = '\n        }\n    }\n\n    /// One shared'
    assert current.count(task_start) == 1 and current.count(task_end) == 1
    task = current.split(task_start, 1)[1].split(task_end, 1)[0]
    assert task.count('Task.sleep(') == 1
    # Reuse the exact sample and its existing native/state substitutes. Keep
    # the historical publication negative control and its assertions above.
    sample = current[current.index('    private func sample()'):].rsplit('\n}', 1)[0]
    support = fixture.split('@main struct SamplingContractTests', 1)[0]\
        .replace('    // INSERT_EXACT_SAMPLE_METHOD', sample)
    native_read = '    received = NativeSnapshot.rows.reduce'
    assert support.count(native_read) == 1
    # Only the native substitute advances controlled time; the product sample
    # body is unchanged. This makes processing overruns observable to the task.
    support = support.replace(native_read, '    Date.advanceForNativeRead()\n' + native_read)
    task_fixture = (ROOT / 'Tests/Statistics/SamplingTaskTests.swift').read_text()
    generated = support + task_fixture.replace('        // INSERT_EXACT_TASK_BODY',
        task.replace('Task.sleep(', 'SleepBoundary.sleep('))
    assert generated.count('// INSERT_EXACT_') == 0
    sleep = 'SleepBoundary.sleep(for: .seconds(delay))'
    clock = 'let time = ProcessInfo.processInfo.systemUptime'
    assert generated.count(sleep) == 1 and generated.count(clock) == 1
    variants = [
        ('current-task', generated, None),
        # Keep delay referenced so this mutation compiles with warnings-as-errors.
        ('fixed-delay-negative', generated.replace(sleep,
            'SleepBoundary.sleep(for: .seconds(delay * 0 + 0.5))'),
            'FAIL: next sleep targets device-clock .0/.5 boundary'),
        ('wall-time-rate-negative', generated.replace(clock,
            'let time = Date().timeIntervalSinceReferenceDate'),
            'FAIL: Total and peer rates use actual elapsed uptime'),
    ]
    source = folder / 'TaskReplay.swift'
    for label, replay, expected_failure in variants:
        source.write_text(replay)
        for optimized in (False, True):
            if (mode == 'debug' and optimized) or (mode == 'optimized' and not optimized):
                continue
            executable = folder / 'task-test'
            subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                            *(['-O'] if optimized else []),
                            str(ROOT / 'Socks5/Statistics/TrafficStatistics.swift'),
                            str(source), '-o', str(executable)], check=True, timeout=90)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=45)
            print('TEST:', label, 'optimized=', optimized, flush=True)
            print(result.stdout, end='', flush=True)
            if expected_failure is None:
                assert result.returncode == 0 and 'PASS:' in result.stdout, result.stderr
            else:
                assert result.returncode == 1 and expected_failure in result.stdout, result.stderr
                print('EXPECTED SCHEDULING/CLOCK CONTRACT FAILURE', flush=True)
print('PASS: exact sample-body replay, one publication and unchanged snapshot/rate semantics', flush=True)
