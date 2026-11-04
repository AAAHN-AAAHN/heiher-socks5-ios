#!/usr/bin/env python3
"""Observe one Simulator lifecycle and its bootstatus child; no app execution."""
import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback

PARENT = "d57f669e9bb87af147b4af9dce7a2abc387cc62c"
SCRIPT = "Bootstrap/simulator_lifecycle_diagnostic.py"
WORKFLOW = ".github/workflows/udp-echo-ui-diagnostic.yml"
HELPERS = {
    "Bootstrap/ios_runtime_staged_preflight.py": (32991, "50f18d556978a4274949d34a8dcafe8af1098c9c0ffc3b2912d3f10e4bc0568c"),
    "Bootstrap/ios_runtime_service_refresh.py": (32975, "11eb509dcfd933eb0f2dd0a7fbf67883e106feb4ca77400bdf516c4071b16c12"),
    "Bootstrap/observe_host_during_command.py": (18796, "277f667fd17d96e9b3f6fbd733282d9b3622d782e20d2e2a4ab3a35d2b4575f8"),
    "Bootstrap/process_wait_diagnostic.py": (21277, "997d8f1dbd86782c1d1b9967a99290ce17dbf02382ff99d423f9cc810cba9bf2"),
}
CONTEXT_KEYS = ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                "GITHUB_JOB", "GITHUB_REF", "RUNNER_NAME", "RUNNER_OS", "RUNNER_ARCH",
                "DEVELOPER_DIR")
MONITOR_SECONDS = 122.0
MONITOR_INTERVAL_SECONDS = 0.1
MONITOR_JOIN_SECONDS = 1.0
NATIVE_CLEANUP_SECONDS = 1.0
OWNED_PROCESSES = []  # Keep objects alive; no implicit destructor poll during measurement.


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


def stamp():
    return {"observed_utc": utc(), "observed_monotonic_ns": time.monotonic_ns()}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def require_interpreter(version):
    require(tuple(sys.version_info) == (*version, "final", 0)
            and sys.implementation.name == "cpython" and sys.platform == "darwin"
            and platform.machine() == "arm64" and __debug__, "Actual interpreter/platform differs")
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.environ.get("DEVELOPER_DIR") == "/Applications/Xcode_27.app/Contents/Developer",
            "Require the unchanged hosted Xcode27 environment")


def bind_control(args):
    out = args.output.resolve()
    out.mkdir()
    report = {"schema": "simulator-lifecycle-control-binding-v1", "started_utc": utc(),
              "product_pass": False, "candidate_credit": False, "result": "INCOMPLETE",
              "context": {key: os.environ.get(key) for key in CONTEXT_KEYS}}
    try:
        report["runtime"] = runtime_record(out)
        require_interpreter((3, 14, 9))
        root = Path.cwd().resolve()
        def git(*argv):
            return subprocess.run(["git", *argv], cwd=root, check=True, capture_output=True,
                                  text=True, timeout=2).stdout.strip()
        report["actual_control"] = {"commit": git("rev-parse", "HEAD"),
                                    "tree": git("rev-parse", "HEAD^{tree}"),
                                    "parents": git("show", "-s", "--format=%P", "HEAD")}
        report["changed_files"] = git("diff-tree", "--no-commit-id", "--name-only", "-r", PARENT, "HEAD").splitlines()
        report["tracked_status"] = git("status", "--porcelain", "--untracked-files=no")
        require(report["actual_control"]["parents"] == PARENT
                and report["actual_control"]["commit"] == os.environ.get("GITHUB_SHA")
                and len(report["changed_files"]) == 2 and set(report["changed_files"]) == {SCRIPT, WORKFLOW}
                and not report["tracked_status"] and Path(__file__).resolve() == root / SCRIPT
                and os.environ.get("GITHUB_REPOSITORY") == "AAAHN-AAAHN/heiher-socks5-ios"
                and os.environ.get("GITHUB_JOB") == "diagnose_simulator_lifecycle_only",
                "Actual diagnostic source or run identity differs")
        report["source_files"] = {name: descriptor(root / name) for name in (*HELPERS, SCRIPT, WORKFLOW)}
        for name, expected in HELPERS.items():
            row = report["source_files"][name]
            require((row["bytes"], row["sha256"]) == expected, "Existing helper changed: " + name)
        cache = Path(os.environ["RUNNER_TOOL_CACHE"]) / "Python/3.14.9/arm64"
        supplied = args.python315
        require(cache.is_absolute() and Path(str(cache) + ".complete").is_file()
                and (cache / "bin/python3.14").resolve() == Path(sys.executable).resolve()
                and supplied.is_absolute() and str(supplied) == shutil.which("python3")
                and str(supplied.resolve()).startswith("/opt/homebrew/Cellar/python@3.15/3.15.1/"),
                "Existing cached/PATH interpreter differs")
        report["lifecycle_interpreter_input"] = descriptor(supplied)
        report["result"] = "CONTROL_BOUND_NO_LIFECYCLE_EXECUTED"
    except Exception as error:
        report["error"] = error_record(error)
    report["finished_utc"] = utc()
    save(out / "control-binding.json", report)
    return 0 if report["result"] == "CONTROL_BOUND_NO_LIFECYCLE_EXECUTED" else 1


