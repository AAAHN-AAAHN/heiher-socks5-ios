#!/usr/bin/env python3
"""Synthetic unit fixtures only: never run the original UI, log stream or CI."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import signal
import sys
import tempfile
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("observer_under_test", HERE / "observe_integrated_destination.py")
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
host_path = Path(sys.argv.pop(1))
host_raw = host_path.read_bytes()
assert hashlib.sha256(host_raw).hexdigest() == observer.HOST_OBSERVER_SHA256
host = types.ModuleType("synthetic_test_bound_host_utilities")
host.__file__ = str(host_path)
exec(compile(host_raw, str(host_path), "exec"), host.__dict__)
IDENTIFIER = "12345678-1234-1234-1234-123456789ABC"


class BoundedFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_regular_bytes_and_stable_identity(self):
        path = self.root / "input"
        path.write_bytes(b"fixture")
        raw, record = observer.read_regular(path, 7)
        self.assertEqual(raw, b"fixture")
        self.assertTrue(record["stable_read"])
        self.assertEqual(record["sha256"], hashlib.sha256(raw).hexdigest())

    def test_oversized_symlink_and_fifo_rejected_without_blocking(self):
        path = self.root / "input"
        path.write_bytes(b"too large")
        link = self.root / "link"
        link.symlink_to(path)
        pipe = self.root / "pipe"
        os.mkfifo(pipe)
        for candidate in (path, link, pipe):
            with self.subTest(path=candidate), self.assertRaises((ValueError, OSError)):
                observer.read_regular(candidate, 2)

    def test_missing_and_permission_errors_are_explicit(self):
        target = observer.DestinationObserver(self.root, self.root, self.root)
        record, raw = target.capture_file(self.root, "copy", self.root / "missing")
        self.assertIsNone(raw)
        self.assertEqual(record["error"]["type"], "FileNotFoundError")
        with mock.patch.object(observer, "read_regular", side_effect=PermissionError("denied")):
            record, raw = target.capture_file(self.root, "copy", self.root / "missing")
        self.assertEqual(record["error"]["type"], "PermissionError")


class SnapshotBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.output = self.root / "output"
        self.devices = self.root / "devices"
        self.ui = self.source / "artifacts/integrated/ui"
        self.ui.mkdir(parents=True)
        self.output.mkdir()
        (self.devices / IDENTIFIER).mkdir(parents=True)
        (self.devices / IDENTIFIER / "device.plist").write_bytes(plistlib.dumps({"UDID": IDENTIFIER, "state": 3}))
        (self.devices / "device_set.plist").write_bytes(plistlib.dumps({"fixture": True}))
        self.target = observer.DestinationObserver(self.source, self.output, self.devices)

    def test_partial_uuid_does_not_create_snapshot(self):
        (self.ui / "created-device.txt").write_text("12345678-")
        self.target.tick()
        self.assertIsNone(self.target.identifier)
        self.assertEqual(self.target.snapshots, [])

    def test_uuid_then_split_build_marker_records_two_actual_detection_times(self):
        (self.ui / "created-device.txt").write_text(IDENTIFIER + "\n")
        self.target.tick()
        self.assertEqual(len(self.target.snapshots), 1)
        self.assertEqual(self.target.snapshots[0]["files"]["environment.json"]["status"], "missing")
        self.assertFalse(self.target.snapshots[0]["all_requested_files_captured_stably"])
        self.assertEqual(self.target.errors, [])
        environment = {"udid": IDENTIFIER, "runtime": {"identifier": "fixture-runtime", "bundlePath": "/Library/Developer/CoreSimulator/Volumes/fixture/Test.simruntime"}}
        (self.ui / "environment.json").write_text(json.dumps(environment))
        log = self.ui / "ui-build.log"
        log.write_bytes(b"prefix\n** TEST BUILD SUC")
        self.target.tick()
        self.assertEqual(len(self.target.snapshots), 1)
        with log.open("ab") as stream:
            stream.write(b"CEEDED **\n")
        original_read = observer.read_regular
        def synthetic_runtime(path, limit=observer.FILE_LIMIT):
            if str(path).startswith("/Library/Developer/CoreSimulator/"):
                raw = plistlib.dumps({"CFBundleIdentifier": "synthetic.fixture"})
                return raw, {"stable_read": True, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            return original_read(path, limit)
        with mock.patch.object(observer, "read_regular", side_effect=synthetic_runtime):
            self.target.tick()
            self.target.tick()
        self.assertEqual(len(self.target.snapshots), 2)
        self.assertTrue(self.target.snapshots[1]["all_requested_files_captured_stably"])
        self.assertEqual(self.target.snapshots[1]["selected_runtime"]["identifier"], "fixture-runtime")
        self.assertLessEqual(self.target.snapshots[0]["observed_monotonic"], self.target.snapshots[1]["observed_monotonic"])

    def test_wrong_environment_uuid_is_incomplete(self):
        self.target.identifier = IDENTIFIER
        (self.ui / "created-device.txt").write_text(IDENTIFIER)
        (self.ui / "environment.json").write_text(json.dumps({"udid": "OTHER"}))
        self.target.capture("build-success-observed")
        self.assertFalse(self.target.snapshots[0]["all_requested_files_captured_stably"])
        self.assertEqual(self.target.snapshots[0]["files"]["environment.json"]["status"], "invalid_original_environment")

    def test_missing_and_changing_plists_are_recorded_without_new_acceptance_gate(self):
        (self.ui / "created-device.txt").write_text(IDENTIFIER)
        (self.devices / IDENTIFIER / "device.plist").unlink()
        original_read = observer.read_regular
        def changing_set(path, limit=observer.FILE_LIMIT):
            raw, record = original_read(path, limit)
            if path.name == "device_set.plist":
                record["stable_read"] = False
            return raw, record
        with mock.patch.object(observer, "read_regular", side_effect=changing_set):
            self.target.tick()
        row = self.target.snapshots[0]
        self.assertEqual(row["files"]["device.plist"]["status"], "missing")
        self.assertEqual(row["files"]["device_set.plist"]["status"], "changed_during_read")
        self.target.thread.start()
        receipt = self.target.finish()
        self.assertTrue(receipt["complete"])
        self.assertFalse(receipt["boundaries_observed"]["build_success_marker"])

    def test_build_log_size_limit_is_enforced(self):
        self.target.identifier = IDENTIFIER
        with (self.ui / "ui-build.log").open("wb") as stream:
            stream.truncate(observer.BUILD_SCAN_LIMIT + 1)
        with self.assertRaises(ValueError):
            self.target.tick()


class OriginalCommandPreservation(unittest.TestCase):
    def exercise(self, original_status, observations_complete=True, original_start_error=False, cleanup_error=False, cleanup_signal=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            control = root / "control"
            output = root / "output"
            source.mkdir()
            control.mkdir()
            collector = mock.Mock(pid=12345)
            original = mock.Mock(pid=12346)
            original.wait.return_value = original_status
            file_observer = mock.Mock()
            file_observer.finish.return_value = {"complete": observations_complete}
            second = OSError("synthetic original launch failure") if original_start_error else original
            def fake_cleanup(*args):
                if cleanup_error:
                    raise OSError("synthetic cleanup failure")
                if cleanup_signal:
                    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            with mock.patch.object(observer.subprocess, "Popen", side_effect=[collector, second]) as popen, \
                 mock.patch.object(observer, "DestinationObserver", return_value=file_observer), \
                 mock.patch.object(host, "stop_collector", side_effect=fake_cleanup) as cleanup:
                status = observer.run_once(source, control, output, {"synthetic_unit_fixture": True}, host)
            cleanup.assert_called_once()
            self.assertIs(cleanup.call_args.args[0], collector)
            self.assertEqual(popen.call_count, 2)
            argv, = popen.call_args_list[1].args
            self.assertEqual(argv, ["bash", str(control / "Bootstrap/run_candidate_runtime.sh"), "ui"])
            self.assertEqual(popen.call_args_list[1].kwargs, {"cwd": source})
            if not original_start_error:
                original.wait.assert_called_once_with()
            report = json.loads((output / "destination-observation-result.json").read_text())
            self.assertEqual(report["original_child_signals_sent"], [])
            self.assertEqual(report["original_command"]["invocation_attempts"], 1)
            self.assertEqual(report["original_invocations"], int(not original_start_error))
            return status, report

    def test_original_nonzero_precedes_observation_failure(self):
        status, report = self.exercise(19, False)
        self.assertEqual(status, 19)
        self.assertEqual(report["exit_reason"], "original_command_nonzero")
        status, report = self.exercise(19, cleanup_error=True)
        self.assertEqual(status, 19)
        self.assertTrue(any(row["where"] == "collector_cleanup" for row in report["observer_errors"]))

    def test_original_zero_requires_complete_observation(self):
        self.assertEqual(self.exercise(0, True)[0], 0)
        status, report = self.exercise(0, False)
        self.assertEqual(status, 1)
        self.assertFalse(report["observation_complete"])

    def test_signal_status_and_failed_launch_are_not_success(self):
        self.assertEqual(self.exercise(-signal.SIGTERM)[0], 143)
        self.assertEqual(self.exercise(None, original_start_error=True)[0], 1)
        status, report = self.exercise(0, cleanup_signal=True)
        self.assertEqual(status, 143)
        self.assertEqual(report["exit_reason"], "wrapper_interrupted")

    def test_cleanup_rejects_a_group_not_owned_by_collector(self):
        process = mock.Mock(pid=12345)
        row = {"cleanup_signals": []}
        with mock.patch.object(host.os, "getpgid", return_value=67890), \
             mock.patch.object(host.os, "getsid", return_value=67890), \
             mock.patch.object(host.os, "killpg") as kill:
            with self.assertRaises(RuntimeError):
                host.signal_owned_group(process, signal.SIGTERM, row)
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
