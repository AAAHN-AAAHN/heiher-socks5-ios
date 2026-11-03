#!/usr/bin/env python3
"""One conditional, exact-UUID watchOS duplicate-removal hypothesis.

This changes one disposable runner's environment, not any application gate.
The existing pinned lifecycle executes only after this preflight succeeds.
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

WATCH = "com.apple.CoreSimulator.SimRuntime.watchOS-27-0"
IOS = "com.apple.CoreSimulator.SimRuntime.iOS-27-0"
WATCH_ASSET = re.compile(r"/System/Library/AssetsV2/com_apple_MobileAsset_watchOSSimulatorRuntime/[0-9a-f]{40}\.asset/AssetData")
UUID = re.compile(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}")
IDENTITY_FIELDS = ("identifier", "runtimeIdentifier", "platformIdentifier", "version", "build",
                   "kind", "state", "path", "parentMountPath", "mountPath", "runtimeBundlePath",
                   "supportedArchitectures")
ORIGINAL_FILES = {
    "simulator_runtime_compare.py": "a855b4e2cf0481f389776a56876345ffbb43f41b744b69d853c15b17bc80de81",
    "simulator_comparison_diagnostics.py": "2674479d846b113204ba0b3c2184f81ba045c5f519c3d1d78c8c04611980e4e0",
}
TOTAL_COMMAND_BUDGET = 120
POST_DELETE_WINDOW = 20
POST_DELETE_MAX_READS = 8


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(text):
    return json.loads(text, object_pairs_hook=unique_object)


def inventory(data):
    if not isinstance(data, dict) or not data:
        raise ValueError("Runtime inventory must be a nonempty object")
    for key, row in data.items():
        if (not isinstance(key, str) or not UUID.fullmatch(key)
                or not isinstance(row, dict) or row.get("identifier") != key):
            raise ValueError("Runtime UUID key/identifier is missing, malformed or ambiguous")
    return data


def identity(row):
    missing = [key for key in IDENTITY_FIELDS if key not in row]
    if missing:
        raise ValueError("Incomplete runtime identity: " + repr(missing))
    return {key: row[key] for key in IDENTITY_FIELDS}


def ios_identities(data):
    inventory(data)
    selected = [row for row in data.values() if row.get("runtimeIdentifier") == IOS]
    if len(selected) != 1:
        raise ValueError("Expected exactly one selected iOS 27.0 runtime image")
    row = selected[0]
    if (row.get("build") != "24A434" or row.get("version") != "27.0"
            or row.get("state") != "Ready"
            or row.get("platformIdentifier") != "com.apple.platform.iphonesimulator"
            or "arm64" not in row.get("supportedArchitectures", [])):
        raise ValueError("Selected iOS image differs from the declared Ready arm64 24A434 input")
    return {key: identity(value) for key, value in data.items()
            if value.get("platformIdentifier") == "com.apple.platform.iphonesimulator"}


def select_target(data, devices):
    inventory(data)
    ios = ios_identities(data)
    watch = [row for row in data.values() if row.get("runtimeIdentifier") == WATCH]
    if len(watch) != 2:
        raise ValueError("No mutation: expected exactly two watchOS 27.0 image registrations")
    for row in watch:
        if (row.get("version") != "27.0" or row.get("build") != "24R362"
                or row.get("platformIdentifier") != "com.apple.platform.watchsimulator"
                or row.get("deletable") is not True
                or "arm64" not in row.get("supportedArchitectures", [])):
            raise ValueError("No mutation: watchOS identity/deletability is not the declared pair")
        identity(row)
    ready = [row for row in watch if row.get("state") == "Ready"]
    unusable = [row for row in watch if row.get("state") == "Unusable"]
    if len(ready) != 1 or len(unusable) != 1:
        raise ValueError("No mutation: require exactly one Ready and one Unusable registration")
    keep, target = ready[0], unusable[0]
    if (target.get("unusableErrorMessage") != "Cryptex Mount Preferred"
            or target.get("unusableSubstate") != "Cryptex Mount Preferred"):
        raise ValueError("No mutation: the Unusable reason is not exactly Cryptex Mount Preferred")
    asset = target.get("path")
    if (not isinstance(asset, str) or not WATCH_ASSET.fullmatch(asset)
            or target.get("parentMountPath") != asset
            or keep.get("path") != asset or keep.get("parentMountPath") != asset):
        raise ValueError("No mutation: exact common watchOS MobileAsset path is not established")
    if any(row.get("path") == asset and row.get("runtimeIdentifier") != WATCH
           for row in data.values()):
        raise ValueError("No mutation: the selected asset is shared with another runtime")
    device_groups = devices.get("devices") if isinstance(devices, dict) else None
    if not isinstance(device_groups, dict) or not isinstance(device_groups.get(WATCH), list):
        raise ValueError("No mutation: watchOS device state inventory is unavailable")
    if any(not isinstance(row, dict) or row.get("state") != "Shutdown"
           for row in device_groups[WATCH]):
        raise ValueError("No mutation: a watchOS device is active or has an unknown state")
    excluded = {target["identifier"], keep["identifier"]}
    return {"target": dict(target), "retained_ready_watch": dict(keep),
            "ios_before": ios, "watch_devices_before": device_groups[WATCH],
            "other_runtime_records": {key: dict(row) for key, row in data.items() if key not in excluded},
            "exact_delete_argv": ["xcrun", "simctl", "runtime", "delete", target["identifier"]]}


def canonical(value):
    """Compare complete JSON values without ignoring unknown or volatile fields."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def other_runtime_filesystem(data, chosen):
    """Preserve paths and filesystem identities of every unaffected runtime."""
    excluded = {chosen["target"]["identifier"], chosen["retained_ready_watch"]["identifier"]}
    result = {}
    for key, row in data.items():
        if key in excluded:
            continue
        paths = {}
        for field in ("path", "mountPath", "runtimeBundlePath"):
            raw = row.get(field)
            if not isinstance(raw, str) or not Path(raw).is_absolute() or not Path(raw).is_dir():
                raise ValueError("Unaffected runtime path is not an existing absolute directory: " + key + ":" + field)
            stat = Path(raw).stat()
            paths[field] = {"path": raw, "resolved_path": str(Path(raw).resolve()),
                            "device": stat.st_dev, "inode": stat.st_ino}
        result[key] = paths
    return result


