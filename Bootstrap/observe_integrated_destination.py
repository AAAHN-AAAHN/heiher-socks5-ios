#!/usr/bin/env python3
"""Passively record destination files around one unchanged Integrated UI phase.

This helper never invokes CoreSimulator or changes a destination. The original
runtime script, its inherited environment/stdio and all consumer deadlines remain
unchanged. Snapshot times are observation times, possibly after testing begins.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import resource
import signal
import stat
import subprocess
import sys
import threading
import time
import types


HOST_OBSERVER_SHA256 = "277f667fd17d96e9b3f6fbd733282d9b3622d782e20d2e2a4ab3a35d2b4575f8"
UUID = re.compile(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
MARKER = b"** TEST BUILD SUCCEEDED **"
FILE_LIMIT = 4 * 1024 * 1024
LOG_LIMIT = 8 * 1024 * 1024
BUILD_SCAN_LIMIT = 32 * 1024 * 1024
PREDICATE = (
    '(subsystem BEGINSWITH "com.apple.dt.CoreDevice" OR '
    'subsystem BEGINSWITH "com.apple.dt.IDE" OR process == "xcodebuild") AND '
    '(eventMessage CONTAINS[c] "destination" OR '
    'eventMessage CONTAINS[c] "simulator" OR '
    'eventMessage CONTAINS[c] "device" OR '
    'eventMessage CONTAINS[c] "runtime")'
)
COLLECTOR_ARGV = ["/usr/bin/log", "stream", "--style", "compact", "--level", "info",
                  "--predicate", PREDICATE]


def now():
    return datetime.now(timezone.utc).isoformat()


def error_record(error):
    return {"type": type(error).__name__, "message": str(error)[:2048]}


def read_regular(path, limit=FILE_LIMIT):
    """One bounded, non-following read; changing files remain explicitly partial."""
    started = now()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError("not a bounded regular file")
        raw = os.read(fd, limit + 1)
        after = os.fstat(fd)
        if len(raw) > limit:
            raise ValueError("file exceeds the read bound")
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                                 item.st_mtime_ns, item.st_ctime_ns)
        return raw, {
            "path": str(path), "read_started_utc": started, "read_finished_utc": now(),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "mode": stat.S_IMODE(after.st_mode), "mtime_ns": after.st_mtime_ns,
            "inode": after.st_ino, "device": after.st_dev,
            "stable_read": identity(before) == identity(after) and len(raw) == after.st_size,
        }
    finally:
        os.close(fd)


def write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def save_json(path, data):
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    if len(raw) > 1024 * 1024:
        raise ValueError("observation JSON exceeds 1 MiB")
    temporary = path.with_suffix(".pending.json")
    write_new(temporary, raw)
    os.replace(temporary, path)


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10)
    if result.returncode or result.stderr or len(result.stdout) > 65536:
        raise ValueError("bounded Git identity check failed: " + " ".join(args))
    return result.stdout.decode().strip()


def tracked_file(root, commit, relative, limit=1024 * 1024):
    path = root / relative
    if path.resolve(strict=True) != path:
        raise ValueError("tracked input contains a symbolic link")
    raw, record = read_regular(path, limit)
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if not record["stable_read"] or git(root, "ls-tree", commit, "--", relative) != (
        "100644 blob " + blob + "\t" + relative
    ):
        raise ValueError("tracked input bytes or mode differs: " + relative)
    return raw, record


def bind_context(args):
    env = os.environ
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "AAAHN-AAAHN/heiher-socks5-ios",
        "GITHUB_REF": "refs/heads/work/udp-echo-build-20261028", "GITHUB_JOB": "runtime",
        "RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64", "CANDIDATE": "integrated",
    }
    if not __debug__ or any(env.get(key) != value for key, value in expected.items()):
        raise ValueError("require the actual Integrated candidate runtime context")
    if sys.platform != "darwin" or platform.machine() != "arm64" or not 0 < os.getuid() == os.geteuid():
        raise ValueError("require the ordinary-user arm64 macOS runtime host")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not re.fullmatch(r"[1-9][0-9]*", env.get(key, "")):
            raise ValueError("missing actual positive run identity")
    source = Path(args.source_root)
    control = Path(args.control_root)
    output = Path(args.output)
    if not COMMIT.fullmatch(args.source_commit) or not COMMIT.fullmatch(env.get("GITHUB_SHA", "")):
        raise ValueError("require exact source/helper commits")
    for root in (source, control):
        if not root.is_absolute() or root.resolve(strict=True) != root:
            raise ValueError("roots must be existing canonical absolute directories")
    runner_temp = Path(env["RUNNER_TEMP"]).resolve(strict=True)
    if source != runner_temp / "udp-source" or control != Path(env["GITHUB_WORKSPACE"]).resolve(strict=True):
        raise ValueError("roots differ from the actual source/control checkouts")
    if Path.cwd() != source or output != runner_temp / "integrated-destination-observation" or output.exists():
        raise ValueError("require the unchanged source cwd and a fresh external observation directory")
    identities = {}
    for name, root, commit in (("source", source, args.source_commit), ("control", control, env["GITHUB_SHA"])):
        if git(root, "rev-parse", "HEAD") != commit:
            raise ValueError("actual checkout differs: " + name)
        git(root, "diff", "--quiet", "HEAD", "--")
        git(root, "diff", "--cached", "--quiet", "HEAD", "--")
        identities[name] = {"root": str(root), "commit": commit, "tree": git(root, "rev-parse", "HEAD^{tree}")}
    if any((source / "artifacts/integrated/ui" / name).exists()
           for name in ("created-device.txt", "environment.json", "ui-build.log")):
        raise ValueError("observation inputs already exist before this original invocation")
    records = {}
    host_raw = None
    for relative in ("Build/ui_review.py", "Build/observe_host_during_command.py"):
        raw, records[relative] = tracked_file(source, args.source_commit, relative)
        if relative == "Build/observe_host_during_command.py":
            host_raw = raw
    if records["Build/observe_host_during_command.py"]["sha256"] != HOST_OBSERVER_SHA256:
        raise ValueError("reviewed collector utilities changed")
    for relative in ("Bootstrap/run_candidate_runtime.sh", "Bootstrap/observe_integrated_destination.py"):
        _, records[relative] = tracked_file(control, env["GITHUB_SHA"], relative)
    if Path(__file__).resolve(strict=True) != control / "Bootstrap/observe_integrated_destination.py":
        raise ValueError("observer is not the actual tracked helper file")
    host = types.ModuleType("bound_host_observer_utilities")
    host.__file__ = str(source / "Build/observe_host_during_command.py")
    # Execute only the already verified module bytes; no source-side pycache.
    exec(compile(host_raw, host.__file__, "exec"), host.__dict__)
    identities["files"] = records
    identities["context"] = {key: env.get(key) for key in (*expected, "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "DEVELOPER_DIR")}
    return source, control, output, identities, host


class DestinationObserver:
    def __init__(self, source, output, devices):
        self.ui = source / "artifacts/integrated/ui"
        self.output = output
        self.devices = devices
        self.stop = threading.Event()
        self.identifier = None
        self.offset = 0
        self.tail = b""
        self.build_seen = False
        self.snapshots = []
        self.errors = []
        self.last_uuid_state = {"status": "not_observed"}
        self.thread = threading.Thread(target=self.run, name="destination-files", daemon=True)

    def capture_file(self, directory, label, path, limit=FILE_LIMIT):
        row = {"path": str(path)}
        try:
            raw, record = read_regular(path, limit)
        except Exception as error:
            missing = isinstance(error, FileNotFoundError)
            row.update(status="missing" if missing else "read_error", error=error_record(error), observed_utc=now())
            if not missing:
                self.errors.append({"where": str(path), "utc": now(), **error_record(error)})
            return row, None
        row.update(record)
        try:
            write_new(directory / label, raw)
            row["saved_as"] = label
            row["status"] = "captured" if record["stable_read"] else "changed_during_read"
        except Exception as error:
            row.update(status="recording_error", error=error_record(error))
            self.errors.append({"where": str(directory / label), "utc": now(), **error_record(error)})
        return row, raw

    def capture(self, event):
        directory = self.output / event
        directory.mkdir(mode=0o700)
        row = {"event": event, "observed_utc": now(), "observed_monotonic": time.monotonic(),
               "device_uuid": self.identifier, "timing_scope": "first observer detection; the original test may already have started", "files": {}}
        inputs = [("created-device.txt", self.ui / "created-device.txt", 128),
                  ("device.plist", self.devices / self.identifier / "device.plist", FILE_LIMIT),
                  ("device_set.plist", self.devices / "device_set.plist", FILE_LIMIT),
                  ("environment.json", self.ui / "environment.json", 1024 * 1024)]
        environment = None
        for label, path, limit in inputs:
            item, raw = self.capture_file(directory, label, path, limit)
            row["files"][label] = item
            if label == "device.plist" and raw is not None:
                try:
                    properties = plistlib.loads(raw)
                    row["device_properties"] = {key: properties.get(key) for key in ("UDID", "name", "state", "deviceType", "runtime")}
                    if properties.get("UDID", self.identifier) != self.identifier:
                        raise ValueError("device.plist UUID differs from the creation output")
                except Exception as error:
                    item.update(status="invalid_device_plist", error=error_record(error))
            if label == "environment.json" and raw is not None:
                try:
                    environment = json.loads(raw)
                    if environment["udid"] != self.identifier:
                        raise ValueError("environment UUID differs from the observed creation output")
                    runtime = environment["runtime"]
                    row["selected_runtime"] = {key: runtime.get(key) for key in ("identifier", "version", "buildversion", "bundlePath", "runtimeRoot", "isAvailable")}
                    bundle = Path(runtime["bundlePath"])
                    if not bundle.is_absolute() or bundle.suffix != ".simruntime" or ".." in bundle.parts:
                        raise ValueError("invalid original runtime bundle path")
                    if not str(bundle).startswith(("/Library/Developer/CoreSimulator/", "/private/var/run/com.apple.security.cryptexd/", "/Applications/Xcode")):
                        raise ValueError("unexpected original runtime bundle location")
                    info, _ = self.capture_file(directory, "runtime-Info.plist", bundle / "Contents/Info.plist", 1024 * 1024)
                    row["files"]["runtime-Info.plist"] = info
                except Exception as error:
                    item["status"] = "invalid_original_environment"
                    item["error"] = error_record(error)
        # Missing, changing and non-decodable input bytes are observations, not
        # a new requirement that Simulator files exist at either boundary.
        row["all_requested_files_captured_stably"] = all(item["status"] == "captured" for item in row["files"].values())
        row["finished_utc"] = now()
        save_json(directory / "snapshot.json", row)
        self.snapshots.append(row)

    def tick(self):
        if self.identifier is None:
            try:
                raw, record = read_regular(self.ui / "created-device.txt", 128)
                value = raw.decode("ascii").strip()
                self.last_uuid_state = {"status": "pending_complete_uuid", **record}
                if record["stable_read"] and UUID.fullmatch(value):
                    self.identifier = value
                    self.last_uuid_state["status"] = "observed"
                    self.capture("uuid-first-observed")
            except FileNotFoundError as error:
                self.last_uuid_state = {"status": "not_yet_present", "error": error_record(error)}
            except Exception as error:
                self.last_uuid_state = {"status": "read_error", "error": error_record(error)}
                if not any(row.get("where") == "creation_output" for row in self.errors):
                    self.errors.append({"where": "creation_output", "utc": now(), **error_record(error)})
        if self.identifier is None or self.build_seen:
            return
        path = self.ui / "ui-build.log"
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > BUILD_SCAN_LIMIT or info.st_size < self.offset:
                raise ValueError("build log is not a bounded append-only regular file")
            os.lseek(fd, self.offset, os.SEEK_SET)
            raw = os.read(fd, 256 * 1024)
            self.offset += len(raw)
        finally:
            os.close(fd)
        if MARKER in self.tail + raw:
            self.build_seen = True
            self.capture("build-success-observed")
        self.tail = raw[-len(MARKER):] if raw else self.tail

    def run(self):
        try:
            # Only this observer waits; the original command never waits for us.
            while not self.stop.is_set():
                self.tick()
                self.stop.wait(0.25)
            if not self.build_seen:
                self.tick()
        except Exception as error:
            self.errors.append({"utc": now(), **error_record(error)})

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            return {"complete": False, "error": "file observer did not finish within 2 seconds"}
        return {"complete": not self.errors,
                "boundaries_observed": {"creation_uuid": self.identifier is not None, "build_success_marker": self.build_seen},
                "last_uuid_state": self.last_uuid_state, "scanned_build_bytes": self.offset,
                "snapshots": self.snapshots, "errors": self.errors}


def run_once(source, control, output, identities, host):
    output.mkdir(mode=0o700)
    report = {"schema": 1, "scope": "passive_destination_observation_of_original_integrated_ui_phase",
              "started_utc": now(), "identity": identities, "recording_complete": False,
              "observer_errors": [], "collector": {"readiness_confirmed": False,
              "delivery_limit": "native log stream can redact, drop or buffer messages; process start is not a readiness handshake"},
              "original_command": {"invocation_attempts": 0, "started_count": 0}, "received_signals": []}
    collector = None
    observer = None
    streams = []
    old_handlers = {}
    cleaning_up = False
    def interrupted(signum, frame):
        if len(report["received_signals"]) < 32:
            report["received_signals"].append({"signal": signum, "utc": now()})
        report.setdefault("wrapper_interruption", {"signal": signum, "utc": now()})
        if not cleaning_up:
            raise host.WrapperInterrupted(signum)
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        old_handlers[signum] = signal.signal(signum, interrupted)
    try:
        save_json(output / "destination-observation-result.json", report)
        try:
            streams = [host.open_regular_new(output / name) for name in ("destination-stream.stdout.log", "destination-stream.stderr.log")]
            finite = [value for value in resource.getrlimit(resource.RLIMIT_FSIZE) if value != resource.RLIM_INFINITY]
            limit = min(LOG_LIMIT, *finite) if finite else LOG_LIMIT
            collector = subprocess.Popen(COLLECTOR_ARGV, stdin=subprocess.DEVNULL, stdout=streams[0], stderr=streams[1],
                                         start_new_session=True, preexec_fn=host.collector_limit(limit))
            report["collector"].update(argv=COLLECTOR_ARGV, pid=collector.pid, per_file_limit=limit, started_utc=now())
        except Exception as error:
            host.issue(report, "collector_start", error)
        try:
            observer = DestinationObserver(source, output, Path.home() / "Library/Developer/CoreSimulator/Devices")
            observer.thread.start()
        except Exception as error:
            host.issue(report, "file_observer_start", error)
        command = ["bash", str(control / "Bootstrap/run_candidate_runtime.sh"), "ui"]
        report["original_command"].update(argv=command, cwd=str(source), environment="inherited unchanged", stdio="inherited unchanged", invocation_attempts=1, started_utc=now())
        # No pipes, environment replacement, session change, retries or timeout.
        process = subprocess.Popen(command, cwd=source)
        report["original_command"]["started_count"] = 1
        report["original_command"]["pid"] = process.pid
        report["original_command"].update(host.returncode_record(process.wait()))
        report["original_command"]["finished_utc"] = now()
    except host.WrapperInterrupted as error:
        report["wrapper_interruption"] = {"signal": error.signum, "utc": now()}
    except Exception as error:
        host.issue(report, "wrapper", error)
    finally:
        cleaning_up = True
        if observer is not None:
            try:
                report["file_observation"] = observer.finish()
                if not report["file_observation"]["complete"]:
                    host.issue(report, "file_observation", RuntimeError("destination recording encountered read/recording errors; see individual records"))
            except BaseException as error:
                host.issue(report, "file_observer_cleanup", error)
        if collector is not None:
            try:
                host.stop_collector(collector, report)
            except BaseException as error:
                host.issue(report, "collector_cleanup", error)
        for stream in streams:
            try:
                stream.close()
            except BaseException as error:
                host.issue(report, "collector_stream_close", error)
        report["collector"]["files"] = {}
        for name in ("destination-stream.stdout.log", "destination-stream.stderr.log"):
            try:
                record = host.file_record(output / name)
                record["cap_reached"] = record["bytes"] >= report["collector"].get("per_file_limit", LOG_LIMIT)
                report["collector"]["files"][name] = record
                if record["cap_reached"]:
                    host.issue(report, "collector_file_limit", RuntimeError(name + " reached its cap"))
            except BaseException as error:
                report["collector"]["files"][name] = {"error": error_record(error)}
                host.issue(report, "collector_file_record", error)
        for signum, previous in old_handlers.items():
            try:
                signal.signal(signum, previous)
            except BaseException as error:
                host.issue(report, "signal_handler_restore", error)
    status, reason = host.chosen_exit(report)
    report.update(wrapper_exit_code=status, exit_reason=reason, finished_utc=now(), recording_complete=True,
                  observation_complete=not report["observer_errors"], original_child_signals_sent=[], original_invocations=report["original_command"]["started_count"])
    try:
        save_json(output / "destination-observation-result.json", report)
    except Exception as error:
        print("Destination observation receipt could not be saved: " + str(error), file=sys.stderr)
        return status if status != 0 else 1
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--control-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source, control, output, identity, host = bind_context(args)
    return run_once(source, control, output, identity, host)


if __name__ == "__main__":
    raise SystemExit(main())
