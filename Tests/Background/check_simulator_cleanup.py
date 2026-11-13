#!/usr/bin/env python3
"""Cleanup-only controls, not SDK compilation or XCTest success evidence."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('background_ui', Path(__file__).with_name('check_async_ui.py'))
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)
DEVICE = 'CA1BE3B0-87C0-4488-9934-99650C762A2F'
KNOWN = ('An error was encountered processing the command '
         '(domain=com.apple.CoreSimulator.SimError, code=405):\n'
         'Unable to shutdown device in current state: Shutdown\n')

class Cleanup(unittest.TestCase):
    def exercise(self, case):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            calls = []
            def run(command, log, timeout=180):
                calls.append((command, timeout))
                (out / log).write_text('')
                if command[2] == 'shutdown' and not case.startswith('normal'):
                    text = KNOWN.replace('Shutdown\n', 'Booted\n') if case == 'wrong-message' else KNOWN
                    if case == 'wrong-domain': text = text.replace('com.apple.CoreSimulator.SimError', 'unrelated.service')
                    (out / log).write_text(text)
                    if case == 'shutdown-timeout': raise subprocess.TimeoutExpired(command, timeout)
                    if case == 'shutdown-oserror': raise OSError('service unavailable')
                    raise subprocess.CalledProcessError(23 if case == 'other-code' else 149,
                                                        command[:-1] + ['wrong'] if case == 'wrong-command' else command)
                if command[2] == 'list':
                    if case == 'query-timeout': raise subprocess.TimeoutExpired(command, timeout)
                    if case == 'query-failed': raise subprocess.CalledProcessError(1, command)
                    device = {'udid': DEVICE.lower(), 'state': 'Booted' if case == 'booted' else 'Shutdown'}
                    if case == 'wrong-uuid': device['udid'] = '00000000-0000-0000-0000-000000000000'
                    devices = [device, dict(device)] if case == 'duplicate-uuid' else [] if case == 'missing-uuid' else [device]
                    payload = json.dumps({'devices': {'runtime': devices}})
                    if case == 'malformed': payload = '{broken'
                    if case == 'duplicate-key': payload = '{"devices":{},"devices":{"runtime":'+json.dumps(devices)+'}}'
                    if case == 'nonfinite': payload = '{"devices":{"runtime":'+json.dumps(devices)+'},"invalid":NaN}'
                    if case == 'oversized': payload = ' ' * (1024 * 1024 + 1)
                    (out / log).write_text(payload)
                if command[2] == 'delete':
                    if case in ('delete-failed','normal-delete-failed'): raise subprocess.CalledProcessError(1, command)
                    if case in ('delete-timeout','normal-delete-timeout'): raise subprocess.TimeoutExpired(command, timeout)
            with patch.object(ui, 'OUT', out), patch.object(ui, 'run', side_effect=run):
                errors = ui.cleanup_simulator(DEVICE)
                self.assertEqual(bool(errors), case not in ('normal', 'already-shutdown'))
                observation = json.loads((out / 'cleanup-observation.json').read_text())
                if case == 'already-shutdown':
                    self.assertEqual(observation['shutdown'], 'accepted-idempotent-already-shutdown')
                    self.assertIn('149', observation['shutdown_error'])
                self.assertEqual(calls[0], (['xcrun','simctl','shutdown',DEVICE], 120))
                self.assertEqual(calls[-1], (['xcrun','simctl','delete',DEVICE], 120))
                for command, timeout in calls[1:-1]:
                    self.assertEqual(command, ['xcrun','simctl','list','devices','-j'])
                    self.assertEqual(timeout, 5)
                if case in ('normal','normal-delete-failed','normal-delete-timeout','wrong-message','wrong-domain','other-code','wrong-command','shutdown-timeout','shutdown-oserror'):
                    self.assertEqual(len(calls), 2)
                original = subprocess.CalledProcessError(65, ['xcodebuild','test'])
                with self.assertRaises(subprocess.CalledProcessError) as result:
                    ui.finish_audit(original, list(errors))
                self.assertIs(result.exception, original)
                if errors:
                    with self.assertRaises(RuntimeError): ui.finish_audit(None, errors)
                else: ui.finish_audit(None, errors)
                self.assertFalse((out / 'SUCCESS.txt').exists())
    def test_cleanup_outcomes_and_original_failure_priority(self):
        cases = ['normal','already-shutdown','wrong-message','wrong-domain','other-code','wrong-command',
                 'shutdown-timeout','shutdown-oserror','query-timeout','query-failed','malformed',
                 'duplicate-key','duplicate-uuid','wrong-uuid','missing-uuid','booted','oversized',
                 'delete-failed','delete-timeout','normal-delete-failed','normal-delete-timeout','nonfinite']
        for case in cases:
            with self.subTest(case=case): self.exercise(case)
    def test_evidence_failure_never_masks_original_failure(self):
        original = RuntimeError('original assertion')
        with patch.object(Path, 'write_text', side_effect=OSError('disk unavailable')):
            with self.assertRaises(RuntimeError) as result: ui.finish_audit(original, [])
            self.assertIs(result.exception, original)
            with self.assertRaises(RuntimeError): ui.finish_audit(None, [])
    def test_assertion_and_timeout_priority(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(ui, 'OUT', Path(temporary)):
            for original in (AssertionError('app'), subprocess.TimeoutExpired(['xcodebuild','test'], 900)):
                for cleanup in ([], ['cleanup failure']):
                    with self.subTest(kind=type(original).__name__, cleanup=cleanup):
                        with self.assertRaises(type(original)) as result: ui.finish_audit(original, list(cleanup))
                        self.assertIs(result.exception, original)
    def test_observation_write_failure_is_cleanup_failure(self):
        with patch.object(ui, 'run'), patch.object(Path, 'write_text', side_effect=OSError('disk unavailable')):
            self.assertTrue(ui.cleanup_simulator(DEVICE))

if __name__ == '__main__':
    if not __debug__: raise SystemExit('Assertions must be enabled')
    unittest.main(verbosity=2)
