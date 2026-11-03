#!/usr/bin/env python3
"""Observe a single original command without changing its argv, stdio or deadline.

Only the directly owned log-stream process group receives cleanup signals. The
original command runs once in the inherited environment/directory/process group,
with no added timeout. A nonzero original return code always takes precedence.
This module observes host logs; it neither prepares nor modifies a simulator.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time


FILE_LIMIT_BYTES = 32 * 1024 * 1024
COLLECTOR_TERM_SECONDS = 2
COLLECTOR_KILL_SECONDS = 1
PREDICATE = (
    'process == "com.apple.CoreSimulator.CoreSimulatorService" OR '
    'process == "CoreSimulatorService" OR '
    'process BEGINSWITH "SimLaunchHost" OR '
    'process == "launchd_sim" OR process == "simdiskimaged" OR '
    'subsystem BEGINSWITH "com.apple.CoreSimulator"'
)
COLLECTOR_ARGV = [
    "/usr/bin/log", "stream", "--style", "compact", "--level", "info",
    "--predicate", PREDICATE,
]
CONTEXT_KEYS = (
    "GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
    "GITHUB_JOB", "GITHUB_REF", "RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH",
    "DEVELOPER_DIR",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def exception_record(error):
    return {"type": type(error).__name__, "message": str(error)}


def issue(report, where, error):
    report["observer_errors"].append({
        "where": where, "utc": utc_now(), **exception_record(error),
    })


def stderr_best_effort(message):
    try:
        print(message, file=sys.stderr, flush=True)
    except BaseException:
        pass


def open_regular_new(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        entry = os.fstat(fd)
        if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
            raise RuntimeError(f"not a newly owned regular file: {path}")
        return os.fdopen(fd, "wb", buffering=0)
    except BaseException:
        os.close(fd)
        raise


def atomic_save(report, output):
    temporary = output / "host-observation-result.pending.json"
    destination = output / "host-observation-result.json"
    with open_regular_new(temporary) as stream:
        raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
        remaining = memoryview(raw)
        while remaining:
            written = stream.write(remaining)
            if not written:
                raise OSError("result file write made no progress")
            remaining = remaining[written:]
    os.replace(temporary, destination)


def save_best_effort(report, output, where):
    try:
        atomic_save(report, output)
        return True
    except Exception as error:
        issue(report, where, error)
        report["result"] = "OBSERVATION_RECORDING_FAILED"
        report["recording_complete"] = False
        stderr_best_effort(f"Host observer {where}: {type(error).__name__}: {error}")
        return False


def file_record(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise RuntimeError(f"not an owned regular file: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = os.fstat(fd)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode,
                                 item.st_uid, item.st_gid, item.st_size,
                                 item.st_mtime_ns, item.st_ctime_ns)
        if identity(before) != identity(after):
            raise RuntimeError(f"file changed while recording: {path}")
        return {
            "path": str(path), "bytes": after.st_size, "sha256": digest,
            "device": after.st_dev, "inode": after.st_ino,
            "mode": stat.S_IMODE(after.st_mode), "uid": after.st_uid,
            "gid": after.st_gid, "mtime_ns": after.st_mtime_ns,
        }
    finally:
        os.close(fd)


def effective_file_limit():
    inherited = resource.getrlimit(resource.RLIMIT_FSIZE)
    finite = [value for value in inherited if value != resource.RLIM_INFINITY]
    return min([FILE_LIMIT_BYTES, *finite]), list(inherited)


def collector_limit(effective):
    # Popen invokes this only in its new, directly owned collector child. The
    # wrapper is single-threaded; the original command never receives this limit.
    def apply():
        resource.setrlimit(resource.RLIMIT_FSIZE, (effective, effective))
    return apply


def shell_status(returncode):
    if returncode >= 0:
        return returncode
    return 128 + (-returncode)


def returncode_record(returncode):
    record = {"raw_popen_returncode": returncode}
    if returncode is not None:
        record["shell_numeric_exit_code"] = shell_status(returncode)
        record["terminated_by_signal"] = returncode < 0
        if returncode < 0:
            record["signal_number"] = -returncode
            try:
                record["signal_name"] = signal.Signals(-returncode).name
            except ValueError:
                record["signal_name"] = None
    return record


class WrapperInterrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum
        super().__init__(f"wrapper received signal {signum}")


def signal_owned_group(process, signum, row):
    # The direct child has not been reaped on this path, reserving its PID.
    # start_new_session=True binds this PID to the only group we may signal.
    pgid = os.getpgid(process.pid)
    sid = os.getsid(process.pid)
    if pgid != process.pid or sid != process.pid or pgid == os.getpgrp():
        raise RuntimeError("collector process-group/session ownership changed")
    event = {
        "utc": utc_now(), "signal": signal.Signals(signum).name,
        "pid": process.pid, "pgid": pgid, "sid": sid,
        "invocation_attempted": True, "returned_successfully": False,
    }
    row["cleanup_signals"].append(event)
    try:
        os.killpg(pgid, signum)
        event["returned_successfully"] = True
    except BaseException as error:
        event["error"] = exception_record(error)
        raise


def stop_collector(process, report):
    row = report["collector"]
    row["cleanup_started_utc"] = utc_now()
    row["cleanup_signals"] = []
    # poll reaps an already exited child. Never signal its PID/group afterwards.
    existing = process.poll()
    if existing is not None:
        row["exited_before_cleanup_poll"] = True
        row.update(returncode_record(existing))
        issue(report, "collector_exited_before_cleanup", RuntimeError(
            f"log stream had already exited with returncode {existing}"))
        row["cleanup_finished_utc"] = utc_now()
        return
    row["exited_before_cleanup_poll"] = False
    try:
        signal_owned_group(process, signal.SIGTERM, row)
    except ProcessLookupError as error:
        row["term_target_already_gone"] = exception_record(error)
    except BaseException as error:
        issue(report, "collector_sigterm", error)
    try:
        process.wait(timeout=COLLECTOR_TERM_SECONDS)
    except BaseException as error:
        if isinstance(error, subprocess.TimeoutExpired):
            row["term_wait_timeout"] = exception_record(error)
        else:
            issue(report, "collector_term_wait", error)
        if process.returncode is not None:
            row.update(returncode_record(process.returncode))
            row["direct_child_reaped"] = True
            row["cleanup_finished_utc"] = utc_now()
            return
        # A failed wait can also leave our direct collector child running.
        # Only this still-unreaped, owned group is eligible for the fallback.
        try:
            signal_owned_group(process, signal.SIGKILL, row)
        except ProcessLookupError as lookup_error:
            row["kill_target_already_gone"] = exception_record(lookup_error)
        except BaseException as kill_error:
            issue(report, "collector_sigkill", kill_error)
        try:
            process.wait(timeout=COLLECTOR_KILL_SECONDS)
        except BaseException as wait_error:
            issue(report, "collector_kill_wait", wait_error)
    row.update(returncode_record(process.returncode))
    row["direct_child_reaped"] = process.returncode is not None
    if process.returncode is None:
        issue(report, "collector_unreaped", RuntimeError(
            "owned log process did not complete within bounded cleanup"))
    elif process.returncode not in (0, -signal.SIGTERM, -signal.SIGKILL):
        issue(report, "collector_returncode", RuntimeError(
            f"unexpected log stream returncode {process.returncode}"))
    row["cleanup_finished_utc"] = utc_now()


def chosen_exit(report):
    child = report["original_command"]
    returncode = child.get("raw_popen_returncode")
    if returncode is not None and returncode != 0:
        return shell_status(returncode), "original_command_nonzero"
    if report.get("wrapper_interruption"):
        return 128 + report["wrapper_interruption"]["signal"], "wrapper_interrupted"
    if child.get("error") or returncode is None:
        return 1, "original_command_did_not_return"
    if report["observer_errors"]:
        return 1, "observer_failure_with_original_exit_zero"
    return 0, "original_exit_zero_and_observer_completed"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command or args.command[0] != "--" or len(args.command) == 1:
        parser.error("require -- followed by the unchanged original command argv")
    command = args.command[1:]
    requested_output = Path(args.output)
    if not requested_output.is_absolute():
        parser.error("--output must be an absolute new directory")
    output = requested_output.parent.resolve(strict=True) / requested_output.name
    output.mkdir(mode=0o700)
    report = {
        "schema": 1, "scope": "host_log_observation_around_one_original_command",
        "result": "IN_PROGRESS", "recording_complete": False,
        "started_utc": utc_now(), "context": {key: os.environ.get(key) for key in CONTEXT_KEYS},
        "wrapper_pid": os.getpid(), "wrapper_uid": os.getuid(),
        "wrapper_cwd": str(Path.cwd().resolve()), "wrapper_argv": list(sys.argv),
        "original_command": {"argv": command, "launch_attempts": 0, "launches": 0,
                             "timeout_seconds": None, "stdio": "inherited",
                             "environment": "inherited_without_modification",
                             "raw_popen_returncode": None},
        "collector": {"argv": COLLECTOR_ARGV, "launch_attempts": 0, "launches": 0,
                      "cleanup_signals": [], "new_session": True,
                      "stdout_file": "host-stream.stdout.log",
                      "stderr_file": "host-stream.stderr.log",
                      "requested_limit_bytes_per_file": FILE_LIMIT_BYTES,
                      "term_wait_seconds": COLLECTOR_TERM_SECONDS,
                      "kill_wait_seconds": COLLECTOR_KILL_SECONDS},
        "observer_errors": [], "received_wrapper_signals": [],
        "limits": {
            "no_original_command_timeout_added": True,
            "original_command_signals_sent_by_wrapper": 0,
            "other_infrastructure_signals_sent_by_wrapper": 0,
            "original_command_retry_count": 0,
            "runtime_device_cache_or_logging_configuration_mutations": 0,
            "collector_live_subscription_readiness_is_not_proven_by_spawn": True,
            "live_stream_may_buffer_drop_redact_or_miss_messages": True,
            "logging_and_regular_file_writes_can_affect_host_timing": True,
            "job_timeout_and_external_cancellation_remain_owned_by_existing_workflow": True,
            "negative_child_returncode_is_mapped_to_128_plus_signal_without_signaling_wrapper": True,
            "exit_zero_report_requires_actual_wrapper_exit_zero_and_original_result": True,
        },
    }
    started = time.monotonic()
    collector = None
    original = None
    streams = []
    previous_handlers = {}
    cleanup_started = False

    def interrupted(signum, _frame):
        report["received_wrapper_signals"].append({"signal": signum, "utc": utc_now()})
        if not report.get("wrapper_interruption"):
            report["wrapper_interruption"] = {"signal": signum, "utc": utc_now()}
            if not cleanup_started:
                raise WrapperInterrupted(signum)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, interrupted)
        try:
            report["wrapper_source"] = file_record(Path(__file__).resolve())
        except Exception as error:
            issue(report, "wrapper_source_record", error)
        save_best_effort(report, output, "initial_report")
        try:
            if sys.platform != "darwin":
                raise RuntimeError("host collector requires the existing macOS runner")
            for name in ("host-stream.stdout.log", "host-stream.stderr.log"):
                streams.append(open_regular_new(output / name))
            effective, inherited = effective_file_limit()
            report["collector"]["effective_limit_bytes_per_file"] = effective
            report["collector"]["inherited_rlimit_fsize"] = inherited
            collector_env = os.environ.copy()
            collector_env.update({"LC_ALL": "C", "TZ": "UTC"})
            report["collector"]["environment_overrides"] = {"LC_ALL": "C", "TZ": "UTC"}
            report["collector"]["launch_attempts"] += 1
            report["collector"]["launch_started_utc"] = utc_now()
            collector = subprocess.Popen(
                COLLECTOR_ARGV, stdin=subprocess.DEVNULL, stdout=streams[0],
                stderr=streams[1], env=collector_env, start_new_session=True,
                preexec_fn=collector_limit(effective),
            )
            report["collector"].update({"launches": 1, "pid": collector.pid,
                                        "launch_returned_utc": utc_now()})
            report["collector"]["pgid_after_spawn"] = os.getpgid(collector.pid)
            report["collector"]["sid_after_spawn"] = os.getsid(collector.pid)
            if (report["collector"]["pgid_after_spawn"] != collector.pid or
                    report["collector"]["sid_after_spawn"] != collector.pid):
                raise RuntimeError("collector did not receive its own process group/session")
        except Exception as error:
            issue(report, "collector_start", error)
        save_best_effort(report, output, "pre_original_report")
        if report.get("wrapper_interruption"):
            raise WrapperInterrupted(report["wrapper_interruption"]["signal"])
        child = report["original_command"]
        child["launch_attempts"] += 1
        child["launch_started_utc"] = utc_now()
        try:
            # Exactly one unmodified command; no shell, no pipes, no deadline,
            # no new session, no limit/env/stdio/cwd changes and no retries.
            original = subprocess.Popen(command)
            child.update({"launches": 1, "pid": original.pid, "launch_returned_utc": utc_now()})
            save_best_effort(report, output, "original_started_report")
            returncode = original.wait()
            child.update(returncode_record(returncode))
            child["returned_utc"] = utc_now()
        except BaseException as error:
            child["error"] = exception_record(error)
            if original is not None and original.returncode is not None:
                child.update(returncode_record(original.returncode))
            raise
    except WrapperInterrupted:
        pass
    except BaseException as error:
        issue(report, "wrapper", error)
    finally:
        cleanup_started = True
        if collector is not None:
            try:
                stop_collector(collector, report)
            except BaseException as error:
                issue(report, "collector_cleanup", error)
        for stream in streams:
            try:
                stream.close()
            except BaseException as error:
                issue(report, "collector_file_close", error)
        for name in ("host-stream.stdout.log", "host-stream.stderr.log"):
            try:
                record = file_record(output / name)
                report["collector"].setdefault("files", []).append(record)
                limit = report["collector"].get("effective_limit_bytes_per_file", FILE_LIMIT_BYTES)
                if record["bytes"] >= limit:
                    report["collector"]["file_limit_reached"] = True
                    issue(report, "collector_file_limit", RuntimeError(f"capture reached its byte limit: {name}"))
            except BaseException as error:
                issue(report, "collector_file_record", error)
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except BaseException as error:
                issue(report, "restore_wrapper_signal_handler", error)
        report["finished_utc"] = utc_now()
        report["elapsed_seconds"] = time.monotonic() - started
        code, reason = chosen_exit(report)
        report["wrapper_exit_code"] = code
        report["wrapper_exit_reason"] = reason
        report["result"] = "OBSERVED_ORIGINAL_COMMAND_COMPLETED" if code == 0 else "OBSERVATION_OR_ORIGINAL_COMMAND_FAILED"
        report["recording_complete"] = True
        if not save_best_effort(report, output, "final_report"):
            report["wrapper_exit_code"], report["wrapper_exit_reason"] = chosen_exit(report)
        # Re-evaluate after all secondary operations; never replace a known
        # original nonzero exit, including a negative native signal return code.
        code, reason = chosen_exit(report)
        stderr_best_effort(json.dumps({"host_observation_report": str(output / "host-observation-result.json"),
                                      "original_returncode": report["original_command"].get("raw_popen_returncode"),
                                      "wrapper_exit_code": code, "wrapper_exit_reason": reason,
                                      "observer_error_count": len(report["observer_errors"])}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
