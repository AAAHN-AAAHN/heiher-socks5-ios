#!/usr/bin/env python3
"""Source-owned bounded preconditioning; invoked only by the hash-pinned common.

No CLI, original preparation, retirement or consumer is launched by this module.
Collector/policy ancestry and exact preservation are recorded by the draft builder.
Budgets bound waits and check completed OS calls; they do not forcibly interrupt syscalls.
"""
from __future__ import annotations
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import types


EPOCHS = tuple(range(0, 121, 15))
TOTAL_SECONDS = 150.0
COMMAND_SECONDS = 10.0
MOUNT = ("/sbin/mount",)
RUNTIMES = ("/usr/bin/xcrun", "simctl", "runtime", "list", "-j")
DEVICES = ("/usr/bin/xcrun", "simctl", "list", "devices", "-j")
ALLOWED = (MOUNT, RUNTIMES, DEVICES)
PATH_FIELDS = ("path", "parentMountPath", "mountPath", "runtimeBundlePath")
ROOTS = ("/Library/Developer/CoreSimulator/", "/System/Library/AssetsV2/",
         "/private/var/run/com.apple.security.cryptexd/mnt/")
UUID = re.compile(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}")
HELP = ("/usr/bin/xcrun", "simctl", "help", "runtime")
SCAN = ("/usr/bin/xcrun", "simctl", "runtime", "scan-and-mount")
WATCH = "com.apple.CoreSimulator.SimRuntime.watchOS-27-0"
TVOS = "com.apple.CoreSimulator.SimRuntime.tvOS-27-0"
TVOS_OLD = "54D35026-7325-4069-BF3A-FDFEA26D5885"
WATCH_OLD = {"4E2A8325-62E2-427F-A198-FFEE1E5EF15A", "61FE15D4-6286-4FC9-B531-8FFEAAD0E8D8"}
VOLUMES = "/Library/Developer/CoreSimulator/Volumes/"
CRYPTEX = "/private/var/run/com.apple.security.cryptexd/mnt/"
WATCH_ASSET = "/System/Library/AssetsV2/com_apple_MobileAsset_watchOSSimulatorRuntime/3f39f470a745ea5cc62fc1967054b0dcf8fb0875.asset/AssetData"
TVOS_ASSET = "/System/Library/AssetsV2/com_apple_MobileAsset_appleTVOSSimulatorRuntime/f6a3a9321156c52c0d245f50953d9867b2b139ab.asset/AssetData"
UNUSABLE = {"unusableErrorMessage": "Cryptex Mount Preferred", "unusableSubstate": "Cryptex Mount Preferred",
            "unusableErrorDetail": 'Error Domain=SimDiskImageErrorDomain Code=7 "Cryptex Mount Preferred" UserInfo={NSLocalizedDescription=Cryptex Mount Preferred, unusableErrorDetail=}'}
PURE_LABELS = ("original_select_target_on_final_metadata", "original_watch_records_on_final_metadata",
               "original_require_same_filesystem_for_all_protected_nonwatch_records")