def cleanup_owned_child(process):
    """After the original wait outcome: only this unreaped direct child, once."""
    row = {"pid": process.pid, "started": stamp(), "waitpid_calls": 0,
           "signal_attempts": 0, "errors": [], "complete": False,
           "popen_returncode_at_entry": process.returncode}
    if process.returncode is not None:
        row.update(complete=True, reaped_by_measured_wait=True)
        return row
    def reap_once():
        row["waitpid_calls"] += 1
        pid, status = os.waitpid(process.pid, os.WNOHANG)
        event = {**stamp(), "pid": pid, "raw_status": status}
        row["last_native_waitpid"] = event
        if pid == process.pid:
            event["decoded_exitcode"] = os.waitstatus_to_exitcode(status)
            row["complete"] = True
            return True
        require(pid == 0, "Native cleanup returned a different child")
        return False
    try:
        if not reap_once():
            # No other code reaps this child: the monitor uses WNOWAIT only.
            row["signal_attempts"] = 1
            row["signal"] = {**stamp(), "name": "SIGKILL", "target_pid": process.pid}
            try:
                os.kill(process.pid, signal.SIGKILL)
                row["signal"]["returned_normally"] = True
            except ProcessLookupError as error:
                row["signal"]["error"] = error_record(error)
            deadline = time.monotonic() + NATIVE_CLEANUP_SECONDS
            pause = threading.Event()
            while not reap_once():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    row["deadline_expired"] = True
                    break
                pause.wait(min(0.01, remaining))
    except Exception as error:
        row["errors"].append(error_record(error))
    row["finished"] = stamp()
    row["popen_returncode_after_native_cleanup"] = process.returncode
    return row


def monitor_exit(pid, stop, state, out):
    """Observe, never reap: no Popen access, mutation, signalling or retries."""
    state.update(started=stamp(), pid=pid, calls=0, no_exit_observations=0,
                 flags=int(os.WEXITED | os.WNOWAIT | os.WNOHANG), errors=[])
    deadline = time.monotonic() + MONITOR_SECONDS
    try:
        while not stop.is_set() and time.monotonic() < deadline:
            state["calls"] += 1
            call_started = stamp()
            try:
                result = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                observed = stamp()
            except OSError as error:
                observed = stamp()
                if error.errno == errno.ECHILD:
                    state["echild_inconclusive"] = {**observed, "errno": error.errno,
                        "reason": "A normal measured wait may already have reaped; no anomaly inferred."}
                    break
                raise
            if result is not None:
                require(result.si_pid == pid, "Native monitor returned a different child")
                event = {**observed, "call_started": call_started,
                         "si_pid": result.si_pid, "si_uid": result.si_uid,
                         "si_signo": result.si_signo, "si_code": result.si_code,
                         "si_status": result.si_status,
                         "meaning": "Observed an exited, unreaped own child; this is not the kernel exit timestamp."}
                state["first_native_exit_observation"] = event
                # Write the first actual observation independently of the parent outcome.
                save(out / "bootstatus-first-native-exit.json", event)
                break
            state["no_exit_observations"] += 1
            state["last_no_exit_observation"] = observed
            stop.wait(min(MONITOR_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic())))
        state["deadline_reached"] = time.monotonic() >= deadline
    except Exception as error:
        state["errors"].append(error_record(error))
    finally:
        state["finished"] = stamp()


