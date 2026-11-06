#!/usr/bin/env python3
"""Observe nine fixed daemon-startup epochs; no preparation or runtime acceptance.

Only runtime-list, bracketed mount tables and initial/final device-list children
are launched. A failed query ends collection without another epoch or retry.
The deadline bounds scheduled waits/child waits, not blocking OS/filesystem calls.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import sysconfig
import time
import types

REPOSITORY = "AAAHN-AAAHN/heiher-socks5-ios"
SOURCE = "3a6ba06abcbffc48bb5c7290a5e53709e3809fbc"
TREE = "6e745ac08beb1ab9eeb9e367cdaa28148d2f3600"
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
SOURCE_PINS = {
    "Build/runtime_environment.py": "32bdd3b00bfcbaebc0239add52fc0094db81f42afb84c342bb8d90a39befcabe",
    "Build/observe_host_during_command.py": "277f667fd17d96e9b3f6fbd733282d9b3622d782e20d2e2a4ab3a35d2b4575f8",
    "Build/ui_review.py": "3a155a9c78b5acdd5f40b3057d3077c309c4a5ff8545a509e8da1d591e50ad30",
    "Build/simulator_review.py": "e1897dd4aba4702ad6ee28332fa6d614606260e05c98c310ba6a4464c9e4590f",
}
HELPER_PINS = {
    "Bootstrap/observe_runtime_mounts.py": "af543a4fcfcab66b6eca6da0de678d7f3f226a53cd3aa1654d5ce55b868117d4",
    "Bootstrap/import_candidates.py": "1e647ab8a266a64097c5cc543f22d6a2c58010bfba8988b10fa4809589a6367e",
    "Bootstrap/record_runtime_python.py": "06546a77bf446de421fdd37771339a3e9e0c70b141b2a5574f1789ca905509bb",
    "Bootstrap/candidates.json": "ccbbc4bc9de3c07c3b64d15a215c355b9230314376b21f142f5934f7a8e2c6a9",
}
CONTEXT_KEYS = ("GITHUB_ACTIONS", "GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_REF", "GITHUB_EVENT_NAME",
                "GITHUB_WORKFLOW", "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA",
                "RUNNER_OS", "RUNNER_ARCH", "RUNNER_NAME", "DEVELOPER_DIR", "CANDIDATE")


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


def load_legacy(raw, path):
    require(sha(raw) == HELPER_PINS["Bootstrap/observe_runtime_mounts.py"], "Original mount observer changed")
    module = types.ModuleType("_unchanged_terminal_observer_pure_helpers")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), vars(module))
    return module


def pure_subset(raw, epochs):
    """Saved-data-only projection; never original preparation acceptance."""
    require(sha(raw) == SOURCE_PINS["Build/runtime_environment.py"], "Original common source changed")
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
    keys = {key for key, row in a.items() if row.get("runtimeIdentifier") != values["WATCH"]}
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


def bind_context(report, budget):
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
                "GITHUB_JOB": "startup_observation", "GITHUB_EVENT_NAME": "push",
                "GITHUB_REF": "refs/heads/work/udp-echo-build-20261028", "RUNNER_OS": "macOS",
                "RUNNER_ARCH": "ARM64", "CANDIDATE": "integrated",
                "DEVELOPER_DIR": "/Applications/Xcode_27.app/Contents/Developer"}
    require(__debug__ and all(os.environ.get(k) == v for k, v in expected.items()), "Wrong actual diagnostic context")
    require(sys.platform == "darwin" and platform.machine() == "arm64" and os.getuid() == os.geteuid() > 0,
            "Ordinary-user Darwin arm64 required")
    require(re.fullmatch("[0-9a-f]{40}", os.environ["GITHUB_SHA"])
            and os.environ["GITHUB_WORKFLOW_SHA"] == os.environ["GITHUB_SHA"], "Actual helper/workflow SHA differs")
    require(all(os.environ[k].isdigit() and int(os.environ[k]) > 0 for k in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")), "Invalid actual run identity")
    source = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "udp-source"
    control = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    require(Path.cwd() == source and source.resolve(strict=True) == source, "Wrong exact source worktree")
    require(Path(__file__).resolve(strict=True) == control / "Bootstrap/observe_runtime_startup.py", "Wrong tracked observer")
    python = Path("/Users/runner/hostedtoolcache/Python/3.14.9/arm64/bin/python3.14")
    require(os.environ["RUNNER_TOOL_CACHE"] == "/Users/runner/hostedtoolcache"
            and Path(str(python.parents[1]) + ".complete").is_file(), "Exact original Python cache incomplete")
    require(list(sys.version_info) == [3, 14, 9, "final", 0] and sys.implementation.name == "cpython"
            and sysconfig.get_config_var("Py_GIL_DISABLED") in (None, 0)
            and Path(sys.executable).resolve(strict=True) == python.resolve(strict=True), "Observer is not the pinned CPython interpreter")
    context_path = source / "artifacts/startup-context/context.json"
    context_raw = context_path.read_bytes()
    context = decode(context_raw)
    require(context["schema"] == "startup-observation-source-context-v1"
            and context["context_binding_complete"] is True and "error" not in context
            and context["actual_context"] == report["context"]
            and context["source"] == {"commit": SOURCE, "tree": TREE}
            and context["helper"]["commit"] == os.environ["GITHUB_SHA"], "Actual context/source/helper binding differs")
    require(context["commands"] and all(type(r["returncode"]) is int and r["returncode"] == 0 for r in context["commands"]), "Context Git observation failed")
    report["context_record"] = descriptor(context_path)
    report["source"] = context["source"]
    report["helper"] = context["helper"]
    report["bound_files"] = []
    for role, directory, pins in (("source", source, SOURCE_PINS), ("helper", control, HELPER_PINS)):
        for relative, expected_sha in pins.items():
            budget.check("source/control binding")
            path = directory / relative
            row = descriptor(path)
            require(row["sha256"] == expected_sha and context["files"][role][relative]["sha256"] == expected_sha,
                    "Pinned source/control changed: " + relative)
            report["bound_files"].append({"role": role, "relative_path": relative, **row})
    for relative in ("Bootstrap/observe_runtime_startup.py", ".github/workflows/udp-echo-candidate.yml"):
        row = descriptor(control / relative)
        require(all(row[k] == context["files"]["helper"][relative][k] for k in ("path", "bytes", "sha256")), "Actual diagnostic helper file changed")
        report["bound_files"].append({"role": "helper", "relative_path": relative, **row})
    after_path = source / "artifacts/runtime-python-provisioning/after.json"
    after = decode(after_path.read_bytes())
    require(after["phase"] == "after" and after["exact_required_cache_ready"] is True
            and all(after["context"][k] == os.environ[k] for k in after["context"]), "Original Python provisioning/context differs")
    report["original_python_provisioning_after"] = descriptor(after_path)
    importer = decode((source / "artifacts/candidate-prepare/result.json").read_bytes())
    require(importer["result"] == "PASS" and importer["helper_commit"] == os.environ["GITHUB_SHA"]
            and importer["refs_changed"] is False and importer["remote_mutations"] is False
            and [r["sha"] for r in importer["candidates"] if r["name"] == "integrated"] == [SOURCE], "Original importer did not prepare exact source")
    report["original_importer_result"] = descriptor(source / "artifacts/candidate-prepare/result.json")
    legacy = load_legacy((control / "Bootstrap/observe_runtime_mounts.py").read_bytes(), control / "Bootstrap/observe_runtime_mounts.py")
    return source, control, legacy


def main():
    started = time.monotonic()
    budget = Budget(started)
    report = {"schema": "fixed-daemon-startup-observation-v1", "result": "COLLECTION_IN_PROGRESS_NO_ACCEPTANCE",
              "started_utc": now(), "started_monotonic": started, "deadline_monotonic": budget.deadline,
              "context": {k: os.environ.get(k) for k in CONTEXT_KEYS}, "observer_pid": os.getpid(),
              "observer_uid": os.getuid(), "observer_euid": os.geteuid(), "argv": list(sys.argv),
              "planned_epoch_seconds": list(EPOCHS), "total_budget_seconds": TOTAL_SECONDS,
              "metadata_command_budget_seconds": COMMAND_SECONDS, "commands": [], "epochs": [], "epoch_files": [],
              "errors": [], "collection_complete": False, "formal_candidate_credit": False,
              "product_builds": 0, "runtime_acceptance": False, "original_preparation_executions": 0,
              "retirement_executions": 0, "consumer_executions": 0, "runtime_mutation_commands": 0,
              "daemon_device_or_unowned_process_signals": 0, "query_retries": 0,
              "completion_requires_actual_outer_wrapper_and_child_exit_zero_and_no_failure_marker": True,
              "actual_process_exit_requires_separate_caller_binding": True,
              "limitations": ["This is one fixed startup observation, not the original initial stage-before or a substitute for preparation.",
                  "Read-only simctl requests can start daemons and influence their scheduling; the runner may already have started services.",
                  "Epochs have fixed nominal times; real launch delays and non-atomic command/path timing are retained.",
                  "Matching endpoint samples never prove continuous stability or image identity; device/inode numbers can be reused.",
                  "The shared deadline bounds scheduled waits and child waits, not blocking filesystem, Popen, signal, or OS syscalls.",
                  "The unchanged outer host wrapper separately owns only its log-stream child and has its original bounded cleanup.",
                  "Unavailable paths including ENOENT remain evidence and cannot satisfy the original filesystem predicate.",
                  "Collection completion and saved-data-only subset predicates grant no preparation, runtime, build or publication acceptance."]}
    output = None
    exit_code = 1
    try:
        source, control, legacy = bind_context(report, budget)
        output = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "runtime-startup-observation"
        output.mkdir(exist_ok=False)
        report["observer_source"] = descriptor(Path(__file__))
        write_new(output / "planned-observation.json", {k: v for k, v in report.items() if k not in ("epochs", "commands")})
        queries = Queries(output, budget, report)
        collect_window(report, output, budget, queries, legacy)
        budget.check("saved metadata subset")
        report["original_pure_subset"] = pure_subset((source / "Build/runtime_environment.py").read_bytes(), report["epochs"])
        for row in report["bound_files"]:
            budget.check("final source/control metadata")
            actual = descriptor(Path(row["path"]))
            require(all(actual[k] == row[k] for k in ("path", "bytes", "sha256")), "Bound file changed during observation")
        budget.check("before final observation record")
        report.update(result="FIXED_WINDOW_COLLECTED_NO_ACCEPTANCE", collection_complete=True)
        exit_code = 0
    except BaseException as error:
        report["errors"].append({"stage": "collection", **error_record(error)})
        report["result"] = "COLLECTION_FAILED_NO_ACCEPTANCE"
        report["collection_complete"] = False
    finally:
        report.update(finished_utc=now(), finished_monotonic=time.monotonic(), intended_exit_status_before_final_record=exit_code)
        report["elapsed_seconds"] = report["finished_monotonic"] - started
        if report["elapsed_seconds"] > TOTAL_SECONDS:
            report["errors"].append({"stage": "finalization", "type": "BudgetExceeded", "message": "The actual observation exceeded its shared budget"})
            report.update(result="COLLECTION_FAILED_NO_ACCEPTANCE", collection_complete=False, intended_exit_status_before_final_record=1)
            exit_code = 1
        try:
            if output is None:
                # Context failures are still printed for the unchanged outer collector/job log.
                print(json.dumps(report, allow_nan=False), file=sys.stderr)
            else:
                write_new(output / "observation.json", report)
                if time.monotonic() > budget.deadline:
                    exit_code = 1
                    write_new(output / "final-write-budget-failure.json", {"result": "COLLECTION_FAILED_NO_ACCEPTANCE", "intended_process_exit_status": 1,
                              "reason": "Final metadata write/readback crossed the shared deadline", "finished_utc": now(),
                              "observation_record_must_not_be_treated_as_success": True})
        except BaseException as error:
            exit_code = 1
            print(json.dumps({"result": "COLLECTION_RECORDING_FAILED_NO_ACCEPTANCE", "error": error_record(error), "intended_process_exit_status": 1}), file=sys.stderr)
        print(json.dumps({"startup_observation_output": str(output) if output else None,
                          "intended_process_exit_status": exit_code, "formal_candidate_credit": False}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
