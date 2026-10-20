#!/usr/bin/env python3
"""Bounded original/fixed SettingsStore regression, with real filesystem failures.

Only SwiftUI/provider API imports are substituted on Linux, using the repository's
existing host boundaries. The production store bodies are otherwise exact.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import uuid

CASES = {
    "write-failure": "ROLLBACK_FAILURE_NOT_MARKED_UNCERTAIN",
    "cancelled": "ROLLBACK_FAILURE_NOT_MARKED_UNCERTAIN",
    "superseded": "ROLLBACK_FAILURE_NOT_MARKED_UNCERTAIN",
    "failed-load-write": "FAILED_LOAD_ADOPTED_REJECTED_IMPORT",
    "failed-load-cancelled": "FAILED_LOAD_ADOPTED_REJECTED_IMPORT",
    "failed-load-superseded": "FAILED_LOAD_ADOPTED_REJECTED_IMPORT",
    "ordinary-failure": None,
    "cleanup-failure": None,
}
REVISION_CASES = {
    "revision-write": "TERMINAL_ROLLBACK_DURABILITY_NOT_INVALIDATED",
    "revision-cancelled": "REVISION_ERROR_REPLACED_BY_ROLLBACK",
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--original-commit")
    parser.add_argument("--fixed", required=True, type=Path)
    parser.add_argument("--fixture", type=Path, default=Path(__file__).with_name("RollbackFailureTests.swift"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--swiftc", default="swiftc")
    args = parser.parse_args(argv)
    root, fixed, fixture, out = (p.resolve() for p in (args.root, args.fixed, args.fixture, args.out))
    out.mkdir(parents=True, exist_ok=False)
    production = args.original.resolve() if args.original else root / "Socks5/Settings/SettingsStore.swift"
    common = [root / "Socks5/Server/ServerSettings.swift", root / "Socks5/Settings/AppSettings.swift",
              root / "Tests/Settings/HostUI.swift", root / "Tests/Settings/HostProvider.swift", fixture]
    result = {"schema": 1, "scope": "actual original/fixed store; controlled write-boundary fault; not physical iOS",
              "platform": sys.platform, "original_commit": args.original_commit,
              "sources": [], "commands": [], "passed": False}
    for path in [production, fixed, *common, Path(__file__).resolve()]:
        data = path.read_bytes()
        result["sources"].append({"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    def persist():
        (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    def no_core():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    def run(label, argv, marker=None, compile=False, behavior=False):
        runtime_report = None
        case_directory = None
        child_cleanup = None
        parent_cleanup = None
        parent_defaults_cleanup = None
        defaults_suite = None
        cleanup_command = None
        env = None
        temporary = None
        if behavior:
            temporary = tempfile.TemporaryDirectory(prefix="rollback-case-")
            case_directory = temporary.name
            env = os.environ.copy()
            env["TMPDIR"] = case_directory + os.sep
            env["TMP"] = case_directory
            env["TEMP"] = case_directory
            defaults_suite = "Settings-rollback-CI-" + str(uuid.uuid4())
            env["ROLLBACK_TEST_DEFAULTS_SUITE"] = defaults_suite
        try:
            completed = subprocess.run(list(map(str, argv)), cwd=root, capture_output=True,
                                       text=True, timeout=120 if compile else 30, preexec_fn=no_core, env=env)
            code, output = completed.returncode, completed.stdout + completed.stderr
        except subprocess.TimeoutExpired as error:
            code, output = 124, str(error)
        finally:
            if temporary is not None:
                cleanup_argv = [str(argv[0]), "--cleanup-suite", defaults_suite]
                try:
                    cleaned = subprocess.run(cleanup_argv, cwd=root, capture_output=True, text=True,
                                             timeout=10, preexec_fn=no_core, env=env)
                    cleanup_code = cleaned.returncode
                    cleanup_output = cleaned.stdout + cleaned.stderr
                except subprocess.TimeoutExpired as error:
                    cleanup_code, cleanup_output = 124, str(error)
                (out / (label + "-defaults-cleanup.log")).write_text(cleanup_output)
                cleanup_reports = []
                for line in cleanup_output.splitlines():
                    try:
                        item = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(item, dict) and item.get("kind") == "rollback-reassessment-cleanup":
                        cleanup_reports.append(item)
                parent_defaults_cleanup = (cleanup_code == 0 and len(cleanup_reports) == 1 and
                                           cleanup_reports[0].get("suite") == defaults_suite and
                                           cleanup_reports[0].get("defaults_removed") is True)
                cleanup_command = {"argv": cleanup_argv, "returncode": cleanup_code,
                                   "passed": parent_defaults_cleanup}
                temporary.cleanup()
                parent_cleanup = not Path(case_directory).exists()
        (out / (label + ".log")).write_text(output)
        if behavior:
            reports = []
            for line in output.splitlines():
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(item, dict) and item.get("kind") == "rollback-reassessment-result":
                    reports.append(item)
            if len(reports) == 1:
                runtime_report = reports[0]
                child_cleanup = (runtime_report.get("cleanup", {}).get("directory_removed") is True and
                                 runtime_report.get("cleanup", {}).get("defaults_removed") is True and
                                 runtime_report.get("cleanup", {}).get("defaults_suite") == defaults_suite)
            expected_code = 0 if marker is None else 74
            expected_status = "passed" if marker is None else "failed"
            expected_failures = [] if marker is None else [marker]
            passed = (code == expected_code and runtime_report is not None and
                      runtime_report.get("status") == expected_status and
                      runtime_report.get("failures") == expected_failures and
                      runtime_report.get("unexpected_error") is None and
                      child_cleanup is True and parent_cleanup is True and parent_defaults_cleanup is True)
        else:
            passed = code == 0
        result["commands"].append({"label": label, "argv": list(map(str, argv)), "returncode": code,
                                   "expected_marker": marker, "compile": compile, "passed": passed,
                                   "runtime_report": runtime_report, "child_cleanup_verified": child_cleanup,
                                   "parent_temporary_cleanup_verified": parent_cleanup,
                                   "parent_defaults_cleanup": cleanup_command})
        persist()
        print(("PASS " if passed else "FAIL ") + label, flush=True)
        if not passed:
            print(output[-16000:], file=sys.stderr, flush=True)
            raise RuntimeError("rollback reassessment failed: " + label)

    run("swift-version", [args.swiftc, "--version"])
    with tempfile.TemporaryDirectory(prefix="rollback-reassessment-") as tmp:
        folder = Path(tmp)
        for name, path in [("original", production), ("fixed", fixed)]:
            source = path.read_text()
            if sys.platform != "darwin":
                assert source.count("import SwiftUI\n") == 1
                source = source.replace("import SwiftUI\n", "import Foundation\n", 1)
            for boundary, cases in [("normal", CASES), ("revision", REVISION_CASES)]:
                body = source
                if boundary == "revision":
                    old = "private var revision: UInt64 = 0"
                    new = "private var revision: UInt64 = UInt64.max - 1"
                    assert body.count(old) == 1
                    body = body.replace(old, new, 1)
                    result.setdefault("source_translations", []).append({
                        "variant": name + "-revision", "exact_replacement_count": 1,
                        "before": old, "after": new, "physical_lifetime_claim": False})
                compiled = folder / (name + "-" + boundary + ".swift")
                compiled.write_text(body)
                result.setdefault("compiled_source_sha256", {})[name + "-" + boundary] = hashlib.sha256(body.encode()).hexdigest()
                for mode in ["-Onone", "-O"]:
                    executable = folder / (name + "-" + boundary + mode)
                    label = name + "-" + boundary + mode
                    run(label + "-compile", [args.swiftc, mode, "-swift-version", "5",
                        "-strict-concurrency=complete", "-warnings-as-errors", "-parse-as-library",
                        *common[:2], compiled, *common[2:], "-o", executable], compile=True)
                    for case, marker in cases.items():
                        run(label + "-" + case, [executable, case], marker if name == "original" else None, behavior=True)
    result["passed"] = True
    result["counts"] = {"compiler_identity": 1, "successful_compiles": 8,
                         "expected_runtime_failures": 16, "positive_executions": 24,
                         "separate_parent_defaults_cleanup_commands": 40}
    result["physical_device_executed"] = False
    persist()


def repository_check():
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "Build/features.json").read_text())
    baseline = "11ffc688cc4a1b02db63ae9d7e062ae88f0568ab"
    path = "Socks5/Settings/SettingsStore.swift"
    data = subprocess.check_output(["git", "-C", str(root), "show", baseline + ":" + path], timeout=30)
    expected = "3884dc86adaf5269990f19da5756808ae7e11f065caa6cb7bbdd72b8865ab7c9"
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("Historical SettingsStore baseline mismatch")
    with tempfile.TemporaryDirectory(prefix="rollback-baseline-") as tmp:
        original = Path(tmp) / "SettingsStore-original.swift"
        original.write_bytes(data)
        main(["--root", str(root), "--original", str(original), "--original-commit", baseline,
              "--fixed", str(root / path),
              "--out", str(root / "artifacts" / config["name"] / "rollback-storage" / uuid.uuid4().hex)])


if __name__ == "__main__":
    if len(sys.argv) == 1:
        repository_check()
    else:
        main()
