#!/usr/bin/env python3
"""Refresh one own-UID CoreSimulatorService after the unchanged staged preflight.

This is one bounded hypothesis probe, not an application gate or a proven fix.
Only the exact owned service receives one SIGTERM. No service force fallback,
runtime/device deletion, permission change, retry, or lifecycle change occurs.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import locale
import os
from pathlib import Path
import platform
import re
import select
import signal
import stat
import subprocess
import sys
import time

import ios_runtime_staged_preflight as staged
from ios_runtime_signature_preflight import recording_failure, save_preserving_failure
from simulator_runtime_compare import EXPECTED_DEVELOPER_DIR, LIMITS
from watch_runtime_preflight import canonical, decode

STAGED_SHA256 = "50f18d556978a4274949d34a8dcafe8af1098c9c0ffc3b2912d3f10e4bc0568c"
SOURCE_FILES = {**staged.SOURCE_FILES, "ios_runtime_staged_preflight.py": STAGED_SHA256}
SERVICE_NAME = "com.apple.CoreSimulator.CoreSimulatorService"
SERVICE_PATH = "/Library/Developer/PrivateFrameworks/CoreSimulator.framework/Versions/A/XPCServices/" + SERVICE_NAME + ".xpc/Contents/MacOS/" + SERVICE_NAME
METADATA_TIMEOUT, EXIT_TIMEOUT = 10, 10
PS_FIELDS = "uid=,ruid=,pid=,ppid=,lstart=,comm="
PS_COMMAND = ["/bin/ps", "-ww", "-A", "-o", PS_FIELDS]
READ_COMMANDS = {
    "source-head": ["git", "rev-parse", "HEAD"],
    "ps-keywords": ["/bin/ps", "-L"],
    "service-before": PS_COMMAND,
    "runtime-images-before": ["xcrun", "simctl", "runtime", "list", "-j"],
    "devices-before": ["xcrun", "simctl", "list", "devices", "-j"],
    "service-before-signal": PS_COMMAND,
    "service-after-exit": PS_COMMAND,
    "runtime-images-after": ["xcrun", "simctl", "runtime", "list", "-j"],
    "logical-runtimes-after": ["xcrun", "simctl", "list", "runtimes", "-j"],
    "device-types-after": ["xcrun", "simctl", "list", "devicetypes", "-j"],
    "devices-after": ["xcrun", "simctl", "list", "devices", "-j"],
    "service-final": PS_COMMAND,
}


class ProcBSDInfo(ctypes.Structure):
    """Public Darwin proc_bsdinfo; require the API's complete 136-byte return."""
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
    _fields_ += [("nice", ctypes.c_int32), ("start_seconds", ctypes.c_uint64), ("start_microseconds", ctypes.c_uint64)]


def native_identity(pid):
    """Read the executable and creation identity from public libproc, not argv[0]."""
    if sys.platform != "darwin" or ctypes.sizeof(ProcBSDInfo) != 136:
        raise ValueError("Require the declared Darwin proc_bsdinfo ABI")
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    info = ProcBSDInfo()
    ctypes.set_errno(0)
    size = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size != ctypes.sizeof(info):
        raise OSError(ctypes.get_errno(), "proc_pidinfo did not return the complete process identity", pid)
    buffer = ctypes.create_string_buffer(4096)
    ctypes.set_errno(0)
    length = lib.proc_pidpath(pid, buffer, len(buffer))
    if length <= 0 or length >= len(buffer) or len(buffer.value) != length:
        raise OSError(ctypes.get_errno(), "proc_pidpath did not return one complete executable path", pid)
    return {"pid": info.pid, "ppid": info.ppid, "uid": info.uid, "ruid": info.ruid, "svuid": info.svuid,
            "start_seconds": info.start_seconds, "start_microseconds": info.start_microseconds,
            "executable": buffer.value.decode("utf-8"), "proc_bsdinfo_bytes": size}


