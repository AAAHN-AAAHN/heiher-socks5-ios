#!/usr/bin/env python3
"""Fixed diagnostic only: original selected, original full, traced-copy selected."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import time
import traceback

SOURCE = "8bec30de328543f8f23b79a736385ed0e80aaa88"
TREE = "08cf0d3e49753d5de7f9f5c87f8d88549625197d"
HELPER_PARENT = "d46a235b83347bb42b9267c9041e7fea5ccf07fe"
PATCHER_PIN = (24357, "f423644f9ff9c879fec9b1318495799d40cb7aebcec82a65265f59d0b0bdeba8")
SOURCE_FILES = {
    "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift":
        (32767, "57da93313e01f5c3938f0be3b112de58afeeaf0aab5013ca9a8c20278d377465"),
    "Tests/Background/UDPEchoTransportProbe.swift":
        (7108, "f931e5c1ca829642739cece332d26ba7b043a13227fb804b586ebe6b6d3fa91a"),
    "Tests/Background/UDPEchoTransportTests.py":
        (13674, "9983165ff22ec16b3fcea0ae661f64906939bb4dd006dabae92c7086d4c6f4e6"),
}
TEST = "Tests/Background/UDPEchoTransportTests.py"
CLIENT = "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift"
PROBE = "Tests/Background/UDPEchoTransportProbe.swift"
TRACED_PINS = {
    CLIENT: SOURCE_FILES[CLIENT],
    PROBE: (12036, "27aa95d94a9df806b20e4f195f6c9419e1db3119f1e93330af9fde17d1074610"),
    TEST: (22141, "ed60adabf3a82b537bb07546693f7bd01010b4769902643874e7ec957c8455fa"),
}
TRIAL_CAP_SECONDS = 300


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def identity(path):
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise RuntimeError(f"Expected a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest(),
            "mode": f"{stat.S_IMODE(mode):04o}"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, cwd, directory, limit=30):
    """Record actual command and kill its process group on the outer deadline."""
    directory.mkdir(parents=True, exist_ok=False)
    record = {"argv": list(map(str, command)), "cwd": str(cwd),
              "started_utc": utc(), "started_monotonic_ns": time.monotonic_ns(),
              "outer_timeout_seconds": limit, "pid": None, "returncode": None,
              "timed_out": False, "launch_error": None}
    child_environment = os.environ.copy()
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN",
                "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        child_environment.pop(key, None)
    process = None
    try:
        with (directory / "stdout.log").open("xb") as stdout:
            with (directory / "stderr.log").open("xb") as stderr:
                process = subprocess.Popen(record["argv"], cwd=cwd, stdout=stdout,
                                           stderr=stderr, env=child_environment,
                                           start_new_session=True)
                record["pid"] = process.pid
                try:
                    record["returncode"] = process.wait(timeout=limit)
                except subprocess.TimeoutExpired:
                    record["timed_out"] = True
                    record["deadline_observed_utc"] = utc()
                    record["deadline_observed_monotonic_ns"] = time.monotonic_ns()
                    record["termination_signal"] = "SIGKILL"
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    reap_start = time.monotonic_ns()
                    try:
                        record["returncode"] = process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        record["reap_error"] = "Process was not reaped within 10 seconds after SIGKILL."
                    record["post_kill_reap_seconds"] = (time.monotonic_ns() - reap_start) / 1e9
    except Exception as error:
        record["launch_error"] = repr(error)
    record["finished_utc"] = utc()
    record["finished_monotonic_ns"] = time.monotonic_ns()
    record["wall_seconds"] = (record["finished_monotonic_ns"] -
                              record["started_monotonic_ns"]) / 1e9
    record["success"] = (record["pid"] is not None and record["returncode"] == 0
                         and not record["timed_out"] and record["launch_error"] is None)
    write_json(directory / "command.json", record)
    return record


def checked(command, cwd, directory, limit=30):
    result = run(command, cwd, directory, limit)
    require(result["success"], f"Required metadata command failed: {command}")
    return (directory / "stdout.log").read_text(encoding="utf-8").strip()


def source_snapshot(source, directory):
    directory.mkdir(parents=True, exist_ok=False)
    head = checked(["git", "rev-parse", "HEAD"], source, directory / "head")
    tree = checked(["git", "rev-parse", "HEAD^{tree}"], source, directory / "tree")
    status = checked(["git", "status", "--porcelain=v1", "--untracked-files=all"],
                     source, directory / "status")
    checked(["git", "diff", "--exit-code", SOURCE, "--"], source, directory / "worktree")
    checked(["git", "diff", "--cached", "--exit-code", SOURCE, "--"],
            source, directory / "index")
    files = {name: identity(source / name) for name in SOURCE_FILES}
    record = {"head": head, "tree": tree, "status_porcelain": status, "files": files}
    write_json(directory / "snapshot.json", record)
    require(head == SOURCE and tree == TREE and status == "", "Source checkout identity or clean state differs.")
    for name, (size, digest) in SOURCE_FILES.items():
        require(files[name] == {"bytes": size, "sha256": digest, "mode": "0644"},
                f"Pinned source bytes or mode differ: {name}")
    return record


def record_environment(source, output):
    directory = output / "environment"
    directory.mkdir()
    swiftc = shutil.which("swiftc")
    require(platform.system() == "Darwin" and swiftc is not None, "The diagnostic requires the canonical macOS Swift environment.")
    require(__debug__ and sys.flags.optimize == 0, "Python assertions must remain enabled.")
    commands = [
        ("sw-vers", ["sw_vers"]),
        ("uname", ["uname", "-a"]),
        ("xcodebuild", ["xcodebuild", "-version"]),
        ("iphoneos-sdk", ["xcrun", "--sdk", "iphoneos", "--show-sdk-version"]),
        ("swiftc-version", [swiftc, "--version"]),
        ("xcrun-swiftc-version", ["xcrun", "swiftc", "--version"]),
        ("xcrun-swiftc-path", ["xcrun", "--find", "swiftc"]),
        ("clang-version", ["clang", "--version"]),
        ("python-version", [sys.executable, "--version"]),
        ("formatter-version", ["clang-format-18", "--version"]),
    ]
    answers = {name: checked(command, source, directory / name, 60)
               for name, command in commands}
    require(answers["iphoneos-sdk"].startswith("27."), "The SDK is outside the canonical 27.x contract.")
    require("version 18." in answers["formatter-version"], "Canonical formatter setup differs.")
    binaries = {}
    for name, located in [("swiftc-path", swiftc),
                          ("swiftc-selected-toolchain", answers["xcrun-swiftc-path"]),
                          ("python", sys.executable), ("clang", shutil.which("clang"))]:
        require(located is not None, f"Missing executable: {name}")
        resolved = Path(located).resolve(strict=True)
        binaries[name] = {"invoked_path": located, "resolved_path": str(resolved),
                          **identity(resolved)}
    safe_keys = ["GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
                 "GITHUB_SHA", "GITHUB_REF", "GITHUB_WORKFLOW", "GITHUB_WORKFLOW_REF",
                 "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion", "DEVELOPER_DIR"]
    clock = {}
    for name in ("time", "monotonic", "perf_counter"):
        info = time.get_clock_info(name)
        clock[name] = {"implementation": info.implementation, "monotonic": info.monotonic,
                       "adjustable": info.adjustable, "resolution": info.resolution}
    write_json(directory / "identity.json", {
        "observed_utc": utc(), "safe_environment": {k: os.environ.get(k) for k in safe_keys},
        "python": {"executable": sys.executable, "optimize": sys.flags.optimize},
        "commands": answers, "binaries": binaries, "clock_information": clock,
        "clock_limit": "Python and Swift monotonic values are recorded separately; cross-process epoch equality is not assumed.",
        "runner_scope": "Same xcode-27 label and canonical formatter setup; this is a fresh job, not the original machine or its preceding build workload.",
    })
    return swiftc


def trial(source, output, name, swiftc, selected):
    directory = output / "trials" / name
    directory.mkdir(parents=True, exist_ok=False)
    product = directory / "output"
    command = [sys.executable, str(source / TEST), "--swiftc", swiftc, "--output", str(product)]
    if selected:
        command += ["--case", "wildcard6"]
    expected_compile = [swiftc, "-swift-version", "6", "-warnings-as-errors", "-O",
                        "-module-cache-path", str(product / "module-cache"),
                        str(source / CLIENT), str(source / PROBE),
                        "-o", str(product / "transport-probe")]
    write_json(directory / "compile-command-from-pinned-source.json", {
        "scope": "Deterministically derived from the unchanged original Python compile statement and these invocation arguments; not a compiler-execution receipt.",
        "argv": expected_compile,
        "original_emission_limit": "The original compile-command.json is emitted only after the entire selected case list succeeds.",
    })
    record = run(command, source, directory / "process", TRIAL_CAP_SECONDS)
    files = {}
    record["emitted_compile_command_matches"] = None
    record["result_row_count"] = None
    record["expected_result_row_count"] = 1 if selected else 25
    record["required_output_evidence_complete"] = False
    record["post_execution_errors"] = []
    try:
        for basename in ("last-case.json", "results.json", "compile-command.json", "transport-probe"):
            path = product / basename
            files[basename] = {"present": path.exists()}
            if path.exists():
                files[basename].update(identity(path))
        if files["compile-command.json"]["present"]:
            actual = json.loads((product / "compile-command.json").read_text(encoding="utf-8"))
            record["emitted_compile_command_matches"] = actual == expected_compile
        if files["results.json"]["present"]:
            rows = json.loads((product / "results.json").read_text(encoding="utf-8"))
            require(isinstance(rows, list), "The original results file is not a list.")
            record["result_row_count"] = len(rows)
        if all(item["present"] for item in files.values()):
            last = json.loads((product / "last-case.json").read_text(encoding="utf-8"))
            record["required_output_evidence_complete"] = (
                record["emitted_compile_command_matches"] is True
                and record["result_row_count"] == record["expected_result_row_count"]
                and last["mode"] == ("wildcard6" if selected else "echo")
                and last["returncode"] == 0 and last["fixture_error"] is None
                and last["fixture_thread_alive"] is False)
    except Exception:
        record["post_execution_errors"].append(traceback.format_exc())
    record["artifacts"] = files
    record["trial_name"] = name
    record["selected_case"] = "wildcard6" if selected else None
    record["test_assertions_unchanged"] = True
    record["original_probe_finish_ms"] = 650
    record["original_process_timeout_seconds"] = 6
    record["scope"] = "Diagnostic only; no candidate/canonical gate credit and no retrospective resolution of the preserved 44/55 failures."
    write_json(directory / "trial-result.json", record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    source = options.source.resolve(strict=True)
    output = options.output.resolve()
    require(output != source and source not in output.parents, "Output must be outside the exact source checkout.")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "scope": "Fixed transport diagnostic only",
        "source_sha": SOURCE, "source_tree": TREE, "expected_helper_parent": HELPER_PARENT,
        "origin_failures": [
            {"run_id": 41332855090, "attempt": 1, "job_id": 124926417360, "artifact_id": 13095118243},
            {"run_id": 41332856832, "attempt": 1, "job_id": 124929512438, "artifact_id": 13095387452},
        ],
        "planned_trials": ["01-original-wildcard6", "02-original-full", "03-traced-copy-wildcard6"],
        "started_utc": utc(), "trials": [], "errors": [],
        "source_before": None, "source_after": None,
        "historical_failure_cause_resolved": False, "canonical_gate_credit": 0,
        "product_acceptance": False, "whole_task_complete": False,
    }
    try:
        helper = Path(__file__).resolve().parent.parent
        helper_sha = checked(["git", "rev-parse", "HEAD"], helper, output / "helper-head")
        parent = checked(["git", "rev-parse", "HEAD^"], helper, output / "helper-parent")
        require(helper_sha == os.environ.get("GITHUB_SHA") and parent == HELPER_PARENT,
                "Diagnostic helper event identity or parent differs.")
        result["helper_sha"] = helper_sha
        result["source_before"] = source_snapshot(source, output / "source-before")
        for relative in SOURCE_FILES:
            target = output / "original-source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        swiftc = record_environment(source, output)
        for name, selected in (("01-original-wildcard6", True), ("02-original-full", False)):
            try:
                result["trials"].append(trial(source, output, name, swiftc, selected))
            except Exception:
                result["errors"].append({"trial": name, "error": traceback.format_exc()})
        source_snapshot(source, output / "source-before-overlay")
        overlay = output / "traced-source"
        shutil.copytree(output / "original-source", overlay, copy_function=shutil.copy2)
        instrument = output / "instrumentation"
        instrument.mkdir()
        patcher = helper / "Bootstrap" / "instrument_udp_echo_transport.py"
        require(identity(patcher) == {"bytes": PATCHER_PIN[0], "sha256": PATCHER_PIN[1],
                                      "mode": "0644"}, "The reviewed patcher bytes or mode differ.")
        patch = run([sys.executable, str(patcher), "--overlay", str(overlay),
                     "--receipt", str(instrument / "receipt.json"),
                     "--diff", str(instrument / "source.diff")],
                    helper, instrument / "patch-process", 30)
        require(patch["success"], "The traced-copy preparation failed; the third trial was not run.")
        require(identity(overlay / CLIENT) == identity(source / CLIENT),
                "The production client must be completely unchanged in the traced copy.")
        overlay_before = {name: identity(overlay / name) for name in SOURCE_FILES}
        for name, (size, digest) in TRACED_PINS.items():
            require(overlay_before[name] == {"bytes": size, "sha256": digest, "mode": "0644"},
                    f"The reviewed traced-copy bytes or mode differ: {name}")
        write_json(instrument / "recorded-artifact-identities.json", {
            "patcher": identity(patcher), "receipt": identity(instrument / "receipt.json"),
            "diff": identity(instrument / "source.diff"),
        })
        receipt = json.loads((instrument / "receipt.json").read_text(encoding="utf-8"))
        require(receipt["original_inputs"] == result["source_before"]["files"]
                and receipt["patched_files"] == overlay_before
                and receipt["insertion_count"] == 47
                and receipt["production_client_unchanged"] is True
                and all(receipt["reversal"][name]["recorded_spans_removed_match_original_bytes"] is True
                        for name in (PROBE, TEST)),
                "The instrumentation receipt does not describe the reviewed exact-copy transformation.")
        write_json(instrument / "overlay-before.json", overlay_before)
        result["trials"].append(trial(overlay, output, "03-traced-copy-wildcard6", swiftc, True))
        overlay_after = {name: identity(overlay / name) for name in SOURCE_FILES}
        write_json(instrument / "overlay-after.json", overlay_after)
        require(overlay_before == overlay_after, "The traced trial modified its source files.")
    except Exception:
        result["errors"].append({"phase": "preflight_or_overlay", "error": traceback.format_exc()})
    finally:
        try:
            result["source_after"] = source_snapshot(source, output / "source-after")
        except Exception:
            result["errors"].append({"phase": "source-after", "error": traceback.format_exc()})
        result["not_executed_trials"] = [
            name for name in result["planned_trials"]
            if name not in {row["trial_name"] for row in result["trials"]}]
        result["diagnostic_success"] = (
            not result["errors"] and not result["not_executed_trials"]
            and all(row["success"] and not row["post_execution_errors"]
                    and row["required_output_evidence_complete"]
                    for row in result["trials"]))
        result["finished_utc"] = utc()
        result["instrumentation_limit"] = (
            "Logging changes timing and may change reproduction probability. "
            "A traced-copy pass cannot establish the cause of either earlier failure.")
        write_json(output / "diagnostic-result.json", result)
    return 0 if result["diagnostic_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
