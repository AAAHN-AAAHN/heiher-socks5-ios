#!/usr/bin/env python3
"""One exact installed iOS 27.0 runtime signature verification.

This is a bounded state check, not an established failure fix. A zero command
exit and preserved runtime identities permit the unchanged lifecycle once.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

from simulator_runtime_compare import validate_toolchain
from watch_runtime_preflight import IOS, canonical, decode, identity, inventory, ios_identities

VERIFY_TIMEOUT = 120
METADATA_TIMEOUT = 10
SOURCE_FILES = {
    "simulator_runtime_compare.py": "a855b4e2cf0481f389776a56876345ffbb43f41b744b69d853c15b17bc80de81",
    "simulator_comparison_diagnostics.py": "2674479d846b113204ba0b3c2184f81ba045c5f519c3d1d78c8c04611980e4e0",
    "watch_runtime_preflight.py": "e50a7b7d39b8abf80698b9c5401cbe09b9d48b66059c96ee06e6695b32e88c02",
}
READ_COMMANDS = {
    "source-head": ["git", "rev-parse", "HEAD"],
    "xcode-version": ["xcodebuild", "-version"],
    "simulator-sdk": ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"],
    "simctl-path": ["xcrun", "--find", "simctl"],
    "xcodebuild-path": ["xcrun", "--find", "xcodebuild"],
    "runtime-help": ["xcrun", "simctl", "help", "runtime"],
    "devices-before": ["xcrun", "simctl", "list", "devices", "-j"],
    "runtime-images-before": ["xcrun", "simctl", "runtime", "list", "-j"],
    "runtime-images-after": ["xcrun", "simctl", "runtime", "list", "-j"],
}


def select_target(data, devices):
    """Resolve exactly one current UUID; never fall back to another runtime."""
    ios_identities(data)
    matches = [row for row in data.values() if row.get("runtimeIdentifier") == IOS]
    row = matches[0]
    identity(row)
    architectures = row["supportedArchitectures"]
    if (not isinstance(architectures, list) or "arm64" not in architectures
            or any(not isinstance(value, str) for value in architectures)
            or not isinstance(row.get("signatureState"), str) or not row["signatureState"].strip()):
        raise ValueError("Selected runtime architecture or signature metadata is invalid")
    groups = devices.get("devices") if isinstance(devices, dict) else None
    if not isinstance(groups, dict) or not isinstance(groups.get(IOS), list):
        raise ValueError("Selected iOS device inventory is unavailable")
    if any(not isinstance(device, dict) or device.get("state") != "Shutdown" for device in groups[IOS]):
        raise ValueError("Selected iOS runtime has an active or unknown-state device")
    return {"target_uuid": row["identifier"], "target_before": dict(row),
            "devices_before": groups[IOS],
            "exact_verify_argv": ["xcrun", "simctl", "runtime", "verify", row["identifier"]]}


def runtime_filesystem(data, selected_id):
    """Record all runtime path identities, including observed absent paths."""
    inventory(data)
    result = {}
    for key, row in data.items():
        paths = {}
        for field in ("path", "parentMountPath", "mountPath", "runtimeBundlePath"):
            raw = row.get(field)
            if not isinstance(raw, str) or not Path(raw).is_absolute():
                raise ValueError("Runtime path is not absolute: " + key + ":" + field)
            path = Path(raw)
            entry = {"path": raw, "resolved_path": str(path.resolve())}
            try:
                stat = path.stat()
                entry.update(exists=True, is_directory=path.is_dir(), device=stat.st_dev, inode=stat.st_ino)
            except FileNotFoundError:
                entry["exists"] = False
            if key == selected_id and (not entry["exists"] or not entry["is_directory"]):
                raise ValueError("Selected iOS runtime path is not an existing directory: " + field)
            paths[field] = entry
        result[key] = paths
    return result


def assess_after(before, after, selected_id):
    """Only the selected record's existing signatureState value may change."""
    inventory(before)
    inventory(after)
    if set(before) != set(after):
        raise ValueError("A runtime was added, removed or re-registered")
    target = after[selected_id]
    if set(before[selected_id]) != set(target):
        raise ValueError("Selected runtime metadata keys changed")
    if not isinstance(target.get("signatureState"), str) or not target["signatureState"].strip():
        raise ValueError("Selected runtime signatureState is absent or invalid")
    for key in before:
        old, new = before[key], after[key]
        if key == selected_id:
            old = {name: value for name, value in old.items() if name != "signatureState"}
            new = {name: value for name, value in new.items() if name != "signatureState"}
        if canonical(old) != canonical(new):
            raise ValueError("Runtime changed beyond the permitted selected signatureState: " + key)
    return {"before": before[selected_id]["signatureState"], "after": target["signatureState"],
            "changed": before[selected_id]["signatureState"] != target["signatureState"]}


