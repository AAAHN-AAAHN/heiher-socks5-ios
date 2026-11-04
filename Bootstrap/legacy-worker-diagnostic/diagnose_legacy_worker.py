#!/usr/bin/env python3
"""Execute a fixed historical/observed/declared-causal matrix on actual macOS.

Every selected binary runs once. The exact historical failure remains evidence;
an observed or causal result cannot replace its outcome or earn candidate credit.
"""
import argparse
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

BASE = '618b3d2b413937aaad7373ee2af9e693ec81b84a'
ENTRY_SHA = '3c328e52f33d5c731306a535b6bb923eb1bce27e89eb0367b67c213be761017d'
EXPECTED = {
    'Controller.swift': '0595d9f05d35f1f63d5e5b6ab6ce8e7487bf8e96560e10403febce382f34a6ec',
    'Test.swift': '91d5f6acdcbae6a32269cfa42653acf33aba1048b297a4314f68774f9e10519f',
    'PlatformMocks.swift': '59f9aed88294a478bd54c1d5a548a213b2d8c38c37bce6b7d800806d1a678648',
}
ASSERTION = '        precondition(state.result == true && session.isActive && !session.synchronousOnMain && state.beats >= 3)'
OBSERVATION = '''        let observation: [String: Any] = [
            "resultReceived": state.result != nil, "result": state.result ?? false,
            "sessionIsActive": session.isActive, "synchronousOnMain": session.synchronousOnMain,
            "beats": state.beats, "synchronousCalls": session.synchronousCalls,
            "observationUptime": ProcessInfo.processInfo.systemUptime,
            "observedOnMain": Thread.isMainThread]
        let observationData = try! JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys])
        FileHandle.standardError.write(Data("LEGACY_ORIGINAL_OBSERVATION ".utf8) + observationData + Data("\\n".utf8))
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def git(repo, *arguments):
    return subprocess.check_output(['git', '-C', str(repo), *arguments], timeout=30)


def original_inputs(repo):
    entry = git(repo, 'show', BASE + ':Tests/Background/check_async_session.py')
    require(digest(entry) == ENTRY_SHA, 'Historical driver bytes differ.')
    literals = {}
    for node in ast.parse(entry).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                literals[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    controller = git(repo, 'show', BASE + ':' + literals['CONTROLLER']).decode() + literals['extension']
    require(controller.count(literals['IMPORTS']) == 1, 'Unexpected original import boundary.')
    controller = controller.replace(literals['IMPORTS'], 'import Foundation\n', 1)
    inputs = {'Controller.swift': controller.encode(), 'Test.swift': literals['legacy'].encode(),
              'PlatformMocks.swift': git(repo, 'show', BASE + ':Tests/Background/PlatformMocks.swift')}
    for name, body in inputs.items():
        require(digest(body) == EXPECTED[name], 'Historical failed input differs: ' + name)
    return inputs, entry


def observed_inputs(original):
    observed = dict(original)
    test = original['Test.swift'].decode()
    require(test.count(ASSERTION) == 1, 'Unexpected exact failing assertion boundary.')
    changed = test.replace(ASSERTION, OBSERVATION + ASSERTION, 1)
    require(changed.replace(OBSERVATION, '', 1) == test, 'Observation cannot be removed exactly.')
    require([line.strip() for line in changed.splitlines() if line.strip().startswith('precondition(')] ==
            [line.strip() for line in test.splitlines() if line.strip().startswith('precondition(')],
            'Observation changed an original precondition.')
    observed['Test.swift'] = changed.encode()
    return observed


def execute(command, folder, label, timeout):
    started = time.monotonic()
    row = {'command': command, 'label': label, 'timeout_seconds': timeout, 'started_utc': utc()}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        row.update({'returncode': result.returncode, 'timed_out': False,
                    'stdout': result.stdout, 'stderr': result.stderr})
    except subprocess.TimeoutExpired as error:
        def decode(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
        row.update({'returncode': None, 'timed_out': True,
                    'stdout': decode(error.stdout), 'stderr': decode(error.stderr)})
    row.update({'finished_utc': utc(), 'elapsed_seconds': time.monotonic() - started})
    for stream in ('stdout', 'stderr'):
        (folder / (label + '.' + stream + '.txt')).write_text(row[stream])
    (folder / (label + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    return row


def observations(result, prefix):
    return [json.loads(line[len(prefix):]) for line in result['stderr'].splitlines() if line.startswith(prefix)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__ and sys.platform == 'darwin' and platform.machine() == 'arm64',
            'Actual macOS arm64 and enabled assertions are required.')
    repo = args.repo.resolve()
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    require(head == os.environ['GITHUB_SHA'], 'Checkout differs from actual diagnostic control SHA.')
    require(os.environ['GITHUB_REPOSITORY'] == 'AAAHN-AAAHN/heiher-socks5-ios', 'Unexpected repository.')
    require(git(repo, 'status', '--porcelain', '--untracked-files=no') == b'', 'Tracked checkout is dirty.')
    args.output.mkdir(parents=True, exist_ok=False)
    original, entry = original_inputs(repo)
    observed = observed_inputs(original)
    pins_path = Path(__file__).with_name('pins.json')
    pins = json.loads(pins_path.read_bytes())
    fixture_path = Path(__file__).with_name('LegacyWorkerCausalTests.swift')
    fixture = fixture_path.read_bytes()
    require(digest(fixture) == pins['causal_fixture_sha256'], 'Unreviewed causal fixture bytes.')
    require(pins['original_input_sha256'] == EXPECTED and pins['historical_entry_sha256'] == ENTRY_SHA,
            'Historical input pins differ.')
    causal = {**original, 'Test.swift': fixture}
    original_asserts = [line.strip() for line in original['Test.swift'].decode().splitlines()
                       if line.strip().startswith('precondition(')]
    causal_asserts = [line.strip() for line in fixture.decode().splitlines()
                     if line.strip().startswith('precondition(')]
    require(all(causal_asserts.count(line) == original_asserts.count(line) for line in original_asserts),
            'Causal fixture omitted or duplicated an original precondition.')
    (args.output / 'historical-entry.py').write_bytes(entry)
    report = {'schema': 'legacy-worker-fixed-diagnostic-matrix-v1', 'started_utc': utc(),
              'scope': 'No candidate/canonical/D28 acceptance. Original, observed, and declared causal outcomes remain distinct.',
              'historical_commit': BASE, 'historical_entry_sha256': ENTRY_SHA,
              'original_failed_run': {'id': 41740668457, 'attempt': 1, 'job_id': 126281119452,
                                      'artifact_id': 13284000105, 'original_failure_overwritten': False},
              'actual_context': {name: os.environ[name] for name in
                  ('GITHUB_SHA', 'GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB')},
              'actual_control_tree': git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip(),
              'platform': platform.platform(), 'python': sys.version,
              'swift_version': subprocess.check_output(['swiftc', '--version'], text=True, timeout=30),
              'xcode_version': subprocess.check_output(['xcodebuild', '-version'], text=True, timeout=30),
              'pins_sha256': digest(pins_path.read_bytes()), 'input_sha256': {}, 'commands': [],
              'project_complete': False, 'formal_gate_credit': False, 'retries': 0}
    report_path = args.output / 'results.json'
    expected_ok = True
    matrix = [('exact-original', 'debug', original, [('execute', [])]),
              ('observed-copy', 'debug', observed, [('execute', [])]),
              ('declared-causal', 'debug', causal, [('positive', []), ('blocking-control', ['blocking-control'])]),
              ('declared-causal', 'optimized', causal, [('positive', []), ('blocking-control', ['blocking-control'])])]
    try:
        for variant, mode, inputs, invocations in matrix:
            folder = args.output / (variant + '-' + mode)
            folder.mkdir()
            for name, body in inputs.items():
                (folder / name).write_bytes(body)
            report['input_sha256'][folder.name] = {name: digest(body) for name, body in inputs.items()}
            exe = folder / 'fixture'
            command = ['swiftc', '-swift-version', '5', '-warnings-as-errors',
                       *(['-O'] if mode == 'optimized' else []),
                       *[str(folder / name) for name in ('PlatformMocks.swift', 'Controller.swift', 'Test.swift')],
                       '-o', str(exe)]
            compiled = execute(command, folder, 'compile', 90)
            report['commands'].append({'variant': variant, 'mode': mode, **compiled})
            report_path.write_text(json.dumps(report, indent=2) + '\n')
            if compiled['returncode'] != 0:
                expected_ok = False
                continue
            for label, arguments in invocations:
                result = execute([str(exe), *arguments], folder, label, 30)
                valid = result['returncode'] == 0
                if variant == 'observed-copy':
                    result['observations'] = observations(result, 'LEGACY_ORIGINAL_OBSERVATION ')
                    valid = valid and len(result['observations']) == 1
                elif variant == 'declared-causal':
                    rows = observations(result, 'LEGACY_HEARTBEAT_OBSERVATION ')
                    result['observations'] = rows
                    if label == 'positive':
                        valid = (valid and len(rows) == 1 and rows[0]['beats'] >= 3
                                 and rows[0]['synchronousCalls'] == 1 and rows[0]['synchronousOnMain'] is False
                                 and rows[0]['releasedByHeartbeats'] is True and rows[0]['sessionIsActive'] is True
                                 and rows[0]['result'] is True)
                    else:
                        valid = (result['returncode'] is not None and result['returncode'] != 0 and not result['timed_out']
                                 and len(rows) == 1 and rows[0]['beats'] == 0
                                 and rows[0]['synchronousCalls'] == 1 and rows[0]['synchronousOnMain'] is True
                                 and rows[0]['releasedByHeartbeats'] is False
                                 and 'LEGACY_HEARTBEAT_DID_NOT_PROGRESS' in result['stderr'])
                result['expected_outcome_observed'] = bool(valid)
                report['commands'].append({'variant': variant, 'mode': mode, **result})
                expected_ok = expected_ok and bool(valid)
                report_path.write_text(json.dumps(report, indent=2) + '\n')
                print(variant, mode, label, 'actual_returncode=', result['returncode'],
                      'expected_outcome=', valid, flush=True)
        report['matrix_complete'] = len(report['commands']) == 10
        report['all_expected_outcomes_observed'] = expected_ok and report['matrix_complete']
        report['checkout_clean_after'] = git(repo, 'status', '--porcelain', '--untracked-files=no') == b''
        require(report['checkout_clean_after'], 'Diagnostic modified tracked source.')
    finally:
        report['finished_utc'] = utc()
        report_path.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['all_expected_outcomes_observed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
