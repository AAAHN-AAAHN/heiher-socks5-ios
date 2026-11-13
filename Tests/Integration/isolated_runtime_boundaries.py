#!/usr/bin/env python3
"""Portable isolation/provenance fault injection, not Simulator product evidence."""
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Build'))
import runtime_environment as runtime


class IsolatedRuntimeBoundaries(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='isolated-runtime-')))
        self.source = {'commit': 'a' * 40, 'tree': 'b' * 40}
        self.request = {'mode': 'canonical', 'owner': 'integrated', 'isolated_consumer': 'integrated-ui'}
        self.caller = {'repository': 'fixture/project', 'job': 'review-macos'}
        self.env = {'REVIEW_CONSUMER': 'integrated-ui', 'GITHUB_SHA': self.source['commit'],
                    'GITHUB_WORKFLOW_SHA': self.source['commit'], 'GITHUB_REF': 'refs/heads/release/integrated',
                    'GITHUB_WORKFLOW_REF': 'fixture/project/.github/workflows/verify-build.yml@refs/heads/release/integrated',
                    'RUNNER_NAME': 'hosted-fixture-runner'}
        self.stack.enter_context(mock.patch.dict(os.environ, self.env, clear=True))
        self.workflow = (ROOT / '.github/workflows/verify-build.yml').read_bytes()
        self.tracked = self.stack.enter_context(mock.patch.object(runtime, 'tracked_regular_file',
            return_value=(self.workflow, {'sha256': 'c' * 64})))
        self.boot = self.stack.enter_context(mock.patch.object(runtime.subprocess, 'run',
            return_value=subprocess.CompletedProcess([], 0, b'11111111-2222-3333-4444-555555555555\n', b'')))
        self.stack.enter_context(mock.patch.object(runtime.os, 'uname', return_value=mock.Mock(nodename='fixture-host')))

    def binding(self):
        return runtime.isolated_review_binding(self.request, self.source, self.source, self.caller, self.root)

    def context(self, consumer='integrated-ui'):
        self.request['isolated_consumer'] = consumer
        os.environ['REVIEW_CONSUMER'] = consumer
        return {'mode': 'canonical', 'owner': 'integrated', 'source_root': str(self.root),
                'source': self.source, 'isolated_review': self.binding()}

    def test_binding_carries_host_workflow_and_single_consumer(self):
        value = self.binding()
        self.assertEqual(value['consumer'], 'integrated-ui')
        self.assertEqual(value['boot_session_uuid'], '11111111-2222-3333-4444-555555555555')
        self.assertEqual(value['runner_name'], self.env['RUNNER_NAME'])
        self.assertEqual(value['host_name'], 'fixture-host')
        self.assertEqual(value['workflow_sha'], self.source['commit'])
        self.tracked.assert_called_once_with(self.root, self.source['commit'], '.github/workflows/verify-build.yml')
        self.boot.assert_called_once_with(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'],
                                         capture_output=True, timeout=runtime.META)

    def test_ordinary_contract_does_not_implicitly_isolate(self):
        self.request.pop('isolated_consumer')
        with self.assertRaises(ValueError):
            self.binding()
        del os.environ['REVIEW_CONSUMER']
        self.assertIsNone(self.binding())
        self.boot.assert_not_called()
        self.assertEqual(runtime.consumer_order({'owner': 'integrated'}),
                         ['integrated-ui', 'integrated-simulator'])

    def test_reject_wrong_missing_mode_owner_and_consumer(self):
        for key, value in [('mode', 'candidate'), ('mode', 'workflow-input'), ('owner', 'server'),
                           ('isolated_consumer', None), ('isolated_consumer', 'icon-ui'),
                           ('isolated_consumer', 'integrated-simulator')]:
            with self.subTest(key=key, value=value):
                previous = self.request[key]
                self.request[key] = value
                with self.assertRaises(ValueError):
                    self.binding()
                self.request[key] = previous
        del os.environ['REVIEW_CONSUMER']
        with self.assertRaises(ValueError):
            self.binding()

    def test_reject_source_control_job_and_workflow_mismatch(self):
        with self.assertRaises(ValueError):
            runtime.isolated_review_binding(self.request, self.source,
                {'commit': 'd' * 40, 'tree': 'e' * 40}, self.caller, self.root)
        for key, value in [('GITHUB_SHA', 'd' * 40), ('GITHUB_WORKFLOW_SHA', 'd' * 40),
                           ('GITHUB_WORKFLOW_REF', 'fixture/project/.github/workflows/other.yml@refs/heads/release/integrated'),
                           ('GITHUB_REF', 'refs/heads/other'), ('GITHUB_REF', ''), ('RUNNER_NAME', '')]:
            with self.subTest(key=key):
                with mock.patch.dict(os.environ, {key: value}):
                    with self.assertRaises(ValueError):
                        self.binding()
        self.caller['job'] = 'runtime'
        with self.assertRaises(ValueError):
            self.binding()

    def test_reject_workflow_without_exact_reviewed_matrix(self):
        for old, new in [(b'fail-fast: false', b'fail-fast: true'),
                         (b'consumer: [integrated-ui, integrated-simulator]', b'consumer: [integrated-ui]'),
                         (b'REVIEW_CONSUMER: ${{ matrix.consumer }}', b'REVIEW_CONSUMER: integrated-ui'),
                         (b"if: matrix.consumer == 'integrated-simulator'", b'if: false')]:
            with self.subTest(old=old):
                self.tracked.return_value = (self.workflow.replace(old, new), {})
                with self.assertRaises(ValueError):
                    self.binding()

    def test_reject_unavailable_or_invalid_boot_identity(self):
        for code, stdout, stderr in [(1, b'', b'failed'), (0, b'', b''), (0, b'invalid', b''),
                                     (0, b'11111111-2222-3333-4444-555555555555', b'warning')]:
            self.boot.return_value = subprocess.CompletedProcess([], code, stdout, stderr)
            with self.assertRaises(ValueError):
                self.binding()

    def test_isolation_uses_only_own_initial_selection(self):
        for consumer in ('integrated-ui', 'integrated-simulator'):
            context = self.context(consumer)
            initial = {'selections': {consumer: {'runtime': {'identifier': 'fixture-runtime'}, 'device': 'fixture-device'}}}
            self.assertEqual(runtime.consumer_order(context), [consumer])
            self.assertEqual(runtime.preceding_consumer(context, consumer, {}, initial),
                             (initial['selections'][consumer], None))
            other = 'integrated-ui' if consumer.endswith('simulator') else 'integrated-simulator'
            with self.assertRaises(ValueError):
                runtime.consumer_profile(context, other)
        # Ordinary simulator remains fail-closed without its actual preceding UI receipt.
        context.pop('isolated_review')
        with self.assertRaises((ValueError, FileNotFoundError)):
            runtime.preceding_consumer(context, consumer, {}, initial)

    def test_reject_cross_host_cross_consumer_and_prior_attempt_preparation(self):
        context = self.context()
        for altered in ('host_name', 'boot_session_uuid', 'runner_name', 'consumer', 'workflow_sha'):
            foreign = copy.deepcopy(context)
            foreign['isolated_review'][altered] = 'foreign'
            receipt = {'schema': runtime.EXIT_SCHEMA, 'identity': foreign,
                       'actual_shell_status_argument': 0, 'product_pass': False, 'candidate_credit': False}
            with mock.patch.object(runtime, 'read_bound_json', return_value=(receipt, {})):
                with self.subTest(altered=altered), self.assertRaises(ValueError):
                    runtime.load_preparation(context)
        foreign = {**context, 'attempt': 'previous'}
        with mock.patch.object(runtime, 'read_bound_json', return_value=({'identity': foreign}, {})):
            with self.assertRaises(ValueError):
                runtime.load_preparation(context)

    def test_reject_reused_before_and_original_consumer_receipt(self):
        context = self.context()
        consumer = 'integrated-ui'
        initial = {'selections': {consumer: {'runtime': {}, 'device': {}}}}
        with mock.patch.object(runtime, 'load_preparation', return_value=(initial, {})):
            prep = runtime.preparation_root(context)
            prior = prep / 'consumers' / consumer
            prior.mkdir(parents=True)
            with self.assertRaises(ValueError):
                runtime.before_consumer(self.request, context, consumer)
            prior.rmdir()
            original = self.root / runtime.consumer_profile(context, consumer)['receipt']
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_text('{}')
            with self.assertRaises(ValueError):
                runtime.before_consumer(self.request, context, consumer)
            original.unlink()
            (prep / 'sequence-terminal.json').write_text('{}')
            with self.assertRaises(ValueError):
                runtime.before_consumer(self.request, context, consumer)

    def run_after(self, changed_context=False):
        context = self.context()
        consumer = 'integrated-ui'
        prep = runtime.preparation_root(context)
        out = prep / 'consumers' / consumer
        out.mkdir(parents=True)
        selection = {'runtime': {}, 'device': {}}
        before = {'schema': runtime.BEFORE_SCHEMA, 'identity': context, 'consumer': consumer,
                  'result': 'BOUND_BEFORE_ORIGINAL_CONSUMER', 'errors': [], 'preparation_binding': {},
                  'preceding_consumer_after_binding': None, 'selection_baseline': selection,
                  'selection': selection, 'raw_files': []}
        (out / 'before.json').write_text(json.dumps(before))
        original = self.root / runtime.consumer_profile(context, consumer)['receipt']
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_text('{}')
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(runtime, 'load_preparation', return_value=({'selections': {consumer: selection}}, {})))
            stack.enter_context(mock.patch.object(runtime, 'capture_for', return_value=None))
            stack.enter_context(mock.patch.object(runtime, 'readback_commands', return_value=[]))
            stack.enter_context(mock.patch.object(runtime, 'validate_original_receipt', return_value={}))
            stack.enter_context(mock.patch.object(runtime, 'observer_status', return_value=(0, {})))
            stack.enter_context(mock.patch.object(runtime, 'observe_selection', return_value={'selections': {consumer: selection}}))
            recheck = stack.enter_context(mock.patch.object(runtime, 'recheck_context'))
            if changed_context:
                recheck.side_effect = ValueError('Actual host/consumer changed')
            status = runtime.after_consumer(self.request, context, consumer, 0)
            report = json.loads((out / 'after.json').read_text())
            self.assertTrue(report['terminal'])
            self.assertTrue((prep / 'sequence-terminal.json').exists())
            self.assertFalse(report['product_pass'])
            self.assertFalse(report['candidate_credit'])
            with self.assertRaises(ValueError):
                runtime.after_consumer(self.request, context, consumer, 0)
            return status, report

    def test_successful_isolated_ui_is_terminal_and_not_product_credit(self):
        status, report = self.run_after()
        self.assertEqual(status, 0)
        self.assertEqual(report['result'], 'BOUND_AFTER_ORIGINAL_CONSUMER')

    def test_changed_actual_host_context_cannot_become_success(self):
        status, report = self.run_after(changed_context=True)
        self.assertNotEqual(status, 0)
        self.assertEqual(report['result'], 'AFTER_BINDING_FAILED')
        self.assertEqual(report['errors'][0]['where'], 'source_control_after')


