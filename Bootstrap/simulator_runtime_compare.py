#!/usr/bin/env python3
"""One explicitly pinned empty-Simulator lifecycle using installed Xcode 27.0.

No app install, test replacement, retry, global shutdown, service reset or
candidate credit. A different result between jobs is evidence of an
association, not by itself proof that the runtime version caused an old failure.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from simulator_comparison_diagnostics import capture_failure, observed_run

RUNTIME_PAIRS = {
    "27.0": {"build": "24A434", "device_type": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"},
}
EXPECTED_SDK = "27.0"
EXPECTED_XCODE = "Xcode 27.0\nBuild version 27A266a"
EXPECTED_DEVELOPER_DIR = "/Applications/Xcode_27.app/Contents/Developer"
LIMITS = {"create": 60, "boot": 180, "bootstatus": 120, "shutdown": 30, "delete": 30}


def select_exact(runtimes, device_types, version, build, device_identifier, sdk):
    if RUNTIME_PAIRS.get(version) != {"build": build, "device_type": device_identifier} or sdk != EXPECTED_SDK:
        raise ValueError("Comparison requires the declared runtime/build/device pair and Simulator SDK 27.0")
    identifier = "com.apple.CoreSimulator.SimRuntime.iOS-" + version.replace(".", "-")
    matches = [r for r in runtimes if r.get("identifier") == identifier]
    if len(matches) != 1:
        raise ValueError("Missing or duplicate exact runtime identifier")
    runtime = matches[0]
    if runtime.get("isAvailable") is not True or runtime.get("version") != version or runtime.get("buildversion") != build:
        raise ValueError("Runtime availability/version/build differs from the explicit comparison input")
    if runtime.get("platform") != "iOS" or "arm64" not in runtime.get("supportedArchitectures", []):
        raise ValueError("Expected available arm64 runtime")
    devices = [d for d in device_types if d.get("identifier") == device_identifier]
    if len(devices) != 1 or device_identifier not in {d.get("identifier") for d in runtime.get("supportedDeviceTypes", [])}:
        raise ValueError("Pinned device type is not supported by this runtime")
    return runtime, devices[0]


def validate_toolchain(xcode, sdk, developer_dir, simctl_path, xcodebuild_path):
    """Reject a changed installation before creating any device."""
    if developer_dir != EXPECTED_DEVELOPER_DIR:
        raise ValueError("DEVELOPER_DIR differs from the declared installed Xcode 27.0 path")
    if xcode != EXPECTED_XCODE or sdk != EXPECTED_SDK:
        raise ValueError("Actual Xcode version/build or Simulator SDK differs from the fixed diagnostic input")
    expected = Path(EXPECTED_DEVELOPER_DIR).resolve()
    resolved = {}
    for name, value in (("simctl", simctl_path), ("xcodebuild", xcodebuild_path)):
        tool = Path(value)
        if not tool.is_absolute() or tool.name != name or not tool.resolve().is_relative_to(expected):
            raise ValueError("Selected " + name + " is outside the declared Xcode developer directory")
        resolved[name] = str(tool.resolve())
    return {"developer_directory": str(expected), "resolved_tools": resolved}


def lifecycle(run, capture, runtime, device_type):
    row = {"device": None, "stage": "create", "success": False, "cleanup_errors": []}
    primary = None
    try:
        row["device"] = run(["xcrun", "simctl", "create", "Explicit Runtime Comparison " + runtime["version"],
                             device_type["identifier"], runtime["identifier"]], LIMITS["create"], "create").strip()
        if not re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", row["device"]):
            row["device"] = None
            raise ValueError("simctl create did not return one valid owned device UUID")
        for stage, extra in (("boot", []), ("bootstatus", ["-b"])):
            row["stage"] = stage
            run(["xcrun", "simctl", stage, row["device"], *extra], LIMITS[stage], stage)
        row["stage"] = "ready"
        capture("after-ready-before-cleanup", row["device"], None)
    except Exception as error:
        primary = error
        row["failure"] = {"stage": row["stage"], "type": type(error).__name__, "message": repr(error)}
        capture(row["stage"], row["device"], error)
    finally:
        if row["device"]:
            for action in ("shutdown", "delete"):
                try:
                    run(["xcrun", "simctl", action, row["device"]], LIMITS[action], action)
                except Exception as error:
                    row["cleanup_errors"].append({"action": action, "type": type(error).__name__, "message": repr(error)})
                    # Preserve shutdown failure before attempting deletion.
                    capture("cleanup-" + action, row["device"], error)
            capture("after-cleanup", row["device"], primary)
    if primary is not None:
        return row, primary
    if row["cleanup_errors"]:
        return row, RuntimeError("Original cleanup requirement failed: " + repr(row["cleanup_errors"]))
    row["stage"] = "deleted"
    row["success"] = True
    return row, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime-version", required=True, choices=sorted(RUNTIME_PAIRS))
    parser.add_argument("--runtime-build", required=True)
    parser.add_argument("--device-type", required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not __debug__ or sys.platform != "darwin" or out.exists():
        raise SystemExit("Use assertions, macOS and a fresh output directory")
    out.mkdir(parents=True)
    calls = []
    report = {
        "schema": 1, "started_unix": time.time(), "requested_runtime": args.runtime_version,
        "requested_build": args.runtime_build, "expected_sdk": EXPECTED_SDK,
        "device_type_identifier": args.device_type, "limits_seconds": LIMITS,
        "expected_xcode": EXPECTED_XCODE, "expected_developer_dir": EXPECTED_DEVELOPER_DIR,
        "developer_dir_environment": os.environ.get("DEVELOPER_DIR"),
        "helper_sha": os.environ.get("GITHUB_SHA"), "repository": os.environ.get("GITHUB_REPOSITORY"),
        "run_id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner_name": os.environ.get("RUNNER_NAME"), "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"), "image_version": os.environ.get("ImageVersion"),
        "runner_environment": os.environ.get("RUNNER_ENVIRONMENT"), "image_os": os.environ.get("ImageOS"),
        "commands": calls, "planned_devices": 1, "product_pass": False, "candidate_credit": False,
        "scope": "One owned empty device in one job. Actual runner/host identity and boot time are recorded; separate jobs alone do not prove fresh or distinct hosts. No application/UI assertion executes. No retry, host reset, runtime fallback or timeout change.",
        "comparison_limits": "This one job selects installed Xcode 27.0 while retaining iOS 27.0 build 24A434 and iPhone 16 from the existing Xcode 27.1 control (run 41519414260 attempt 1). Host allocation, timing and service state can differ; the runner label does not pin an immutable image. This tests an alternative supported toolchain configuration and does not isolate a sole causal variable or prove an app gate. SDK equality does not imply runtime device support.",
        "preparation_limits": "The before snapshot adds read-only runtime image inventory and host-log work. Those queries may initialize or warm CoreSimulator services; the original UI harness does not perform identical pre-boot work. This probe does not reproduce the original workload or prove its failure cause.",
        "declared_pairs": RUNTIME_PAIRS,
        "capture_scope": "Folders failure-before, failure-after-ready-before-cleanup and failure-after-cleanup are read-only snapshots, not failure assertions. Diagnostics have a separate 20-second command-time budget; optional diagnostic timeouts never change the lifecycle result.",
    }

    def run(command, timeout, label):
        number = len(calls) + 1
        row = {"label": label, "command": list(map(str, command)), "timeout_seconds": timeout,
               "stdout": f"{number:02d}-{label}.stdout.log", "stderr": f"{number:02d}-{label}.stderr.log",
               "started_unix": time.time()}
        calls.append(row)
        started = time.monotonic()
        try:
            with (out / row["stdout"]).open("wb") as stdout, (out / row["stderr"]).open("wb") as stderr:
                result = observed_run(command, out=out, timeout=timeout, stdout=stdout, stderr=stderr, check=True)
            row["returncode"] = result.returncode
            return (out / row["stdout"]).read_text(encoding="utf-8")
        except Exception as error:
            row["failure"] = {"type": type(error).__name__, "message": repr(error)}
            row["returncode"] = getattr(error, "returncode", None)
            raise
        finally:
            row["elapsed_seconds"] = time.monotonic() - started
            row["finished_unix"] = time.time()
            with (out / "commands.jsonl").open("a") as stream:
                stream.write(json.dumps(row) + "\n")

    def capture(phase, device, error):
        capture_failure(out, phase, device, error)

    failure = None
    try:
        report["checked_out_sha"] = run(["git", "rev-parse", "HEAD"], 30, "source-head").strip()
        if report["checked_out_sha"] != report["helper_sha"]:
            raise ValueError("Checked-out helper differs from GitHub run source")
        report["source_files"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), Path(__file__).with_name("simulator_comparison_diagnostics.py"))}
        report["xcode"] = run(["xcodebuild", "-version"], 30, "xcode-version").strip()
        report["sdk"] = run(["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], 30, "simulator-sdk").strip()
        report["simctl_path"] = run(["xcrun", "--find", "simctl"], 30, "simctl-path").strip()
        report["xcodebuild_path"] = run(["xcrun", "--find", "xcodebuild"], 30, "xcodebuild-path").strip()
        report["toolchain_validation"] = validate_toolchain(report["xcode"], report["sdk"],
                                                            report["developer_dir_environment"],
                                                            report["simctl_path"], report["xcodebuild_path"])
        report["macos"] = run(["sw_vers"], 30, "macos-version").strip()
        report["host_name"] = run(["hostname"], 30, "host-name").strip()
        report["hardware"] = run(["sysctl", "hw.ncpu", "hw.memsize", "hw.machine", "kern.boottime"], 30, "hardware").strip()
        runtimes = json.loads(run(["xcrun", "simctl", "list", "runtimes", "-j"], 60, "runtimes"))["runtimes"]
        types = json.loads(run(["xcrun", "simctl", "list", "devicetypes", "-j"], 60, "device-types"))["devicetypes"]
        runtime, device_type = select_exact(runtimes, types, args.runtime_version, args.runtime_build, args.device_type, report["sdk"])
        report["selected_runtime"], report["selected_device_type"] = runtime, device_type
        capture("before", None, None)
        row, failure = lifecycle(run, capture, runtime, device_type)
        report["lifecycle"] = row
    except Exception as error:
        failure = error
        capture("selection", None, error)
    report["result"] = "DIAGNOSTIC_PASS" if failure is None else "DIAGNOSTIC_FAIL"
    if failure is not None:
        report["original_failure"] = {"type": type(failure).__name__, "message": repr(failure)}
    report["finished_unix"] = time.time()
    (out / "diagnostic-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["result"], "runtime", args.runtime_version, "product_pass=false", "candidate_credit=false")
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
