#!/usr/bin/env python3
"""Terminal evidence after failed original preparation; never a runtime gate.

No live simctl queries: path names come from preserved preparation inventory.
The only subprocesses are two separate /sbin/mount observations bracketing the
path reads. These are not preparation-before/after snapshots, an atomic view,
or proof that a host daemon has settled. A stat tuple can be reused after eject.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time


INVENTORIES = tuple("runtime-images-" + phase + ".stdout.log"
                    for phase in ("before", "after-add", "after-verify"))
PATH_FIELDS = ("path", "parentMountPath", "mountPath", "runtimeBundlePath")
ROOTS = ("/Library/Developer/CoreSimulator/", "/System/Library/AssetsV2/",
         "/private/var/run/com.apple.security.cryptexd/mnt/")
FIXED_PATHS = tuple(path for name, build in (("watchOS", "24R362"), ("tvOS", "24J360"))
                    for prefix in ("/Library/Developer/CoreSimulator/Volumes/",
                                   "/private/var/run/com.apple.security.cryptexd/mnt/")
                    for path in (prefix + name + "_" + build,
                                 prefix + name + "_" + build + "/Library/Developer/CoreSimulator/Profiles/Runtimes/" + name + " 27.0.simruntime"))


def now():
    return datetime.now(timezone.utc).isoformat()


def error_record(error):
    return {"type": type(error).__name__, "message": str(error), "errno": getattr(error, "errno", None)}


def descriptor(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key in saved inventory: " + key)
        result[key] = value
    return result


def mount_observation(output, label):
    row = {"label": label, "argv": ["/sbin/mount"], "started_utc": now(),
           "requested_timeout_seconds": 5, "invocations": 0}
    started = time.monotonic()
    stdout, stderr = output / (label + ".stdout.log"), output / (label + ".stderr.log")
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            row["invocations"] = 1
            # Timeout handling belongs only to this /sbin/mount child.
            completed = subprocess.run(row["argv"], stdout=out, stderr=err, timeout=5)
            row["returncode"] = completed.returncode
    except Exception as error:
        row["error"] = error_record(error)
        row["timed_out"] = isinstance(error, subprocess.TimeoutExpired)
    row.update(finished_utc=now(), elapsed_seconds=time.monotonic() - started)
    row["files"] = [descriptor(path) for path in (stdout, stderr) if path.is_file()]
    row["mount_rows"], row["unparsed_lines"] = [], []
    if stdout.is_file():
        try:
            lines = stdout.read_bytes().decode("utf-8", errors="strict").splitlines()
            for number, line in enumerate(lines, 1):
                match = re.fullmatch(r"(.+) on (/.*) \(([^\n]*)\)", line)
                if match:
                    row["mount_rows"].append({"line": number, "source": match[1],
                                              "mount_path": match[2], "options": match[3]})
                elif line:
                    row["unparsed_lines"].append({"line": number, "raw": line})
        except UnicodeError as error:
            row["parse_error"] = error_record(error)
    row["table_usable_for_literal_lookup"] = (row.get("returncode") == 0
        and "error" not in row and "parse_error" not in row and not row["unparsed_lines"]
        and bool(row["mount_rows"]))
    return row


def stat_fields(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid, "gid": info.st_gid, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
            "is_directory": stat.S_ISDIR(info.st_mode), "is_regular": stat.S_ISREG(info.st_mode),
            "is_symlink": stat.S_ISLNK(info.st_mode)}


def observation(operation):
    row = {"started_utc": now()}
    try:
        row.update(capture="observed", value=operation())
    except OSError as error:
        row.update(capture="unavailable", error=error_record(error))
    row["finished_utc"] = now()
    return row


def path_observation(value, references):
    path = Path(value)
    row = {"path": value, "references": references, "started_utc": now()}
    row["lstat"] = observation(lambda: stat_fields(path.lstat()))
    row["stat"] = observation(lambda: stat_fields(path.stat()))
    row["resolve_strict"] = observation(lambda: str(path.resolve(strict=True)))
    row["os_path_ismount"] = observation(lambda: os.path.ismount(value))
    # Preserve permission errors and links rather than treating either as absent.
    row["ancestor_lstat"] = [{"path": str(parent), **observation(lambda p=parent: stat_fields(p.lstat()))}
                             for parent in reversed(path.parents)]
    row["finished_utc"] = now()
    return row


def collect_saved_inventory(source, output):
    staged = source / "artifacts/integrated/runtime-preparation/staged"
    inputs, paths, issues = [], {path: [{"fixed_alias": True}] for path in FIXED_PATHS}, []
    for name in INVENTORIES:
        path = staged / name
        row = {"original_path": str(path), "started_utc": now()}
        try:
            if path.resolve(strict=True) != path or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("Saved inventory is not an exact regular path")
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Saved inventory exceeds 8 MiB observation limit")
            raw = path.read_bytes()
            target = output / name
            with target.open("xb") as stream:
                stream.write(raw)
            row["copy"] = descriptor(target)
            data = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(data, dict) or len(data) > 256:
                raise ValueError("Saved runtime inventory is not a bounded object")
            row["registration_count"] = len(data)
            for uuid, record in data.items():
                if not isinstance(record, dict):
                    raise ValueError("Saved runtime record is not an object")
                for field in PATH_FIELDS:
                    value = record.get(field)
                    if value is None:
                        continue
                    if (not isinstance(value, str) or len(value) > 4096 or "\0" in value
                            or not value.startswith(ROOTS) or ".." in Path(value).parts):
                        issues.append({"inventory": name, "uuid": uuid, "field": field,
                                       "reason": "Path outside observation scope", "value": value})
                        continue
                    paths.setdefault(value, []).append({"inventory": name, "uuid": uuid,
                        "field": field, "saved_state": record.get("state"),
                        "runtime_identifier": record.get("runtimeIdentifier")})
        except Exception as error:
            row["error"] = error_record(error)
        row["finished_utc"] = now()
        inputs.append(row)
    return inputs, paths, issues


def capture_terminal_mounts(source, output):
    """Capture once after preparation failure. Returned data cannot grant credit."""
    source, output = Path(source), Path(output)
    output.mkdir(exist_ok=False)
    report = {"schema": "failed-preparation-terminal-mount-observation-v1", "started_utc": now(),
        "purpose": "Read-only terminal evidence; original preparation has already failed.",
        "observer_source": descriptor(Path(__file__)),
        "context": {key: os.environ.get(key) for key in
                    ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")},
        "observer_pid": os.getpid(), "uid": os.getuid(), "euid": os.geteuid(),
        "formal_candidate_credit": False, "publication_credit": False, "runtime_acceptance": False,
        "new_simctl_queries": 0, "runtime_mutation_commands": 0,
        "limitations": ["Saved inventory is historical, not a new registration observation.",
            "Mount samples bracket terminal filesystem reads, not original preparation.",
            "All observations are non-atomic; equal samples do not prove settlement.",
            "Device/inode numbers may be reused after unmount; they do not prove image identity.",
            "ismount false alone cannot establish absence or resolve permission failures.",
            "Additional read syscalls and elapsed time may affect daemon scheduling."]}
    first = mount_observation(output, "terminal-mount-before-path-reads")
    report["saved_inventory"], paths, report["path_scope_issues"] = collect_saved_inventory(source, output)
    report["paths"] = [path_observation(path, refs) for path, refs in sorted(paths.items())]
    last = mount_observation(output, "terminal-mount-after-path-reads")
    report["mount_samples"] = [first, last]
    for row in report["paths"]:
        row["literal_mount_table_matches"] = [{"label": sample["label"],
            "table_usable_for_literal_lookup": sample["table_usable_for_literal_lookup"],
            "exact": [entry for entry in sample["mount_rows"] if entry["mount_path"] == row["path"]]}
            for sample in (first, last)]
    report["finished_utc"] = now()
    path = output / "observation.json"
    write_json(path, report)
    return descriptor(path)
