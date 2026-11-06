#!/usr/bin/env python3
"""One advertised runtime scan between two fixed windows; no acceptance gate.

The unchanged startup observer owns collection. This diagnostic owns at most one
scan-and-mount mutation, never add/delete/verify, device lifecycle or daemon kill.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import types

OBSERVER_SHA256 = "481f56b53ab222e8eee732031416115957870da5e640f07504d71fdc893b3d08"
SELF_PATH = "Bootstrap/probe_runtime_scan.py"
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


def require(value, message):
    if not value:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_observer():
    """Pin before import; importing this unchanged module does not call main."""
    path = Path(__file__).resolve(strict=True).with_name("observe_runtime_startup.py")
    require(stat.S_ISREG(path.lstat().st_mode), "Original observer must be a regular file")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == OBSERVER_SHA256, "Original observer bytes changed")
    module = types.ModuleType("_unchanged_runtime_startup_observer")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), vars(module))
    return module


def bind_self(observer, report, source, control, budget):
    budget.check("new orchestrator context")
    own = Path(__file__).resolve(strict=True)
    require(own == control / SELF_PATH, "Wrong tracked scan orchestrator")
    context = observer.decode((source / "artifacts/startup-context/context.json").read_bytes())
    row = observer.descriptor(own)
    bound = context["files"]["helper"][SELF_PATH]
    raw = own.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(all(row[k] == bound[k] for k in ("path", "bytes", "sha256"))
            and bound["git_blob"] == blob and bound["git_mode"] == "100644",
            "New orchestrator differs from actual workflow Git context")
    report["bound_files"].append({"role": "helper", "relative_path": SELF_PATH, **row})
    budget.check("new orchestrator bound")


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
    row = {"schema": "scan-probe-fixed-window-v1", "phase": phase,
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
        row["original_pure_subset"] = observer.pure_subset((source / "Build/runtime_environment.py").read_bytes(), row["epochs"])
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


def run_protocol(observer, source, output, report, legacy, baseline_budget, *, collect=collect_phase, command=run_command):
    report["stage"] = "baseline"
    baseline = collect(observer, source, output, report, legacy, "baseline", baseline_budget)
    report["stage"] = "baseline-classification"
    report["baseline_decision"] = classify_baseline(baseline)
    if report["baseline_decision"]["result"] == "UNNEEDED_NOT_RUN":
        report["phases"]["postscan"]["reason"] = "No supported baseline issue; scan was not run"
        return "SCAN_UNNEEDED_NOT_RUN_NO_ACCEPTANCE"
    report["stage"] = "actual-runtime-help"
    raw = command(observer, output, report, "runtime-help")
    report["help_advertisement"] = advertised_scan(raw)
    recheck_files(observer, report)
    report["stage"] = "single-scan-and-mount"
    command(observer, output, report, "scan-and-mount")
    report["stage"] = "postscan"
    seed = {r["path"]: r["references"] for r in baseline["epochs"][-1]["paths"]}
    post = collect(observer, source, output, report, legacy, "postscan", observer.Budget(time.monotonic()), seed=seed)
    before, after = baseline["epochs"][-1]["runtime_inventory"], post["epochs"][-1]["runtime_inventory"]
    report["full_raw_inventory_delta"] = {
        "added": {k: after[k] for k in sorted(set(after) - set(before))},
        "removed": {k: before[k] for k in sorted(set(before) - set(after))},
        "changed": {k: {"before": before[k], "after": after[k]} for k in sorted(set(before) & set(after)) if canonical(before[k]) != canonical(after[k])}}
    try:
        report["postscan_observed_condition"] = classify_baseline(post)
    except Exception as error:
        report["postscan_observed_condition"] = {"result": "OUTSIDE_BASELINE_DIAGNOSTIC_PRECONDITION_NO_ACCEPTANCE",
                                                 "error": observer.error_record(error)}
    return "FIXED_SCAN_SEQUENCE_COLLECTED_NO_ACCEPTANCE"


def main():
    started = time.monotonic()
    observer, output, report = None, None, None
    exit_code = 1
    try:
        require(len(sys.argv) == 1 and __debug__, "This diagnostic accepts no arguments or optimized execution")
        observer = load_observer()
        budget = observer.Budget(started)
        report = {"schema": "single-runtime-scan-diagnostic-v2", "result": "IN_PROGRESS_NO_ACCEPTANCE",
                  "context": {k: os.environ.get(k) for k in observer.CONTEXT_KEYS},
                  "started_utc": observer.now(), "started_monotonic": started, "pid": os.getpid(),
                  "argv": list(sys.argv), "stage": "context", "control_commands": [], "errors": [],
                  "phases": {"baseline": {"status": "NOT_RUN"}, "postscan": {"status": "NOT_RUN"}},
                  "formal_candidate_credit": False, "runtime_acceptance": False, "original_preparation_executions": 0,
                  "retirement_executions": 0, "consumer_executions": 0, "product_builds": 0,
                  "owned_add_delete_verify_boot_or_daemon_signal_commands": 0, "query_or_scan_retries": 0,
                  "diagnostic_precondition_revision": "observed-ready-tvos-enoent-422694",
                  "maximum_runtime_mutation_commands": 1, "observation_phase_budget_seconds": 150,
                  "help_budget_seconds": 10, "scan_budget_seconds": 120,
                  "actual_exit_requires_separate_outer_wrapper_binding": True,
                  "limitations": ["scan-and-mount reconciles all runtime storage locations; this is an actual mutation.",
                      "This test does not establish that scan can repair an already registered Ready but unmounted runtime.",
                      "All raw unknown fields and filesystem errors remain evidence; fixed final samples do not prove continuous stability.",
                      "Each observation uses the unchanged 150-second shared collection budget; control child caps include cleanup.",
                      "Budgets bound scheduled/child waits, not blocking filesystem, Popen, signal, or other OS syscalls.",
                      "No original preparation, retirement, consumer, product, or formal acceptance follows this diagnostic."]}
        source, control, legacy = observer.bind_context(report, budget)
        bind_self(observer, report, source, control, budget)
        output = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "runtime-scan-observation"
        output.mkdir(exist_ok=False)
        observer.write_new(output / "planned-scan.json", report)
        report["result"] = run_protocol(observer, source, output, report, legacy, budget)
        recheck_files(observer, report)
        exit_code = 0
    except BaseException as error:
        if report is None:
            print(json.dumps({"result": "SCAN_DIAGNOSTIC_INITIALIZATION_FAILED_NO_ACCEPTANCE",
                              "type": type(error).__name__, "message": str(error)}), file=sys.stderr)
        else:
            report["errors"].append({"stage": report["stage"], **observer.error_record(error)})
            report["result"] = "SCAN_DIAGNOSTIC_FAILED_NO_ACCEPTANCE"
    finally:
        if report is not None:
            report.update(finished_utc=observer.now(), finished_monotonic=time.monotonic(),
                          intended_exit_status_before_final_record=exit_code)
            report["elapsed_seconds"] = report["finished_monotonic"] - started
            report["actual_launched_runtime_mutation_commands"] = sum(r["launches"] for r in report["control_commands"] if r["mutation"])
            report["actual_scan_spawn_attempts"] = sum(r["launch_attempts"] for r in report["control_commands"] if r["mutation"])
            try:
                if output is None:
                    print(json.dumps(report, allow_nan=False), file=sys.stderr)
                else:
                    observer.write_new(output / "scan-diagnostic.json", report)
            except BaseException as error:
                exit_code = 1
                print(json.dumps({"result": "SCAN_DIAGNOSTIC_RECORDING_FAILED_NO_ACCEPTANCE",
                                  "error": observer.error_record(error)}), file=sys.stderr)
        print(json.dumps({"scan_diagnostic_output": str(output) if output else None,
                          "intended_process_exit_status": exit_code, "formal_candidate_credit": False}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
