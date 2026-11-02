#!/usr/bin/env python3
"""Bounded, read-only evidence for a failed Simulator operation.

Never starts/stops a device, restarts a service, retries a failed gate, or changes
its result. Host evidence is collected even when a device has not finished boot.
"""
import json
from pathlib import Path
import subprocess
import sys
import time


def warning(message):
    try:
        print(message, file=sys.stderr, flush=True)
    except Exception:
        pass


def record_command(out, filename, command, timeout, started, started_unix,
                   failure=None, returncode=None):
    record = {'command': list(map(str, command)), 'timeout_seconds': timeout,
              'started_unix': started_unix, 'finished_unix': time.time(),
              'elapsed_seconds': time.monotonic() - started,
              'failure': type(failure).__name__ if failure else None,
              'returncode': returncode}
    try:
        with (Path(out) / filename).open('a') as stream:
            stream.write(json.dumps(record) + '\n')
    except Exception as error:
        if failure is None:
            raise
        warning('Command timing evidence could not be saved: ' + repr(error))


def output_bytes(value):
    if value is None:
        return b''
    return value if isinstance(value, bytes) else value.encode('utf-8')


def capture_failure(out, phase, device, failure):
    """Best effort, at most 20 seconds of diagnostic command time per capture."""
    try:
        folder = Path(out) / ('failure-' + phase)
        folder.mkdir(parents=True, exist_ok=True)
        receipt = {'phase': phase, 'device': device, 'original_error': repr(failure),
                   'started_unix': time.time(), 'budget_seconds': 20, 'commands': [],
                   'scope': 'Read-only failure evidence; no gate retry or device/service mutation.'}
        deadline = time.monotonic() + 20
        predicate = ('process == "CoreSimulatorService" OR process == "simulatord" '
                     'OR process == "Simulator" OR subsystem BEGINSWITH "com.apple.CoreSimulator"')
        if device:
            # Device identifiers come from simctl create; JSON quoting prevents
            # interpretation as additional log-predicate syntax.
            predicate += ' OR eventMessage CONTAINS[c] ' + json.dumps(device)
        checks = [
            ('processes', ['/bin/ps', '-axo', 'pid,ppid,state,etime,%cpu,%mem,comm'], 2),
            ('virtual-memory', ['/usr/bin/vm_stat'], 2),
            ('disk', ['/bin/df', '-k', str(Path(out).resolve())], 2),
            ('devices', ['xcrun', 'simctl', 'list', 'devices', '-j'], 4),
            ('host-core-simulator', ['/usr/bin/log', 'show', '--last', '5m',
                                    '--style', 'compact', '--info', '--predicate', predicate], 10),
        ]
        for label, command, limit in checks:
            remaining = deadline - time.monotonic()
            item = {'name': label, 'command': command}
            if remaining <= 0:
                item['error'] = 'Diagnostic capture budget exhausted; command not started'
            else:
                item['timeout_seconds'] = min(limit, remaining)
                started = time.monotonic()
                try:
                    # File output retains partial bytes even if the command times
                    # out, without borrowing subprocess PIPEs after its exit.
                    with (folder / (label + '.log')).open('wb') as log:
                        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                                timeout=item['timeout_seconds'])
                    item['returncode'] = result.returncode
                except Exception as error:
                    item['error'] = repr(error)
                item['elapsed_seconds'] = time.monotonic() - started
            receipt['commands'].append(item)
        receipt['finished_unix'] = time.time()
        (folder / 'capture.json').write_text(json.dumps(receipt, indent=2) + '\n')
    except Exception as error:
        warning('Failed to preserve Simulator diagnostics: ' + repr(error))
