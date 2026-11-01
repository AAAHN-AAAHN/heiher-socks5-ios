#!/usr/bin/env python3
"""One instrumented temporary-app run of the unchanged original four UI cases.

This is diagnosis only. It never updates a release source, retries a test,
changes an assertion/deadline, or contributes canonical acceptance.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import traceback

SOURCE = "8bec30de328543f8f23b79a736385ed0e80aaa88"
TREE = "08cf0d3e49753d5de7f9f5c87f8d88549625197d"
HELPER_PARENT = "8d6bcde33ed916af160bd3c716828578d7a20067"
PRODUCER = {"repository": "AAAHN-AAAHN/heiher-socks5-ios", "run_id": "41338124364",
            "attempt": "1", "job": "verify-macos"}
ARTIFACT_ID = "13097822204"
ARCHIVE_SHA = "383a250492fb252af100e882a84365443456730104f8e97c9b0b9b65f7d5a8db"
SUBSYSTEM = "hev.Socks5.StateBoundaryDiagnostic"
SAFE_ENV = ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA",
            "GITHUB_REF", "GITHUB_JOB", "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def identity(path):
    mode = path.lstat().st_mode
    require(stat.S_ISREG(mode), "Expected regular file: " + str(path))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest(),
            "mode": f"{stat.S_IMODE(mode):04o}"}


def git(folder, *arguments):
    return subprocess.check_output(["git", "-C", str(folder), *arguments],
                                   text=True, timeout=30).strip()


def snapshot(source):
    head, tree = git(source, "rev-parse", "HEAD"), git(source, "rev-parse", "HEAD^{tree}")
    status = git(source, "status", "--porcelain=v1", "--untracked-files=all")
    git(source, "diff", "--exit-code", SOURCE, "--")
    git(source, "diff", "--cached", "--exit-code", SOURCE, "--")
    require(head == SOURCE and tree == TREE and not status, "Exact source checkout changed")
    files = {name: identity(source / name)
             for name in git(source, "ls-tree", "-r", "--name-only", "HEAD").splitlines()}
    return {"head": head, "tree": tree, "status": status, "files": files}


def command(args, folder, timeout=60):
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    record = {"argv": list(map(str, args)), "started_utc": utc(), "timeout_seconds": timeout,
              "returncode": None, "exception": None}
    try:
        with (folder / "stdout.log").open("xb") as stdout, (folder / "stderr.log").open("xb") as stderr:
            completed = subprocess.run(record["argv"], stdout=stdout, stderr=stderr, timeout=timeout)
        record["returncode"] = completed.returncode
    except Exception:
        record["exception"] = traceback.format_exc()
    record["elapsed_seconds"] = time.monotonic() - started
    record["finished_utc"] = utc()
    write_json(folder / "command.json", record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    source = options.source.resolve(strict=True)
    archive = options.archive.resolve(strict=True)
    out = options.output.resolve()
    require(source not in out.parents and out != source, "Output must be outside exact source")
    out.mkdir(parents=True, exist_ok=False)
    result = {"schema": 1, "scope": "One instrumented temporary app; unchanged original UI4 diagnosis only",
              "started_utc": utc(), "actual_environment": {k: os.environ.get(k) for k in SAFE_ENV},
              "original_failure": {"run_id": 41338124364, "attempt": 1, "job_id": 124955337528,
                                   "artifact_id": 13098193895},
              "canonical_gate_credit": 0, "product_acceptance": False, "whole_task_complete": False,
              "ui_invocations": 0, "patched_build_invocations": 0, "original_ui_exception": None,
              "preparation_exception": None, "collection_errors": [], "source_after": None}
    ui = handoff = None
    stream_process = stream_file = stream_errors = None
    stream_record = None
    collection_done = False
    try:
        require(__debug__ and sys.flags.optimize == 0 and sys.platform == "darwin",
                "Requires assertions and the Apple toolchain")
        helper = Path(__file__).resolve().parents[1]
        helper_head = git(helper, "rev-parse", "HEAD")
        require(helper_head == os.environ.get("GITHUB_SHA")
                and git(helper, "rev-parse", "HEAD^") == HELPER_PARENT,
                "Unexpected diagnostic helper event or parent")
        result["helper_sha"] = helper_head
        result["source_before"] = snapshot(source)
        write_json(out / "source-before.json", result["source_before"])
        patcher = Path(__file__).with_name("instrument_ui_state_boundaries.py")
        result["recipes"] = {"driver": identity(Path(__file__)), "patcher": identity(patcher)}
        shutil.copy2(archive, out / "original-review-input.tar.gz")
        require(identity(archive)["sha256"] == ARCHIVE_SHA, "Wrong producer archive bytes")
        sys.path.insert(0, str(source / "Build"))
        import review_handoff as handoff
        import release_source
        import ui_review as ui
        manifest, payloads = handoff.read_archive(archive, ARCHIVE_SHA)
        require(manifest["producer"] == PRODUCER, "Wrong original producer identity")
        handoff.check_payloads(manifest, payloads, {"commit": SOURCE, "tree": TREE})
        require(not release_source.PRODUCT.exists(), "Existing product destination")
        require(not release_source.OUT.exists(), "Existing phase destination")
        # read_archive/check_payloads validate every path, mode, file hash and full source inventory.
        for name, (raw, mode) in payloads.items():
            destination = (release_source.PRODUCT / name[len("product/"):] if name.startswith("product/")
                           else release_source.OUT / name[len("phases/"):])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(raw)
            destination.chmod(mode)
            require(handoff.read_file(destination) == (raw, mode), "Restored payload differs")
        release_source.check_product()
        write_json(out / "diagnostic-input-receipt.json", {
            "scope": "Cross-run diagnostic input, not the canonical same-run consumer receipt",
            "actual_consumer": result["actual_environment"], "original_producer": PRODUCER,
            "download_requested_artifact_id": ARTIFACT_ID, "archive": identity(archive),
            "manifest": manifest, "original_product_check_passed": True})
        for name, args in (("xcodebuild", ["xcodebuild", "-version"]),
                           ("sdk", ["xcrun", "--sdk", "iphoneos", "--show-sdk-version"]),
                           ("swiftc", ["xcrun", "swiftc", "--version"]), ("sw-vers", ["sw_vers"])):
            record = command(args, out / "environment" / name)
            require(record["returncode"] == 0 and record["exception"] is None, "Environment command failed")
        original_run = ui.run

        def collect(identifier):
            nonlocal collection_done, stream_process, stream_file, stream_errors
            if collection_done:
                return
            collection_done = True
            # These observations happen after the original UI command and its assertions finish.
            history = command(["xcrun", "simctl", "spawn", identifier, "log", "show",
                               "--style", "json", "--last", "30m", "--predicate",
                               'subsystem == "' + SUBSYSTEM + '"'], out / "oslog-history", 60)
            result["history_collection"] = history
            if stream_process is not None:
                stream_record["poll_before_stop"] = stream_process.poll()
                if stream_process.poll() is None:
                    stream_process.terminate()
                try:
                    stream_record["returncode"] = stream_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stream_process.kill()
                    stream_record["killed_after_10_seconds"] = True
                    stream_record["returncode"] = stream_process.wait(timeout=10)
                stream_record["finished_utc"] = utc()
                stream_file.close()
                stream_errors.close()
                write_json(out / "oslog-live" / "process.json", stream_record)
                stream_process = None
            lookup = command(["xcrun", "simctl", "get_app_container", identifier,
                              "hev.Socks5", "data"], out / "settings-container", 60)
            if lookup["returncode"] == 0 and lookup["exception"] is None:
                container = Path((out / "settings-container" / "stdout.log").read_text().strip())
                path = container / "Library/Application Support/Socks5/settings.json"
                if path.is_file() and not path.is_symlink():
                    shutil.copy2(path, out / "observed-final-settings.json")
                    result["observed_final_settings"] = identity(out / "observed-final-settings.json")
                else:
                    result["observed_final_settings"] = {"present": False}

        def diagnostic_run(args, log, timeout=180, cwd=ui.ROOT, timing=False):
            nonlocal stream_process, stream_file, stream_errors, stream_record
            argv = list(map(str, args))
            if argv[:2] == ["xcodebuild", "build-for-testing"]:
                require(result["patched_build_invocations"] == 0, "Unexpected repeated UI build")
                result["patched_build_invocations"] += 1
                app = ui.WORK / "application"
                receipt = out / "instrumentation" / "receipt.json"
                patch = command([sys.executable, str(patcher), "--application", str(app),
                                 "--receipt", str(receipt), "--diff", str(out / "instrumentation" / "source.diff")],
                                out / "instrumentation" / "patch-process", 60)
                require(patch["returncode"] == 0 and patch["exception"] is None, "Temporary-app instrumentation failed")
                # Preserve exactly what the original builder will compile, independently of source.zip.
                for name in ("Socks5/AppRoot.swift", "Socks5/Settings/SettingsStore.swift",
                             "Socks5/BackgroundKeepAlive/PeriodicUDPEchoModel.swift",
                             "Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift",
                             "StatisticsUITests.swift", "Socks5.xcodeproj/project.pbxproj",
                             "Socks5.xcodeproj/xcshareddata/xcschemes/StatisticsUIAudit.xcscheme"):
                    target = out / "compiled-temporary-source" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(app / name, target)
                environment = json.loads((ui.OUT / "environment.json").read_text())
                identifier = environment["udid"]
                live_dir = out / "oslog-live"
                live_dir.mkdir()
                stream_file = (live_dir / "stdout.log").open("xb")
                stream_errors = (live_dir / "stderr.log").open("xb")
                live_args = ["xcrun", "simctl", "spawn", identifier, "log", "stream", "--style", "ndjson",
                             "--level", "debug", "--predicate", 'subsystem == "' + SUBSYSTEM + '"']
                stream_record = {"argv": live_args, "started_utc": utc(),
                                 "scope": "Passive diagnostic capture; no readiness or UI condition changed"}
                stream_process = subprocess.Popen(live_args, stdout=stream_file, stderr=stream_errors)
                stream_record["pid"] = stream_process.pid
            if argv[:2] == ["xcodebuild", "test-without-building"]:
                result["ui_invocations"] += 1
                require(result["ui_invocations"] == 1, "No diagnostic test retry is allowed")
            if argv[:3] == ["xcrun", "simctl", "shutdown"]:
                try:
                    collect(argv[3])
                except Exception:
                    result["collection_errors"].append(traceback.format_exc())
            return original_run(args, log, timeout=timeout, cwd=cwd, timing=timing)

        ui.run = diagnostic_run
        try:
            ui.main()
        except Exception:
            result["original_ui_exception"] = traceback.format_exc()
        result["original_ui_completed_without_exception"] = result["original_ui_exception"] is None
        release_source.check_product()
    except Exception:
        result["preparation_exception"] = traceback.format_exc()
    finally:
        if stream_process is not None:
            try:
                stream_process.terminate()
                try:
                    stream_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stream_process.kill()
                    stream_process.wait(timeout=10)
                if stream_record is not None:
                    stream_record.update({"fallback_cleanup": True, "returncode": stream_process.returncode,
                                          "finished_utc": utc()})
                    if not (out / "oslog-live" / "process.json").exists():
                        write_json(out / "oslog-live" / "process.json", stream_record)
            except Exception:
                result["collection_errors"].append(traceback.format_exc())
        for stream in (stream_file, stream_errors):
            if stream is not None and not stream.closed:
                stream.close()
        try:
            result["source_after"] = snapshot(source)
            write_json(out / "source-after.json", result["source_after"])
            require(result["source_after"] == result.get("source_before"), "Source snapshot changed")
        except Exception:
            result["collection_errors"].append(traceback.format_exc())
        if ui is not None and ui.OUT.parent.exists():
            try:
                shutil.copytree(ui.OUT.parent, out / "actual-artifacts", copy_function=shutil.copy2)
            except Exception:
                result["collection_errors"].append(traceback.format_exc())
        result["finished_utc"] = utc()
        result["limits"] = ["Instrumentation can affect timing and reproduction probability.",
                            "Missing OSLog events are not proof that code did not execute.",
                            "A diagnostic pass does not resolve the historical failure cause or satisfy a canonical gate.",
                            "Original UI assertions, four cases, 900-second build/test limits and 10/5-second audio conditions are unchanged."]
        result["requires_independent_trace_read"] = True
        write_json(out / "diagnostic-result.json", result)
    return 0 if (result["ui_invocations"] == 1 and result["preparation_exception"] is None
                 and result["original_ui_exception"] is None and not result["collection_errors"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