def verify_and_capture(before, chosen, filesystem_before, run, report, filesystem=runtime_filesystem):
    """Attempt verification once and capture once, preserving its primary error."""
    primary = None
    try:
        run("verify-exact-selected-ios", chosen["exact_verify_argv"], VERIFY_TIMEOUT)
    except Exception as error:
        primary = error
        report["verify_failure"] = {"type": type(error).__name__, "message": str(error)}
    try:
        after = decode(run("runtime-images-after", READ_COMMANDS["runtime-images-after"], METADATA_TIMEOUT))
        report["runtime_inventory_after"] = after
        report["runtime_filesystem_after"] = filesystem(after, chosen["target_uuid"])
        report["signature_state_observation"] = assess_after(before, after, chosen["target_uuid"])
        if canonical(filesystem_before) != canonical(report["runtime_filesystem_after"]):
            raise ValueError("A runtime path, resolved path or filesystem identity changed")
        report["other_runtime_records_unchanged"] = True
        report["target_identity_unchanged"] = True
        report["all_runtime_filesystem_identities_unchanged"] = True
    except Exception as error:
        report["after_capture_failure"] = {"type": type(error).__name__, "message": str(error)}
        if primary is None:
            primary = error
    if primary is not None:
        raise primary


def recording_failure(primary, error, stage, record):
    """Preserve a command failure when recording that failure also fails."""
    record.setdefault("recording_errors", []).append(
        {"stage": stage, "type": type(error).__name__, "message": str(error)})
    return error if primary is None else primary


