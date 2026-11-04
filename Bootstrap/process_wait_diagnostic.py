#!/usr/bin/env python3
"""Observe five fixed process waits per real interpreter; no project execution."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import shutil
import signal
import subprocess
import sys
import time
import traceback

PARENT = "39a3be345e01435d595f1e9d9fb4102e23d26f59"
SCRIPT = "Bootstrap/process_wait_diagnostic.py"
WORKFLOW = ".github/workflows/udp-echo-ui-diagnostic.yml"
WAIT_SECONDS = 2.0
LIVE_WAIT_SECONDS = 0.25
DRIVER_SECONDS = 20.0
CLEANUP_SECONDS = 1.0
CASES = (("immediate-zero", 0, False, False),
         ("immediate-seven", 7, False, False),
         ("observed-exited-zero", 0, True, False),
         ("observed-exited-seven", 7, True, False),
         ("live-stdin-timeout", None, False, True))


def utc():
    return datetime.now(timezone.utc).isoformat()


def error_record(error):
    return {"type": type(error).__name__, "message": str(error),
            "traceback": traceback.format_exc()}


def descriptor(path):
    path = Path(path)
    raw = path.read_bytes()
    return {"path": str(path), "resolved_path": str(path.resolve()),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    temporary.replace(path)


def runtime_record(out):
    source = Path(subprocess.__file__)
    raw = source.read_bytes()
    saved = out / "actual-subprocess.py"
    with saved.open("xb") as stream:
        stream.write(raw)
    names = ("waitid", "waitpid", "waitstatus_to_exitcode", "P_PID", "WEXITED",
             "WNOWAIT", "WNOHANG", "CLD_EXITED", "pidfd_open")
    primitives = {}
    for name in names:
        value = getattr(os, name, None)
        primitives["os." + name] = {"available": hasattr(os, name),
                                   "value": int(value) if isinstance(value, int) else None}
    for name in ("kqueue", "kevent", "KQ_FILTER_PROC", "KQ_NOTE_EXIT", "KQ_EV_ADD",
                 "KQ_EV_ONESHOT", "KQ_EV_ENABLE", "KQ_EV_ERROR"):
        value = getattr(select, name, None)
        primitives["select." + name] = {"available": hasattr(select, name),
                                       "value": int(value) if isinstance(value, int) else None}
    return {"sys_executable": sys.executable, "executable": descriptor(sys.executable),
            "sys_version": sys.version, "sys_version_info": list(sys.version_info),
            "sys_implementation": sys.implementation.name, "sys_flags": repr(sys.flags),
            "sys_platform": sys.platform, "machine": platform.machine(),
            "pid": os.getpid(), "ppid": os.getppid(), "PATH": os.environ.get("PATH"),
            "subprocess_module": descriptor(source), "saved_subprocess": descriptor(saved),
            "subprocess_flags": {name: getattr(subprocess, name, None) for name in
                                 ("_CAN_USE_KQUEUE", "_CAN_USE_PIDFD_OPEN", "_USE_POSIX_SPAWN", "_USE_VFORK")},
            "primitives": primitives}


def cleanup_owned_child(process, allow_sigkill=True):
    """After measurement only: native nonblocking reap; one own-child SIGKILL."""
    row = {"pid": process.pid, "started_utc": utc(),
           "popen_returncode_before_cleanup": process.returncode,
           "waitpid_options": os.WNOHANG, "waitpid_calls": 0,
           "signal_attempts": 0, "allow_sigkill": allow_sigkill,
           "errors": [], "reaped": False}

    def reap_once():
        row["waitpid_calls"] += 1
        try:
            pid, status = os.waitpid(process.pid, os.WNOHANG)
        except ChildProcessError as error:
            row["native_waitpid"] = {"errno": error.errno, "message": str(error)}
            # A successful measured Popen.wait already reaps its own child.
            row["reaped_by_measured_wait"] = process.returncode is not None
            row["reaped"] = process.returncode is not None
            return True
        row["native_waitpid"] = {"pid": pid, "raw_status": status}
        if pid == process.pid:
            code = os.waitstatus_to_exitcode(status)
            row["native_waitpid"]["decoded_exitcode"] = code
            row["reaped"] = True
            # Synchronize the Popen object only after actual independent reaping.
            # No method, builtin flag, or measured return/exception is modified.
            process.returncode = code
            return True
        if pid != 0:
            raise RuntimeError("waitpid returned a different child")
        return False

    try:
        if not reap_once():
            if allow_sigkill:
                row["signal_attempts"] = 1
                row["signal"] = "SIGKILL"
                row["signal_started_utc"] = utc()
                try:
                    os.kill(process.pid, signal.SIGKILL)
                    row["signal_returned_normally"] = True
                except ProcessLookupError as error:
                    row["signal_returned_normally"] = False
                    row["signal_error"] = error_record(error)
            deadline = time.monotonic() + CLEANUP_SECONDS
            while not reap_once():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    row["cleanup_deadline_expired"] = True
                    break
                # Cleanup-only native WNOHANG observation, never another test wait.
                select.select([], [], [], min(0.01, remaining))
    except Exception as error:
        row["errors"].append(error_record(error))
    finally:
        if process.stdin is not None:
            process.stdin.close()
        row["finished_utc"] = utc()
        row["popen_returncode_after_cleanup"] = process.returncode
    return row


def one_case(out, declaration):
    name, expected, observe_exit, live = declaration
    row = {"name": name, "expected_exitcode": expected,
           "expected_timeout": live, "waitid_before_timed_wait": observe_exit,
           "launches": 0, "measurement_attempts": 0, "started_utc": utc(),
           "result": "NOT_COMPLETED"}
    target = out / (name + ".json")
    process = None
    required = ("waitid", "P_PID", "WEXITED", "WNOWAIT", "CLD_EXITED")
    if observe_exit and not all(hasattr(os, key) for key in required):
        row["result"] = "UNSUPPORTED_PRIMITIVE"
        row["missing"] = [key for key in required if not hasattr(os, key)]
        row["finished_utc"] = utc()
        save(target, row)
        return row
    stdout_path, stderr_path = out / (name + ".stdout.log"), out / (name + ".stderr.log")
    marker = "LIVE_READY\n" if live else "CHILD_EXIT_" + str(expected) + "\n"
    if live:
        code = "import os; os.write(1, b'LIVE_READY\\n'); os.read(0, 1); os._exit(0)"
    else:
        code = ("import os,sys; os.write(1, " + repr(marker.encode()) + "); "
                "os.write(2, b'CHILD_STDERR\\n'); sys.exit(" + str(expected) + ")")
    argv = [sys.executable, "-B", "-c", code]
    row["argv"] = argv
    row["requested_wait_seconds"] = LIVE_WAIT_SECONDS if live else WAIT_SECONDS
    save(target, row)
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        try:
            row["launch_started_utc"] = utc()
            process = subprocess.Popen(argv, stdin=subprocess.PIPE if live else subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr)
            row.update(launches=1, pid=process.pid, launch_returned_utc=utc())
            save(target, row)
            if observe_exit:
                begin = time.monotonic()
                row["waitid_call"] = {"idtype": int(os.P_PID), "pid": process.pid,
                                      "options": int(os.WEXITED | os.WNOWAIT),
                                      "started_utc": utc(), "blocking": True,
                                      "bounded_by_outer_driver_seconds": DRIVER_SECONDS}
                save(target, row)
                observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
                row["waitid_call"].update(
                    elapsed_seconds=time.monotonic() - begin, returned_utc=utc(),
                    result={field: getattr(observed, field, None) for field in
                            ("si_pid", "si_uid", "si_signo", "si_status", "si_code")})
                if (observed.si_pid != process.pid or observed.si_code != os.CLD_EXITED
                        or observed.si_status != expected or process.returncode is not None):
                    raise RuntimeError("waitid did not observe the declared unreaped normal exit")
            row["popen_returncode_before_measurement"] = process.returncode
            row["measurement_attempts"] = 1
            row["measurement_started_utc"] = utc()
            save(target, row)
            begin = time.monotonic()
            try:
                returned = process.wait(timeout=row["requested_wait_seconds"])
                row["measurement"] = {"kind": "RETURN", "raw_returncode": returned}
                row["result"] = "EXPECTED_RETURN" if not live and returned == expected else "UNEXPECTED_RETURN"
            except subprocess.TimeoutExpired as error:
                row["measurement"] = {"kind": "TIMEOUT", "error": error_record(error)}
                row["result"] = "EXPECTED_TIMEOUT" if live else "UNEXPECTED_TIMEOUT"
            except Exception as error:
                row["measurement"] = {"kind": "EXCEPTION", "error": error_record(error)}
                row["result"] = "UNEXPECTED_EXCEPTION"
            row["measurement"].update(elapsed_seconds=time.monotonic() - begin,
                                      finished_utc=utc(), popen_returncode=process.returncode)
            save(target, row)
        except Exception as error:
            row["setup_or_recording_error"] = error_record(error)
            row["result"] = "CASE_INCOMPLETE"
        finally:
            if process is not None:
                row["cleanup"] = cleanup_owned_child(process)
                if not row["cleanup"]["reaped"] or row["cleanup"]["errors"]:
                    row["cleanup_incomplete"] = True
    row["stdout"] = descriptor(stdout_path)
    row["stderr"] = descriptor(stderr_path)
    row["stdout_text"] = stdout_path.read_text(encoding="utf-8", errors="replace")
    row["stderr_text"] = stderr_path.read_text(encoding="utf-8", errors="replace")
    row["expected_child_stdout_observed"] = row["stdout_text"] == marker
    row["finished_utc"] = utc()
    save(target, row)
    return row


def driver(args):
    out = Path(args.output).resolve()
    out.mkdir()
    report = {"schema": "fixed-process-wait-driver-v1", "started_utc": utc(),
              "product_pass": False, "candidate_credit": False, "application_runs": 0,
              "script": descriptor(__file__), "requested_interpreter": args.label,
              "cases": [], "result": "INCOMPLETE"}
    target = out / "driver-result.json"
    try:
        report["runtime"] = runtime_record(out)
        expected_version = (3, 15, 1, "final", 0) if args.label == "python315" else (3, 14, 9, "final", 0)
        if (tuple(sys.version_info) != expected_version or sys.implementation.name != "cpython"
                or sys.platform != "darwin" or platform.machine() != "arm64" or not __debug__):
            raise RuntimeError("Actual interpreter/platform differs from the declared comparison")
        save(target, report)
        for declaration in CASES:
            report["cases"].append(one_case(out, declaration))
            save(target, report)
        complete = all(row["result"] in ("EXPECTED_RETURN", "EXPECTED_TIMEOUT")
                       and row.get("expected_child_stdout_observed") is True
                       and not row.get("cleanup_incomplete") for row in report["cases"])
        report["result"] = "OBSERVATIONS_MATCH_FIXED_EXPECTATIONS" if complete else "ANOMALY_OR_INCOMPLETE_OBSERVATION"
    except Exception as error:
        report["error"] = error_record(error)
    report["finished_utc"] = utc()
    save(target, report)
    print(json.dumps({"driver_result": str(target), "result": report["result"],
                      "product_pass": False, "candidate_credit": False}))
    return 0 if report["result"] == "OBSERVATIONS_MATCH_FIXED_EXPECTATIONS" else 1


def supervise(args):
    out = Path(args.output).resolve()
    out.mkdir()
    report = {"schema": "fixed-process-wait-supervisor-v1", "started_utc": utc(),
              "product_pass": False, "candidate_credit": False, "application_runs": 0,
              "source_parent": PARENT, "driver_limit_seconds": DRIVER_SECONDS,
              "cleanup_limit_seconds": CLEANUP_SECONDS,
              "context": {key: os.environ.get(key) for key in
                          ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                           "GITHUB_JOB", "GITHUB_REF", "RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH")},
              "script": descriptor(__file__), "drivers": [], "result": "INCOMPLETE"}
    target = out / "supervisor-result.json"
    try:
        report["runtime"] = runtime_record(out)
        if (tuple(sys.version_info) != (3, 14, 9, "final", 0) or sys.implementation.name != "cpython"
                or sys.platform != "darwin" or platform.machine() != "arm64" or not __debug__):
            raise RuntimeError("Supervisor requires the unchanged cached CPython3.14.9 Darwin arm64")
        root = Path.cwd().resolve()
        def git(*argv):
            return subprocess.run(["git", *argv], cwd=root, check=True, capture_output=True,
                                  text=True, timeout=2).stdout.strip()
        report["actual_control"] = {"commit": git("rev-parse", "HEAD"),
                                    "tree": git("rev-parse", "HEAD^{tree}"),
                                    "parents": git("show", "-s", "--format=%P", "HEAD")}
        report["changed_files"] = git("diff-tree", "--no-commit-id", "--name-only", "-r", PARENT, "HEAD").splitlines()
        report["worktree_status"] = git("status", "--porcelain", "--untracked-files=no")
        if (report["actual_control"]["parents"] != PARENT or report["actual_control"]["commit"] != os.environ.get("GITHUB_SHA")
                or set(report["changed_files"]) != {SCRIPT, WORKFLOW} or len(report["changed_files"]) != 2
                or report["worktree_status"] or Path(__file__).resolve() != root / SCRIPT
                or os.environ.get("GITHUB_REPOSITORY") != "AAAHN-AAAHN/heiher-socks5-ios"
                or os.environ.get("GITHUB_JOB") != "diagnose_process_wait_only"):
            raise RuntimeError("Actual diagnostic source or execution identity differs")
        report["workflow"] = descriptor(root / WORKFLOW)
        cache = Path(os.environ["RUNNER_TOOL_CACHE"]) / "Python/3.14.9/arm64"
        supplied314, supplied315 = Path(args.python314), Path(args.python315)
        if (not cache.is_absolute() or not Path(str(cache) + ".complete").is_file()
                or supplied314 != cache / "bin/python3.14" or not supplied314.is_file()
                or supplied314.resolve() != Path(sys.executable).resolve()
                or not supplied315.is_absolute() or str(supplied315) != shutil.which("python3")
                or not str(supplied315.resolve()).startswith("/opt/homebrew/Cellar/python@3.15/3.15.1/")):
            raise RuntimeError("Declared actual PATH interpreter/cache input differs")
        report["interpreter_inputs"] = {"python315": descriptor(supplied315), "python314": descriptor(supplied314)}
        save(target, report)
        for label, executable in (("python315", supplied315), ("python314", supplied314)):
            row = {"label": label, "argv": [str(executable), "-B", str(root / SCRIPT), "driver",
                    "--label", label, "--output", str(out / label)], "started_utc": utc(),
                   "requested_timeout_seconds": DRIVER_SECONDS, "launches": 0}
            report["drivers"].append(row)
            process = None
            stdout_path, stderr_path = out / (label + ".stdout.log"), out / (label + ".stderr.log")
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                try:
                    driver_begin = time.monotonic()
                    process = subprocess.Popen(row["argv"], stdin=subprocess.DEVNULL, stdout=stdout,
                                               stderr=stderr, start_new_session=True)
                    row.update(pid=process.pid, launches=1, launch_returned_utc=utc())
                    row["owned_session"] = {"pid": process.pid, "pgid": os.getpgid(process.pid),
                                            "sid": os.getsid(process.pid), "observed_utc": utc()}
                    if row["owned_session"]["pid"] != row["owned_session"]["pgid"] or row["owned_session"]["pid"] != row["owned_session"]["sid"]:
                        raise RuntimeError("Driver is not the leader of its new owned session/group")
                    row["owned_session"]["verified"] = True
                    save(target, report)
                    begin = time.monotonic()
                    row["actual_wait_timeout_seconds"] = max(0, DRIVER_SECONDS - (begin - driver_begin))
                    try:
                        row["raw_returncode"] = process.wait(timeout=row["actual_wait_timeout_seconds"])
                    except Exception as error:
                        row["wait_error"] = error_record(error)
                    row["wait_elapsed_seconds"] = time.monotonic() - begin
                    row["driver_elapsed_before_cleanup_seconds"] = time.monotonic() - driver_begin
                except Exception as error:
                    row["launch_or_recording_error"] = error_record(error)
                finally:
                    if process is not None:
                        if process.returncode is None and row.get("owned_session", {}).get("verified"):
                            group = row["group_cleanup"] = {
                                "scope": "only this verified diagnostic driver and its own probe child",
                                "reason": "driver exit not observed after timeout or setup/recording error",
                                "pgid": process.pid, "signal": "SIGKILL", "signal_attempts": 1,
                                "started_utc": utc(), "owned_session": dict(row["owned_session"])}
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                                group["signal_returned_normally"] = True
                            except Exception as signal_error:
                                group["signal_error"] = error_record(signal_error)
                            group["finished_utc"] = utc()
                        # A verified-group cleanup already sent its one signal.
                        row["cleanup"] = cleanup_owned_child(process, allow_sigkill="group_cleanup" not in row)
            row.update(finished_utc=utc(), stdout=descriptor(stdout_path), stderr=descriptor(stderr_path))
            driver_report = out / label / "driver-result.json"
            if driver_report.is_file():
                row["driver_report"] = descriptor(driver_report)
            save(target, report)
        complete = len(report["drivers"]) == 2 and all(
            row.get("raw_returncode") == 0 and not row.get("wait_error")
            and row.get("cleanup", {}).get("reaped") is True
            and not row.get("cleanup", {}).get("errors") for row in report["drivers"])
        report["result"] = "OBSERVATIONS_MATCH_FIXED_EXPECTATIONS" if complete else "ANOMALY_OR_INCOMPLETE_OBSERVATION"
    except Exception as error:
        report["error"] = error_record(error)
    report["finished_utc"] = utc()
    report["interpretation_limit"] = ("Only these real fixed short-child waits on this job are observed. "
        "Matching expectations cannot prove absence of a timing-dependent defect; an anomaly does not alone "
        "establish the cause of historical Simulator/app failures. No original application, gate, deadline, "
        "Popen method or subprocess feature flag was changed.")
    save(target, report)
    print(json.dumps({"supervisor_result": str(target), "result": report["result"],
                      "product_pass": False, "candidate_credit": False}))
    return 0 if report["result"] == "OBSERVATIONS_MATCH_FIXED_EXPECTATIONS" else 1


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    parent = sub.add_parser("supervise")
    parent.add_argument("--python314", required=True)
    parent.add_argument("--python315", required=True)
    parent.add_argument("--output", required=True)
    child = sub.add_parser("driver")
    child.add_argument("--label", choices=("python315", "python314"), required=True)
    child.add_argument("--output", required=True)
    args = parser.parse_args()
    return supervise(args) if args.mode == "supervise" else driver(args)


if __name__ == "__main__":
    raise SystemExit(main())
