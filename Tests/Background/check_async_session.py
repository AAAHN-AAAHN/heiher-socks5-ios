#!/usr/bin/env python3
"""Preserve historical controls and declare a causal preparation-worker fixture.

The old fixed-120ms heartbeat observation remains preserved as historical evidence;
it is not reported as a pass from this explicitly revised fixture. The controller,
platform double, original negative controls, assertion meaning and limits remain.
"""
import ast
import hashlib
from pathlib import Path
import runpy
import subprocess
import sys

if not __debug__:
    raise SystemExit('Assertions must be enabled.')

HERE = Path(__file__).resolve().parent
history = runpy.run_path(str(HERE / 'historical_checks.py'))['run_historical']


def preparation_revision(original):
    """Revise only the named fixture and add its main-blocking rejection control."""
    source = original.decode()
    assignments = [node for node in ast.parse(source).body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == 'preparation_worker']
    assert len(assignments) == 1
    assignment = assignments[0]
    previous = ast.literal_eval(assignment.value)
    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
    assert previous_sha == '0bdcea655523bac57c4c0b87bd9222340732c54d23774d7dd04e4783d4162be9'
    fixture = (HERE / 'PreparationWorkerCausalTests.swift').read_text()
    # Retain the four existing checks verbatim; the causal check is additional.
    for check in (
        'precondition(state.result == true && state.beats >= 3)',
        'precondition(AVAudioPlayer.preparations == 1 && AVAudioPlayer.preparationsOnMain == 0)',
        'precondition(player.isPrepared && !player.isPlaying)',
        'precondition(player.play() && AVAudioPlayer.implicitPreparations == 0)',
    ):
        assert previous.count(check) == fixture.count(check) == 1
    lines = source.splitlines(keepends=True)
    source = ''.join(lines[:assignment.lineno - 1]) + 'preparation_worker = ' + repr(fixture) + '\n' + ''.join(lines[assignment.end_lineno:])
    anchor = '                subprocess.run([str(exe)], check=True, timeout=30)\n'
    assert source.count(anchor) == 1
    control = '''                if label == 'preparation-worker':
                    command = [str(exe), 'blocking-control']
                    blocked = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    print('CAUSAL PREPARATION BLOCKING CONTROL:', json.dumps({
                        'optimized': optimize, 'returncode': blocked.returncode,
                        'stdout': blocked.stdout, 'stderr': blocked.stderr,
                        'execution_timeout_seconds': 30,
                    }, sort_keys=True), flush=True)
                    observations = [json.loads(line.removeprefix('PREPARATION_HEARTBEAT_OBSERVATION '))
                        for line in blocked.stderr.splitlines() if line.startswith('PREPARATION_HEARTBEAT_OBSERVATION ')]
                    rejected = (blocked.returncode != 0 and len(observations) == 1
                        and observations[0]['beats'] == 0
                        and observations[0]['preparations'] == 1
                        and observations[0]['preparationsOnMain'] == 1
                        and observations[0]['releasedByHeartbeats'] is False
                        and 'PREPARATION_HEARTBEAT_DID_NOT_PROGRESS' in blocked.stderr)
                    if not rejected:
                        raise subprocess.CalledProcessError(blocked.returncode or 1, command,
                            output=blocked.stdout, stderr=blocked.stderr)
                    print('PASS: causal preparation fixture rejects main-thread blocking', flush=True)
'''
    source = source.replace(anchor, anchor + control, 1)
    # Every other historical fixture literal and controller source selection stays
    # byte-identical; the altered driver is saved beside the original by history.
    ast.parse(source)
    return source.encode(), {
        'name': 'causal-preparation-heartbeats-v1',
        'fixture_file': 'Tests/Background/PreparationWorkerCausalTests.swift',
        'previous_fixture_sha256': previous_sha,
        'fixture_sha256': hashlib.sha256(fixture.encode()).hexdigest(),
        'controller_and_platform_double': 'Exact historical inputs, unchanged.',
        'retained_original_controls': 'All other historical fixtures and their compile/execution limits are unchanged.',
        'change': 'Hold the mock preparation until three real main heartbeats occur, within the same two-second total deadline; additionally reject direct main-thread preparation.',
        'process_timeout_seconds': 30, 'fixture_deadline_seconds': 2,
        'claim_boundary': 'Declared new fixture, not an exact historical fixture pass or Apple playback evidence.',
    }


if __name__ == '__main__':
    history('check_async_session.py', entry_revision=preparation_revision)
    subprocess.run([sys.executable, str(HERE / 'check_loop_audio.py'), '--group', 'adapter'], check=True)