def save_preserving_failure(save, primary, stage, record):
    try:
        save()
    except Exception as error:
        primary = recording_failure(primary, error, stage, record)
        if "original_lifecycle_may_run" in record:
            record["original_lifecycle_may_run"] = False
            record["result"] = "PREFLIGHT_FAILED"
            record["failure"] = {"type": type(primary).__name__, "message": str(primary)}
        try:
            print("Preflight evidence persistence failed:", json.dumps(record), file=sys.stderr)
        except Exception:
            pass  # A broken stderr must not replace the original command error.
    return primary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    out = parser.parse_args().output.resolve()
    if (not __debug__ or sys.implementation.name != "cpython" or sys.platform != "darwin"
            or platform.machine() != "arm64" or tuple(sys.version_info) != (3, 14, 9, "final", 0)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or out.exists()):
        raise SystemExit("Use the declared cached interpreter on a hosted macOS job with a fresh output directory")
    out.mkdir(parents=True)
    started = time.monotonic()
    report = {"schema": 1, "started_unix": time.time(), "helper_sha": os.environ.get("GITHUB_SHA"),
              "run_id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "verify_timeout_seconds": VERIFY_TIMEOUT, "metadata_command_timeout_seconds": METADATA_TIMEOUT,
              "maximum_metadata_commands": len(READ_COMMANDS), "verify_attempts": 0, "verify_invocations": 0,
              "commands": [], "original_lifecycle_may_run": False, "product_pass": False, "candidate_credit": False,
              "scope": "One exact current Ready arm64 iOS 27.0 build 24A434 UUID is verified once. Only its signatureState value may change. Every other runtime record and all runtime filesystem identities must stay equal. No watchOS preflight, deletion, force, reinstall, reset, fallback or retry.",
              "comparison_limits": "Unknown signatureState and unrelated host signing errors do not establish a defective selected iOS signature. Verify exit zero reports command completion, not an inferred valid signature or repaired lifecycle. Verification and metadata queries may warm services or alter timing; a later lifecycle result across jobs does not isolate causation. No application or candidate credit.",
              "timing_limits": "Each of at most nine metadata commands waits at most 10 seconds; the sole verify command has its own 120-second wait. On a command error only that owned subprocess may be killed, with a one-second reap wait. Process creation, filesystem access and scheduling can exceed these wait bounds; they are not a strict wall-clock deadline. Original lifecycle deadlines remain unchanged."}
    chosen = None
    failure = None
    used_labels = set()

    def save():
        (out / "preflight-result.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(label, argv, timeout):
        is_verify = label == "verify-exact-selected-ios"
        if label in used_labels:
            raise ValueError("No preflight command may be retried: " + label)
        if is_verify:
            if (chosen is None or argv != chosen["exact_verify_argv"]
                    or timeout != VERIFY_TIMEOUT or report["verify_attempts"]):
                raise ValueError("Only one exact selected UUID verification is permitted")
            report["verify_attempts"] = 1
        elif label not in READ_COMMANDS or argv != READ_COMMANDS[label] or timeout != METADATA_TIMEOUT:
            raise ValueError("Preflight command is outside its fixed allowlist")
        used_labels.add(label)
        row = {"label": label, "argv": list(argv), "requested_timeout_seconds": timeout,
               "started_unix": time.time(), "stdout_file": label + ".stdout.log",
               "stderr_file": label + ".stderr.log"}
        report["commands"].append(row)
        begin = time.monotonic()
        process = None
        error = None
        try:
            with (out / row["stdout_file"]).open("xb") as stdout, (out / row["stderr_file"]).open("xb") as stderr:
                process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
                row["pid"] = process.pid
                if is_verify:
                    report["verify_invocations"] = 1
                row["returncode"] = process.wait(timeout=timeout)
                if row["returncode"] != 0:
                    raise subprocess.CalledProcessError(row["returncode"], argv)
        except Exception as caught:
            error = caught
            row["timeout"] = isinstance(caught, subprocess.TimeoutExpired)
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                    row["owned_process_kill_requested"] = True
                    row["returncode"] = process.wait(timeout=1)
                except Exception as cleanup_error:
                    row["cleanup_error"] = {"type": type(cleanup_error).__name__, "message": str(cleanup_error)}
        finally:
            row["finished_unix"] = time.time()
            row["elapsed_seconds"] = time.monotonic() - begin
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
            error = save_preserving_failure(save, error, "command-result-save", row)
        if error is not None:
            raise error
        if (out / row["stdout_file"]).stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Refusing oversized command metadata: " + label)
        return (out / row["stdout_file"]).read_text(encoding="utf-8")

    try:
        report["checked_out_sha"] = run("source-head", READ_COMMANDS["source-head"], METADATA_TIMEOUT).strip()
        if report["checked_out_sha"] != report["helper_sha"]:
            raise ValueError("Checked-out source differs from the actual run head")
        report["source_files"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                  for name in SOURCE_FILES}
        report["preflight_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if report["source_files"] != SOURCE_FILES:
            raise ValueError("Original lifecycle, observer or imported read-only helpers changed")
        xcode = run("xcode-version", READ_COMMANDS["xcode-version"], METADATA_TIMEOUT).strip()
        sdk = run("simulator-sdk", READ_COMMANDS["simulator-sdk"], METADATA_TIMEOUT).strip()
        simctl = run("simctl-path", READ_COMMANDS["simctl-path"], METADATA_TIMEOUT).strip()
        xcodebuild = run("xcodebuild-path", READ_COMMANDS["xcodebuild-path"], METADATA_TIMEOUT).strip()
        report["xcode"], report["sdk"] = xcode, sdk
        report["toolchain"] = validate_toolchain(xcode, sdk, os.environ.get("DEVELOPER_DIR"), simctl, xcodebuild)
        help_text = run("runtime-help", READ_COMMANDS["runtime-help"], METADATA_TIMEOUT)
        help_text += (out / "runtime-help.stderr.log").read_text(encoding="utf-8")
        if not re.search(r"(?m)^\s*verify <identifier>\s*$", help_text):
            raise ValueError("Selected simctl does not advertise runtime verify <identifier>")
        devices = decode(run("devices-before", READ_COMMANDS["devices-before"], METADATA_TIMEOUT))
        before = decode(run("runtime-images-before", READ_COMMANDS["runtime-images-before"], METADATA_TIMEOUT))
        chosen = select_target(before, devices)
        report["selection"] = chosen
        report["runtime_inventory_before"] = before
        report["runtime_filesystem_before"] = runtime_filesystem(before, chosen["target_uuid"])
        save()
        verify_and_capture(before, chosen, report["runtime_filesystem_before"], run, report)
        report["result"] = "VERIFY_COMMAND_COMPLETED_AND_IDENTITIES_PRESERVED"
        report["original_lifecycle_may_run"] = True
    except Exception as error:
        failure = error
        report["result"] = "PREFLIGHT_FAILED"
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        report["finished_unix"] = time.time()
        report["elapsed_seconds"] = time.monotonic() - started
        failure = save_preserving_failure(save, failure, "final-result-save", report)
        if failure is not None:
            report["original_lifecycle_may_run"] = False
            report["result"] = "PREFLIGHT_FAILED"
            report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
    try:
        print(report["result"], "verify_invocations=" + str(report["verify_invocations"]),
              "product_pass=false candidate_credit=false")
    except Exception as error:
        failure = recording_failure(failure, error, "final-console-output", report)
        report["original_lifecycle_may_run"] = False
        report["result"] = "PREFLIGHT_FAILED"
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        failure = save_preserving_failure(save, failure, "console-failure-result-save", report)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