def command(out, label, argv, timeout, observe=False, merged=True):
    row = {"label": label, "argv": argv, "cwd": str(Path.cwd().resolve()),
           "timeout_seconds": timeout, "launch_attempts": 0, "launches": 0,
           "stdio": "stdout/stderr merged regular log" if merged else "separate stdout/stderr regular logs",
           "environment": "inherited_without_modification", "started": stamp(), "errors": []}
    process = thread = None
    stop = threading.Event()
    state = {}
    stdout_path, stderr_path = out / (label + ".stdout.log"), out / (label + ".stderr.log")
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            row["launch_attempts"] = 1
            process = subprocess.Popen(argv, stdout=stdout,
                                       stderr=subprocess.STDOUT if merged else stderr)
            OWNED_PROCESSES.append(process)
            row.update(pid=process.pid, launches=1, spawn_returned=stamp())
            if observe:
                thread = threading.Thread(target=monitor_exit, args=(process.pid, stop, state, out),
                                          name="owned-bootstatus-native-exit", daemon=True)
                thread.start()
            row["measured_wait_started"] = stamp()
            begin = time.monotonic()
            try:
                code = process.wait(timeout=timeout)  # The single original timed wait.
                outcome = {**stamp(), "kind": "RETURN", "returncode": code}
            except subprocess.TimeoutExpired as error:
                outcome = {**stamp(), "kind": "TIMEOUT", "error": error_record(error)}
            except Exception as error:
                outcome = {**stamp(), "kind": "EXCEPTION", "error": error_record(error)}
            outcome["elapsed_seconds"] = time.monotonic() - begin
            row["measured_wait_outcome"] = outcome
            # This original outcome is saved before monitor join, native reap or signal.
            save(out / (label + "-measured-wait.json"), row)
    except Exception as error:
        row["errors"].append(error_record(error))
    finally:
        if thread is not None:
            stop.set()
            thread.join(MONITOR_JOIN_SECONDS)
            row["monitor_shutdown"] = {**stamp(), "joined": not thread.is_alive(),
                                       "join_limit_seconds": MONITOR_JOIN_SECONDS}
            # A daemon thread that fails to join is recorded as an incomplete failure.
            row["native_monitor"] = dict(state)
            first = state.get("first_native_exit_observation")
            outcome = row.get("measured_wait_outcome")
            row["native_exit_observed_before_wait_outcome"] = (
                first["observed_monotonic_ns"] < outcome["observed_monotonic_ns"]
                if first is not None and outcome is not None else None)
        if process is not None:
            row["owned_child_cleanup"] = cleanup_owned_child(process)
        row["finished"] = stamp()
        for name, path in (("stdout", stdout_path), ("stderr", stderr_path)):
            if path.is_file():
                row[name] = descriptor(path)
        outcome = row.get("measured_wait_outcome", {})
        row["complete_zero"] = (outcome.get("kind") == "RETURN" and outcome.get("returncode") == 0
            and not row["errors"] and row.get("owned_child_cleanup", {}).get("complete") is True
            and (not observe or (row.get("monitor_shutdown", {}).get("joined") is True
                                and not row.get("native_monitor", {}).get("errors"))))
        save(out / (label + "-result.json"), row)
    return row


