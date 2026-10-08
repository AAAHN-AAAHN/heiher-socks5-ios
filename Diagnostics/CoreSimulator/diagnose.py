#!/usr/bin/env python3
"""Observe a fresh Simulator and, separately, retain host diagnostics.

No product code is built or changed here. A successful boot is an environment
result only; the workflow then runs the unchanged, exact-commit product gates.
Only the Simulator created by this process is shut down or deleted. Service
restarts, cache deletion, runtime installation and privilege changes are absent.
"""
import argparse
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import pty
import re
import subprocess
import sys
import threading
import time

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument('--output', type=Path, required=True)
PARSER.add_argument('--capture-only', action='store_true')
ARGS = PARSER.parse_args()
OUT = ARGS.output.resolve()
LOCK = threading.Lock()
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'
DEVICE = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'


def event(value):
    value = dict(utc=datetime.now(timezone.utc).isoformat(), **value)
    with LOCK:
        with (OUT / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(value) + '\n')
        print(json.dumps(value), flush=True)


def command(args, name, timeout=15, terminal=False, started=None):
    """Record a command's own deadline and exit status, including stalled reads."""
    path = OUT / (name + '.log')
    beginning = time.monotonic()
    process = None
    master = slave = None
    timed_out = False
    event(dict(stage='begin', name=name, args=args, timeout=timeout))
    with path.open('wb', buffering=0) as stream:
        try:
            if terminal:
                master, slave = pty.openpty()
                os.set_blocking(master, False)
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                stdout=slave if terminal else stream,
                stderr=slave if terminal else subprocess.STDOUT,
                start_new_session=True)
            if slave is not None:
                os.close(slave)
                slave = None
            if started:
                started(process.pid)
            if terminal:
                while True:
                    if process.poll() is None and time.monotonic() - beginning >= timeout:
                        raise subprocess.TimeoutExpired(args, timeout)
                    try:
                        data = os.read(master, 65536)
                        if data:
                            stream.write(data)
                            continue
                    except BlockingIOError:
                        pass
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                    if process.poll() is not None:
                        break
                    if time.monotonic() - beginning >= timeout:
                        raise subprocess.TimeoutExpired(args, timeout)
                    time.sleep(0.05)
            else:
                process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Kill this diagnostic command only, never the Simulator service.
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        except Exception as exc:
            stream.write((repr(exc) + '\n').encode())
            if process and process.poll() is None:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if master is not None:
                os.close(master)
            if slave is not None:
                os.close(slave)
    result = dict(name=name, returncode=process.returncode if process else None,
                  timed_out=timed_out, elapsed_seconds=round(time.monotonic() - beginning, 3))
    event(dict(stage='end', **result))
    return result


def succeeded(result):
    return result['returncode'] == 0 and not result['timed_out']


def snapshot(label, client_pid=None, sample_service=False, stop=None):
    if stop and stop.is_set():
        return
    process_result = command(['/bin/ps', '-axo', 'pid,uid,%cpu,%mem,rss,state,etime,comm'], label + '-processes', timeout=5)
    if (client_pid or sample_service) and succeeded(process_result):
        own_uid = os.getuid()
        selected = [client_pid] if client_pid else []
        for line in (OUT / (label + '-processes.log')).read_text(errors='replace').splitlines()[1:]:
            fields = line.split(None, 7)
            if len(fields) == 8 and fields[1] == str(own_uid) and 'CoreSimulatorService' in fields[7]:
                selected.append(int(fields[0]))
                break
        for pid in dict.fromkeys(selected):
            if stop and stop.is_set():
                return
            command(['/usr/bin/sample', str(pid), '3', '1', '-file', str(OUT / (label + '-sample-' + str(pid) + '.txt'))],
                    label + '-sample-' + str(pid), timeout=8)
    for args, suffix in [(['/usr/bin/vm_stat'], 'vm-stat'),
                         (['/usr/bin/memory_pressure', '-Q'], 'memory-pressure'),
                         (['/bin/df', '-h'], 'disk')]:
        if stop and stop.is_set():
            return
        command(args, label + '-' + suffix, timeout=5)
    # This request has no device argument: preserve whether service enumeration
    # still responds while bootstatus waits for the new device.
    if not stop or not stop.is_set():
        command(['xcrun', 'simctl', 'list', 'devices', '-j'], label + '-devices', timeout=10)


def collect_failure(label):
    snapshot(label, sample_service=True)
    predicate = ('process == "CoreSimulatorService" OR process == "launchd_sim" '
                 'OR subsystem BEGINSWITH "com.apple.CoreSimulator" '
                 'OR process == "SimulatorTrampoline"')
    command(['/usr/bin/log', 'show', '--last', '10m', '--style', 'compact', '--info',
             '--predicate', predicate], label + '-unified-log', timeout=45)
    help_result = command(['xcrun', 'simctl', 'help', 'diagnose'], label + '-diagnose-help')
    if succeeded(help_result):
        help_text = (OUT / (label + '-diagnose-help.log')).read_text(errors='replace')
        if '--output' in help_text:
            directory = OUT / (label + '-diagnose')
            directory.mkdir(exist_ok=True)
            args = ['xcrun', 'simctl', 'diagnose', '-l', '--output', str(directory)]
            if '--timeout' in help_text:
                args += ['--timeout', '45']
            command(args, label + '-diagnose', timeout=55)
        else:
            event(dict(stage='diagnostic-unavailable', name=label,
                       reason='Installed simctl help did not advertise an output directory option.'))