def assess_after(data, chosen):
    """Return one explicit completion effect, or None while deletion is pending.

    One UUID deletion request may remove its shared watchOS asset. This is an
    allowed preparation effect only when all unrelated runtime records stay
    exactly equal and no watchOS replacement registration appears.
    """
    if ios_identities(data) != chosen["ios_before"]:
        raise ValueError("Selected/other iOS runtime identity changed after the watchOS operation")
    keep_id = chosen["retained_ready_watch"]["identifier"]
    target_id = chosen["target"]["identifier"]
    others = {key: row for key, row in data.items() if key not in {keep_id, target_id}}
    if canonical(others) != canonical(chosen["other_runtime_records"]):
        raise ValueError("Runtime outside the exact watchOS pair changed, disappeared or was re-registered")
    if keep_id in data and canonical(data[keep_id]) != canonical(chosen["retained_ready_watch"]):
        raise ValueError("The original Ready watchOS registration changed")
    watch = [row for row in data.values() if row.get("runtimeIdentifier") == WATCH]
    if target_id not in data:
        if keep_id in data and len(watch) == 1 and watch[0]["identifier"] == keep_id:
            return "unusable_registration_removed_ready_retained"
        if keep_id not in data and not watch:
            return "shared_watchos_asset_registrations_removed"
        raise ValueError("Unexpected watchOS registration after the exact deletion")
    target = data[target_id]
    for field in ("identifier", "runtimeIdentifier", "platformIdentifier", "version", "build",
                  "path", "parentMountPath", "mountPath", "runtimeBundlePath"):
        if target.get(field) != chosen["target"].get(field):
            raise ValueError("Original deletion target changed identity; no further mutation allowed")
    if target.get("state") not in ("Unusable", "Deleting"):
        raise ValueError("Original deletion target has an unexpected state")
    expected_ids = {target_id} | ({keep_id} if keep_id in data else set())
    if {row["identifier"] for row in watch} != expected_ids:
        raise ValueError("Unexpected replacement or multiple watchOS registration")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if (not __debug__ or sys.platform != "darwin" or platform.machine() != "arm64"
            or tuple(sys.version_info) != (3, 14, 9, "final", 0)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or out.exists()):
        raise SystemExit("Use the declared cached interpreter on a disposable hosted macOS job with a fresh output directory")
    out.mkdir(parents=True)
    started = time.monotonic()
    report = {"schema": 2, "started_unix": time.time(), "helper_sha": os.environ.get("GITHUB_SHA"),
              "run_id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "total_command_budget_seconds": TOTAL_COMMAND_BUDGET,
              "post_delete_completion_window_seconds": POST_DELETE_WINDOW,
              "post_delete_max_inventory_reads": POST_DELETE_MAX_READS,
              "delete_attempts": 0, "delete_invocations": 0, "commands": [], "product_pass": False, "candidate_credit": False,
              "scope": "One exact Unusable watchOS UUID may be deleted before the original owned device exists. Completion permits either that registration alone to disappear while the original Ready record remains exact, or both registrations of the same watchOS asset to disappear. All other runtime records and filesystem identities must stay equal. No other deletion request, service reset, fallback or original lifecycle retry.",
              "comparison_limits": "Diagnostic and candidate runtime both select Xcode27.0. This diagnostic uses cached CPython3.14.9; candidate runtime uses workflow python3. Producer builds use the default toolchain separately. No application gate credit."}

    def save():
        (out / "preflight-result.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(label, argv, timeout, *, check=True):
        remaining = TOTAL_COMMAND_BUDGET - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("Preflight command budget exhausted before " + label)
        timeout = min(timeout, remaining)
        row = {"label": label, "argv": argv, "requested_timeout_seconds": timeout,
               "started_unix": time.time(), "stdout_file": label + ".stdout.log",
               "stderr_file": label + ".stderr.log"}
        if argv[:4] == ["xcrun", "simctl", "runtime", "delete"]:
            if chosen is None or argv != chosen["exact_delete_argv"] or report["delete_attempts"]:
                raise ValueError("Only the one selected exact UUID deletion may be attempted")
            report["delete_attempts"] = 1
        report["commands"].append(row)
        command_start = time.monotonic()
        process = None
        error = None
        try:
            with (out / row["stdout_file"]).open("xb") as stdout, (out / row["stderr_file"]).open("xb") as stderr:
                process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
                row["pid"] = process.pid
                if argv[:4] == ["xcrun", "simctl", "runtime", "delete"]:
                    report["delete_invocations"] = 1
                try:
                    row["returncode"] = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired as caught:
                    row["timeout"] = True
                    process.kill()
                    try:
                        row["returncode"] = process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        row["reap_incomplete"] = True
                    error = caught
        except Exception as caught:
            error = caught
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                    row["returncode"] = process.wait(timeout=1)
                except Exception as cleanup_error:
                    row["cleanup_error"] = {"type": type(cleanup_error).__name__, "message": str(cleanup_error)}
        finally:
            row["finished_unix"] = time.time()
            row["elapsed_seconds"] = time.monotonic() - command_start
            if error is not None:
                row["error"] = {"type": type(error).__name__, "message": str(error)}
            save()
        if error is not None:
            raise error
        if check and row.get("returncode") != 0:
            raise RuntimeError(label + " returned " + str(row.get("returncode")))
        path = out / row["stdout_file"]
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Refusing oversized command metadata: " + label)
        return path.read_text(encoding="utf-8")

    chosen = None
    failure = None
    try:
        report["checked_out_sha"] = run("source-head", ["git", "rev-parse", "HEAD"], 10).strip()
        if report["checked_out_sha"] != report["helper_sha"]:
            raise ValueError("Checked-out source differs from the actual run head")
        report["source_files"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                  for name in ORIGINAL_FILES}
        report["preflight_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if report["source_files"] != ORIGINAL_FILES:
            raise ValueError("Original reviewed lifecycle/observer source changed")
        xcode = run("xcode-version", ["xcodebuild", "-version"], 10).strip()
        sdk = run("simulator-sdk", ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], 10).strip()
        simctl = run("simctl-path", ["xcrun", "--find", "simctl"], 10).strip()
        xcodebuild = run("xcodebuild-path", ["xcrun", "--find", "xcodebuild"], 10).strip()
        report["xcode"], report["sdk"] = xcode, sdk
        report["toolchain"] = validate_toolchain(xcode, sdk, os.environ.get("DEVELOPER_DIR"), simctl, xcodebuild)
        run("runtime-help", ["xcrun", "simctl", "help", "runtime"], 10)
        devices = decode(run("devices-before", ["xcrun", "simctl", "list", "devices", "-j"], 10))
        before = decode(run("runtime-images-before", ["xcrun", "simctl", "runtime", "list", "-j"], 10))
        chosen = select_target(before, devices)
        report["selection"] = chosen
        report["other_runtime_filesystem_before"] = other_runtime_filesystem(before, chosen)
        selected_id = next(key for key, row in before.items() if row.get("runtimeIdentifier") == IOS)
        report["selected_ios_filesystem_before"] = report["other_runtime_filesystem_before"][selected_id]
        report["delete_requested_unix"] = time.time()
        save()
        run("delete-exact-unusable-watch", chosen["exact_delete_argv"], 30)
        deadline = time.monotonic() + POST_DELETE_WINDOW
        report["post_delete_snapshots"] = []
        completed = False
        for number in range(1, POST_DELETE_MAX_READS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            label = "runtime-images-after-" + str(number).zfill(2)
            after = decode(run(label, ["xcrun", "simctl", "runtime", "list", "-j"], min(10, remaining)))
            effect = assess_after(after, chosen)
            filesystem = other_runtime_filesystem(after, chosen)
            if filesystem != report["other_runtime_filesystem_before"]:
                raise ValueError("Unaffected runtime asset/mount filesystem identity changed")
            completed = effect is not None
            report["post_delete_snapshots"].append({"label": label, "completed": completed,
                                                    "effect": effect, "all_other_runtimes_unchanged": True,
                                                    "ios_unchanged": True, "other_runtime_filesystem": filesystem})
            save()
            if completed:
                report["preflight_effect"] = effect
                break
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        if not completed:
            raise TimeoutError("One requested watchOS deletion did not complete within the bounded observation window")
        report["result"] = "PREFLIGHT_APPLIED"
        report["original_lifecycle_may_run"] = True
    except Exception as error:
        failure = error
        report["result"] = "PREFLIGHT_FAILED"
        report["original_lifecycle_may_run"] = False
        report["failure"] = {"type": type(error).__name__, "message": str(error)}
        if report["delete_invocations"]:
            try:
                text = run("runtime-images-after-failure", ["xcrun", "simctl", "runtime", "list", "-j"], 10)
                after = decode(text)
                report["after_failure_ios_unchanged"] = ios_identities(after) == chosen["ios_before"]
                filesystem = other_runtime_filesystem(after, chosen)
                report["after_failure_other_runtime_filesystem"] = filesystem
                report["after_failure_other_runtime_filesystem_unchanged"] = filesystem == report["other_runtime_filesystem_before"]
            except Exception as capture_error:
                report["after_failure_capture_error"] = {"type": type(capture_error).__name__, "message": str(capture_error)}
    finally:
        report["finished_unix"] = time.time()
        report["elapsed_seconds"] = time.monotonic() - started
        save()
    print(report["result"], "delete_invocations=" + str(report["delete_invocations"]), "product_pass=false candidate_credit=false")
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
