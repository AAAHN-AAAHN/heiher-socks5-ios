#!/usr/bin/env python3
"""One predefined standard-host qualification, without product execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parents[1]
out = root / 'artifacts/host-qualification'
out.mkdir(parents=True, exist_ok=True)
assert os.uname().sysname == 'Darwin'
records = []


def run(label, command, timeout=120):
    began = time.monotonic()
    with (out / (label + '.log')).open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    records.append({'label': label, 'argv': command, 'exit_code': result.returncode,
                    'elapsed_seconds': time.monotonic() - began})
    (out / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
    assert result.returncode == 0, label


run('os', ['sw_vers'])
run('architecture', ['uname', '-m'])
run('cpu', ['sysctl', 'hw.model', 'hw.logicalcpu', 'hw.memsize'])
run('compiler', ['xcrun', 'swiftc', '--version'])
run('sdk', ['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'])
source = root / 'Diagnostics/FixtureCosts.swift'
(out / source.name).write_bytes(source.read_bytes())
binary = out / 'unmodified-host-costs'
run('compile', ['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5',
               '-strict-concurrency=complete', '-warnings-as-errors', '-Onone',
               str(source), '-o', str(binary)])
run('costs', [str(binary)], timeout=30)
costs = json.loads((out / 'costs.log').read_text())
timer = next(item for item in costs['measurements'] if item['name'] == 'same_timer_1000')
qualified = timer['complete'] and timer['completed_ticks'] == 1000 and timer['elapsed_seconds'] <= 8
record = {'result': 'QUALIFIED' if qualified else 'NOT_QUALIFIED',
          'criterion': 'Unmodified default-queue one-shot 5ms+1ms-leeway timer completes 1000 ticks within 8s, retaining its original 10s cutoff.',
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
          'timer': timer, 'runner_label': 'macos-26-intel',
          'control_commit': os.environ['GITHUB_SHA'], 'run_id': os.environ['GITHUB_RUN_ID'],
          'attempt': os.environ['GITHUB_RUN_ATTEMPT'],
          'scope': 'One different standard Intel host. No product test or iOS 27 SDK claim, no activity/priority/timer changes, no new paid runner.',
          'next_step': 'Execute unchanged source predicates once only if qualified; otherwise retain prior failures and do not retry for luck.'}
(out / 'qualification.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