def main():
    if sys.platform != 'darwin' or not __debug__:
        raise SystemExit('Actual macOS and enabled Python assertions are required.')
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = {key: os.environ.get(key) for key in ['GITHUB_SHA', 'GITHUB_RUN_ID',
        'GITHUB_RUN_ATTEMPT', 'RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH',
        'ImageOS', 'ImageVersion', 'DEVELOPER_DIR']}
    metadata.update(product_ui_tests_executed_by_this_script=False,
                    capture_only=ARGS.capture_only, expected_runtime=RUNTIME, expected_device=DEVICE)
    (OUT / 'context.json').write_text(json.dumps(metadata, indent=2) + '\n')
    if ARGS.capture_only:
        collect_failure('after-product-gate')
        return 0
    for args, name in [(['/usr/bin/sw_vers'], 'host-os'), (['/usr/bin/uname', '-m'], 'host-architecture'),
                       (['/usr/sbin/sysctl', 'hw.memsize', 'hw.ncpu'], 'host-capacity'),
                       (['xcode-select', '-p'], 'selected-xcode'), (['xcodebuild', '-version'], 'xcode-version'),
                       (['xcodebuild', '-checkFirstLaunchStatus'], 'first-launch-status'),
                       (['xcrun', '--find', 'simctl'], 'simctl-path'),
                       (['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], 'simulator-sdk'),
                       (['xcrun', 'simctl', 'help', 'bootstatus'], 'bootstatus-help')]:
        command(args, name, timeout=30)
    snapshot('before-boot')
    identifier = None
    boot_result = None
    cleanup = []
    error = None
    try:
        for kind in ['runtimes', 'devicetypes']:
            result = command(['xcrun', 'simctl', 'list', kind, '-j'], kind, timeout=60)
            if not succeeded(result):
                raise RuntimeError('Cannot enumerate ' + kind)
        runtimes = json.loads((OUT / 'runtimes.log').read_text())['runtimes']
        runtime = next(r for r in runtimes if r['identifier'] == RUNTIME and r.get('isAvailable'))
        if DEVICE not in {d['identifier'] for d in runtime.get('supportedDeviceTypes', [])}:
            raise RuntimeError('Requested device is not declared supported by the exact runtime')
        name = 'CoreSimulator Diagnostic ' + os.environ.get('GITHUB_RUN_ID', str(os.getpid()))
        created = command(['xcrun', 'simctl', 'create', name, DEVICE, RUNTIME], 'create', timeout=60)
        if not succeeded(created):
            raise RuntimeError('Disposable device creation failed')
        identifier = (OUT / 'create.log').read_text().strip()
        if not re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', identifier):
            identifier = None
            raise RuntimeError('Device creation did not return one UUID')
        (OUT / 'device.json').write_text(json.dumps(dict(udid=identifier, runtime=runtime, device_type=DEVICE), indent=2) + '\n')
        if not succeeded(command(['xcrun', 'simctl', 'boot', identifier], 'boot', timeout=180)):
            raise RuntimeError('Disposable device boot request failed')
        stop = threading.Event()
        monitors = []

        def observe(pid):
            def collect():
                beginning = time.monotonic()
                for second in [30, 90]:
                    if stop.wait(max(0, second - (time.monotonic() - beginning))):
                        return
                    snapshot('during-boot-' + str(second), client_pid=pid if second == 90 else None, stop=stop)
            thread = threading.Thread(target=collect, daemon=True)
            monitors.append(thread)
            thread.start()

        try:
            # A pseudo-terminal preserves progress normally buffered when the
            # original audit redirects stdout to a file; the deadline stays 120s.
            boot_result = command(['xcrun', 'simctl', 'bootstatus', identifier, '-b'],
                                  'bootstatus', timeout=120, terminal=True, started=observe)
        finally:
            stop.set()
            for thread in monitors:
                thread.join(timeout=30)
        if not succeeded(boot_result):
            raise RuntimeError('Original 120-second boot-readiness boundary failed')
    except Exception as exc:
        error = str(exc)
        event(dict(stage='environment-failure', reason=error))
        collect_failure('boot-failure')
    finally:
        if identifier:
            for action in ['shutdown', 'delete']:
                cleanup.append(command(['xcrun', 'simctl', action, identifier], 'cleanup-' + action, timeout=30))
    success = error is None and boot_result is not None and succeeded(boot_result) and all(map(succeeded, cleanup))
    result = dict(environment_boot_ready=success, error=error, bootstatus=boot_result,
                  cleanup=cleanup, product_ui_gate_result='Recorded separately by the unchanged product audit; not executed by this script.',
                  note='The separate workflow steps run the unchanged exact-commit native, SDK and UI gates only after this environment check succeeds.')
    (OUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
