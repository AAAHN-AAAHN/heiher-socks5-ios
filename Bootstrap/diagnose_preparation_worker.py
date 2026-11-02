#!/usr/bin/env python3
"""Run one exact historical fixture and one observed copy; never retry a failure.

The original source, assertions, 120ms delay, two-second fixture deadline and
30-second process deadline are preserved. The observed copy only records thread
and monotonic event information. Its outcome never substitutes for the original.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time

BASE = '618b3d2b413937aaad7373ee2af9e693ec81b84a'
EXPECTED = {
    'Controller.swift': '0595d9f05d35f1f63d5e5b6ab6ce8e7487bf8e96560e10403febce382f34a6ec',
    'Test.swift': '0bdcea655523bac57c4c0b87bd9222340732c54d23774d7dd04e4783d4162be9',
    'PlatformMocks.swift': '59f9aed88294a478bd54c1d5a548a213b2d8c38c37bce6b7d800806d1a678648',
}
TRACE = r'''
final class PreparationTrace: @unchecked Sendable {
    static let shared = PreparationTrace()
    private let lock = NSLock()
    func emit(_ event: String, _ detail: String = "") {
        lock.lock(); defer { lock.unlock() }
        let row: [String: Any] = ["event": event,
            "uptime": ProcessInfo.processInfo.systemUptime,
            "main": Thread.isMainThread,
            "thread": String(describing: Thread.current), "detail": detail]
        let data = try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
        FileHandle.standardError.write(Data("PREPARATION_TRACE ".utf8) + data + Data("\n".utf8))
    }
}
'''


def replace_once(text, before, after):
    assert text.count(before) == 1, ('Unexpected original source anchor', before)
    return text.replace(before, after, 1)


def original_inputs(repo):
    def read(path):
        return subprocess.check_output(['git', '-C', str(repo), 'show', BASE + ':' + path]).decode()
    entry = read('Tests/Background/check_async_session.py')
    literals = {}
    for node in ast.parse(entry).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                literals[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    controller = read(literals['CONTROLLER']) + literals['extension']
    controller = replace_once(controller, literals['IMPORTS'], 'import Foundation\n')
    inputs = {'Controller.swift': controller, 'Test.swift': literals['preparation_worker'],
              'PlatformMocks.swift': read('Tests/Background/PlatformMocks.swift')}
    for name, body in inputs.items():
        assert hashlib.sha256(body.encode()).hexdigest() == EXPECTED[name], name
    return inputs, entry


def observed_inputs(original):
    observed = dict(original)
    mocks = replace_once(original['PlatformMocks.swift'], '    func prepareToPlay() -> Bool {\n',
        '    func prepareToPlay() -> Bool {\n'
        '        PreparationTrace.shared.emit("prepare-enter", "delay=\\(Self.preparationDelay)")\n'
        '        defer { PreparationTrace.shared.emit("prepare-exit", "preparations=\\(Self.preparations) onMain=\\(Self.preparationsOnMain) prepared=\\(isPrepared)") }\n')
    observed['PlatformMocks.swift'] = mocks + TRACE
    test = replace_once(original['Test.swift'],
        '            MainActor.assumeIsolated { state.beats += 1 }',
        '            MainActor.assumeIsolated {\n'
        '                state.beats += 1\n'
        '                PreparationTrace.shared.emit("heartbeat", "beats=\\(state.beats)")\n'
        '            }')
    test = replace_once(test, '        func observe(_ stage: String, _ values: String) {\n',
        '        func observe(_ stage: String, _ values: String) {\n'
        '            PreparationTrace.shared.emit(stage, values)\n')
    test = replace_once(test, '            DispatchQueue.main.async { state.result = success }',
        '            PreparationTrace.shared.emit("worker-completion", "success=\\(success)")\n'
        '            DispatchQueue.main.async {\n'
        '                state.result = success\n'
        '                PreparationTrace.shared.emit("main-completion", "beats=\\(state.beats)")\n'
        '            }')
    test = replace_once(test, '        let limit = Date().addingTimeInterval(2)',
        '        PreparationTrace.shared.emit("request-return")\n'
        '        let limit = Date().addingTimeInterval(2)')
    test = replace_once(test, '        precondition(state.result == true && state.beats >= 3)',
        '        PreparationTrace.shared.emit("before-first-assertion", "result=\\(String(describing: state.result)) beats=\\(state.beats) preparations=\\(AVAudioPlayer.preparations) onMain=\\(AVAudioPlayer.preparationsOnMain) prepared=\\(player.isPrepared) playing=\\(player.isPlaying)")\n'
        '        precondition(state.result == true && state.beats >= 3)')
    observed['Test.swift'] = test
    assert observed['Controller.swift'] == original['Controller.swift']
    assert [line.strip() for line in test.splitlines() if line.strip().startswith('precondition(')] == [
        line.strip() for line in original['Test.swift'].splitlines() if line.strip().startswith('precondition(')]
    return observed


def run(command, folder, label, timeout):
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        row = {'command': command, 'returncode': result.returncode, 'timed_out': False,
               'stdout': result.stdout, 'stderr': result.stderr}
    except subprocess.TimeoutExpired as error:
        def decode(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
        row = {'command': command, 'returncode': None, 'timed_out': True,
               'stdout': decode(error.stdout), 'stderr': decode(error.stderr)}
    row.update({'label': label, 'timeout_seconds': timeout, 'elapsed_seconds': time.monotonic() - started,
                'host_load_after': list(os.getloadavg())})
    for stream in ('stdout', 'stderr'):
        (folder / (label + '.' + stream + '.txt')).write_text(row[stream])
    row['events'] = [json.loads(line.removeprefix('PREPARATION_TRACE '))
                     for line in row['stderr'].splitlines() if line.startswith('PREPARATION_TRACE ')]
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('debug', 'optimized', 'all'), default='debug')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        raise SystemExit('This fixed diagnostic is for the actual macOS host.')
    args.output.mkdir(parents=True, exist_ok=False)
    original, entry = original_inputs(args.repo)
    observed = observed_inputs(original)
    (args.output / 'historical-entry.py').write_text(entry)
    report = {'historical_commit': BASE, 'historical_entry_sha256': hashlib.sha256(entry.encode()).hexdigest(),
              'scope': 'Fixed one original and one observed run per requested mode; no retries, no assertion changes, no replacement of an original failure.',
              'platform': platform.platform(), 'host_load_before': list(os.getloadavg()),
              'tested_repo_head': subprocess.check_output(['git', '-C', str(args.repo), 'rev-parse', 'HEAD'], text=True).strip(),
              'swift_version': subprocess.check_output(['swiftc', '--version'], text=True),
              'input_sha256': {}, 'commands': []}
    modes = ('debug', 'optimized') if args.mode == 'all' else (args.mode,)
    try:
        for variant, inputs in [('exact-original', original), ('observed-copy', observed)]:
            for mode in modes:
                folder = args.output / (variant + '-' + mode)
                folder.mkdir()
                for name, body in inputs.items():
                    (folder / name).write_text(body)
                report['input_sha256'][folder.name] = {name: hashlib.sha256(body.encode()).hexdigest() for name, body in inputs.items()}
                exe = folder / 'fixture'
                command = ['swiftc', '-swift-version', '5', '-warnings-as-errors',
                           *(['-O'] if mode == 'optimized' else []),
                           *[str(folder / name) for name in ('PlatformMocks.swift', 'Controller.swift', 'Test.swift')], '-o', str(exe)]
                compiled = run(command, folder, 'compile', 90)
                report['commands'].append({'variant': variant, 'mode': mode, **compiled})
                if compiled['returncode'] == 0:
                    result = run([str(exe)], folder, 'execute', 30)
                    report['commands'].append({'variant': variant, 'mode': mode, **result})
                    print(variant, mode, 'returncode=', result['returncode'], 'timed_out=', result['timed_out'], flush=True)
        report['diagnostic_matrix_complete'] = len(report['commands']) == len(modes) * 4
        report['all_fixture_invocations_passed'] = report['diagnostic_matrix_complete'] and all(row['returncode'] == 0 for row in report['commands'])
    finally:
        (args.output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['all_fixture_invocations_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