def service_rows(text):
    """Parse only candidate service rows; retain other-UID services as evidence."""
    rows = []
    for line in text.splitlines():
        if SERVICE_NAME not in line:
            continue
        fields = line.split(maxsplit=9)
        if len(fields) != 10 or any(not value.isdecimal() for value in fields[:4]):
            raise ValueError("Unparseable CoreSimulatorService ps row")
        started = datetime.strptime(" ".join(fields[4:9]), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
        rows.append({"uid": int(fields[0]), "ruid": int(fields[1]), "pid": int(fields[2]), "ppid": int(fields[3]),
                     "lstart_utc": started.isoformat(), "start_seconds": int(started.timestamp()),
                     "ps_comm": fields[9], "raw_line": line})
    return rows


def select_owned_service(rows, uid, allow_absent=False):
    owned = [row for row in rows if row["uid"] == uid or row["ruid"] == uid]
    if allow_absent and not owned:
        return None
    if len(owned) != 1:
        raise ValueError("Require exactly one own-UID CoreSimulatorService")
    row = owned[0]
    if uid <= 0 or row["uid"] != uid or row["ruid"] != uid or row["pid"] <= 1 or row["ps_comm"] != SERVICE_PATH:
        raise ValueError("Service ps identity is outside the exact own-UID executable boundary")
    return row


def validate_native(row, native, uid):
    if (any(native.get(key) != row[key] for key in ("pid", "ppid", "uid", "ruid", "start_seconds"))
            or native.get("svuid") != uid or native.get("executable") != SERVICE_PATH
            or native.get("proc_bsdinfo_bytes") != 136
            or not isinstance(native.get("start_microseconds"), int)
            or not 0 <= native["start_microseconds"] < 1000000 or native["start_seconds"] <= 0):
        raise ValueError("Native service executable, owner or creation identity differs from ps")
    return native


def require_shutdown_devices(data):
    groups = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(groups, dict) or not isinstance(groups.get(staged.IOS), list):
        raise ValueError("Complete device inventory including the selected iOS runtime is required")
    selected = {}
    for runtime, rows in groups.items():
        if not isinstance(runtime, str) or not isinstance(rows, list):
            raise ValueError("Malformed device inventory")
        for row in rows:
            if (not isinstance(row, dict) or row.get("state") != "Shutdown"
                    or not isinstance(row.get("udid"), str) or row["udid"] in selected):
                raise ValueError("An active, unknown-state, malformed or duplicate device prevents service refresh")
            selected[row["udid"]] = {"runtime": runtime, "state": row["state"],
                                     "name": row.get("name"), "deviceTypeIdentifier": row.get("deviceTypeIdentifier")}
    return {"runtime_group_count": len(groups), "device_count": len(selected), "all_shutdown": True,
            "device_identities": selected}


def validate_preflight(p, context):
    if (p.get("result") != "STAGED_RUNTIME_VERIFIED_AND_SELECTED" or p.get("original_lifecycle_may_run") is not True
            or p.get("product_pass") is not False or p.get("candidate_credit") is not False
            or p.get("preflight_sha256") != STAGED_SHA256 or p.get("source_files") != staged.SOURCE_FILES
            or any(p.get(key) != value for key, value in context.items())
            or any(p.get(key) != 1 for key in ("add_attempts", "add_invocations", "verify_attempts", "verify_invocations"))):
        raise ValueError("Require the unchanged successful staged preflight from this exact run/head/attempt")
    old, new = p["selected_original_runtime"]["target_uuid"], p["scope_after_verify"]["new_uuid"]
    if not re.fullmatch(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}", new):
        raise ValueError("Staged runtime UUID is malformed")
    source, image = p["source_dmg_after"], p["staged_dmg_after"]
    if (not staged.same_file(p["source_dmg_before"], source)
            or not staged.same_file(p["staged_dmg_before_verify"], image)
            or p.get("source_dmg_unchanged") is not True or p.get("staged_dmg_unchanged_after_capture") is not True
            or source["sha256"] != image["sha256"] or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            or source["identity"]["size"] != image["identity"]["size"] or source["identity"]["size"] <= 0
            or Path(source["path"]).parent != staged.IOS_ASSET / "Restore"
            or Path(source["path"]).suffix != ".dmg" or source["path"] != source["resolved_path"]
            or image["path"] != str(staged.IMAGES / (new + ".dmg")) or image["path"] != image["resolved_path"]):
        raise ValueError("Preflight DMG identity/content receipts do not bind the exact source and new image")
    commands = {row["label"]: row for row in p["commands"]}
    expected = dict(staged.READ_COMMANDS)
    expected["add-exact-installed-dmg"] = ["xcrun", "simctl", "runtime", "add", source["path"]]
    expected["verify-new-staged-ios"] = ["xcrun", "simctl", "runtime", "verify", new]
    if len(commands) != len(p["commands"]) or set(commands) != set(expected):
        raise ValueError("Preflight command inventory differs from the unchanged single-add/single-verify sequence")
    for label, argv in expected.items():
        row = commands[label]
        timeout = staged.ADD_TIMEOUT if label == "add-exact-installed-dmg" else staged.VERIFY_TIMEOUT if label == "verify-new-staged-ios" else staged.METADATA_TIMEOUT
        if row["argv"] != argv or row.get("returncode") != 0 or row.get("requested_timeout_seconds") != timeout or row.get("timeout") is True or "error" in row or row.get("recording_errors"):
            raise ValueError("Preflight command failed or differs from the fixed command/deadline: " + label)
    return old, new


def validate_runtime(p, data, filesystem):
    original, final = p["runtime_snapshots"]["before"], p["runtime_snapshots"]["after-verify"]
    old, new = p["selected_original_runtime"]["target_uuid"], p["scope_after_verify"]["new_uuid"]
    scope = staged.assess_scope(original["inventory"], data, old, new,
                                before_fs=original["filesystem"], after_fs=filesystem)
    staged.require_same_filesystem(original["filesystem"], filesystem, scope["protected_uuids"])
    staged.require_same_filesystem(original["filesystem"], filesystem, [old], ("path", "parentMountPath"))
    staged.require_same_filesystem(final["filesystem"], filesystem, [new], ("path", "mountPath", "runtimeBundlePath"))
    if canonical(data[new]) != canonical(final["inventory"][new]) or data[new].get("signatureState") != "Verified":
        raise ValueError("Same new Ready/Verified runtime UUID or its complete identity changed")
    return scope


def bound_file_stat(receipt):
    path = Path(receipt["path"])
    result = {"path": str(path), "capture": "pending",
              "bound_preflight_sha256": receipt["sha256"], "additional_content_hash_performed": False}
    try:
        info = path.lstat()
        result.update(capture="observed", resolved_path=str(path.resolve()), identity=staged.file_identity(info),
                      is_regular=stat.S_ISREG(info.st_mode), is_symlink=stat.S_ISLNK(info.st_mode))
        result["matches_verified_receipt"] = result["is_regular"] and all(result[key] == receipt[key] for key in ("path", "resolved_path", "identity"))
    except OSError as error:
        result.update(capture="unavailable", matches_verified_receipt=False,
                      error={"type": type(error).__name__, "message": str(error), "errno": error.errno})
    return result


def event_record(event):
    return {"ident": event.ident, "filter": event.filter, "flags": event.flags, "fflags": event.fflags,
            "data": event.data, "udata": event.udata}


def refresh_service(old, read_final_identity, report, save):
    """One fixed service SIGTERM, one NOTE_EXIT wait, no process polling/retry."""
    queue, primary = None, None
    observation = report["service_refresh"]
    try:
        queue = select.kqueue()
        event = select.kevent(old["pid"], filter=select.KQ_FILTER_PROC,
                             flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
                             fflags=select.KQ_NOTE_EXIT | select.KQ_NOTE_EXEC)
        observation["registration"] = {"started_unix": time.time(), "change": event_record(event), "returned_without_error": False}
        # Darwin returns -1 on registration failure when no output event slot is
        # supplied; Python raises OSError. CPython 3.14 does not export EV_RECEIPT.
        receipts = queue.control([event], 0, 0)
        observation["registration"].update(finished_unix=time.time(), returned_without_error=True,
                                            events=[event_record(row) for row in receipts])
        if receipts:
            raise ValueError("Unexpected output from zero-event registration")
        current = read_final_identity()
        observation["final_native_identity"] = current
        if current != old:
            raise ValueError("Service identity changed after watcher registration")
        save()
        # No subprocess or filesystem work between this final native read and signal.
        immediate = native_identity(old["pid"])
        observation["immediate_native_identity"] = immediate
        if immediate != old:
            raise ValueError("Service identity changed immediately before its one signal")
        pending = queue.control(None, 1, 0)
        observation["events_before_signal"] = [event_record(row) for row in pending]
        if pending:
            raise ValueError("Service exited or executed a new image before the one signal")
        if observation["sigterm_attempts"] or old["pid"] <= 1 or os.getuid() <= 0 or old["uid"] != os.getuid() or old["ruid"] != os.getuid() or old["svuid"] != os.getuid() or old["executable"] != SERVICE_PATH:
            raise ValueError("Service signal identity or at-most-once boundary failed")
        observation["sigterm_attempts"] = 1
        observation["signal_started_unix"] = time.time()
        started = time.monotonic()
        observation["sigterm_invocations"] = 1
        os.kill(old["pid"], signal.SIGTERM)
        observation["signal_returned_successfully"] = True
        observation["signal_returned_unix"] = time.time()
        remaining = max(0, EXIT_TIMEOUT - (time.monotonic() - started))
        events = queue.control(None, 1, remaining)
        observation["wait_returned_unix"], observation["elapsed_seconds"] = time.time(), time.monotonic() - started
        observation["events_after_signal"] = [event_record(row) for row in events]
        if not events:
            raise TimeoutError("Exact service NOTE_EXIT was not delivered within the separate 10-second wait")
        event = events[0]
        if (len(events) != 1 or event.ident != old["pid"] or event.filter != select.KQ_FILTER_PROC
                or event.flags & select.KQ_EV_ERROR or not event.fflags & select.KQ_NOTE_EXIT
                or event.fflags & select.KQ_NOTE_EXEC):
            raise ValueError("Service event did not establish the unchanged target's NOTE_EXIT")
        observation["old_service_exit_observed"] = True
    except Exception as error:
        primary = error
        observation["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if queue is not None:
            try:
                queue.close()
            except Exception as error:
                primary = recording_failure(primary, error, "service-watcher-close", observation)
        primary = save_preserving_failure(save, primary, "service-watcher-result-save", observation)
    if primary is not None:
        raise primary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out, incoming = args.output.resolve(), args.preflight.resolve()
    if (not __debug__ or sys.implementation.name != "cpython" or sys.platform != "darwin" or platform.machine() != "arm64"
            or tuple(sys.version_info) != (3, 14, 9, "final", 0) or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or os.getuid() != os.geteuid() or os.getuid() <= 0
            or os.environ.get("DEVELOPER_DIR") != EXPECTED_DEVELOPER_DIR or out.exists() or out == incoming):
        raise SystemExit("Require the unchanged hosted Darwin arm64 environment, own non-root UID and a fresh output directory")
    locale.setlocale(locale.LC_TIME, "C")
    out.mkdir(parents=True)
    started, ready, failure, p = time.monotonic(), False, None, None
    used = set()
    context = {"helper_sha": os.environ.get("GITHUB_SHA"), "checked_out_sha": os.environ.get("GITHUB_SHA"),
               "run_id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
    report = {"schema": 1, "started_unix": time.time(), **context, "own_uid": os.getuid(), "own_euid": os.geteuid(),
              "source_files": {}, "commands": [], "runtime_snapshots": {}, "service_snapshots": {},
              "metadata_timeout_seconds": METADATA_TIMEOUT, "service_exit_wait_seconds": EXIT_TIMEOUT,
              "original_limits_seconds": LIMITS, "original_lifecycle_may_run": False, "product_pass": False, "candidate_credit": False,
              "service_refresh": {"target_executable": SERVICE_PATH, "sigterm_attempts": 0, "sigterm_invocations": 0,
                                  "old_service_exit_observed": False, "force_fallbacks": 0, "other_infrastructure_service_signals": 0},
              "owned_metadata_child_cleanup_signals": [],
              "success_requires_helper_process_exit_zero": True,
              "scope": "Unchanged staged preflight once, then own-UID exact CoreSimulatorService SIGTERM at most once and one NOTE_EXIT wait. All actual devices must be Shutdown. No launchctl, sudo, runtime/device removal, permission change, service SIGKILL, reset or retry. The original lifecycle runs once only if every preparation guard succeeds.",
              "comparison_limits": "A successful refresh or later lifecycle does not prove sole causation or application correctness. Read-only queries, staging, service respawn and elapsed time can affect state. ps argv[0] is checked against native executable/creation identity. PID signalling is not atomic with identity checks; a narrow exit/reuse race remains despite pre-registered exit/exec observation and immediate native recheck. NOTE_EXIT delivery time is observed, not an exact exit timestamp or non-child exit status.",
              "timing_limits": "Each metadata subprocess waits at most 10 seconds; after a command/wait error only its directly owned child whose exit has not yet been observed may be killed and reaped with a separate one-second wait. Service NOTE_EXIT has its own 10-second wait and no force fallback. Native/FS access, launch and scheduling are not guaranteed hard wall-clock bounds. Original create60/boot180/bootstatus120/shutdown30/delete30 and workflow15min are unchanged.",
              "content_hash_limit": "The source and staged DMGs are not rehashed. Their immediate before/after stat/path identities are bound to the same-run unchanged preflight's already verified content hashes. This is not a new independent content proof.",
              "evidence_persistence_limit": "Result JSON is replaced only after a complete temporary-file write. A final recording or console failure keeps process exit nonzero and the in-memory result failed; a previously committed success file cannot by itself authorize the lifecycle. Actual helper process success and the workflow handoff must also be verified.",
              "after_failure_capture_scope": "After a service signal attempt, remaining allowlisted after snapshots may run once even if NOTE_EXIT fails. These read-only observations can initialize services but are not another signal, a retry, or a force fallback; any capture error remains secondary to the original failure."}

    def save():
        pending = out / "refresh-result.pending.json"
        pending.write_text(json.dumps(report, indent=2) + "\n")
        pending.replace(out / "refresh-result.json")

    def run(label):
        if label not in READ_COMMANDS or label in used:
            raise ValueError("Read command is outside the single-invocation metadata allowlist: " + label)
        used.add(label)
        argv = READ_COMMANDS[label]
        row = {"label": label, "argv": list(argv), "requested_timeout_seconds": METADATA_TIMEOUT,
               "started_unix": time.time(), "stdout_file": label + ".stdout.log", "stderr_file": label + ".stderr.log"}
        report["commands"].append(row)
        begin, process, error = time.monotonic(), None, None
        try:
            with (out / row["stdout_file"]).open("xb") as stdout, (out / row["stderr_file"]).open("xb") as stderr:
                process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, env=dict(os.environ, LC_ALL="C", TZ="UTC"))
                row["pid"] = process.pid
                row["returncode"] = process.wait(timeout=METADATA_TIMEOUT)
                if row["returncode"] != 0:
                    raise subprocess.CalledProcessError(row["returncode"], argv)
        except Exception as caught:
            error = caught
            row["timeout"] = isinstance(caught, subprocess.TimeoutExpired)
            if process is not None and process.returncode is None:
                try:
                    cleanup = {"label": label, "pid": process.pid, "signal": "SIGKILL", "scope": "directly owned metadata child only", "attempted_unix": time.time()}
                    report["owned_metadata_child_cleanup_signals"].append(cleanup)
                    process.kill()
                    cleanup["signal_returned"] = True
                    row["returncode"] = process.wait(timeout=1)
                    cleanup["reaped_returncode"] = row["returncode"]
                except Exception as cleanup_error:
                    row["cleanup_error"] = {"type": type(cleanup_error).__name__, "message": str(cleanup_error)}
        finally:
            row["finished_unix"], row["elapsed_seconds"] = time.time(), time.monotonic() - begin
            for field in ("stdout_file", "stderr_file"):
                try:
                    path = out / row[field]
                    if path.exists():
                        row[field + "_bytes"] = path.stat().st_size
                        with path.open("rb") as stream:
                            row[field + "_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                except Exception as recording_error:
                    error = recording_failure(error, recording_error, field, row)
            if error is not None:
                row["error"] = {"type": type(error).__name__, "message": str(error)}
            error = save_preserving_failure(save, error, "metadata-result-save", row)
        if error is not None:
            raise error
        if (out / row["stdout_file"]).stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Refusing oversized command metadata")
        return (out / row["stdout_file"]).read_text(encoding="utf-8")

    def snapshot(phase):
        data = decode(run("runtime-images-" + phase))
        target = report["runtime_snapshots"][phase] = {"inventory": data}
        target["filesystem"] = staged.filesystem_snapshot(data)
        target["scope_validation"] = validate_runtime(p, data, target["filesystem"])
        return data

    def service(label, allow_absent=False):
        rows = service_rows(run(label))
        target = report["service_snapshots"][label] = {"candidate_rows": rows}
        row = select_owned_service(rows, report["own_uid"], allow_absent)
        if row is None:
            target["own_service_observed"] = False
            return None
        target["own_service_observed"] = True
        target["ps_identity"] = row
        target["native_identity"] = native_identity(row["pid"])
        validate_native(row, target["native_identity"], report["own_uid"])
        target["executable_filesystem"] = staged.path_snapshot(SERVICE_PATH)
        if target["executable_filesystem"].get("capture") != "observed" or target["executable_filesystem"].get("is_regular") is not True:
            raise ValueError("Exact service executable filesystem identity unavailable")
        return target["native_identity"]

    def file_stats(phase):
        target = report.setdefault("dmg_stats", {}).setdefault(phase, {})
        for key in ("source_dmg_after", "staged_dmg_after"):
            target[key] = bound_file_stat(p[key])
        if any(row.get("matches_verified_receipt") is not True for row in target.values()):
            raise ValueError("Source or staged DMG stat/path identity differs from its preflight hash receipt")

    try:
        head = run("source-head").strip()
        if head != context["helper_sha"] or not re.fullmatch(r"[0-9a-f]{40}", head):
            raise ValueError("Actual checked-out head differs from GitHub run source")
        report["source_files"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCE_FILES}
        report["helper_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if report["source_files"] != SOURCE_FILES:
            raise ValueError("An original source or unchanged staged v3 preflight changed")
        raw = (incoming / "preflight-result.json").read_bytes()
        (out / "bound-preflight-result.json").write_bytes(raw)
        report["preflight_binding"] = {"path": str(incoming / "preflight-result.json"), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        p = json.loads(raw)
        old_id, new_id = validate_preflight(p, context)
        report["preflight_binding"].update(old_uuid=old_id, new_uuid=new_id, finished_unix=p["finished_unix"],
                                          age_seconds_at_binding=time.time() - p["finished_unix"])
        report["bound_preflight_command_files"] = []
        for row in p["commands"]:
            for channel in ("stdout", "stderr"):
                name = row[channel + "_file"]
                if Path(name).name != name:
                    raise ValueError("Preflight command evidence path is not a direct filename")
                contents = (incoming / name).read_bytes()
                observed = {"file": name, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}
                if observed["bytes"] != row[channel + "_file_bytes"] or observed["sha256"] != row[channel + "_file_sha256"]:
                    raise ValueError("Preflight command evidence no longer matches the completed receipt")
                report["bound_preflight_command_files"].append(observed)
        if (incoming / "verify-new-staged-ios.stdout.log").read_text() != "Signature verified, signature is valid.\n" or (incoming / "verify-new-staged-ios.stderr.log").read_bytes():
            raise ValueError("Exact staged UUID verification did not preserve its successful raw result")
        file_stats("before")
        keywords = set(run("ps-keywords").split())
        if not {"uid", "ruid", "pid", "ppid", "lstart", "comm"}.issubset(keywords):
            raise ValueError("Actual ps does not advertise the required identity fields")
        old = service("service-before")
        report["service_refresh"]["target_native_identity"] = old
        snapshot("before")
        report["devices_before"] = require_shutdown_devices(decode(run("devices-before")))
        report["preflight_devices_after"] = require_shutdown_devices(decode((incoming / "devices-after.stdout.log").read_text()))
        if report["devices_before"]["device_identities"] != report["preflight_devices_after"]["device_identities"]:
            raise ValueError("Device identities changed after the staged preflight")
        refresh_service(old, lambda: service("service-before-signal"), report, save)
        immediate = service("service-after-exit", allow_absent=True)
        report["service_refresh"]["replacement_observed_before_reinit"] = immediate is not None
        if immediate is not None and immediate["pid"] == old["pid"]:
            raise ValueError("Old service PID still identifies the service after NOTE_EXIT")
        current = snapshot("after")
        logical = decode(run("logical-runtimes-after"))
        types = decode(run("device-types-after"))
        report["logical_selection"] = staged.require_logical_selection(logical, types, current[new_id], p["sdk"])
        if report["logical_selection"]["expected_later_lifecycle_bundle_path"] != p["logical_selection"]["expected_later_lifecycle_bundle_path"]:
            raise ValueError("Exact later lifecycle bundle binding changed after service refresh")
        report["devices_after"] = require_shutdown_devices(decode(run("devices-after")))
        if report["devices_before"]["device_identities"] != report["devices_after"]["device_identities"]:
            raise ValueError("Device identities changed during service refresh")
        replacement = service("service-final")
        if (replacement["pid"] == old["pid"] or replacement["start_seconds"] * 1000000 + replacement["start_microseconds"] <= old["start_seconds"] * 1000000 + old["start_microseconds"]
                or immediate is not None and replacement != immediate):
            raise ValueError("Replacement is not one distinct newer own-UID service identity")
        if report["service_snapshots"]["service-before"]["executable_filesystem"] != report["service_snapshots"]["service-final"]["executable_filesystem"]:
            raise ValueError("Service executable filesystem identity changed")
        report["service_refresh"]["replacement_native_identity"] = replacement
        report["service_refresh"]["replacement_origin_limit"] = "No launchctl/start command was issued. A replacement seen before simctl reinitialization is consistent with automatic launch-service respawn; exact platform causation is not inferred."
        ready = True
    except Exception as error:
        failure = error
    finally:
        if p is not None:
            try:
                file_stats("after")
            except Exception as error:
                failure = recording_failure(failure, error, "after-DMG-stat", report)
        if report["service_refresh"]["sigterm_invocations"]:
            for label, capture in (("runtime-images-after", lambda: snapshot("after")),
                                   ("devices-after", lambda: report.update(devices_after=require_shutdown_devices(decode(run("devices-after"))))),
                                   ("service-final", lambda: service("service-final", allow_absent=True))):
                if label not in used:
                    try:
                        capture()
                    except Exception as error:
                        failure = recording_failure(failure, error, "after-failure-" + label, report)
        report["result"] = "OWN_SERVICE_REFRESHED_AND_SAME_RUNTIME_SELECTED" if failure is None and ready else "REFRESH_FAILED"
        report["original_lifecycle_may_run"] = failure is None and ready
        if not report["original_lifecycle_may_run"]:
            failure = failure or RuntimeError("Refresh did not establish every required condition")
            report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        report["finished_unix"], report["elapsed_seconds"] = time.time(), time.monotonic() - started
        failure = save_preserving_failure(save, failure, "final-refresh-result-save", report)
        if failure is not None:
            ready = False
            report["original_lifecycle_may_run"], report["result"] = False, "REFRESH_FAILED"
            report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
    try:
        print(report["result"], "service_sigterm_invocations=" + str(report["service_refresh"]["sigterm_invocations"]), "product_pass=false candidate_credit=false")
    except Exception as error:
        failure = recording_failure(failure, error, "final-refresh-console", report)
        report["original_lifecycle_may_run"], report["result"] = False, "REFRESH_FAILED"
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        failure = save_preserving_failure(save, failure, "console-failure-result-save", report)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
