#!/usr/bin/env python3
"""One fixed, fail-closed two-device Simulator lifecycle diagnostic.

No app/UI execution, retry, service reset, global shutdown, or product PASS claim.
Run on the same xcode-27 runner image as the failed Integrated runtime job.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from simulator_diagnostics import capture_failure, output_bytes, record_command


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not __debug__ or sys.platform != 'darwin' or out.exists():
        raise SystemExit('Use assertions, macOS and a fresh diagnostic output path')
    out.mkdir(parents=True)
    calls = []

    def run(command, timeout, label):
        number = len(calls) + 1
        record = {'label': label, 'command': command, 'timeout_seconds': timeout,
                  'stdout': f'{number:02d}-{label}.stdout.log',
                  'stderr': f'{number:02d}-{label}.stderr.log'}
        calls.append(record)
        started, started_unix = time.monotonic(), time.time()
        error = None
        result = None
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout)
            (out / record['stdout']).write_bytes(result.stdout)
            (out / record['stderr']).write_bytes(result.stderr)
            record['returncode'] = result.returncode
            if result.returncode:
                raise subprocess.CalledProcessError(result.returncode, command)
            return result.stdout.decode('utf-8').strip()
        except Exception as exc:
            error = exc
            record['error'] = repr(exc)
            if isinstance(exc, subprocess.TimeoutExpired):
                (out / record['stdout']).write_bytes(output_bytes(exc.stdout))
                (out / record['stderr']).write_bytes(output_bytes(exc.stderr))
            raise
        finally:
            record['elapsed_seconds'] = time.monotonic() - started
            record_command(out, 'commands.jsonl', command, timeout, started,
                           started_unix, error, getattr(result, 'returncode', None))

    report = {'schema': 1, 'started_unix': time.time(),
              'helper_sha': os.environ.get('GITHUB_SHA'),
              'run_id': os.environ.get('GITHUB_RUN_ID'),
              'attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'runner': os.environ.get('RUNNER_NAME'),
              'planned_cycles': 2, 'cycles': [], 'commands': calls,
              'product_pass': False,
              'scope': 'Isolated simctl lifecycle only; no app, UI or product gate. A pass does not explain a previous failure.'}
    failure = None
    try:
        report['toolchain'] = run(['xcodebuild', '-version'], 30, 'xcode-version')
        runtimes = json.loads(run(['xcrun', 'simctl', 'list', 'runtimes', '-j'], 60, 'runtimes'))['runtimes']
        types = json.loads(run(['xcrun', 'simctl', 'list', 'devicetypes', '-j'], 60, 'device-types'))['devicetypes']
        runtime = next(r for r in runtimes if r.get('isAvailable') and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
        device_type = next(t for t in types if t['name'] == 'iPhone 16')
        report['runtime'], report['device_type'] = runtime, device_type
        for index, (name, create_limit, boot_limit, ready_limit) in enumerate([
            ('ui', 60, 180, 120), ('production', 120, 120, 240)
        ], start=1):
            row = {'index': index, 'kind': name, 'device': None, 'stage': 'create',
                   'success': False, 'cleanup_errors': []}
            report['cycles'].append(row)
            primary = None
            try:
                row['device'] = run(['xcrun', 'simctl', 'create', f'Integrated {name} fixed diagnostic',
                                     device_type['identifier'], runtime['identifier']], create_limit, name + '-create')
                row['stage'] = 'boot'
                run(['xcrun', 'simctl', 'boot', row['device']], boot_limit, name + '-boot')
                row['stage'] = 'bootstatus'
                run(['xcrun', 'simctl', 'bootstatus', row['device'], '-b'], ready_limit, name + '-ready')
                row['stage'] = 'ready'
            except Exception as exc:
                primary = exc
                row['failure'] = repr(exc)
                capture_failure(out, name + '-' + row['stage'], row['device'], exc)
            finally:
                if row['device']:
                    for action in ('shutdown', 'delete'):
                        try:
                            run(['xcrun', 'simctl', action, row['device']], 30, name + '-' + action)
                        except Exception as exc:
                            row['cleanup_errors'].append({'action': action, 'error': repr(exc)})
                    if row['cleanup_errors']:
                        capture_failure(out, name + '-cleanup', row['device'], row['cleanup_errors'])
            if primary is not None:
                raise primary
            if row['cleanup_errors']:
                raise RuntimeError('Diagnostic cleanup did not succeed: ' + repr(row['cleanup_errors']))
            row['success'] = True
            row['stage'] = 'deleted'
    except Exception as exc:
        failure = exc
        report['error'] = repr(exc)
        if not report['cycles']:
            capture_failure(out, 'selection', None, exc)
    report['result'] = 'DIAGNOSTIC_PASS' if failure is None else 'DIAGNOSTIC_FAIL'
    report['finished_unix'] = time.time()
    (out / 'diagnostic-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(report['result'], 'cycles:', len(report['cycles']), 'product_pass: false')
    if failure is not None:
        raise failure


if __name__ == '__main__':
    main()