class IsolatedWorkflowBoundaries(unittest.TestCase):
    def test_original_consumer_scripts_are_preserved(self):
        import hashlib
        import re
        previous = subprocess.check_output(['git', '-C', str(ROOT), 'show',
            'b94bab039714c6b4a2a4e39abe37689c735eff33:.github/workflows/verify-build.yml']).decode()
        current = (ROOT / '.github/workflows/verify-build.yml').read_text()
        old_status = subprocess.check_output(['git', '-C', str(ROOT), 'show',
            'b94bab039714c6b4a2a4e39abe37689c735eff33:Build/observed_command_status.py'])
        old_hash = hashlib.sha256(old_status).hexdigest()
        new_hash = hashlib.sha256((ROOT / 'Build/observed_command_status.py').read_bytes()).hexdigest()
        self.assertEqual(current.count(new_hash), 2)
        def body(text, title):
            section = text.split('      - name: ' + title + '\n', 1)[1].split('      - name: ', 1)[0]
            return section.split('        run: |\n', 1)[1]
        ui = 'Actual integrated UI, saved intent and native response'
        simulator = 'Original and remapped Simulator installs, saved tabs and real TCP'
        old_ui = body(previous, ui)
        start = old_ui.index('          # Capture real process status')
        end = old_ui.index('          runtime_common_invoke before --consumer integrated-ui')
        prepare = old_ui[start:end]
        extra = '          runtime_common_args+=(--isolated-consumer "$REVIEW_CONSUMER")\n'
        for title in (ui, simulator):
            actual = body(current, title)
            self.assertEqual(actual.count(extra), 1)
            actual = actual.replace(extra, '').replace(new_hash, old_hash)
            if title == simulator:
                self.assertEqual(actual.count(prepare), 1)
                actual = actual.replace(prepare, '')
            self.assertEqual(actual, body(previous, title))
        self.assertIn('      fail-fast: false\n', current)
        self.assertIn('consumer: [integrated-ui, integrated-simulator]', current)
        self.assertNotIn('continue-on-error', current)
        self.assertIn('name: Integrated-review-${{ matrix.consumer }}-macOS-', current)
        old_checkout = '          ref: ${{ inputs.ref || github.sha }}\n'
        new_checkout = '          ref: ${{ github.sha }}\n'
        previous_build = previous.split('  review-macos:', 1)[0]
        self.assertEqual(previous.count(old_checkout), 3)
        self.assertEqual(previous_build.count(old_checkout), 2)
        self.assertEqual(current.count(new_checkout), 3)
        self.assertNotIn('inputs.ref', current)
        self.assertIn('  workflow_dispatch:\npermissions:\n', current)
        self.assertEqual(current.split('  review-macos:', 1)[0],
                         previous_build.replace(old_checkout, new_checkout))


if __name__ == '__main__':
    unittest.main()