def require(value, message):
    if not value:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def error_record(error):
    return {"type": type(error).__name__, "message": str(error), "errno": getattr(error, "errno", None)}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("Nonfinite JSON number: " + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def descriptor(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "Regular nonlinked evidence required: " + str(path))
    raw = path.read_bytes()
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(all(getattr(before, k) == getattr(after, k) for k in fields), "Evidence changed while read")
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def write_new(path, value):
    raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    require(path.read_bytes() == raw, "Written diagnostic bytes changed")
    return descriptor(path)


class Budget:
    def __init__(self, started, clock=time.monotonic, sleep=time.sleep):
        self.started, self.deadline, self.clock, self.sleep = started, started + TOTAL_SECONDS, clock, sleep

    def remaining(self):
        return self.deadline - self.clock()

    def check(self, stage):
        require(self.remaining() > 0, "Shared 150-second collection budget exhausted: " + stage)

    def wait_epoch(self, offset):
        require(offset in EPOCHS, "Unplanned observation epoch")
        self.check("before epoch " + str(offset))
        delay = self.started + offset - self.clock()
        if delay > 0:
            self.sleep(delay)
        self.check("after epoch wait")
        # Do not collapse a missed epoch into a later scheduled one.
        require(self.clock() < self.started + offset + 15,
                "Missed fixed epoch; collection cannot relabel a later sample")


class QueryFailure(RuntimeError):
    pass


class Queries:
    def __init__(self, output, budget, report, popen=subprocess.Popen):
        self.output, self.budget, self.report, self.popen = output, budget, report, popen

    def run(self, epoch, label, argv):
        require(tuple(argv) in ALLOWED, "Unapproved observation command")
        require(tuple(argv) != DEVICES or epoch in (0, 120), "Device query outside the two fixed endpoints")
        self.budget.check(label)
        row = {"epoch": epoch, "label": label, "argv": list(argv), "launches": 0,
               "started_utc": now(), "started_monotonic": self.budget.clock(),
               "returncode": None, "timed_out": False, "owned_child_signals": []}
        self.report["commands"].append(row)
        child, deadline = None, None
        out_path, err_path = (self.output / (label + "." + kind + ".log") for kind in ("stdout", "stderr"))
        failure = None
        try:
            cap = min(COMMAND_SECONDS, self.budget.remaining())
            require(cap > 0.1, "Insufficient shared budget to launch metadata child")
            deadline = self.budget.clock() + cap
            reserve = min(1.0, cap / 4)
            row.update(command_budget_seconds=cap, command_deadline_monotonic=deadline,
                       wait_timeout_seconds=cap - reserve, cleanup_reserve_seconds=reserve)
            with out_path.open("xb") as out, err_path.open("xb") as err:
                self.budget.check("before metadata spawn")
                require(self.budget.clock() < deadline, "Metadata spawn budget expired during file creation")
                child = self.popen(list(argv), stdin=subprocess.DEVNULL, stdout=out, stderr=err)
                row.update(launches=1, pid=child.pid, launch_returned_utc=now())
                try:
                    child.wait(timeout=max(0.001, deadline - self.budget.clock() - reserve))
                except subprocess.TimeoutExpired as error:
                    row["timed_out"] = True
                    row["timeout_error"] = error_record(error)
                    raise QueryFailure("Metadata query timed out; no retry or later epoch is allowed")
                row["returncode"] = child.returncode
                require(type(child.returncode) is int and child.returncode == 0, "Metadata child returned nonzero")
                require(self.budget.clock() <= deadline, "Metadata child exceeded its declared command budget")
        except BaseException as error:
            failure = error
            row["error"] = error_record(error)
        finally:
            if child is not None:
                # Timeout, failed wait, or recording interruption can leave our
                # direct child unreaped. Never signal a reaped/reused PID or group.
                if child.returncode is None:
                    try:
                        if child.poll() is None:
                            event = {"pid": child.pid, "signal": "SIGKILL", "utc": now(), "returned": False}
                            row["owned_child_signals"].append(event)
                            child.kill()
                            event["returned"] = True
                        left = min(deadline, self.budget.deadline) - self.budget.clock()
                        if child.returncode is None and left > 0:
                            child.wait(timeout=left)
                        if child.returncode is None:
                            child.poll()
                        require(child.returncode is not None, "Owned metadata child could not be reaped within remaining budget")
                    except BaseException as error:
                        row["cleanup_error"] = error_record(error)
                        failure = failure or error
                row["returncode"] = child.returncode
                row["direct_child_reaped"] = child.returncode is not None
            row.update(finished_utc=now(), finished_monotonic=self.budget.clock())
            row["elapsed_seconds"] = row["finished_monotonic"] - row["started_monotonic"]
            row["files"] = []
            for path in (out_path, err_path):
                try:
                    row["files"].append(descriptor(path))
                except Exception as error:
                    row.setdefault("recording_errors", []).append(error_record(error))
                    failure = failure or error
        if failure is not None:
            raise QueryFailure(label + ": " + str(failure)) from failure
        self.budget.check("metadata readback " + label)
        require(out_path.stat().st_size <= 8 * 1024 * 1024, "Metadata stdout exceeds the explicit 8 MiB parsing bound")
        return out_path.read_bytes(), row


def mount_table(raw):
    rows = []
    for number, line in enumerate(raw.decode("utf-8", errors="strict").splitlines(), 1):
        if not line:
            continue
        match = re.fullmatch(r"(.+) on (/.*) \(([^\n]*)\)", line)
        require(match is not None, "Unparsed mount row " + str(number))
        rows.append({"line": number, "source": match[1], "mount_path": match[2], "options": match[3]})
    require(rows, "Empty mount table")
    return rows


def runtime_inventory(raw):
    data = decode(raw)
    require(isinstance(data, dict) and len(data) <= 256, "Runtime inventory is not a bounded object")
    for key, row in data.items():
        require(isinstance(key, str) and UUID.fullmatch(key) and isinstance(row, dict)
                and row.get("identifier") == key, "Runtime UUID key/identity is invalid")
    return data


def devices_inventory(raw):
    data = decode(raw)
    require(isinstance(data, dict) and isinstance(data.get("devices"), dict), "Device inventory has no groups")
    require(all(isinstance(k, str) and isinstance(v, list) and all(isinstance(x, dict) for x in v)
                for k, v in data["devices"].items()), "Invalid device group or row")
    return data


def add_paths(paths, data, epoch):
    fields = []
    for key, runtime in data.items():
        for field in PATH_FIELDS:
            value = runtime.get(field)
            ref = {"epoch": epoch, "uuid": key, "field": field, "state": runtime.get("state"),
                   "runtime_identifier": runtime.get("runtimeIdentifier"), "value": value,
                   "field_present": field in runtime}
            fields.append(ref)
            if value is None:
                continue
            require(isinstance(value, str) and len(value) <= 4096 and "\0" not in value,
                    "Invalid runtime path value; raw inventory is preserved")
            path = Path(value)
            require(value.startswith(ROOTS) and path.is_absolute() and ".." not in path.parts
                    and str(path) == value, "Runtime path outside the explicit read-only scope")
            paths.setdefault(value, []).append(ref)
    require(len(paths) <= 2048, "Cumulative path union exceeds the explicit observation bound")
    return fields


def fs_operation(operation, budget):
    budget.check("before filesystem observation")
    result = {"started_utc": now(), "started_monotonic": budget.clock()}
    try:
        result.update(capture="observed", value=operation())
    except OSError as error:
        # ENOENT/permission errors remain evidence, never successful filesystem identity.
        result.update(capture="unavailable", error=error_record(error))
    result.update(finished_utc=now(), finished_monotonic=budget.clock())
    result["budget_exceeded_after_syscall"] = budget.remaining() <= 0
    return result


def observe_paths(paths, budget, legacy, rows):
    for value, references in sorted(paths.items()):
        budget.check("path union")
        path = Path(value)
        row = {"path": value, "references": list(references), "started_utc": now()}
        rows.append(row)
        row["lstat"] = fs_operation(lambda: legacy.stat_fields(path.lstat()), budget)
        row["stat"] = fs_operation(lambda: legacy.stat_fields(path.stat()), budget)
        row["resolve_strict"] = fs_operation(lambda: str(path.resolve(strict=True)), budget)
        row["os_path_ismount"] = fs_operation(lambda: os.path.ismount(value), budget)
        row["ancestor_lstat"] = []
        for parent in reversed(path.parents):
            row["ancestor_lstat"].append({"path": str(parent), **fs_operation(lambda p=parent: legacy.stat_fields(p.lstat()), budget)})
        row["finished_utc"] = now()
    budget.check("after all filesystem observations")


def collect_window(report, output, budget, queries, legacy, path_reader=observe_paths):
    paths = {}
    for name, build in (("iOS", "24A434"), ("watchOS", "24R362"), ("tvOS", "24J360")):
        for prefix in ("/Library/Developer/CoreSimulator/Volumes/", "/private/var/run/com.apple.security.cryptexd/mnt/"):
            mount = prefix + name + "_" + build
            for value in (mount, mount + "/Library/Developer/CoreSimulator/Profiles/Runtimes/" + name + " 27.0.simruntime"):
                paths[value] = [{"fixed_alias": True}]
    for offset in EPOCHS:
        budget.wait_epoch(offset)
        epoch = {"offset_seconds": offset, "scheduled_monotonic": budget.started + offset,
                 "started_utc": now(), "started_monotonic": budget.clock(), "paths": [], "complete": False}
        epoch["start_lateness_seconds"] = epoch["started_monotonic"] - epoch["scheduled_monotonic"]
        report["epochs"].append(epoch)
        prefix = f"epoch-{offset:03d}"
        raw, command = queries.run(offset, prefix + "-mount-before", MOUNT)
        epoch["mount_before"] = {"command_label": command["label"], "rows": mount_table(raw)}
        raw, command = queries.run(offset, prefix + "-runtime-list", RUNTIMES)
        epoch["runtime_inventory"] = runtime_inventory(raw)
        epoch["runtime_command_label"] = command["label"]
        if offset in (0, 120):
            raw, command = queries.run(offset, prefix + "-devices-list", DEVICES)
            epoch["devices_inventory"] = devices_inventory(raw)
            epoch["devices_command_label"] = command["label"]
        epoch["all_runtime_path_fields"] = add_paths(paths, epoch["runtime_inventory"], offset)
        epoch["cumulative_path_count"] = len(paths)
        path_reader(paths, budget, legacy, epoch["paths"])
        raw, command = queries.run(offset, prefix + "-mount-after", MOUNT)
        epoch["mount_after"] = {"command_label": command["label"], "rows": mount_table(raw)}
        for row in epoch["paths"]:
            row["literal_mount_matches"] = {side: [r for r in epoch[side]["rows"] if r["mount_path"] == row["path"]]
                                             for side in ("mount_before", "mount_after")}
        epoch["mount_tables_equal"] = epoch["mount_before"]["rows"] == epoch["mount_after"]["rows"]
        epoch["atomic_snapshot_claimed"] = False
        epoch.update(complete=True, finished_utc=now(), finished_monotonic=budget.clock())
        budget.check("before epoch persistence")
        report["epoch_files"].append(write_new(output / (prefix + ".json"), epoch))
        budget.check("after epoch persistence")
    require(len(report["epochs"]) == 9 and all(r["complete"] for r in report["epochs"]), "Incomplete fixed window")


def pure_subset(raw, epochs, expected_common_sha256):
    """Saved-data-only projection; never original preparation acceptance."""
    require(sha(raw) == expected_common_sha256, "Actual tracked common source changed")
    tree = ast.parse(raw)
    names = ("inventory", "identity", "ios_identities", "canonical", "select_target", "watch_records", "require_same_filesystem")
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    require(len(functions) == len(names), "Exact original pure functions unavailable")
    values = {"json": json, "UUID": UUID}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("IOS", "WATCH", "WATCH_ASSET", "IDENTITY_FIELDS", "PATH_FIELDS"):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    exec(compile(ast.Module(body=functions, type_ignores=[]), "original-common-pure-subset", "exec"), values)
    result = {"scope": "Saved final metadata and last-two-epoch subset only; not original stage-before or full preparation",
              "original_common_sha256": sha(raw), "formal_acceptance": False, "original_preparation_executed": False,
              "tests": [], "function_source_sha256": {n.name: sha(ast.get_source_segment(raw.decode(), n).encode()) for n in functions}}
    def assess(label, call):
        row = {"label": label}
        try:
            row.update(result="MET_SUBSET_ONLY", returned=call())
        except Exception as error:
            row.update(result="INCOMPATIBLE_WITH_SUBSET", error=error_record(error))
        result["tests"].append(row)
    final = epochs[-1]
    assess("original_select_target_on_final_metadata", lambda: values["select_target"](final["runtime_inventory"], final["devices_inventory"]))
    assess("original_watch_records_on_final_metadata", lambda: values["watch_records"](final["runtime_inventory"]))
    def projection(epoch):
        by_path = {r["path"]: r for r in epoch["paths"]}
        data = {}
        for key, runtime in epoch["runtime_inventory"].items():
            data[key] = {}
            for field in PATH_FIELDS:
                path = runtime.get(field)
                row = {"value": path}
                if path is None:
                    row["capture"] = "field_absent"
                else:
                    observed = by_path[path]
                    info, resolved = observed["stat"], observed["resolve_strict"]
                    if info["capture"] == resolved["capture"] == "observed":
                        row.update(capture="observed", resolved_path=resolved["value"],
                                   **{k: info["value"][k] for k in ("device", "inode", "mode", "uid", "gid", "is_directory", "is_regular")})
                    else:
                        row.update(capture="unavailable", stat_observation=info, resolve_observation=resolved)
                data[key][field] = row
        return data
    before = epochs[-2]
    a, b = before["runtime_inventory"], final["runtime_inventory"]
    # Protect every non-watch UUID, including Unusable tvOS and missing paths.
    keys = sorted(key for key, row in a.items() if row.get("runtimeIdentifier") != values["WATCH"])
    result["protected_nonwatch_UUIDs"] = sorted(keys)
    result["all_UUIDs_added"] = sorted(set(b) - set(a))
    result["all_UUIDs_removed"] = sorted(set(a) - set(b))
    def protected():
        require(set(a) == set(b), "Runtime UUID inventory changed in the last two fixed epochs")
        for key in keys:
            require(values["canonical"](a[key]) == values["canonical"](b[key]), "Protected non-watch raw record changed: " + key)
        values["require_same_filesystem"](projection(before), projection(final), keys)
        return {"all_protected_fields_observed_and_unchanged": True, "epoch_pair_seconds": [105, 120]}
    assess("original_require_same_filesystem_for_all_protected_nonwatch_records", protected)
    result["overall"] = "INCOMPATIBLE_WITH_SUBSET" if any(r["result"] != "MET_SUBSET_ONLY" for r in result["tests"]) else "MET_SUBSET_ONLY_NO_ACCEPTANCE"
    result["verify_argv_returned_by_select_target_is_metadata_only_and_was_not_executed"] = True
    return result

def stat_fields(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid, "gid": info.st_gid, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
            "is_directory": stat.S_ISDIR(info.st_mode), "is_regular": stat.S_ISREG(info.st_mode),
            "is_symlink": stat.S_ISLNK(info.st_mode)}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def recheck_files(observer, report, budget=None):
    for row in report["bound_files"]:
        if budget is not None:
            budget.check("unchanged source and helper files")
        actual = observer.descriptor(Path(row["path"]))
        require(all(actual[k] == row[k] for k in ("path", "bytes", "sha256")),
                "Bound source or helper changed: " + row["relative_path"])


def seeded_path_reader(observer, phase_report, seed):
    """Keep every baseline path after registration removal, within the same budget."""
    first = True
    def read(paths, budget, legacy, rows):
        nonlocal first
        if first:
            for value, references in seed.items():
                paths.setdefault(value, []).extend({"source_phase": "baseline", "baseline_reference": ref}
                                                   for ref in references)
            first = False
        require(len(paths) <= 2048, "Cross-phase cumulative paths exceed original bound")
        phase_report["epochs"][-1]["cumulative_path_count"] = len(paths)
        phase_report["epochs"][-1]["baseline_union_retained"] = True
        observer.observe_paths(paths, budget, legacy, rows)
    return read


def collect_phase(observer, source, output, report, legacy, phase, budget, seed=None):
    directory = output / phase
    directory.mkdir(exist_ok=False)
    summary = report["phases"][phase]
    row = {"schema": "source-runtime-preconditioning-window-v1", "phase": phase,
           "result": "COLLECTION_IN_PROGRESS_NO_ACCEPTANCE", "context": report["context"],
           "collector_entered_utc": observer.now(), "collector_entered_monotonic": budget.clock(),
           "budget_started_monotonic": budget.started,
           "deadline_monotonic": budget.deadline, "total_budget_seconds": observer.TOTAL_SECONDS,
           "planned_epoch_seconds": list(observer.EPOCHS), "commands": [], "epochs": [], "epoch_files": [],
           "errors": [], "collection_complete": False, "formal_candidate_credit": False,
           "runtime_acceptance": False, "phase_owned_runtime_mutations": 0,
           "source": report["source"], "helper": report["helper"], "bound_files": report["bound_files"],
           "baseline_union_seed_path_count": len(seed or {}),
           "completion_requires_separate_actual_outer_exit_zero_and_no_failure_marker": True}
    summary.update(status="COLLECTING", output=str(directory))
    failure = None
    try:
        queries = observer.Queries(directory, budget, row)
        reader = observer.observe_paths if seed is None else seeded_path_reader(observer, row, seed)
        observer.collect_window(row, directory, budget, queries, legacy, path_reader=reader)
        budget.check("unchanged saved predicate subset")
        row["original_pure_subset"] = observer.pure_subset((source / report["common_source_relative_path"]).read_bytes(), row["epochs"])
        recheck_files(observer, report, budget)
        budget.check("before phase record")
        row.update(result="FIXED_WINDOW_COLLECTED_NO_ACCEPTANCE", collection_complete=True)
    except BaseException as error:
        failure = error
        row["errors"].append(observer.error_record(error))
        row.update(result="COLLECTION_FAILED_NO_ACCEPTANCE", collection_complete=False)
    finally:
        row.update(finished_utc=observer.now(), finished_monotonic=budget.clock())
        row["elapsed_seconds"] = row["finished_monotonic"] - budget.started
        if budget.remaining() <= 0:
            error = RuntimeError("Fixed phase exceeded the original shared 150-second budget")
            row["errors"].append(observer.error_record(error))
            failure = failure or error
            row.update(result="COLLECTION_FAILED_NO_ACCEPTANCE", collection_complete=False)
        try:
            summary["record"] = observer.write_new(directory / "observation.json", row)
            if budget.remaining() <= 0:
                error = RuntimeError("Final phase write/readback crossed its shared deadline")
                observer.write_new(directory / "final-write-budget-failure.json",
                                   {"phase": phase, "result": "COLLECTION_FAILED_NO_ACCEPTANCE",
                                    "error": observer.error_record(error), "observation_record_must_not_be_treated_as_success": True})
                failure = failure or error
        except BaseException as error:
            summary.setdefault("recording_errors", []).append(observer.error_record(error))
            failure = failure or error
        summary.update(status="COLLECTED_NO_ACCEPTANCE" if failure is None else "COLLECTION_FAILED",
                       epochs=len(row["epochs"]), commands=len(row["commands"]),
                       completed_epochs=sum(e["complete"] for e in row["epochs"]),
                       actual_elapsed_seconds_including_record=budget.clock() - budget.started)
    if failure is not None:
        raise failure
    return row


def observation_value(row):
    return {key: row.get(key) for key in ("capture", "value", "error")}


def observed_directory(row):
    for name in ("lstat", "stat"):
        require(row[name]["capture"] == "observed" and row[name]["value"]["is_directory"] is True
                and row[name]["value"]["is_symlink"] is False, "Unknown or non-directory runtime path: " + row["path"])
    require(row["resolve_strict"]["capture"] == "observed"
            and row["resolve_strict"]["value"] == row["path"], "Unknown runtime path alias: " + row["path"])


def no_mount(row):
    return (row["os_path_ismount"]["capture"] == "observed" and row["os_path_ismount"]["value"] is False
            and all(row["literal_mount_matches"][side] == [] for side in ("mount_before", "mount_after")))


def exact_enoent(row):
    return (all(row[name]["capture"] == "unavailable" and row[name]["error"].get("errno") == 2
                for name in ("lstat", "stat", "resolve_strict")) and no_mount(row))


def healthy_mount(mount, bundle):
    observed_directory(mount)
    observed_directory(bundle)
    before, after = (mount["literal_mount_matches"][side] for side in ("mount_before", "mount_after"))
    require(mount["os_path_ismount"]["capture"] == "observed" and mount["os_path_ismount"]["value"] is True
            and len(before) == 1 and before == after
            and mount["stat"]["value"]["device"] == bundle["stat"]["value"]["device"],
            "Ready runtime is not an observed bracketed mount: " + mount["path"])


def expected_special(row, kind):
    asset, build, platform_name, size = ((WATCH_ASSET, "24R362", "watchsimulator", 3814435665)
                                       if kind == "watchOS" else (TVOS_ASSET, "24J360", "appletvsimulator", 3697822545))
    suffix = "/Library/Developer/CoreSimulator/Profiles/Runtimes/" + kind + " 27.0.simruntime"
    mounts = (VOLUMES + kind + "_" + build, CRYPTEX + kind + "_" + build)
    require(row.get("mountPath") in mounts, "Unsupported special runtime mount alias")
    expected = {"identifier": row["identifier"], "runtimeIdentifier": "com.apple.CoreSimulator.SimRuntime." + kind + "-27-0",
                "platformIdentifier": "com.apple.platform." + platform_name, "version": "27.0", "build": build,
                "path": asset, "parentMountPath": asset, "kind": "Patchable Cryptex Disk Image",
                "supportedArchitectures": ["arm64"], "signatureState": "Unknown", "sizeBytes": size,
                "deletable": True, "state": row["state"], "mountPath": row["mountPath"],
                "runtimeBundlePath": row["mountPath"] + suffix}
    if row["state"] == "Unusable":
        expected.update(UNUSABLE)
    require(canonical(row) == canonical(expected), "Special runtime differs from full observed identity, including unknown fields")
    return expected


def classify_baseline(window):
    """Saved observations only. This predicate authorizes one diagnostic, not preparation."""
    require(window["collection_complete"] is True and len(window["epochs"]) == 9,
            "A completed fixed window is required before classification")
    previous, final = window["epochs"][-2:]
    require(previous["offset_seconds"] == 105 and final["offset_seconds"] == 120
            and canonical(previous["runtime_inventory"]) == canonical(final["runtime_inventory"]),
            "Full raw inventory changed at the final fixed pair; no scan or wait reset")
    tests = {r["label"]: r for r in window["original_pure_subset"]["tests"]}
    target = tests["original_select_target_on_final_metadata"]
    watch = tests["original_watch_records_on_final_metadata"]
    require(target["result"] == watch["result"] == "MET_SUBSET_ONLY", "Original target or Watch classification failed")
    for epoch in (window["epochs"][0], final):
        groups = epoch["devices_inventory"]["devices"]
        require(groups and all(r.get("state") == "Shutdown" for group in groups.values() for r in group),
                "Every observed device group must be Shutdown for a global scan")
    before_paths = {r["path"]: r for r in previous["paths"]}
    after_paths = {r["path"]: r for r in final["paths"]}
    data = final["runtime_inventory"]
    special_watch = watch["returned"]
    require(special_watch == {key: r for key, r in data.items() if r.get("runtimeIdentifier") == WATCH}
            and sum(r["state"] == "Ready" for r in special_watch.values()) == 1,
            "Expected exactly one Ready Watch in the observed exact asset")
    issues, inactive = [], []
    for key, runtime in sorted(data.items()):
        require(runtime.get("state") in ("Ready", "Unusable"), "Unsupported runtime state before scan: " + key)
        paths = {field: after_paths[runtime[field]] for field in ("path", "parentMountPath", "mountPath", "runtimeBundlePath")}
        for observed in paths.values():
            earlier = before_paths[observed["path"]]
            require(all(observation_value(earlier[name]) == observation_value(observed[name])
                        for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")),
                    "Filesystem observation changed at the final fixed pair")
        for field in ("path", "parentMountPath"):
            observed_directory(paths[field])
        mount, bundle = paths["mountPath"], paths["runtimeBundlePath"]
        if key == TVOS_OLD:
            expected_special(runtime, "tvOS")
            require(runtime["mountPath"] == VOLUMES + "tvOS_24J360", "Old tvOS alias changed")
            if runtime["state"] == "Unusable":
                require(exact_enoent(mount) and exact_enoent(bundle), "Old tvOS is not the exact observed ENOENT condition")
                issues.append({"kind": "exact_old_tvos_unusable_enoent", "uuid": key,
                               "mount_path": mount["path"], "bundle_path": bundle["path"]})
                continue
        if runtime.get("runtimeIdentifier") == TVOS and key != TVOS_OLD and runtime["state"] == "Ready":
            expected_special(runtime, "tvOS")
            require(runtime["mountPath"] == CRYPTEX + "tvOS_24J360"
                    and sum(r.get("runtimeIdentifier") == TVOS and r.get("state") == "Ready"
                            for r in data.values()) == 1,
                    "Expected one new Ready tvOS at the exact canonical Cryptex alias")
            if exact_enoent(bundle):
                if not exact_enoent(mount):
                    observed_directory(mount)
                    require(no_mount(mount), "Missing tvOS bundle is not the known unmounted-directory condition")
                issues.append({"kind": "exact_ready_tvos_bundle_enoent", "uuid": key,
                               "mount_path": mount["path"], "bundle_path": bundle["path"]})
                continue
        if key in special_watch:
            expected_special(runtime, "watchOS")
            if runtime["state"] == "Unusable":
                require(key in WATCH_OLD and runtime["mountPath"] == VOLUMES + "watchOS_24R362"
                        and exact_enoent(mount) and exact_enoent(bundle), "Unsupported inactive Watch registration")
                inactive.append(key)
                continue
            if exact_enoent(bundle):
                if not exact_enoent(mount):
                    observed_directory(mount)
                    require(no_mount(mount), "Missing Watch bundle is not the known unmounted-directory condition")
                issues.append({"kind": "exact_ready_watch_bundle_enoent", "uuid": key,
                               "mount_path": mount["path"], "bundle_path": bundle["path"]})
                continue
        require(runtime["state"] == "Ready", "Unrecognized inactive runtime before global scan: " + key)
        healthy_mount(mount, bundle)
    return {"result": "SUPPORTED_KNOWN_ISSUE_SCAN_ELIGIBLE" if issues else "UNNEEDED_NOT_RUN",
            "issues": issues, "recognized_inactive_watch_UUIDs": inactive,
            "selected_ios_UUID": target["returned"]["target_uuid"], "fixed_epoch_pair": [105, 120],
            "continuous_stability_claimed": False, "preparation_acceptance": False}


def run_command(observer, output, report, label, *, clock=time.monotonic, popen=subprocess.Popen):
    """Only these two fixed argv are possible; cleanup belongs to the direct child."""
    require(label in ("runtime-help", "scan-and-mount"), "Unapproved control command")
    require(not any(r["label"] == label for r in report["control_commands"]), "Control command cannot be retried")
    argv, cap = (HELP, 10.0) if label == "runtime-help" else (SCAN, 120.0)
    started = clock()
    deadline, reserve = started + cap, 1.0
    row = {"label": label, "argv": list(argv), "started_utc": observer.now(), "started_monotonic": started,
           "command_budget_seconds": cap, "deadline_monotonic": deadline, "cleanup_reserve_seconds": reserve,
           "launch_attempts": 0, "launches": 0, "returncode": None, "timed_out": False,
           "owned_child_signals": [], "mutation": label == "scan-and-mount"}
    report["control_commands"].append(row)
    stdout, stderr = (output / (label + "." + stream + ".log") for stream in ("stdout", "stderr"))
    child, failure = None, None
    try:
        with stdout.open("xb") as out, stderr.open("xb") as err:
            require(clock() < deadline - reserve, "Control command budget exhausted before spawn")
            row["launch_attempts"] = 1
            child = popen(list(argv), stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            row.update(launches=1, pid=child.pid, launch_returned_utc=observer.now())
            try:
                child.wait(timeout=max(0.001, deadline - clock() - reserve))
            except subprocess.TimeoutExpired:
                row["timed_out"] = True
                raise
            require(type(child.returncode) is int and child.returncode == 0, "Control child returned nonzero")
            require(clock() <= deadline, "Control child exceeded declared command budget")
    except BaseException as error:
        failure = error
        row["error"] = observer.error_record(error)
    finally:
        if child is not None and child.returncode is None:
            try:
                if child.poll() is None:
                    event = {"pid": child.pid, "signal": "SIGKILL", "utc": observer.now(), "returned": False}
                    row["owned_child_signals"].append(event)
                    child.kill()
                    event["returned"] = True
                left = deadline - clock()
                if child.returncode is None and left > 0:
                    child.wait(timeout=left)
                if child.returncode is None:
                    child.poll()
                require(child.returncode is not None, "Owned control child was not reaped within its budget")
            except BaseException as error:
                row["cleanup_error"] = observer.error_record(error)
                failure = failure or error
        if child is not None:
            row.update(returncode=child.returncode, direct_child_reaped=child.returncode is not None)
        row.update(finished_utc=observer.now(), finished_monotonic=clock())
        row["elapsed_seconds"] = row["finished_monotonic"] - started
        row["files"] = []
        for path in (stdout, stderr):
            try:
                row["files"].append(observer.descriptor(path))
            except BaseException as error:
                row.setdefault("recording_errors", []).append(observer.error_record(error))
                failure = failure or error
        if clock() > deadline:
            error = RuntimeError("Control raw record readback crossed its command budget")
            row.setdefault("recording_errors", []).append(observer.error_record(error))
            failure = failure or error
    if failure is not None:
        raise failure
    try:
        require(all(p.stat().st_size <= 8 * 1024 * 1024 for p in (stdout, stderr)), "Control output exceeds explicit parsing limit")
        raw = {"stdout": stdout.read_bytes(), "stderr": stderr.read_bytes()}
        row["finished_including_readback_monotonic"] = clock()
        row["total_elapsed_seconds_including_readback"] = row["finished_including_readback_monotonic"] - started
        require(row["finished_including_readback_monotonic"] <= deadline,
                "Final control raw readback crossed its command budget")
        return raw
    except BaseException as error:
        row.setdefault("recording_errors", []).append(observer.error_record(error))
        raise


def advertised_scan(raw):
    matches = []
    for stream in ("stdout", "stderr"):
        text = raw[stream].decode("utf-8", errors="strict")
        for line, value in enumerate(text.splitlines(), 1):
            if re.fullmatch(r"[ \t]+scan-and-mount[ \t]*", value):
                matches.append({"stream": stream, "line": line, "raw_line": value})
    combined = (raw["stdout"] + b"\n" + raw["stderr"]).decode("utf-8", errors="strict")
    require(len(matches) == 1 and "Usage: simctl runtime <operation> <arguments>" in combined.splitlines()
            and "Supported Operations:" in combined.splitlines(), "Actual help does not advertise the exact command heading")
    return {"exact_advertised_command": list(SCAN), "matches": matches, "same_run_actual_help_required": True}

def fixed_window_invariants(observer, scanner, window):
    require(window["collection_complete"] is True and not window["errors"] and len(window["epochs"]) == 9
            and [row["offset_seconds"] for row in window["epochs"]] == list(observer.EPOCHS)
            and all(row["complete"] is True for row in window["epochs"]), "Fixed window is incomplete")
    require(len(window["commands"]) == 29 and all(type(row["returncode"]) is int and row["returncode"] == 0
            and row["launches"] == 1 and row["direct_child_reaped"] is True and row["timed_out"] is False
            for row in window["commands"]), "Fixed window metadata commands did not all actually complete once")
    previous, final = window["epochs"][-2:]
    require(scanner.canonical(previous["runtime_inventory"]) == scanner.canonical(final["runtime_inventory"]),
            "Full raw runtime inventory changed at the final105/120 pair")
    for epoch in (window["epochs"][0], final):
        groups = epoch["devices_inventory"]["devices"]
        require(groups and all(row.get("state") == "Shutdown" for group in groups.values() for row in group),
                "All endpoint device groups must be Shutdown")
    before = {row["path"]: row for row in previous["paths"]}
    after = {row["path"]: row for row in final["paths"]}
    require(len(before) == len(previous["paths"]) and len(after) == len(final["paths"]) and set(before) == set(after),
            "Final cumulative filesystem path inventories differ")
    def physical(row):
        values = {name: scanner.observation_value(row[name]) for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")}
        values["ancestor_lstat"] = [{"path": item["path"], **scanner.observation_value(item)} for item in row["ancestor_lstat"]]
        values["literal_mount_matches"] = row["literal_mount_matches"]
        return values
    for path in before:
        require(scanner.canonical(physical(before[path])) == scanner.canonical(physical(after[path])),
                "Filesystem evidence changed at the final105/120 pair: " + path)
        for row in (before[path], after[path]):
            operations = [row[name] for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")] + row["ancestor_lstat"]
            require(all(value["capture"] == "observed" or (value["capture"] == "unavailable"
                        and type(value["error"].get("errno")) is int and value["error"]["errno"] == 2)
                        for value in operations), "Unknown or permission filesystem error cannot qualify")
    return final, after


def closed_runtime_pair(kind, row):
    """Choose one complete literal pair; no normalization or prefix aliasing."""
    require(kind in ("tvOS", "watchOS"), "Unknown paired runtime kind")
    build = "24J360" if kind == "tvOS" else "24R362"
    canonical_mount, volumes_mount = (prefix + kind + "_" + build for prefix in (CRYPTEX, VOLUMES))
    mount = row.get("mountPath")
    require(mount in (canonical_mount, volumes_mount), "Paired runtime mount is not an exact supported literal")
    bundle = mount + "/Library/Developer/CoreSimulator/Profiles/Runtimes/" + kind + " 27.0.simruntime"
    require(row.get("runtimeBundlePath") == bundle, "Paired runtime mixes mount and bundle flavors")
    return {"flavor": "canonical" if mount == canonical_mount else "Volumes",
            "mountPath": mount, "runtimeBundlePath": bundle}


def closed_runtime_pair_closure(data, kind, identities):
    """Both complete aliases and the asset are a recursively closed reference set."""
    build, asset = ("24J360", TVOS_ASSET) if kind == "tvOS" else ("24R362", WATCH_ASSET)
    roots = [prefix + kind + "_" + build for prefix in (CRYPTEX, VOLUMES)] + [asset]

    def values(value, location=()):
        if isinstance(value, str) and Path(value).is_absolute():
            yield location, value
        elif isinstance(value, dict):
            for field, child in sorted(value.items()):
                yield from values(child, (*location, field))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from values(child, (*location, index))

    closure = []
    for key, record in sorted(data.items()):
        for location, value in values(record):
            require(Path(value).as_posix() == value and '..' not in Path(value).parts and '\0' not in value and '//' not in value,
                    "Paired runtime recursive absolute reference is not a direct literal path")
            if any(Path(value).is_relative_to(Path(root)) or Path(root).is_relative_to(Path(value)) for root in roots):
                require(key in identities and len(location) == 1 and location[0] in PATH_FIELDS
                        and value == data[key][location[0]],
                        "Paired runtime aliases or asset overlap an unrelated runtime, nested field or ancestor")
                closure.append({"uuid": key, "field": location[0], "value": value})
    return closure


def observed_tvos_volumes_pair(scanner, epoch, paths):
    """The one known old tvOS and sole Ready share a directly observed Volumes pair."""
    data = epoch["runtime_inventory"]
    group = {key: row for key, row in data.items() if row.get("runtimeIdentifier") == TVOS}
    ready = [key for key, row in group.items() if row.get("state") == "Ready"]
    old = sorted(key for key, row in group.items() if row.get("state") == "Unusable")
    require(len(ready) == 1 and old == [TVOS_OLD] and set(group) == {ready[0], *old},
            "Shared Volumes tvOS requires its sole Ready and exact known old UUID")
    for key, row in group.items():
        require(row.get("identifier") == key, "Shared Volumes tvOS UUID key differs")
        scanner.expected_special(row, "tvOS")
    pair = closed_runtime_pair("tvOS", group[ready[0]])
    require(pair["flavor"] == "Volumes" and all(closed_runtime_pair("tvOS", row) == pair for row in group.values()),
            "Shared Volumes tvOS pair differs across exact registrations")
    closure = closed_runtime_pair_closure(data, "tvOS", set(group))
    mount, bundle, asset = (paths[value] for value in (pair["mountPath"], pair["runtimeBundlePath"], TVOS_ASSET))
    scanner.healthy_mount(mount, bundle)
    scanner.observed_directory(asset)
    require(scanner.no_mount(bundle) and scanner.no_mount(asset), "Shared tvOS bundle/asset is an unexpected mount")
    for row in (mount, bundle, asset):
        for operation in (row["lstat"], row["stat"]):
            value = operation["value"]
            require(all(type(value[field]) is int and value[field] >= 0
                        for field in ("device", "inode", "mode", "uid", "gid", "size", "mtime_ns", "ctime_ns"))
                    and value["device"] > 0 and value["inode"] > 0
                    and value['is_directory'] is True and value['is_regular'] is False and value['is_symlink'] is False,
                    "Shared tvOS has malformed typed physical identity")
        for ancestor in row["ancestor_lstat"]:
            require(ancestor["capture"] == "observed" and ancestor["value"]["is_symlink"] is False,
                    "Shared tvOS path has an unavailable or linked ancestor")
    require(canonical(mount["lstat"]["value"]) == canonical(mount["stat"]["value"])
            and canonical(bundle["lstat"]["value"]) == canonical(bundle["stat"]["value"])
            and type(bundle["stat"]["value"]["device"]) is int
            and mount["stat"]["value"]["device"] == bundle["stat"]["value"]["device"],
            "Shared tvOS direct mount/bundle identity differs")
    for side in ("mount_before", "mount_after"):
        related = [row for row in epoch[side]["rows"]
                   if Path(row["mount_path"]).is_relative_to(Path(pair["mountPath"]))]
        require(canonical(related) == canonical(mount["literal_mount_matches"][side]) and len(related) == 1,
                "Shared tvOS mount contains an unexpected descendant mount")
        require(not any(Path(row["mount_path"]).is_relative_to(Path(TVOS_ASSET)) for row in epoch[side]["rows"]),
                "Shared tvOS asset contains an unexpected mount")
    return {"schema": "source-runtime-tvos-volumes-pair-v2", "ready_uuid": ready[0], "old_uuids": old,
            "literal_pair": pair, "reference_closure": closure}


def paired_tvos_volumes_ready_repair(scanner, baseline, post, decision, key):
    """Admit only the original missing Ready tvOS's two literal path substitutions."""
    before, after = (window["epochs"][-1] for window in (baseline, post))
    old, new = before["runtime_inventory"], after["runtime_inventory"]
    issues = {(row["kind"], row["uuid"]) for row in decision["issues"]}
    require(("exact_ready_tvos_bundle_enoent", key) in issues
            and ("exact_old_tvos_unusable_enoent", TVOS_OLD) in issues,
            "Ready tvOS Volumes repair lacks both original exact missing-path classifications")
    group = {identifier: row for identifier, row in old.items() if row.get("runtimeIdentifier") == TVOS}
    require(set(group) == {key, TVOS_OLD} and old[key].get("state") == "Ready"
            and old[TVOS_OLD].get("state") == "Unusable", "Ready tvOS repair changed the original two-UUID group")
    for identifier, row in group.items():
        require(row.get("identifier") == identifier, "Baseline tvOS repair UUID key differs")
        scanner.expected_special(row, "tvOS")
    pair = closed_runtime_pair("tvOS", old[key])
    require(pair["flavor"] == "canonical"
            and closed_runtime_pair("tvOS", old[TVOS_OLD])["flavor"] == "Volumes",
            "Ready tvOS repair is outside canonical-missing to known Volumes")
    expected = dict(old[key], mountPath=VOLUMES + "tvOS_24J360",
                    runtimeBundlePath=VOLUMES + "tvOS_24J360/Library/Developer/CoreSimulator/Profiles/Runtimes/tvOS 27.0.simruntime")
    require(key in new and canonical(new[key]) == canonical(expected)
            and TVOS_OLD in new and canonical(new[TVOS_OLD]) == canonical(old[TVOS_OLD]),
            "Ready tvOS repair changed more than its two paths or the known old raw registration")
    old_paths, new_paths = ({row["path"]: row for row in epoch["paths"]} for epoch in (before, after))
    require(scanner.exact_enoent(old_paths[pair["runtimeBundlePath"]]), "Ready tvOS baseline bundle is not missing")
    if not scanner.exact_enoent(old_paths[pair["mountPath"]]):
        scanner.observed_directory(old_paths[pair["mountPath"]])
        require(scanner.no_mount(old_paths[pair["mountPath"]]), "Ready tvOS baseline canonical mount was healthy")
    for field in ("mountPath", "runtimeBundlePath"):
        require(scanner.exact_enoent(old_paths[old[TVOS_OLD][field]]), "Known old tvOS baseline Volumes path was not missing")
        path = pair[field]
        require(path in new_paths and canonical({name: scanner.observation_value(old_paths[path][name])
                    for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")})
                == canonical({name: scanner.observation_value(new_paths[path][name])
                    for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")}),
                "Original missing/nonmounted canonical tvOS leaf changed across repair")
    before_closure = closed_runtime_pair_closure(old, "tvOS", set(group))
    qualified = observed_tvos_volumes_pair(scanner, after, new_paths)
    require(qualified["ready_uuid"] == key, "Ready tvOS repair selected another UUID")
    return {"schema": "source-runtime-tvos-volumes-repair-v2", "ready_uuid": key,
            "old_uuids": [TVOS_OLD], "before_literal_pair": pair,
            "after_literal_pair": qualified["literal_pair"], "baseline_reference_closure": before_closure,
            "postscan_reference_closure": qualified["reference_closure"],
            "canonical_leaf_preserved": True, "old_raw_registration_preserved": True}


def observed_watch_volumes_pair(scanner, epoch, paths):
    """The one/two known old Watch records and sole Ready share a directly observed Volumes pair."""
    data = epoch["runtime_inventory"]
    group = {key: row for key, row in data.items() if row.get("runtimeIdentifier") == WATCH}
    ready = [key for key, row in group.items() if row.get("state") == "Ready"]
    old = sorted(key for key, row in group.items() if row.get("state") == "Unusable")
    require(len(ready) == 1 and 1 <= len(old) <= 2 and set(old) <= WATCH_OLD and set(group) == {ready[0], *old},
            "Shared Volumes Watch requires its sole Ready and exact known old UUID")
    for key, row in group.items():
        require(row.get("identifier") == key, "Shared Volumes Watch UUID key differs")
        scanner.expected_special(row, "watchOS")
    pair = closed_runtime_pair("watchOS", group[ready[0]])
    require(pair["flavor"] == "Volumes" and all(closed_runtime_pair("watchOS", row) == pair for row in group.values()),
            "Shared Volumes Watch pair differs across exact registrations")
    closure = closed_runtime_pair_closure(data, "watchOS", set(group))
    mount, bundle, asset = (paths[value] for value in (pair["mountPath"], pair["runtimeBundlePath"], WATCH_ASSET))
    scanner.healthy_mount(mount, bundle)
    scanner.observed_directory(asset)
    require(scanner.no_mount(bundle) and scanner.no_mount(asset), "Shared Watch bundle/asset is an unexpected mount")
    for row in (mount, bundle, asset):
        for operation in (row["lstat"], row["stat"]):
            value = operation["value"]
            require(all(type(value[field]) is int and value[field] >= 0
                        for field in ("device", "inode", "mode", "uid", "gid", "size", "mtime_ns", "ctime_ns"))
                    and value["device"] > 0 and value["inode"] > 0
                    and value['is_directory'] is True and value['is_regular'] is False and value['is_symlink'] is False,
                    "Shared Watch has malformed typed physical identity")
        for ancestor in row["ancestor_lstat"]:
            require(ancestor["capture"] == "observed" and ancestor["value"]["is_symlink"] is False,
                    "Shared Watch path has an unavailable or linked ancestor")
    require(canonical(mount["lstat"]["value"]) == canonical(mount["stat"]["value"])
            and canonical(bundle["lstat"]["value"]) == canonical(bundle["stat"]["value"])
            and type(bundle["stat"]["value"]["device"]) is int
            and mount["stat"]["value"]["device"] == bundle["stat"]["value"]["device"],
            "Shared Watch direct mount/bundle identity differs")
    for side in ("mount_before", "mount_after"):
        related = [row for row in epoch[side]["rows"]
                   if Path(row["mount_path"]).is_relative_to(Path(pair["mountPath"]))]
        require(canonical(related) == canonical(mount["literal_mount_matches"][side]) and len(related) == 1,
                "Shared Watch mount contains an unexpected descendant mount")
        require(not any(Path(row["mount_path"]).is_relative_to(Path(WATCH_ASSET)) for row in epoch[side]["rows"]),
                "Shared Watch asset contains an unexpected mount")
    return {"schema": "source-runtime-watch-volumes-pair-v3", "ready_uuid": ready[0], "old_uuids": old,
            "literal_pair": pair, "reference_closure": closure}


def paired_watch_volumes_ready_repair(scanner, baseline, post, decision, key):
    """Only the same missing Ready Watch moves to its known unchanged old Volumes pair."""
    before, after = (window["epochs"][-1] for window in (baseline, post))
    old, new = before["runtime_inventory"], after["runtime_inventory"]
    issues = {(row["kind"], row["uuid"]) for row in decision["issues"]}
    require(("exact_ready_watch_bundle_enoent", key) in issues,
            "Ready Watch Volumes repair lacks the original exact missing-bundle classification")
    group = {identifier: row for identifier, row in old.items() if row.get("runtimeIdentifier") == WATCH}
    old_ids = sorted(identifier for identifier, row in group.items() if row.get("state") == "Unusable")
    require(old[key].get("state") == "Ready" and 1 <= len(old_ids) <= 2 and set(old_ids) <= WATCH_OLD
            and set(group) == {key, *old_ids}
            and set(decision["recognized_inactive_watch_UUIDs"]) == set(old_ids),
            "Ready Watch repair changed its sole Ready or original one/two known inactive registrations")
    for identifier, row in group.items():
        require(row.get("identifier") == identifier, "Baseline Watch repair UUID key differs")
        scanner.expected_special(row, "watchOS")
    pair = closed_runtime_pair("watchOS", old[key])
    require(pair["flavor"] == "canonical"
            and all(closed_runtime_pair("watchOS", old[identifier])["flavor"] == "Volumes" for identifier in old_ids),
            "Ready Watch repair is outside canonical-missing to known Volumes")
    expected = dict(old[key], mountPath=VOLUMES + "watchOS_24R362",
                    runtimeBundlePath=VOLUMES + "watchOS_24R362/Library/Developer/CoreSimulator/Profiles/Runtimes/watchOS 27.0.simruntime")
    require(key in new and canonical(new[key]) == canonical(expected)
            and all(identifier in new and canonical(new[identifier]) == canonical(old[identifier]) for identifier in old_ids),
            "Ready Watch repair changed more than its two paths or a known old raw registration")
    old_paths, new_paths = ({row["path"]: row for row in epoch["paths"]} for epoch in (before, after))
    require(scanner.exact_enoent(old_paths[pair["runtimeBundlePath"]]), "Ready Watch baseline bundle is not missing")
    if not scanner.exact_enoent(old_paths[pair["mountPath"]]):
        scanner.observed_directory(old_paths[pair["mountPath"]])
        require(scanner.no_mount(old_paths[pair["mountPath"]]), "Ready Watch baseline canonical mount was healthy")
    for field in ("mountPath", "runtimeBundlePath"):
        require(all(scanner.exact_enoent(old_paths[old[identifier][field]]) for identifier in old_ids),
                "Known old Watch baseline Volumes path was not missing")
        path = pair[field]
        require(path in new_paths and canonical({name: scanner.observation_value(old_paths[path][name])
                    for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")})
                == canonical({name: scanner.observation_value(new_paths[path][name])
                    for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")}),
                "Original missing/nonmounted canonical Watch leaf changed across repair")
    before_closure = closed_runtime_pair_closure(old, "watchOS", set(group))
    qualified = observed_watch_volumes_pair(scanner, after, new_paths)
    require(qualified["ready_uuid"] == key and qualified["old_uuids"] == old_ids,
            "Ready Watch repair selected another original registration")
    return {"schema": "source-runtime-watch-volumes-repair-v3", "ready_uuid": key,
            "old_uuids": old_ids, "before_literal_pair": pair,
            "after_literal_pair": qualified["literal_pair"], "baseline_reference_closure": before_closure,
            "postscan_reference_closure": qualified["reference_closure"],
            "canonical_leaf_preserved": True, "old_raw_registrations_preserved": True}


def qualify_observed_window(observer, scanner, window):
    """Saved facts only, separate from scan-before classification and V2 isolation."""
    final, paths = fixed_window_invariants(observer, scanner, window)
    tests = {row["label"]: row for row in window["original_pure_subset"]["tests"]}
    require(set(tests) == set(PURE_LABELS) and all(tests[label]["result"] == "MET_SUBSET_ONLY" for label in PURE_LABELS),
            "All three unchanged original pure predicates must be met")
    data = final["runtime_inventory"]
    watches = tests[PURE_LABELS[1]]["returned"]
    require(scanner.canonical(watches) == scanner.canonical({key: row for key, row in data.items()
            if row.get("runtimeIdentifier") == scanner.WATCH}), "Original Watch subset differs from full metadata")
    ready_special = {kind: [row for row in data.values() if row.get("runtimeIdentifier") == identifier and row.get("state") == "Ready"]
                     for kind, identifier in (("watchOS", scanner.WATCH), ("tvOS", scanner.TVOS))}
    require(all(len(rows) == 1 for rows in ready_special.values()), "Exactly one observed Ready Watch/tvOS is required")
    ready, shared, inactive_watch = [], [], []
    for key, runtime in sorted(data.items()):
        require(runtime.get("state") in ("Ready", "Unusable"), "Unknown runtime state cannot qualify")
        evidence = {field: paths[runtime[field]] for field in observer.PATH_FIELDS}
        scanner.observed_directory(evidence["path"])
        scanner.observed_directory(evidence["parentMountPath"])
        kind = "watchOS" if runtime.get("runtimeIdentifier") == scanner.WATCH else "tvOS" if runtime.get("runtimeIdentifier") == scanner.TVOS else None
        if kind:
            scanner.expected_special(runtime, kind)
        mount, bundle = evidence["mountPath"], evidence["runtimeBundlePath"]
        if runtime["state"] == "Ready":
            scanner.healthy_mount(mount, bundle)
            ready.append(key)
            continue
        require((kind == "watchOS" and key in scanner.WATCH_OLD) or (kind == "tvOS" and key == scanner.TVOS_OLD),
                "Unknown Unusable registration cannot qualify")
        counterpart = ready_special[kind][0]
        if kind == "tvOS" and runtime["mountPath"] == counterpart["mountPath"] == scanner.VOLUMES + "tvOS_24J360":
            observed_tvos_volumes_pair(scanner, final, paths)
            shared.append({"unusable_uuid": key, "ready_uuid": counterpart["identifier"], "kind": kind,
                           "mount_path": mount["path"], "bundle_path": bundle["path"]})
            continue
        counterpart = ready_special[kind][0]
        if kind == "watchOS" and runtime["mountPath"] == counterpart["mountPath"] == scanner.VOLUMES + "watchOS_24R362":
            observed_watch_volumes_pair(scanner, final, paths)
            shared.append({"unusable_uuid": key, "ready_uuid": counterpart["identifier"], "kind": kind,
                           "mount_path": mount["path"], "bundle_path": bundle["path"]})
            continue
        if kind == "watchOS" and runtime["mountPath"] == scanner.VOLUMES + "watchOS_24R362":
            require(scanner.exact_enoent(mount) and scanner.exact_enoent(bundle), "Known inactive Watch is not exact ENOENT")
            inactive_watch.append(key)
            continue
        counterpart = ready_special[kind][0]
        canonical_path = scanner.CRYPTEX + kind + ("_24R362" if kind == "watchOS" else "_24J360")
        require(runtime["mountPath"] == counterpart["mountPath"] == canonical_path
                and runtime["runtimeBundlePath"] == counterpart["runtimeBundlePath"],
                "Known Unusable record does not share the observed canonical Ready alias")
        scanner.healthy_mount(mount, bundle)
        shared.append({"unusable_uuid": key, "ready_uuid": counterpart["identifier"], "kind": kind,
                       "mount_path": mount["path"], "bundle_path": bundle["path"]})
    return {"result": "OBSERVED_PRECONDITION_ONLY", "original_pure_predicates_met": list(PURE_LABELS),
            "ready_runtime_UUIDs": ready, "recognized_inactive_watch_UUIDs": inactive_watch,
            "recognized_shared_unusable_aliases": shared, "fixed_epoch_pair": [105, 120],
            "cumulative_path_count": len(paths), "continuous_stability_claimed": False,
            "original_preparation_acceptance": False, "v2_retirement_isolation_acceptance": False,
            "shared_aliases_may_still_be_rejected_by_unchanged_original_or_v2_guards": True}


def cross_scan_scope_guard(observer, scanner, baseline, post, baseline_decision):
    """Preserve every original asset and Ready identity across the single scan.

    Leaf observations retain all captured stat fields. Ancestor metadata and mount
    output line numbers are not physical identity across phases; the fixed final
    pair still compares that complete evidence inside each phase.
    """
    before, after = (window["epochs"][-1] for window in (baseline, post))
    old, new = before["runtime_inventory"], after["runtime_inventory"]
    old_paths, new_paths = ({row["path"]: row for row in epoch["paths"]} for epoch in (before, after))
    require(not set(new) - set(old), "New runtime UUID appeared across the scan")
    repairs = {row["uuid"] for row in baseline_decision["issues"]
               if row["kind"] in ("exact_ready_watch_bundle_enoent", "exact_ready_tvos_bundle_enoent")}
    preserved_ready, remapped, removed, asset_paths, healthy_paths = [], [], [], set(), set()
    volumes_repairs = []
    for key, runtime in sorted(old.items()):
        require(runtime["identifier"] == key, "Baseline runtime UUID key differs from its raw identifier")
        asset_paths.update(runtime[field] for field in ("path", "parentMountPath"))
        if runtime["state"] == "Ready":
            require(key in new, "Baseline Ready UUID disappeared across the scan: " + key)
            if scanner.canonical(runtime) != scanner.canonical(new[key]):
                require(key in repairs, "An already healthy Ready record changed across the scan: " + key)
                if runtime.get("runtimeIdentifier") == scanner.TVOS:
                    volumes_repairs.append(paired_tvos_volumes_ready_repair(scanner, baseline, post, baseline_decision, key))
                elif runtime.get("runtimeIdentifier") == scanner.WATCH:
                    volumes_repairs.append(paired_watch_volumes_ready_repair(scanner, baseline, post, baseline_decision, key))
                else:
                    require(False, "Baseline Ready full raw record changed outside its exact paired repair: " + key)
            preserved_ready.append(key)
            if key not in repairs:
                scanner.healthy_mount(old_paths[runtime["mountPath"]], old_paths[runtime["runtimeBundlePath"]])
                healthy_paths.update(runtime[field] for field in observer.PATH_FIELDS)
            continue
        kind = "watchOS" if key in scanner.WATCH_OLD else "tvOS" if key == scanner.TVOS_OLD else None
        require(runtime["state"] == "Unusable" and kind is not None,
                "Unknown baseline Unusable registration in cross-scan scope")
        scanner.expected_special(runtime, kind)
        old_mount = scanner.VOLUMES + kind + ("_24R362" if kind == "watchOS" else "_24J360")
        require(runtime["mountPath"] == old_mount, "Known Unusable baseline alias is not the exact Volumes path")
        if key not in new:
            removed.append(key)
            continue
        if scanner.canonical(runtime) == scanner.canonical(new[key]):
            continue
        canonical_mount = scanner.CRYPTEX + old_mount[len(scanner.VOLUMES):]
        expected = {**runtime, "mountPath": canonical_mount,
                    "runtimeBundlePath": canonical_mount + runtime["runtimeBundlePath"][len(old_mount):]}
        require(scanner.canonical(new[key]) == scanner.canonical(expected),
                "Unusable record changed beyond the exact two canonical alias paths: " + key)
        remapped.append(key)

    def leaf(row):
        return {name: scanner.observation_value(row[name])
                for name in ("lstat", "stat", "resolve_strict", "os_path_ismount")}

    def mounts(row):
        return {side: [{name: item[name] for name in ("source", "mount_path", "options")}
                       for item in row["literal_mount_matches"][side]]
                for side in ("mount_before", "mount_after")}

    for path in sorted(asset_paths | healthy_paths):
        require(path in old_paths and path in new_paths, "Baseline protected path was lost from the seeded postscan inventory")
        require(scanner.canonical(leaf(old_paths[path])) == scanner.canonical(leaf(new_paths[path])),
                "Protected leaf filesystem observation changed across the scan: " + path)
        if path in healthy_paths:
            require(scanner.canonical(mounts(old_paths[path])) == scanner.canonical(mounts(new_paths[path])),
                    "Protected mount source/path/options changed across the scan: " + path)
    return {"result": "CROSS_SCAN_SCOPE_PRESERVED", "preserved_ready_UUIDs": preserved_ready,
            "known_missing_ready_repair_UUIDs": sorted(repairs), "known_unusable_remapped_UUIDs": remapped,
            "recognized_ready_volumes_repairs": volumes_repairs,
            "known_unusable_removed_UUIDs": removed, "all_baseline_asset_parent_paths": sorted(asset_paths),
            "already_healthy_ready_protected_paths": sorted(healthy_paths),
            "cross_scan_leaf_operations": ["lstat", "stat", "resolve_strict", "os_path_ismount"],
            "cross_scan_mount_fields": ["source", "mount_path", "options"],
            "cross_scan_ancestor_metadata_and_mount_line_numbers_compared": False,
            "final_fixed_pair_complete_evidence_comparison_unchanged": True}


def run_protocol(observer, scanner, source, output, report, legacy, baseline_budget, *, collect=None, command=None):
    collect, command = collect or scanner.collect_phase, command or scanner.run_command
    report["stage"] = "baseline"
    baseline = collect(observer, source, output, report, legacy, "baseline", baseline_budget)
    baseline_budget.check("baseline precondition qualification")
    fixed_window_invariants(observer, scanner, baseline)
    try:
        report["qualification"] = qualify_observed_window(observer, scanner, baseline)
    except Exception as error:
        report["baseline_qualification_failure"] = observer.error_record(error)
    else:
        baseline_budget.check("healthy baseline qualification complete")
        report["baseline_decision"] = {"result": "HEALTHY_FIXED_BASELINE_SCAN_NOT_RUN"}
        report["phases"]["postscan"]["reason"] = "Healthy baseline qualifies without help or scan"
        return baseline_budget
    report["stage"] = "strict-known-baseline-issue"
    report["baseline_decision"] = scanner.classify_baseline(baseline)
    require(report["baseline_decision"]["result"] == "SUPPORTED_KNOWN_ISSUE_SCAN_ELIGIBLE"
            and report["baseline_decision"]["issues"], "No exact known issue permits a scan")
    baseline_budget.check("strict baseline classification complete")
    report["stage"] = "actual-runtime-help"
    report["help_advertisement"] = scanner.advertised_scan(command(observer, output, report, "runtime-help"))
    scanner.recheck_files(observer, report)
    report["stage"] = "single-scan-and-mount"
    command(observer, output, report, "scan-and-mount")
    report["stage"] = "postscan"
    seed = {row["path"]: row["references"] for row in baseline["epochs"][-1]["paths"]}
    post_budget = observer.Budget(time.monotonic())
    post = collect(observer, source, output, report, legacy, "postscan", post_budget, seed=seed)
    before, after = baseline["epochs"][-1]["runtime_inventory"], post["epochs"][-1]["runtime_inventory"]
    report["full_raw_inventory_delta"] = {
        "added": {key: after[key] for key in sorted(set(after) - set(before))},
        "removed": {key: before[key] for key in sorted(set(before) - set(after))},
        "changed": {key: {"before": before[key], "after": after[key]} for key in sorted(set(before) & set(after))
                    if scanner.canonical(before[key]) != scanner.canonical(after[key])}}
    report["stage"] = "independent-postscan-qualification"
    post_budget.check("postscan precondition qualification")
    report["cross_scan_scope"] = cross_scan_scope_guard(observer, scanner, baseline, post, report["baseline_decision"])
    report["qualification"] = qualify_observed_window(observer, scanner, post)
    post_budget.check("postscan qualification complete")
    return post_budget


def finalize_report(observer, scanner, output, report, active_budget, exit_code):
    """Qualifying final rechecks and overall write/readback share the final phase cap."""
    if exit_code == 0:
        try:
            report["stage"] = "final-context-and-record"
            active_budget.check("before final context recheck")
            scanner.recheck_files(observer, report, active_budget)
            active_budget.check("after final context recheck")
        except BaseException as error:
            report["errors"].append({"stage": report["stage"], **observer.error_record(error)})
            report["result"], exit_code = "PRECONDITION_FAILED_NO_ORIGINAL_ACCEPTANCE", 1
    report.update(finished_utc=observer.now(), finished_monotonic=time.monotonic(),
                  intended_exit_status_before_final_record=exit_code)
    report["elapsed_seconds"] = report["finished_monotonic"] - report["started_monotonic"]
    report["actual_scan_spawn_attempts"] = sum(row["launch_attempts"] for row in report["control_commands"] if row["mutation"])
    report["actual_launched_runtime_mutation_commands"] = sum(row["launches"] for row in report["control_commands"] if row["mutation"])
    if active_budget is not None and exit_code == 0:
        report["final_active_phase_budget"] = {"started_monotonic": active_budget.started,
                                               "deadline_monotonic": active_budget.deadline, "seconds": observer.TOTAL_SECONDS}
    try:
        if exit_code == 0:
            active_budget.check("before final overall record")
        observer.write_new(output / "precondition.json", report)
        if exit_code == 0:
            active_budget.check("after final overall write/readback")
    except BaseException as error:
        exit_code = 1
        failure = {"result": "PRECONDITION_FINAL_HANDOFF_FAILED_NO_ORIGINAL_ACCEPTANCE",
                   "error": observer.error_record(error), "precondition_record_must_not_be_treated_as_success": True,
                   "intended_process_exit_status": 1, "formal_candidate_credit": False}
        try:
            observer.write_new(output / "final-handoff-failure.json", failure)
        except BaseException as recording_error:
            failure["failure_marker_recording_error"] = observer.error_record(recording_error)
        print(json.dumps(failure), file=sys.stderr)
    return exit_code

"""Source-module support appended after the reviewed bounded collector/policy.

This is build input, not an executable runtime entry point. The generated module
is imported only by a source common whose Git/SHA binding was already checked.
"""


def components(common_sha256):
    observer_names = ('now', 'error_record', 'sha', 'decode', 'descriptor', 'write_new',
                      'Budget', 'Queries', 'observe_paths', 'collect_window',
                      'EPOCHS', 'TOTAL_SECONDS', 'PATH_FIELDS')
    scanner_names = ('canonical', 'recheck_files', 'collect_phase', 'observation_value',
                     'observed_directory', 'no_mount', 'exact_enoent', 'healthy_mount',
                     'expected_special', 'classify_baseline', 'run_command', 'advertised_scan',
                     'WATCH', 'TVOS', 'WATCH_OLD', 'TVOS_OLD', 'VOLUMES', 'CRYPTEX')
    observer = types.SimpleNamespace(**{name: globals()[name] for name in observer_names})
    observer.pure_subset = lambda raw, epochs: pure_subset(raw, epochs, common_sha256)
    scanner = types.SimpleNamespace(**{name: globals()[name] for name in scanner_names})
    return observer, scanner, types.SimpleNamespace(stat_fields=stat_fields)


def validate_context_axes(context, environment):
    """Extend the unchanged common context; never replace or spoof its binder."""
    require(context['mode'] in ('candidate', 'canonical', 'workflow-input'), 'Unknown common context mode')
    require(context['owner'] in ('server', 'statistics', 'icon', 'settings', 'integrated'), 'Unknown source owner')
    actual = context['consumer']
    for key, name in (('repository', 'GITHUB_REPOSITORY'), ('run_id', 'GITHUB_RUN_ID'),
                      ('attempt', 'GITHUB_RUN_ATTEMPT'), ('job', 'GITHUB_JOB')):
        require(actual[key] == environment.get(name), 'Actual common caller differs: ' + key)
    require(actual['runner_os'] == 'macOS', 'Common caller is not the actual macOS runtime')
    require(all(re.fullmatch('[0-9a-f]{40}', context['source'][key]) for key in ('commit', 'tree')),
            'Malformed actual source identity')
    require(re.fullmatch('[0-9a-f]{64}', context['own_helper_sha256']), 'Malformed actual common hash')
    if context['mode'] == 'workflow-input':
        require(context['owner'] == 'statistics' and context['control'] is None
                and context['control_root'] is None and context['actual_caller_environment'] == actual
                and actual['github_sha'] == environment.get('GITHUB_SHA')
                and context['workflow_input_binding']['actual_source'] == context['source']
                and context['workflow_input_binding']['raw_input_ref'] == environment.get('RUNTIME_COMMON_SOURCE_REF'),
                'Actual workflow-input axes changed')
    else:
        require(actual['helper'] == context['control']
                and context['control']['commit'] == environment.get('GITHUB_SHA'), 'Actual control axes changed')
        if context['mode'] == 'canonical':
            require(context['source'] == context['control'], 'Canonical source/control differs')
        else:
            bound = context['original_restorer_binding']['identity']
            require(bound['producer'] == {**actual, 'job': 'build'},
                    'Candidate preconditioning requires the same run AND attempt producer')
            require(bound['matrix_row']['name'] == context['owner']
                    and bound['matrix_row']['sha'] == context['source']['commit']
                    and bound['matrix_row']['os'] == 'xcode-27' and bound['matrix_row']['runtime'] is True,
                    'Candidate producer owner/source/runtime coverage changed')
    return {'mode': context['mode'], 'owner': context['owner'], 'source': context['source'],
            'consumer': actual, 'candidate_requires_equal_producer_attempt': context['mode'] == 'candidate'}


def context_files(context, module_binding):
    """Use descriptors from context_for plus this independently tracked module."""
    expected = {str(Path(relative).with_name('runtime_preconditioning.py'))
                for relative in context['helper_git_entries']}
    require(module_binding['schema'] == 'source-runtime-preconditioning-module-set-v1'
            and module_binding['active_relative_path'] == str(Path(context['own_helper_relative_path']).with_name('runtime_preconditioning.py'))
            and set(module_binding['copies']) == expected
            and len({(row['sha256'], row['git_blob'], row['git_mode']) for row in module_binding['copies'].values()}) == 1
            and all(row['sha256'] == module_binding['sha256'] and row['mode'] == 0o644 and row['git_mode'] == '100644'
                    for row in module_binding['copies'].values()), 'Source module active/inherited binding set changed')
    records = [*context['helper_git_entries'].values(), context['features_file'],
               *context['original_consumer_files'].values(), *module_binding['copies'].values()]
    if context['mode'] == 'candidate':
        records.extend(context['original_restorer_binding'][key] for key in ('matrix', 'restorer', 'receipt'))
    result, seen = [], set()
    for row in records:
        if row['path'] in seen:
            continue
        seen.add(row['path'])
        result.append({'role': 'source-common-context', 'relative_path': row.get('relative_path', row['path']),
                       **{key: row[key] for key in ('path', 'bytes', 'sha256')}})
    return result


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def bound_bytes(record, root, expected_path, maximum=64 * 1024 * 1024):
    path = Path(record['path'])
    require(path == expected_path and path.is_absolute() and path.is_relative_to(root), 'Evidence path/context differs')
    for ancestor in (path, *path.parents):
        require(not ancestor.is_symlink(), 'Linked evidence path')
        if ancestor == root:
            break
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum, 'Nonregular or oversized evidence')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        opened = stream.fileno()
        require(stat_fields(os.fstat(opened)) == stat_fields(before), 'Evidence changed before open')
        raw = stream.read(maximum + 1)
        require(len(raw) <= maximum and stat_fields(os.fstat(opened)) == stat_fields(before), 'Evidence changed while read')
    require(stat_fields(path.lstat()) == stat_fields(before), 'Evidence changed after read')
    require(type(record['bytes']) is int and record['bytes'] == len(raw) and record['sha256'] == sha(raw),
            'Evidence bytes/hash mismatch')
    return raw


def timestamp(value):
    require(type(value) is str, 'Missing actual UTC timestamp')
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, 'UTC timestamp has no offset')
    return parsed.timestamp()


def check_interval(row, start_key, finish_key, lower, upper):
    start, finish = row[start_key], row[finish_key]
    require(finite(start) and finite(finish) and lower <= start <= finish <= upper, 'Clock escapes its actual phase/command')
    require(timestamp(row['started_utc']) <= timestamp(row['finished_utc']), 'UTC command/field order is reversed')
    return start, finish


def saved_command(row, root, directory, label, argv, phase_deadline=None):
    require(row['label'] == label and row['argv'] == list(argv), 'Saved command order or argv changed')
    require(type(row['returncode']) is int and row['returncode'] == 0
            and type(row['launches']) is int and row['launches'] == 1
            and type(row['pid']) is int and row['pid'] > 0 and row['direct_child_reaped'] is True
            and row['timed_out'] is False and row['owned_child_signals'] == [], 'Command did not complete once with actual zero')
    require(not any(key in row for key in ('error', 'cleanup_error', 'timeout_error', 'recording_errors')),
            'Command retains a failure marker')
    deadline = row.get('command_deadline_monotonic', row.get('deadline_monotonic'))
    cap = row['command_budget_seconds']
    require(finite(deadline) and finite(cap) and cap > 0, 'Missing command deadline')
    start, finish = check_interval(row, 'started_monotonic', 'finished_monotonic', -math.inf, deadline)
    require(abs((deadline - start) - cap) < 0.01 and abs(row['elapsed_seconds'] - (finish - start)) < 1e-6,
            'Actual command budget/elapsed arithmetic differs')
    require(0 < row['cleanup_reserve_seconds'] <= cap and
            start <= finish <= deadline, 'Invalid command cleanup budget')
    if phase_deadline is not None:
        require(cap <= COMMAND_SECONDS and deadline <= phase_deadline + 0.01, 'Metadata child exceeded phase budget')
    else:
        expected_cap = 10.0 if label == 'runtime-help' else 120.0
        require(cap == expected_cap and type(row['launch_attempts']) is int and row['launch_attempts'] == 1
                and row['mutation'] is (label == 'scan-and-mount'), 'Control command count/cap changed')
        require(finite(row['finished_including_readback_monotonic'])
                and finish <= row['finished_including_readback_monotonic'] <= deadline,
                'Control final raw readback exceeded deadline')
    require(len(row['files']) == 2, 'Command lacks exact stdout/stderr files')
    raw = {}
    for record, stream in zip(row['files'], ('stdout', 'stderr')):
        raw[stream] = bound_bytes(record, root, directory / (label + '.' + stream + '.log'), 8 * 1024 * 1024)
    return raw


def filesystem_capture(value, epoch, stat_value=False):
    check_interval(value, 'started_monotonic', 'finished_monotonic', epoch['started_monotonic'], epoch['finished_monotonic'])
    require(value['budget_exceeded_after_syscall'] is False, 'Filesystem capture crossed phase deadline')
    require(value['capture'] in ('observed', 'unavailable'), 'Unknown filesystem capture')
    if value['capture'] == 'unavailable':
        require(type(value['error']) is dict and type(value['error']['type']) is str
                and type(value['error']['message']) is str and 'errno' in value['error'], 'Filesystem error details were lost')
        return
    result = value['value']
    if stat_value:
        integers = ('device', 'inode', 'mode', 'uid', 'gid', 'size', 'mtime_ns', 'ctime_ns')
        flags = ('is_directory', 'is_regular', 'is_symlink')
        require(set(result) == set(integers + flags)
                and all(type(result[k]) is int for k in integers)
                and all(type(result[k]) is bool for k in flags), 'Incomplete physical stat value')


def initial_paths():
    paths = {}
    for name, build in (('iOS', '24A434'), ('watchOS', '24R362'), ('tvOS', '24J360')):
        for prefix in (VOLUMES, CRYPTEX):
            mount = prefix + name + '_' + build
            for value in (mount, mount + '/Library/Developer/CoreSimulator/Profiles/Runtimes/' + name + ' 27.0.simruntime'):
                paths[value] = [{'fixed_alias': True}]
    return paths


def validate_window(window, context, module_binding, common_raw, root, directory, seed=None):
    require(window['schema'] == 'source-runtime-preconditioning-window-v1' and window['context'] == context
            and window['source'] == context['source'] and window['helper'] == context['control'], 'Window context/schema differs')
    require(window['result'] == 'FIXED_WINDOW_COLLECTED_NO_ACCEPTANCE' and window['collection_complete'] is True
            and window['errors'] == [] and window['formal_candidate_credit'] is False
            and window['runtime_acceptance'] is False and window['phase_owned_runtime_mutations'] == 0,
            'Window is not a complete zero-credit observation')
    require(window['bound_files'] == context_files(context, module_binding), 'Window source/module/producer bindings differ')
    require(window['planned_epoch_seconds'] == list(EPOCHS) and window['total_budget_seconds'] == TOTAL_SECONDS
            and len(window['epochs']) == len(window['epoch_files']) == 9 and len(window['commands']) == 29,
            'Fixed phase count/budget changed')
    start, deadline = window['budget_started_monotonic'], window['deadline_monotonic']
    require(finite(start) and finite(deadline) and deadline == start + TOTAL_SECONDS
            and start <= window['collector_entered_monotonic'] <= window['finished_monotonic'] < deadline,
            'Phase deadline or actual interval changed')
    require(finite(window['elapsed_seconds'])
            and abs(window['elapsed_seconds'] - (window['finished_monotonic'] - start)) < 1e-6,
            'Phase elapsed arithmetic changed')
    require(window['baseline_union_seed_path_count'] == len(seed or {}), 'Baseline seed count changed')
    require(not (directory / 'final-write-budget-failure.json').exists(), 'Phase final-write failure marker exists')
    commands, raw_files, paths, cursor, prior_finish = {}, [], initial_paths(), 0, start
    for offset, epoch, epoch_file in zip(EPOCHS, window['epochs'], window['epoch_files']):
        require(epoch['offset_seconds'] == offset and epoch['scheduled_monotonic'] == start + offset
                and epoch['complete'] is True and epoch['atomic_snapshot_claimed'] is False,
                'Epoch order/schedule/completion changed')
        check_interval(epoch, 'started_monotonic', 'finished_monotonic', max(prior_finish, start + offset), deadline)
        require(epoch['started_monotonic'] < start + offset + 15, 'Missed epoch relabeled as a valid sample')
        require(abs(epoch['start_lateness_seconds'] - (epoch['started_monotonic'] - start - offset)) < 1e-6,
                'Epoch lateness arithmetic changed')
        prefix = 'epoch-' + str(offset).zfill(3)
        expected = [(prefix + '-mount-before', MOUNT), (prefix + '-runtime-list', RUNTIMES)]
        if offset in (0, 120):
            expected.append((prefix + '-devices-list', DEVICES))
        expected.append((prefix + '-mount-after', MOUNT))
        previous_command_finish = epoch['started_monotonic']
        for label, argv in expected:
            row = window['commands'][cursor]; cursor += 1
            require(row['epoch'] == offset and row['started_monotonic'] >= previous_command_finish
                    and row['finished_monotonic'] <= epoch['finished_monotonic'], 'Child is outside its ordered epoch')
            commands[label] = saved_command(row, root, directory, label, argv, deadline)
            previous_command_finish = row['finished_monotonic']
            raw_files.extend(row['files'])
        require(epoch['runtime_command_label'] == prefix + '-runtime-list'
                and canonical(runtime_inventory(commands[prefix + '-runtime-list']['stdout'])) == canonical(epoch['runtime_inventory']),
                'Full raw runtime inventory differs from saved epoch')
        for side in ('mount_before', 'mount_after'):
            label = prefix + '-' + side.replace('_', '-')
            require(epoch[side]['command_label'] == label
                    and mount_table(commands[label]['stdout']) == epoch[side]['rows'], 'Raw mount table differs')
        require(epoch['mount_tables_equal'] is (epoch['mount_before']['rows'] == epoch['mount_after']['rows']),
                'Mount-table non-atomicity was erased')
        if offset in (0, 120):
            require(epoch['devices_command_label'] == prefix + '-devices-list'
                    and devices_inventory(commands[prefix + '-devices-list']['stdout']) == epoch['devices_inventory'],
                    'Full raw device inventory differs')
        else:
            require('devices_inventory' not in epoch and 'devices_command_label' not in epoch, 'Unexpected device query')
        require(add_paths(paths, epoch['runtime_inventory'], offset) == epoch['all_runtime_path_fields'],
                'Runtime path-field coverage changed')
        if offset == 0 and seed is not None:
            for path, refs in seed.items():
                paths.setdefault(path, []).extend({'source_phase': 'baseline', 'baseline_reference': ref} for ref in refs)
        require(len(epoch['paths']) == len(paths) == epoch['cumulative_path_count']
                and [row['path'] for row in epoch['paths']] == sorted(paths), 'Cumulative physical paths lost or duplicated')
        for row in epoch['paths']:
            require(row['references'] == paths[row['path']], 'Raw path-reference history differs')
            for key in ('lstat', 'stat', 'resolve_strict', 'os_path_ismount'):
                filesystem_capture(row[key], epoch, key in ('lstat', 'stat'))
            require([v['path'] for v in row['ancestor_lstat']] == [str(v) for v in reversed(Path(row['path']).parents)],
                    'Ancestor path coverage was shortened')
            for item in row['ancestor_lstat']:
                filesystem_capture(item, epoch, True)
            require(row['literal_mount_matches'] == {side: [item for item in epoch[side]['rows'] if item['mount_path'] == row['path']]
                    for side in ('mount_before', 'mount_after')}, 'Literal physical mount-row binding changed')
        require(canonical(decode(bound_bytes(epoch_file, root, directory / (prefix + '.json')))) == canonical(epoch), 'Epoch raw file differs')
        raw_files.append(epoch_file)
        prior_finish = epoch['finished_monotonic']
    require(cursor == len(window['commands']), 'Unused metadata child')
    require(window['original_pure_subset'] == pure_subset(common_raw, window['epochs'], context['own_helper_sha256']),
            'Saved pure predicate replay differs from the actual common bytes')
    return raw_files


def validate_evidence(report, context, module_binding, common_raw, root, directory):
    require(report['schema'] == 'source-runtime-preconditioning-v3' and report['identity'] == context
            and report['context'] == context and report['source'] == context['source']
            and report['helper'] == context['control'] and report['module_binding'] == module_binding
            and report['common_source_relative_path'] == context['own_helper_relative_path']
            and report['common_source_sha256'] == sha(common_raw) == context['own_helper_sha256'], 'Source preparation binding changed')
    require(report['result'] == 'OBSERVED_PRECONDITION_QUALIFIED_NO_ORIGINAL_ACCEPTANCE'
            and report['intended_exit_status_before_final_record'] == 0 and report['errors'] == [], 'Preconditioning did not qualify')
    require(all(report[k] is False for k in ('formal_candidate_credit', 'runtime_acceptance', 'publication_credit'))
            and all(type(report[k]) is int and report[k] == 0 for k in
                    ('original_preparation_executions', 'retirement_executions', 'consumer_executions', 'product_builds',
                     'query_or_scan_retries', 'owned_add_delete_verify_boot_or_daemon_signal_commands')),
            'Precondition receipt carries false runtime/consumer credit')
    require(report['maximum_runtime_mutation_commands'] == 1 and report['observation_phase_budget_seconds'] == 150
            and report['help_budget_seconds'] == 10 and report['scan_budget_seconds'] == 120,
            'Fixed precondition budgets changed')
    require(not any((directory / name).exists() for name in ('final-handoff-failure.json', 'completion-readback-failure.json')),
            'Preconditioning has a final failure marker')
    require(report['bound_files'] == context_files(context, module_binding), 'Bound source/common/producer file set changed')
    require(report['actual_context_axes'] == {'mode': context['mode'], 'owner': context['owner'],
            'source': context['source'], 'consumer': context['consumer'],
            'candidate_requires_equal_producer_attempt': context['mode'] == 'candidate'},
            'Recorded actual source/caller axes differ')
    observer, scanner, _ = components(context['own_helper_sha256'])
    plan_record = report['plan_record']
    plan = decode(bound_bytes(plan_record, root, directory / 'planned-precondition.json'))
    require(plan['schema'] == report['schema'] and plan['identity'] == plan['context'] == context
            and plan['module_binding'] == module_binding and plan['common_source_sha256'] == sha(common_raw)
            and plan['actual_context_axes'] == report['actual_context_axes']
            and plan['bound_files'] == report['bound_files'] and plan['control_commands'] == []
            and plan['phases'] == {'baseline': {'status': 'NOT_RUN'}, 'postscan': {'status': 'NOT_RUN'}}
            and plan['result'] == 'IN_PROGRESS_NO_ORIGINAL_ACCEPTANCE', 'Planned immutable precondition context differs')
    raw_files, windows = [plan_record], {}
    require(set(report['phases']) == {'baseline', 'postscan'}, 'Unplanned observation phases')
    count = len(report['control_commands'])
    require(count in (0, 2), 'Help/scan must both be absent or occur once in order')
    for phase in ('baseline', 'postscan'):
        summary = report['phases'][phase]
        if phase == 'postscan' and count == 0:
            require(summary['status'] == 'NOT_RUN' and 'record' not in summary, 'Healthy baseline unexpectedly scanned')
            continue
        require(summary['status'] == 'COLLECTED_NO_ACCEPTANCE' and summary['epochs'] == summary['completed_epochs'] == 9
                and summary['commands'] == 29 and not summary.get('recording_errors')
                and finite(summary['actual_elapsed_seconds_including_record'])
                and 120 <= summary['actual_elapsed_seconds_including_record'] < TOTAL_SECONDS,
                'Observation phase was not completed inside its final write budget')
        record = summary['record']
        window = decode(bound_bytes(record, root, directory / phase / 'observation.json'))
        require(window['phase'] == phase, 'Wrong saved observation phase')
        require(summary['actual_elapsed_seconds_including_record'] >= window['elapsed_seconds'],
                'Phase final record appears earlier than collection finish')
        seed = {row['path']: row['references'] for row in windows['baseline']['epochs'][-1]['paths']} if phase == 'postscan' else None
        raw_files.extend(validate_window(window, context, module_binding, common_raw, root, directory / phase, seed))
        raw_files.append(record); windows[phase] = window
    baseline = windows['baseline']
    fixed_window_invariants(observer, scanner, baseline)
    if count == 0:
        require(report['baseline_decision'] == {'result': 'HEALTHY_FIXED_BASELINE_SCAN_NOT_RUN'}, 'Wrong healthy-baseline branch')
        require(canonical(report['qualification']) == canonical(qualify_observed_window(observer, scanner, baseline)), 'Baseline qualification replay differs')
        require(not any(k in report for k in ('help_advertisement', 'cross_scan_scope', 'full_raw_inventory_delta')),
                'No-scan branch contains scan-only evidence')
        active = baseline
    else:
        decision = classify_baseline(baseline)
        require(canonical(report['baseline_decision']) == canonical(decision) and decision['result'] == 'SUPPORTED_KNOWN_ISSUE_SCAN_ELIGIBLE'
                and decision['issues'], 'One scan lacked its exact known baseline issue')
        prior_end = baseline['finished_monotonic']
        for row, label, argv in zip(report['control_commands'], ('runtime-help', 'scan-and-mount'), (HELP, SCAN)):
            require(row['started_monotonic'] >= prior_end, 'Control command started before its prerequisite')
            raw = saved_command(row, root, directory, label, argv)
            raw_files.extend(row['files'])
            if label == 'runtime-help':
                require(report['help_advertisement'] == advertised_scan(raw), 'Exact help advertisement replay differs')
            prior_end = row['finished_including_readback_monotonic']
        post = windows['postscan']; active = post
        require(post['budget_started_monotonic'] >= prior_end, 'Postscan began before actual scan readback')
        require(canonical(report['cross_scan_scope']) == canonical(cross_scan_scope_guard(observer, scanner, baseline, post, decision))
                and canonical(report['qualification']) == canonical(qualify_observed_window(observer, scanner, post)), 'Cross-scan/qualification replay differs')
        before, after = baseline['epochs'][-1]['runtime_inventory'], post['epochs'][-1]['runtime_inventory']
        delta = {'added': {k: after[k] for k in sorted(set(after) - set(before))},
                 'removed': {k: before[k] for k in sorted(set(before) - set(after))},
                 'changed': {k: {'before': before[k], 'after': after[k]} for k in sorted(set(before) & set(after)) if canonical(before[k]) != canonical(after[k])}}
        require(canonical(report['full_raw_inventory_delta']) == canonical(delta), 'Full raw scan delta was shortened')
    expected_count = count // 2
    require(type(report['actual_scan_spawn_attempts']) is int and type(report['actual_launched_runtime_mutation_commands']) is int
            and report['actual_scan_spawn_attempts'] == report['actual_launched_runtime_mutation_commands'] == expected_count,
            'Actual one-scan counters differ')
    require(report['final_active_phase_budget'] == {'started_monotonic': active['budget_started_monotonic'],
            'deadline_monotonic': active['deadline_monotonic'], 'seconds': TOTAL_SECONDS}
            and active['finished_monotonic'] <= report['finished_monotonic'] < active['deadline_monotonic'],
            'Final overall write/readback escaped the active phase')
    require(len({row['path'] for row in raw_files}) == len(raw_files), 'Duplicate raw evidence descriptor')
    return sorted(raw_files, key=lambda row: row['path'])


def run_source_preconditioning(context, module_binding, common_raw, output, started):
    """One source-owned phase; actual process status remains the common caller's."""
    source = Path(context['source_root'])
    require(output.is_absolute() and output.is_relative_to(source) and output.parent.resolve(strict=True) == output.parent,
            'Precondition output is outside the actual common preparation root')
    output.mkdir(exist_ok=False)
    observer, scanner, legacy = components(context['own_helper_sha256'])
    budget = Budget(started)
    report = {'schema': 'source-runtime-preconditioning-v3', 'result': 'IN_PROGRESS_NO_ORIGINAL_ACCEPTANCE',
              'identity': context, 'context': context, 'source': context['source'], 'helper': context['control'],
              'module_binding': module_binding, 'common_source_sha256': sha(common_raw),
              'common_source_relative_path': context['own_helper_relative_path'],
              'started_utc': now(), 'started_monotonic': started, 'pid': os.getpid(), 'argv': list(sys.argv),
              'bound_files': context_files(context, module_binding), 'stage': 'source-common-context',
              'control_commands': [], 'errors': [], 'phases': {'baseline': {'status': 'NOT_RUN'}, 'postscan': {'status': 'NOT_RUN'}},
              'formal_candidate_credit': False, 'runtime_acceptance': False, 'publication_credit': False,
              'original_preparation_executions': 0, 'retirement_executions': 0, 'consumer_executions': 0, 'product_builds': 0,
              'query_or_scan_retries': 0, 'maximum_runtime_mutation_commands': 1,
              'owned_add_delete_verify_boot_or_daemon_signal_commands': 0,
              'observation_phase_budget_seconds': 150, 'help_budget_seconds': 10, 'scan_budget_seconds': 120,
              'actual_exit_requires_separate_outer_wrapper_binding': True,
              'completion_requires_actual_outer_exit_zero_and_no_final_handoff_failure_marker': True}
    active, failure, status = budget, None, 1
    try:
        report['actual_context_axes'] = validate_context_axes(context, os.environ)
        budget.check('source module/context import and binding')
        recheck_files(observer, report, budget)
        report['plan_record'] = write_new(output / 'planned-precondition.json', report)
        active = run_protocol(observer, scanner, source, output, report, legacy, budget)
        report['result'], status = 'OBSERVED_PRECONDITION_QUALIFIED_NO_ORIGINAL_ACCEPTANCE', 0
    except BaseException as error:
        failure = error
        report['errors'].append({'stage': report['stage'], **error_record(error)})
        report['result'] = 'PRECONDITION_FAILED_NO_ORIGINAL_ACCEPTANCE'
    status = finalize_report(observer, scanner, output, report, active, status)
    if failure is not None:
        raise failure
    require(status == 0, 'Source precondition final handoff failed')
    try:
        active.check('before complete saved phase/raw replay')
        raw_files = validate_evidence(report, context, module_binding, common_raw, source, output)
        active.check('after complete saved phase/raw replay')
        record = descriptor(output / 'precondition.json')
        active.check('after final source precondition descriptor')
    except BaseException as error:
        failure = {'result': 'PRECONDITION_READBACK_FAILED', 'error': error_record(error),
                   'precondition_record_must_not_be_treated_as_success': True}
        try:
            write_new(output / 'completion-readback-failure.json', failure)
        except BaseException as recording_error:
            failure['failure_marker_recording_error'] = error_record(recording_error)
            print(json.dumps(failure), file=sys.stderr)
        raise error
    return report, record, raw_files
