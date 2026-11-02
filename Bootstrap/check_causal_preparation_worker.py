#!/usr/bin/env python3
"""Fixed DEBUG/optimized causal fixture and named blocking rejection, without retries."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import runpy
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        raise SystemExit('Run this fixed compilation and runtime matrix on macOS.')
    helper = runpy.run_path(str(Path(__file__).with_name('diagnose_preparation_worker.py')))
    inputs, entry = helper['original_inputs'](args.repo)
    inputs['Test.swift'] = args.fixture.read_text()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'Declared causal preparation fixture on exact historical controller/mocks; not the original fixture or Apple playback.',
              'historical_commit': helper['BASE'], 'fixture_sha256': hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
              'driver_entry_sha256': hashlib.sha256(entry.encode()).hexdigest(),
              'platform': platform.platform(),
              'swift_version': subprocess.check_output(['swiftc', '--version'], text=True),
              'input_sha256': {name: hashlib.sha256(body.encode()).hexdigest() for name, body in inputs.items()},
              'commands': []}
    passed = True
    try:
        for mode in ('debug', 'optimized'):
            folder = args.output / mode
            folder.mkdir()
            for name, body in inputs.items():
                (folder / name).write_text(body)
            exe = folder / 'fixture'
            command = ['swiftc', '-swift-version', '5', '-warnings-as-errors', *(['-O'] if mode == 'optimized' else []),
                *[str(folder / name) for name in ('PlatformMocks.swift', 'Controller.swift', 'Test.swift')], '-o', str(exe)]
            compiled = helper['run'](command, folder, 'compile', 90)
            report['commands'].append({'mode': mode, **compiled})
            if compiled['returncode'] != 0:
                passed = False
                continue
            for kind, arguments in [('positive', []), ('blocking-control', ['blocking-control'])]:
                result = helper['run']([str(exe), *arguments], folder, kind, 30)
                observations = [json.loads(line.removeprefix('PREPARATION_HEARTBEAT_OBSERVATION '))
                    for line in result['stderr'].splitlines() if line.startswith('PREPARATION_HEARTBEAT_OBSERVATION ')]
                if kind == 'positive':
                    valid = (result['returncode'] == 0 and 'PASS:' in result['stdout']
                             and len(observations) == 1 and observations[0]['beats'] >= 3
                             and observations[0]['preparations'] == 1 and observations[0]['preparationsOnMain'] == 0
                             and observations[0]['releasedByHeartbeats'] is True)
                else:
                    valid = (result['returncode'] is not None and result['returncode'] != 0
                             and len(observations) == 1 and observations[0]['beats'] == 0
                             and observations[0]['preparations'] == 1 and observations[0]['preparationsOnMain'] == 1
                             and observations[0]['releasedByHeartbeats'] is False
                             and 'PREPARATION_HEARTBEAT_DID_NOT_PROGRESS' in result['stderr'])
                result['expected_outcome_observed'] = bool(valid)
                result['observations'] = observations
                report['commands'].append({'mode': mode, **result})
                print(mode, kind, 'expected_outcome=', valid, 'returncode=', result['returncode'], flush=True)
                passed = passed and bool(valid)
        report['matrix_complete'] = len(report['commands']) == 6
        report['passed'] = passed and report['matrix_complete']
    finally:
        (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
