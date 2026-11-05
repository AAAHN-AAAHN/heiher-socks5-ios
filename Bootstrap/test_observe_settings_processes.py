"""Local observer contract fixtures; no CI or Simulator result is simulated."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('settings_process_observer', Path(__file__).with_name('observe_settings_processes.py'))
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class ObserverContracts(unittest.TestCase):
    def test_ps_parse_preserves_full_path_with_spaces(self):
        rows = observer.parse_ps('501 501 1234 987 S 0.1 12345 01:02 Thu Nov  5 07:20:01 2026 /Applications/An Example.app/tool\n')
        self.assertEqual(rows[0]['comm'], '/Applications/An Example.app/tool')
        self.assertEqual(rows[0]['start_display_utc'], 'Thu Nov 5 07:20:01 2026')
        self.assertEqual(rows[0]['rss_kib'], 12345)

    def test_ps_invalid_and_duplicate_rows_rejected(self):
        for text in ('123 invalid\n', '501 501 1 0 S 0.0 1 0 Thu Nov 5 00:00:00 2026 /a\n' * 2):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                observer.parse_ps(text)

    def test_descendants_not_unrelated_same_executable(self):
        rows = [{'pid': 1, 'ppid': 0}, {'pid': 2, 'ppid': 1}, {'pid': 3, 'ppid': 2},
                {'pid': 4, 'ppid': 1}, {'pid': 5, 'ppid': 4}]
        self.assertEqual(observer.descendant_ids(rows, 2), {2, 3})

    def test_native_ancestry_rejects_reused_original_pid(self):
        base = {'pid': 100, 'ppid': 90, 'uid': 501, 'ruid': 501, 'svuid': 501,
                'start_seconds': 1000, 'start_microseconds': 1, 'executable': '/usr/bin/python3'}
        child = dict(base, pid=101, ppid=100, executable='/usr/bin/simctl')
        replacements = {101: child, 100: dict(base, start_microseconds=2)}
        with patch.object(observer, 'owned', return_value=True), patch.object(observer, 'native_identity', side_effect=replacements.__getitem__):
            with self.assertRaisesRegex(RuntimeError, 'birth identity changed'):
                observer.verify_descendant(child, base)

    def test_native_ancestry_allows_only_known_python_launcher_transition(self):
        base = {'pid': 100, 'ppid': 90, 'uid': 501, 'ruid': 501, 'svuid': 501,
                'start_seconds': 1000, 'start_microseconds': 1, 'executable': observer.PYTHON_LAUNCHER}
        child = dict(base, pid=101, ppid=100, executable=observer.CORE_SIMCTL)
        for path, accepted in [(observer.PYTHON_APPLICATION, True), ('/unrelated/Python', False)]:
            identities = {101: child, 100: dict(base, executable=path)}
            with self.subTest(path=path), patch.object(observer, 'owned', return_value=True), \
                    patch.object(observer, 'native_identity', side_effect=identities.__getitem__):
                if accepted:
                    observer.verify_descendant(child, base)
                else:
                    with self.assertRaisesRegex(RuntimeError, 'executable changed'):
                        observer.verify_descendant(child, base)

    def snapshot_fixture(self, directory):
        identity = {'pid': 101, 'ppid': 100, 'uid': 501, 'ruid': 501, 'svuid': 501,
                    'start_seconds': 1000, 'start_microseconds': 1, 'executable': observer.CORE_SIMCTL}
        report = {'simctl_executable': '/Applications/Xcode_27.app/Contents/Developer/usr/bin/simctl',
                  'samples': [], 'inner': {'native_identity': dict(identity, pid=100, ppid=90)},
                  'binding': {'source_root': directory, 'original_service_identity': dict(identity, pid=200, executable=observer.SERVICE)},
                  'last_original_udid': '03ABB540-4FBE-427B-B47E-D2F8D4D96B44'}
        return identity, report

    def test_actual_core_simctl_path_reaches_native_and_argument_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            identity, report = self.snapshot_fixture(directory)
            ps = '501 501 101 100 S 0.1 4096 00:05 Thu Nov 5 07:46:42 2026 ' + observer.CORE_SIMCTL + '\n'
            args = observer.CORE_SIMCTL + ' bootstatus ' + report['last_original_udid'] + ' -b\n'
            with patch.object(observer.os, 'getuid', return_value=501), \
                    patch.object(observer, 'read_command', side_effect=[({'returncode': 0}, ps), ({'returncode': 0}, args)]), \
                    patch.object(observer, 'native_identity', return_value=identity), \
                    patch.object(observer, 'verify_descendant') as ancestry, \
                    patch.object(observer, 'current_device', return_value={'udid': report['last_original_udid']}):
                row = observer.snapshot(100, Path(directory), report, 1, {}, set())
            ancestry.assert_called_once_with(identity, report['inner']['native_identity'])
            self.assertEqual(row['processes'][0]['native_identity'], identity)
            self.assertEqual(report['bound_bootstatus']['identity'], identity)
            self.assertEqual(report['bound_bootstatus']['verified_args'], args.strip())
            self.assertEqual(row['observer_errors'], [])

    def test_same_basename_outside_exact_simctl_paths_is_not_queried(self):
        with tempfile.TemporaryDirectory() as directory:
            _, report = self.snapshot_fixture(directory)
            ps = '501 501 101 100 S 0.1 4096 00:05 Thu Nov 5 07:46:42 2026 /unrelated/simctl\n'
            with patch.object(observer.os, 'getuid', return_value=501), \
                    patch.object(observer, 'read_command', return_value=({'returncode': 0}, ps)) as query, \
                    patch.object(observer, 'native_identity') as native, \
                    patch.object(observer, 'current_device', return_value={}):
                observer.snapshot(100, Path(directory), report, 1, {}, set())
            self.assertEqual(query.call_count, 1)
            native.assert_not_called()
            self.assertNotIn('bound_bootstatus', report)

    def test_failed_ps_retains_actual_query_and_can_sample_bound_live_child(self):
        with tempfile.TemporaryDirectory() as directory:
            identity, report = self.snapshot_fixture(directory)
            report['bound_bootstatus'] = {'identity': identity, 'verified_args': observer.CORE_SIMCTL + ' bootstatus ' + report['last_original_udid'] + ' -b',
                                         'udid': report['last_original_udid'], 'first_seen_monotonic': 0.0,
                                         'last_verified_utc': 'LOCAL_UNIT_FIXTURE'}
            failed = {'argv': ['/bin/ps'], 'error': {'type': 'TimeoutExpired', 'message': 'LOCAL_UNIT_FIXTURE'},
                      'started_utc': 'fixture-start', 'finished_utc': 'fixture-end'}
            with patch.object(observer, 'read_command', return_value=(failed, '')), \
                    patch.object(observer, 'native_identity', return_value=identity), \
                    patch.object(observer, 'verify_descendant') as ancestry, \
                    patch.object(observer, 'sample_once') as sample, \
                    patch.object(observer.time, 'monotonic', return_value=61.0), \
                    patch.object(observer, 'current_device', return_value={}):
                row = observer.snapshot(100, Path(directory), report, 1, {}, set())
            self.assertEqual(row['ps_query'], failed)
            self.assertEqual(row['observer_errors'][0]['query'], failed)
            self.assertEqual(row['processes'], [])
            ancestry.assert_called_once_with(identity, report['inner']['native_identity'])
            self.assertEqual([call.args[2] for call in sample.call_args_list], ['late-bootstatus', 'late-coresimulator'])

    def test_bound_child_pid_reuse_blocks_late_sampling_after_ps_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            identity, report = self.snapshot_fixture(directory)
            report['bound_bootstatus'] = {'identity': identity, 'first_seen_monotonic': 0.0,
                                         'last_verified_utc': 'LOCAL_UNIT_FIXTURE'}
            with patch.object(observer, 'read_command', return_value=({'returncode': 1}, '')), \
                    patch.object(observer, 'native_identity', return_value=dict(identity, start_microseconds=2)), \
                    patch.object(observer, 'sample_once') as sample, \
                    patch.object(observer.time, 'monotonic', return_value=61.0), \
                    patch.object(observer, 'current_device', return_value={}):
                row = observer.snapshot(100, Path(directory), report, 1, {}, set())
            sample.assert_not_called()
            self.assertIn('late_bootstatus_unavailable', row)
            self.assertEqual(len(row['observer_errors']), 1)

    def test_sample_denied_identity_has_no_command_fallback(self):
        identity = {'pid': 100, 'ppid': 90, 'uid': 501, 'ruid': 501, 'svuid': 501,
                    'start_seconds': 1000, 'start_microseconds': 1, 'executable': observer.SERVICE}
        report = {'samples': [], 'simctl_executable': '/fixture/simctl'}
        with tempfile.TemporaryDirectory() as directory, patch.object(observer, 'owned', return_value=True), \
                patch.object(observer, 'native_identity', return_value=dict(identity, start_microseconds=2)), \
                patch.object(observer, 'read_command') as query:
            observer.sample_once(identity, Path(directory), 'fixture', report)
        query.assert_not_called()
        self.assertEqual(report['samples'][0]['invocations'], 0)
        self.assertFalse(report['samples'][0]['usable'])

    def test_changed_runtime_json_is_unavailable_not_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'artifacts/settings-persistence-ui-audit/runtime.json'
            path.parent.mkdir(parents=True)
            path.write_text('{"udid":')
            original = path.read_bytes()
            result = observer.current_device(root, root, 0, set())
            self.assertIn('runtime_json_unavailable', result)
            self.assertEqual(path.read_bytes(), original)

    def test_symlink_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'original'
            original.write_text('evidence')
            link = Path(directory) / 'link'
            link.symlink_to(original)
            with self.assertRaisesRegex(RuntimeError, 'Linked read path'):
                observer.safe_bytes(link)

    def run_fixture(self, exit_code, snapshot_error=False, recording_error=False, periodic_gap=False):
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory), Path(directory) / 'observations'
            child_file = root / 'child.json'
            code = ('import json,os,sys,time; from pathlib import Path; '
                    'time.sleep(0.04); '
                    'Path(sys.argv[1]).write_text(json.dumps({"cwd":os.getcwd(),"sentinel":os.environ.get("SETTINGS_OBSERVATION_UNIT_SENTINEL")})); ')
            code += ('os.kill(os.getpid(),15)' if exit_code < 0 else f'sys.exit({exit_code})')
            command = [sys.executable, '-c', code, str(child_file)]
            binding = {'scope': 'LOCAL_UNIT_FIXTURE_NO_CI_CREDIT', 'expected_inner_argv': command, 'source_root': str(root)}
            fake_identity = {'pid': 123, 'ppid': os.getpid()}
            original_save = observer.save
            def save(out, value):
                if recording_error and value['inner']['launches']:
                    raise OSError('fixture recording failure')
                return original_save(out, value)
            def snapshot(*args):
                if snapshot_error:
                    raise RuntimeError('fixture observation failure')
                return {'scope': 'LOCAL_UNIT_FIXTURE_NO_CI_CREDIT',
                        'observer_errors': [{'tick': 0, 'message': 'fixture first periodic query failed'}]
                        if periodic_gap and args[3] == 0 else []}
            with patch.object(observer, 'inputs', return_value=binding), \
                    patch.object(observer, 'native_identity', return_value=fake_identity), \
                    patch.object(observer, 'owned', return_value=True), \
                    patch.object(observer, 'snapshot', side_effect=snapshot), \
                    patch.object(observer, 'save', side_effect=save), \
                    patch.object(observer, 'INTERVAL', 0.01), \
                    patch.dict(os.environ, {'DEVELOPER_DIR': '/fixture/Xcode', 'SETTINGS_OBSERVATION_UNIT_SENTINEL': 'inherited'}):
                actual = observer.run(output, command)
                self.assertEqual(actual, observer.shell_status(exit_code))
                self.assertEqual(json.loads(child_file.read_text()), {'cwd': os.getcwd(), 'sentinel': 'inherited'})
                if recording_error:
                    with self.assertRaises(RuntimeError):
                        observer.verify(output, actual)
                    return
                report = json.loads((output / 'result.json').read_text())
                self.assertEqual(report['inner']['raw_returncode'], exit_code)
                self.assertEqual(report['inner']['launch_attempts'], 1)
                self.assertEqual(report['inner']['launches'], 1)
                if periodic_gap:
                    self.assertGreater(report['ticks'], 1)
                    self.assertEqual(len(report['observer_errors']), 1)
                if snapshot_error or periodic_gap:
                    with self.assertRaisesRegex(RuntimeError, 'observation failed'):
                        observer.verify(output, actual)
                else:
                    self.assertEqual(observer.verify(output, actual), 0)

    def test_original_success_environment_and_cwd(self):
        self.run_fixture(0)

    def test_original_nonzero_preserved(self):
        self.run_fixture(7)

    def test_original_signal_exit_preserved(self):
        self.run_fixture(-signal.SIGTERM)

    def test_original_failure_precedes_observation_failure(self):
        self.run_fixture(7, snapshot_error=True)

    def test_observation_failure_has_separate_mandatory_rejection(self):
        self.run_fixture(0, snapshot_error=True)

    def test_recording_failure_waits_for_original_and_preserves_failure(self):
        self.run_fixture(7, recording_error=True)

    def test_periodic_gap_does_not_stop_later_observations_or_mask_original_failure(self):
        self.run_fixture(7, periodic_gap=True)

    def test_periodic_gap_still_fails_health_after_original_success(self):
        self.run_fixture(0, periodic_gap=True)

    def test_original_launch_has_no_added_behavior(self):
        tree = ast.parse(Path(observer.__file__).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == 'subprocess' and n.func.attr == 'Popen']
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.unparse(calls[0]), 'subprocess.Popen(command)')
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and isinstance(n.func.value, ast.Name) and n.func.value.id == 'os'
                             and n.func.attr in ('kill', 'killpg') for n in ast.walk(tree)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
