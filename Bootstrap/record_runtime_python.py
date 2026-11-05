#!/usr/bin/env python3
"""Record the real host interpreter before/after exact dependency provisioning.

This does not install anything, write a tool-cache marker, or replace the frozen
runtime host checks. Installation may change framework files and python3's
target even when setup-python does not export environment variables.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def require(value, message):
    if not value:
        raise RuntimeError(message)


def executable_info(value):
    path = Path(value)
    result = {"path": str(path), "exists": path.exists(), "executable": os.access(path, os.X_OK)}
    if path.exists():
        target = path.resolve(strict=True)
        info = target.stat()
        result.update(resolved=str(target), bytes=info.st_size, device=info.st_dev,
                      inode=info.st_ino, mtime_ns=info.st_mtime_ns)
        if target.is_file():
            result["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.source_root
    require(root.is_absolute() and root.resolve(strict=True) == root, "Exact source root required")
    require(sys.platform == "darwin" and platform.machine() == "arm64"
            and os.getuid() == os.geteuid() and os.getuid() > 0, "Hosted own-UID Darwin arm64 required")
    require(os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("GITHUB_REPOSITORY") == "AAAHN-AAAHN/heiher-socks5-ios",
            "Actual repository workflow context required")
    cache = Path(os.environ["RUNNER_TOOL_CACHE"])
    require(str(cache) == "/Users/runner/hostedtoolcache",
            "setup-python macOS cache must equal the original runtime cache")
    entry = cache / "Python/3.14.9/arm64"
    executable = entry / "bin/python3.14"
    marker = Path(str(entry) + ".complete")
    output = root / "artifacts/runtime-python-provisioning"
    output.mkdir(parents=True, exist_ok=True)
    context_keys = ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")
    context = {key: os.environ.get(key) for key in context_keys}
    report = {
        "phase": args.phase, "observed_utc": datetime.now(timezone.utc).isoformat(), "context": context,
        "host": {"system": platform.system(), "macos": platform.mac_ver()[0], "machine": platform.machine(),
                 "uid": os.getuid(), "euid": os.geteuid()},
        "environment": {key: os.environ.get(key) for key in
                        ("PATH", "RUNNER_TOOL_CACHE", "AGENT_TOOLSDIRECTORY", "DEVELOPER_DIR")},
        "recording_interpreter": {"version": list(sys.version_info), **executable_info(sys.executable)},
        "python3_resolution": executable_info(shutil.which("python3") or "/nonexistent-python3"),
        "required_interpreter": executable_info(executable),
        "required_complete_marker": {"path": str(marker), "is_file": marker.is_file()},
        "tool_cache_or_host_files_written_by_recorder": False,
        "host_environment_unchanged_claimed": False,
        "formal_runtime_credit": False,
    }
    if args.phase == "after":
        before_path = output / "before.json"
        before_raw = before_path.read_bytes()
        before = json.loads(before_raw)
        require(before["context"] == context and before["phase"] == "before", "Before record context differs")
        report["before_record"] = {"path": str(before_path), "bytes": len(before_raw),
                                   "sha256": hashlib.sha256(before_raw).hexdigest()}
        report["python3_resolution_changed"] = before["python3_resolution"] != report["python3_resolution"]
        report["environment_changed"] = before["environment"] != report["environment"]
    probe = {"invoked": False}
    if report["required_interpreter"]["executable"]:
        command = [str(executable), "-B", "-c", "import json,sys,platform,pathlib,sysconfig; print(json.dumps({'version':list(sys.version_info),'implementation':sys.implementation.name,'machine':platform.machine(),'executable':str(pathlib.Path(sys.executable).resolve()),'gil_disabled':sysconfig.get_config_var('Py_GIL_DISABLED')}))"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
            probe = {"invoked": True, "argv": command, "returncode": result.returncode,
                     "stdout": result.stdout, "stderr": result.stderr}
            if result.returncode == 0:
                probe["identity"] = json.loads(result.stdout)
        except Exception as exc:
            probe = {"invoked": True, "argv": command, "error": {"type": type(exc).__name__, "message": str(exc)}}
    report["required_interpreter_probe"] = probe
    identity = probe.get("identity", {})
    ready = (marker.is_file() and report["required_interpreter"]["executable"]
             and probe.get("returncode") == 0 and identity.get("version") == [3, 14, 9, "final", 0]
             and identity.get("implementation") == "cpython" and identity.get("machine") == "arm64"
             and identity.get("gil_disabled") in (None, 0)
             and identity.get("executable") == report["required_interpreter"].get("resolved"))
    report["exact_required_cache_ready"] = ready
    with (output / (args.phase + ".json")).open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    if args.phase == "after":
        require(ready, "Exact completed CPython3.14.9 arm64 cache is still unavailable")


if __name__ == "__main__":
    main()