def lifecycle(args):
    base = args.output.resolve()
    out = base / "lifecycle"
    out.mkdir()
    report = {"schema": "simulator-lifecycle-wait-observation-v1", "started": stamp(),
              "result": "INCOMPLETE", "product_pass": False, "candidate_credit": False,
              "application_runs": 0, "build_runs": 0, "checker_runs": 0,
              "context": {key: os.environ.get(key) for key in CONTEXT_KEYS},
              "commands": [], "cleanup_commands": [], "errors": [], "owned_udid": None,
              "limits": {"job_minutes": 10, "monitor_seconds": MONITOR_SECONDS,
                         "monitor_interval_seconds": MONITOR_INTERVAL_SECONDS,
                         "monitor_join_seconds": MONITOR_JOIN_SECONDS, "native_cleanup_seconds": NATIVE_CLEANUP_SECONDS,
                         "command_retries": 0, "runtime_removal": 0, "popen_or_feature_flag_mutations": 0,
                         "native_observation_can_affect_scheduling": True,
                         "no_exit_sample_does_not_prove_child_was_live_at_every_instant": True,
                         "kernel_exit_and_popen_reap_timestamps_not_directly_measured": True}}
    target = out / "lifecycle-result.json"
    identifier = None
    create_attempted = False
    try:
        report["runtime"] = runtime_record(out)
        require_interpreter((3, 15, 1))
        require(str(Path(sys.executable).resolve()).startswith("/opt/homebrew/Cellar/python@3.15/3.15.1/"),
                "Require the actual Homebrew CPython3.15.1 interpreter")
        require(all(hasattr(os, name) for name in ("waitid", "waitpid", "P_PID", "WEXITED", "WNOWAIT", "WNOHANG")),
                "Required native observation primitives are unavailable; no substitute")
        binding_path = base / "control/control-binding.json"
        binding = json.loads(binding_path.read_bytes())
        require(binding["result"] == "CONTROL_BOUND_NO_LIFECYCLE_EXECUTED" and binding["context"] == report["context"]
                and binding["lifecycle_interpreter_input"]["sha256"] == report["runtime"]["executable"]["sha256"],
                "Actual control/interpreter binding differs")
        report["control_binding"] = descriptor(binding_path)
        for name, expected in binding["source_files"].items():
            actual = descriptor(Path.cwd() / name)
            require(all(actual[k] == expected[k] for k in ("path", "bytes", "sha256")), "Bound source changed: " + name)
        preparation = {}
        for phase, relative, expected in (("staged", "preflight/preflight-result.json", "STAGED_RUNTIME_VERIFIED_AND_SELECTED"),
                ("service", "service/refresh-result.json", "OWN_SERVICE_REFRESHED_AND_SAME_RUNTIME_SELECTED")):
            path = base / relative
            value = json.loads(path.read_bytes())
            status_path = base / (phase + ".shell-status.txt")
            require(status_path.read_text() == "0\n" and value["result"] == expected
                    and value["original_lifecycle_may_run"] is True
                    and value["candidate_credit"] is False and value["product_pass"] is False
                    and value["helper_sha"] == os.environ["GITHUB_SHA"]
                    and value["run_id"] == os.environ["GITHUB_RUN_ID"]
                    and value["attempt"] == os.environ["GITHUB_RUN_ATTEMPT"], "Actual preparation failed or differs: " + phase)
            preparation[phase] = value
            report.setdefault("preparation_inputs", {})[phase] = {"result": descriptor(path), "actual_shell_status": descriptor(status_path)}
        selection = preparation["service"]["logical_selection"]
        expected_runtime = selection["logical_runtime"]
        without_usage = lambda row: {k: v for k, v in row.items() if k != "lastUsage"}
        require(without_usage(preparation["staged"]["logical_selection"]["logical_runtime"]) == without_usage(expected_runtime)
                and preparation["staged"]["logical_selection"]["device_type"] == selection["device_type"],
                "Staged/service actual selections differ")
        require(expected_runtime["version"] == "27.0" and expected_runtime["buildversion"] == "24A434"
                and expected_runtime["identifier"] == "com.apple.CoreSimulator.SimRuntime.iOS-27-0"
                and expected_runtime["isAvailable"] is True and selection["device_type"]["name"] == "iPhone 16"
                and expected_runtime["bundlePath"] == selection["expected_later_lifecycle_bundle_path"],
                "Prepared runtime/device is not the fixed diagnostic input")
        for label, subject in (("list-runtimes", "runtimes"), ("list-devicetypes", "devicetypes")):
            row = command(out, label, ["xcrun", "simctl", "list", subject, "-j"], 60, merged=False)
            report["commands"].append(row)
            save(target, report)
            require(row["complete_zero"], "Actual metadata command failed: " + label)
        runtimes = json.loads((out / "list-runtimes.stdout.log").read_bytes())["runtimes"]
        devices = json.loads((out / "list-devicetypes.stdout.log").read_bytes())["devicetypes"]
        # Preserve the original Server driver's selection order, then bind actual identity.
        runtime = next(r for r in runtimes if r.get("isAvailable") and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27-"))
        device = next(d for d in devices if d["name"] == "iPhone 16")
        report["selected_runtime"] = runtime
        report["selected_device_type"] = device
        require(without_usage(runtime) == without_usage(expected_runtime) and device == selection["device_type"],
                "Original selection differs from the actually prepared exact runtime/device")
        save(target, report)
        create_attempted = True
        try:
            row = command(out, "create", ["xcrun", "simctl", "create", "Server Control UI Audit",
                                          device["identifier"], runtime["identifier"]], 60, merged=False)
            report["commands"].append(row)
        finally:
            # Retain a complete UUID emitted by this one owned create even if its wait
            # or evidence write failed. This never changes that failure to success.
            create_stdout = out / "create.stdout.log"
            if create_stdout.is_file():
                raw_identifier = create_stdout.read_text().strip()
                if re.fullmatch(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}", raw_identifier):
                    identifier = raw_identifier
                    report["owned_udid"] = identifier
                    report["owned_udid_origin"] = {"source": descriptor(create_stdout),
                                                   "meaning": "Exact stdout from this one owned create invocation."}
        save(target, report)
        require(row["complete_zero"] and identifier is not None, "Create did not return a successful actual owned UUID")
        for label, argv, timeout, observe in (
                ("boot", ["xcrun", "simctl", "boot", identifier], 180, False),
                ("bootstatus", ["xcrun", "simctl", "bootstatus", identifier, "-b"], 120, True)):
            row = command(out, label, argv, timeout, observe=observe)
            report["commands"].append(row)
            save(target, report)
            require(row["complete_zero"], "Original lifecycle command failed or observation incomplete: " + label)
    except Exception as error:
        report["errors"].append(error_record(error))
    finally:
        if identifier is not None:
            for action in ("shutdown", "delete"):
                try:
                    row = command(out, "cleanup-" + action, ["xcrun", "simctl", action, identifier], 30)
                    report["cleanup_commands"].append(row)
                except Exception as error:
                    report["errors"].append({"where": "cleanup-" + action, **error_record(error)})
        elif create_attempted:
            report["errors"].append({"where": "owned_device_cleanup", "message": "Create was attempted but no exact owned UUID was obtained; no other device may be removed."})
        complete = (not report["errors"] and len(report["commands"]) == 5
                    and len(report["cleanup_commands"]) == 2
                    and all(row["complete_zero"] for row in report["commands"] + report["cleanup_commands"]))
        report["result"] = "ONE_LIFECYCLE_COMPLETED_NO_APP_CREDIT" if complete else "LIFECYCLE_OR_OBSERVATION_FAILED"
        report["finished"] = stamp()
        save(target, report)
    print(json.dumps({"lifecycle_result": str(target), "result": report["result"], "product_pass": False, "candidate_credit": False}))
    return 0 if complete else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    bind = commands.add_parser("bind-control")
    bind.add_argument("--output", required=True, type=Path)
    bind.add_argument("--python315", required=True, type=Path)
    run = commands.add_parser("lifecycle")
    run.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    return bind_control(args) if args.mode == "bind-control" else lifecycle(args)


if __name__ == "__main__":
    raise SystemExit(main())
