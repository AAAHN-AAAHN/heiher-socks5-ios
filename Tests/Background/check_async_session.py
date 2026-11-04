#!/usr/bin/env python3
"""Preserve historical controls and declare two causal worker fixtures.

The old fixed120ms preparation-worker and legacy-worker observations remain
preserved as historical evidence. Neither is reported as a pass from these two
explicit revisions. The controller, platform double, historical negative and
implicit-preparation controls, original assertions and every limit remain.
The legacy revision uses the unchanged onActivation hook and does not relabel
the prior failed legacy observation or claim its unrecorded predicate values.
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
    """Revise only the two named fixtures and add their main-blocking rejection controls."""
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
    # Explicit additional revision of the named legacy fixture only. The
    # preparation-worker transformation and its control above remain unchanged.
    legacy_assignments = [node for node in ast.parse(source).body if isinstance(node, ast.Assign)
                          and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                          and node.targets[0].id == 'legacy']
    assert len(legacy_assignments) == 1
    legacy_assignment = legacy_assignments[0]
    previous_legacy = ast.literal_eval(legacy_assignment.value)
    previous_legacy_sha = hashlib.sha256(previous_legacy.encode()).hexdigest()
    assert previous_legacy_sha == '91d5f6acdcbae6a32269cfa42653acf33aba1048b297a4314f68774f9e10519f'
    legacy_fixture = (HERE / 'LegacyWorkerCausalTests.swift').read_text()
    legacy_fixture_sha = hashlib.sha256(legacy_fixture.encode()).hexdigest()
    assert legacy_fixture_sha == 'ff5ad46f325167c2b4a8cb0260dcc05ac0ec91b93a0c658f1d15762dc5dac3e0'
    for check in (
        'precondition(state.result != nil)',
        'precondition(state.result == true && session.isActive && !session.synchronousOnMain && state.beats >= 3)',
        'precondition(state.result == true && !session.isActive && !session.synchronousOnMain)',
        'precondition(state.result == false && !session.isActive)',
    ):
        assert previous_legacy.count(check) == legacy_fixture.count(check) == 1
    lines = source.splitlines(keepends=True)
    source = ''.join(lines[:legacy_assignment.lineno - 1]) + 'legacy = ' + repr(legacy_fixture) + '\n' + ''.join(lines[legacy_assignment.end_lineno:])
    legacy_control = '''                if label == 'legacy-worker':
                    command = [str(exe), 'blocking-control']
                    blocked = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    print('CAUSAL LEGACY BLOCKING CONTROL:', json.dumps({
                        'optimized': optimize, 'returncode': blocked.returncode,
                        'stdout': blocked.stdout, 'stderr': blocked.stderr,
                        'execution_timeout_seconds': 30,
                    }, sort_keys=True), flush=True)
                    observations = [json.loads(line.removeprefix('LEGACY_HEARTBEAT_OBSERVATION '))
                        for line in blocked.stderr.splitlines() if line.startswith('LEGACY_HEARTBEAT_OBSERVATION ')]
                    rejected = (blocked.returncode != 0 and len(observations) == 1
                        and observations[0]['beats'] == 0
                        and observations[0]['synchronousCalls'] == 1
                        and observations[0]['synchronousOnMain'] is True
                        and observations[0]['releasedByHeartbeats'] is False
                        and 'LEGACY_HEARTBEAT_DID_NOT_PROGRESS' in blocked.stderr)
                    if not rejected:
                        raise subprocess.CalledProcessError(blocked.returncode or 1, command,
                            output=blocked.stdout, stderr=blocked.stderr)
                    print('PASS: causal legacy fixture rejects main-thread setActive', flush=True)
'''
    assert source.count(anchor + control) == 1
    source = source.replace(anchor + control, anchor + control + legacy_control, 1)
    # Every other historical fixture literal and controller source selection stays
    # byte-identical; the altered driver is saved beside the original by history.
    ast.parse(source)
    return source.encode(), {
        'name': 'causal-preparation-heartbeats-v1',
        'fixture_file': 'Tests/Background/PreparationWorkerCausalTests.swift',
        'previous_fixture_sha256': previous_sha,
        'fixture_sha256': hashlib.sha256(fixture.encode()).hexdigest(),
        'controller_and_platform_double': 'Exact historical inputs, unchanged.',
        'retained_original_controls': 'All historical fixtures other than the two explicitly declared revisions, and every compile/execution limit, are unchanged.',
        'change': 'Hold the mock preparation until three real main heartbeats occur, within the same two-second total deadline; additionally reject direct main-thread preparation.',
        'process_timeout_seconds': 30, 'fixture_deadline_seconds': 2,
        'claim_boundary': 'Declared new fixture, not an exact historical fixture pass or Apple playback evidence.',
        'additional_legacy_revision': {
            'name': 'causal-legacy-worker-heartbeats-v1',
            'fixture_file': 'Tests/Background/LegacyWorkerCausalTests.swift',
            'previous_fixture_sha256': previous_legacy_sha,
            'fixture_sha256': legacy_fixture_sha,
            'original_assertion_count_preserved': 4,
            'existing_preparation_revision_and_control_unchanged': True,
            'controller_and_platform_double': 'Exact historical inputs, unchanged; existing first onActivation hook only.',
            'change': 'Hold only first synchronous activation until three actual main timer callbacks before the same two-second total deadline; reject direct main-thread setActive in DEBUG and optimized.',
            'compile_timeout_seconds': 90, 'process_timeout_seconds': 30, 'fixture_deadline_seconds': 2,
            'claim_boundary': 'Separate declared fixture, not an exact old fixed120ms legacy pass; actual four values at the prior failure were not recorded, so its cause remains unresolved.',
        },
    }


if __name__ == '__main__':
    history('check_async_session.py', entry_revision=preparation_revision)
    subprocess.run([sys.executable, str(HERE / 'check_loop_audio.py'), '--group', 'adapter'], check=True)
