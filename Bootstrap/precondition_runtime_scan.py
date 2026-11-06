#!/usr/bin/env python3
"""Qualify one actual runtime before the unchanged preparation/retirement probe.

Reuse the pinned fixed-window collector and single advertised scan. This adapter
never launches original preparation, retirement, consumers or product builds.
"""
from __future__ import annotations

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
SOURCE = {"commit": "3a6ba06abcbffc48bb5c7290a5e53709e3809fbc", "tree": "6e745ac08beb1ab9eeb9e367cdaa28148d2f3600"}
SELF = "Bootstrap/precondition_runtime_scan.py"
WORKFLOW = ".github/workflows/udp-echo-candidate.yml"
WORKFLOW_NAME = "Precondition runtime once and diagnose original preparation"
WORKFLOW_SHA256 = "da3cc77a313ce46a52d213ba1db672b1cdb4884d94eb8e71a772fb94e6a9c0a3"
MODULE_PINS = {
    "Bootstrap/observe_runtime_startup.py": "481f56b53ab222e8eee732031416115957870da5e640f07504d71fdc893b3d08",
    "Bootstrap/probe_runtime_scan.py": "3f2215cd723c3ed0622672e39c63908b6971e50b959cc4e665b4ca4ea9568fe4",
}
EXTRA_HELPER_PINS = {
    "Bootstrap/run_candidate_runtime.sh": "8321264041563bcad1c3a650617297bfe749afc82e71765a010b424816ff24fc",
    "Bootstrap/run_runtime_recovery_probe.py": "038a70cc2bb458b06572edcc7e5d2bbd01e67581b94aa1a9e8a190a0789c33fd",
    "Bootstrap/retire_duplicate_registrations.py": "71ca6a00800ab6a1904d2fc8fa0b9cf87814c961c16770d4224af5e92d5efb6b",
    "Bootstrap/runtime_handoff.py": "228dbcc1e3e28e682e1d956fd91a9100add223e613bb4aa09d47231e16499580",
    "Bootstrap/ci_evidence.py": "827c8f69d562f60f416bfd9378b210beb9fa7aea28667716c54d4b449f5d3adc",
    WORKFLOW: WORKFLOW_SHA256,
}
UPSTREAM_SHA256 = "bc35da2894d16e4416f40086f44b6dfc3a74f4fcbd8fc152ba66188269545fc6"
PURE_LABELS = ("original_select_target_on_final_metadata", "original_watch_records_on_final_metadata",
               "original_require_same_filesystem_for_all_protected_nonwatch_records")


def require(value, message):
    if not value:
        raise RuntimeError(message)


def positive(value):
    return type(value) is int and value > 0


def pin_modules(control):
    """Check both source byte identities before either imported module executes."""
    sources = []
    for relative, expected in MODULE_PINS.items():
        path = control / relative
        info = path.lstat()
        require(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o644 and info.st_nlink == 1, "Linked or nonregular pinned module")
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, "Pinned observation module changed: " + relative)
        sources.append((path, raw))
    modules = []
    for path, raw in sources:
        module = types.ModuleType("_runtime_precondition_" + path.stem)
        module.__file__ = str(path)
        exec(compile(raw, str(path), "exec"), vars(module))
        modules.append(module)
    return modules


def validate_actual_environment(context, host):
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_JOB": "runtime",
                "GITHUB_REF": "refs/heads/work/udp-echo-build-20261028", "GITHUB_EVENT_NAME": "push",
                "RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64", "CANDIDATE": "integrated",
                "DEVELOPER_DIR": "/Applications/Xcode_27.app/Contents/Developer", "GITHUB_WORKFLOW": WORKFLOW_NAME}
    require(__debug__ and all(context.get(key) == value for key, value in expected.items()), "Wrong actual runtime context")
    require(re.fullmatch("[0-9a-f]{40}", context.get("GITHUB_SHA") or "")
            and context.get("GITHUB_WORKFLOW_SHA") == context["GITHUB_SHA"]
            and context.get("GITHUB_WORKFLOW_REF") == REPOSITORY + "/" + WORKFLOW + "@" + expected["GITHUB_REF"],
            "Actual workflow/ref/helper identity differs")
    require(all(re.fullmatch("[1-9][0-9]*", context.get(key) or "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")),
            "Invalid actual runtime run/attempt")
    require(host["platform"] == "darwin" and host["machine"] == "arm64" and host["uid"] == host["euid"] > 0,
            "Ordinary-user Darwin arm64 is required")
    require(host["python_version"] == [3, 14, 9, "final", 0] and host["python_implementation"] == "cpython"
            and host["gil_disabled"] in (None, 0), "Exact CPython3.14.9 interpreter is required")


def git_read(observer, root, arguments, budget, report):
    budget.check("runtime context Git read")
    argv = ["git", "-C", str(root), *arguments]
    row = {"argv": argv, "started_utc": observer.now(), "started_monotonic": budget.clock(), "returncode": None}
    report["context_git_commands"].append(row)
    try:
        result = subprocess.run(argv, capture_output=True, timeout=min(5.0, budget.remaining()))
        row.update(returncode=result.returncode, stdout=result.stdout.decode("utf-8"), stderr=result.stderr.decode("utf-8"))
        require(type(result.returncode) is int and result.returncode == 0 and result.stderr == b"", "Actual Git context read failed")
        budget.check("after runtime context Git read")
        return result.stdout
    except BaseException as error:
        row["error"] = observer.error_record(error)
        raise
    finally:
        row.update(finished_utc=observer.now(), finished_monotonic=budget.clock())


def git_worktree(observer, root, expected, budget, report):
    values = git_read(observer, root, ["rev-parse", "HEAD", "HEAD^{tree}"], budget, report).decode().splitlines()
    require(len(values) == 2 and all(re.fullmatch("[0-9a-f]{40}", value) for value in values), "Invalid Git commit/tree")
    identity = {"commit": values[0], "tree": values[1]}
    require(all(identity.get(key) == value for key, value in expected.items()), "Wrong actual source/helper Git identity")
    for arguments in (["diff", "--no-ext-diff", "--no-textconv", "--exit-code", "HEAD", "--"],
                      ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--exit-code", "HEAD", "--"]):
        require(git_read(observer, root, arguments, budget, report) == b"", "Dirty source/helper worktree")
    return identity


def tracked_file(observer, root, identity, relative, expected, budget, report, role):
    budget.check("tracked file binding")
    path = root / relative
    require(path.resolve(strict=True) == path, "Tracked file alias is not canonical")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o644 and info.st_nlink == 1,
            "Tracked helper/source file mode or link count differs")
    row = observer.descriptor(path)
    require(expected is None or row["sha256"] == expected, "Frozen source/helper bytes changed: " + relative)
    raw = path.read_bytes()
    require(observer.sha(raw) == row["sha256"], "Tracked file changed after descriptor")
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    entry = git_read(observer, root, ["ls-tree", identity["commit"], "--", relative], budget, report)
    require(entry == ("100644 blob " + blob + "\t" + relative + "\n").encode(), "File is not the actual tracked Git blob")
    report["bound_files"].append({"role": role, "relative_path": relative, "git_blob": blob, "git_mode": "100644", **row})
    return raw


def bind_receipt(observer, path, relative, report, budget):
    budget.check("original receipt binding")
    require(path.resolve(strict=True) == path, "Original receipt path is linked")
    row = observer.descriptor(path)
    raw = path.read_bytes()
    require(observer.sha(raw) == row["sha256"], "Original receipt changed after descriptor")
    report["bound_files"].append({"role": "original-receipt", "relative_path": relative, **row})
    return observer.decode(raw), row


def validate_restorer(receipt, metadata, context, helper, pins):
    consumer = {"repository": REPOSITORY, "run_id": context["GITHUB_RUN_ID"], "attempt": context["GITHUB_RUN_ATTEMPT"],
                "helper": helper, "job": "runtime", "runner_os": "macOS"}
    require(receipt["status"] == "VERIFIED_RUNTIME_INPUT_RESTORED" and receipt["consumer"] == consumer,
            "Original restorer does not bind this actual runtime")
    manifest = receipt["manifest"]
    require(type(manifest["schema"]) is int and manifest["schema"] == 1 and manifest["candidate"] == "integrated"
            and manifest["source"] == SOURCE and manifest["native_pins"] == pins
            and type(manifest["files"]) is dict and manifest["files"], "Wrong original source/native input manifest")
    attempt = manifest["producer"]["attempt"]
    require(type(attempt) is str and re.fullmatch("[1-9][0-9]*", attempt) and attempt == consumer["attempt"],
            "This precondition requires the exact same producer and consumer attempt")
    require(manifest["producer"] == {**consumer, "attempt": attempt, "job": "build"}, "Producer context differs")
    job = receipt["producer_job"]
    require(positive(job["id"]) and type(job["run_id"]) is int and job["run_id"] == int(consumer["run_id"])
            and type(job["run_attempt"]) is int and job["run_attempt"] == int(attempt)
            and job["head_sha"] == helper["commit"] and job["status"] == "completed" and job["conclusion"] == "success"
            and job["name"] == "build (integrated, " + SOURCE["commit"] + ", xcode-27, true)", "Actual producer job binding differs")
    stages = [row for row in job["steps"] if row["name"] == "Execute the exact candidate owner gates"]
    require(len(stages) == 1 and stages[0]["conclusion"] == "success", "Original producer execution did not succeed")
    require(positive(receipt["input_artifact_id"]) and positive(receipt["input_artifact_size"])
            and metadata["id"] == receipt["input_artifact_id"] and metadata["size_in_bytes"] == receipt["input_artifact_size"]
            and metadata["digest"] == receipt["input_artifact_digest"]
            and re.fullmatch("sha256:[0-9a-f]{64}", receipt["input_artifact_digest"])
            and re.fullmatch("[0-9a-f]{64}", receipt["archive_sha256"]), "Original artifact identity differs")
    require(metadata["name"] == "UDP-Echo-runtime-integrated-" + consumer["run_id"] + "-" + attempt
            and metadata["workflow_run"]["id"] == int(consumer["run_id"])
            and metadata["workflow_run"]["head_sha"] == helper["commit"]
            and metadata["verified_producer_job"] == job, "Original artifact/producer metadata differs")
    return {"producer_job_id": job["id"], "producer_attempt": int(attempt), "consumer_attempt": int(consumer["attempt"]),
            "runtime_job_slot": "runtime/integrated", "numeric_runtime_job_id": None,
            "numeric_runtime_job_id_requires_external_actual_jobs_API_join": True, "restored_manifest_files": len(manifest["files"])}


def bind_runtime_context(observer, scanner, report, budget, source, control):
    """A new actual-runtime binding; never calls or impersonates startup bind_context."""
    report["source"] = git_worktree(observer, source, SOURCE, budget, report)
    report["helper"] = git_worktree(observer, control, {"commit": report["context"]["GITHUB_SHA"]}, budget, report)
    report["bound_files"] = []
    for relative, expected in {**observer.SOURCE_PINS, "Build/upstream.json": UPSTREAM_SHA256}.items():
        tracked_file(observer, source, report["source"], relative, expected, budget, report, "source")
    helper_pins = {**observer.HELPER_PINS, **MODULE_PINS, **EXTRA_HELPER_PINS, SELF: None}
    for relative, expected in helper_pins.items():
        tracked_file(observer, control, report["helper"], relative, expected, budget, report, "helper")
    after, report["original_python_provisioning_after"] = bind_receipt(observer,
        source / "artifacts/runtime-python-provisioning/after.json", "runtime-python-provisioning/after.json", report, budget)
    require(after["phase"] == "after" and after["exact_required_cache_ready"] is True
            and all(after["context"].get(key) == report["context"][key] for key in
                    ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")),
            "Original Python provisioning receipt does not bind this runtime")
    importer, report["original_importer_result"] = bind_receipt(observer,
        source / "artifacts/candidate-prepare/result.json", "candidate-prepare/result.json", report, budget)
    require(importer["result"] == "PASS" and importer["helper_commit"] == report["helper"]["commit"]
            and importer["refs_changed"] is False and importer["remote_mutations"] is False
            and [row["sha"] for row in importer["candidates"] if row["name"] == "integrated"] == [SOURCE["commit"]],
            "Original importer did not prepare this exact source/helper")
    receipt, report["original_restorer_receipt"] = bind_receipt(observer,
        source / "artifacts/runtime-input/integrated/consumer.json", "runtime-input/integrated/consumer.json", report, budget)
    download = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True) / "runtime-download"
    metadata, report["original_input_artifact_metadata"] = bind_receipt(observer,
        download / "artifact.json", "runtime-download/artifact.json", report, budget)
    pins = observer.decode((source / "Build/upstream.json").read_bytes())["sources"]
    report["restorer_identity"] = validate_restorer(receipt, metadata, report["context"], report["helper"], pins)
    archive = observer.descriptor(download / "runtime-input.zip")
    require(archive["bytes"] == receipt["input_artifact_size"] and archive["sha256"] == receipt["input_artifact_digest"][7:],
            "Actual producer input ZIP bytes differ from the restored artifact")
    report["bound_files"].append({"role": "original-input-zip", "relative_path": "runtime-download/runtime-input.zip", **archive})
    scanner.recheck_files(observer, report, budget)
    context_directory = source / "artifacts/runtime-scan-precondition-context"
    context_directory.mkdir(exist_ok=False)
    record = {"schema": "same-runtime-precondition-context-v1", "context_binding_complete": True,
              "actual_context": report["context"], "actual_host": report["host"], "source": report["source"],
              "helper": report["helper"], "source_root": str(source), "helper_root": str(control),
              "files": list(report["bound_files"]), "git_commands": report["context_git_commands"],
              "restorer_identity": report["restorer_identity"], "original_runtime_acceptance": False,
              "startup_context_or_job_impersonation": False}
    report["context_record"] = observer.write_new(context_directory / "context.json", record)
    report["bound_files"].append({"role": "actual-runtime-context", "relative_path": "runtime-scan-precondition-context/context.json", **report["context_record"]})
    budget.check("new actual runtime context recorded")
    return observer.load_legacy((control / "Bootstrap/observe_runtime_mounts.py").read_bytes(), control / "Bootstrap/observe_runtime_mounts.py")


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
    for key, runtime in sorted(old.items()):
        require(runtime["identifier"] == key, "Baseline runtime UUID key differs from its raw identifier")
        asset_paths.update(runtime[field] for field in ("path", "parentMountPath"))
        if runtime["state"] == "Ready":
            require(key in new and scanner.canonical(runtime) == scanner.canonical(new[key]),
                    "Baseline Ready UUID or full raw record changed across the scan: " + key)
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


def main():
    started, observer, output, report, exit_code, active_budget = time.monotonic(), None, None, None, 1, None
    try:
        require(len(sys.argv) == 1 and __debug__, "No arguments or optimized execution are permitted")
        control = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
        require(Path(__file__).resolve(strict=True) == control / SELF, "Wrong actual tracked precondition adapter")
        observer, scanner = pin_modules(control)
        context = {key: os.environ.get(key) for key in observer.CONTEXT_KEYS}
        host = {"platform": sys.platform, "machine": platform.machine(), "uid": os.getuid(), "euid": os.geteuid(),
                "python_version": list(sys.version_info), "python_implementation": sys.implementation.name,
                "gil_disabled": sysconfig.get_config_var("Py_GIL_DISABLED"), "executable": sys.executable}
        validate_actual_environment(context, host)
        python = Path("/Users/runner/hostedtoolcache/Python/3.14.9/arm64/bin/python3.14")
        require(os.environ["RUNNER_TOOL_CACHE"] == "/Users/runner/hostedtoolcache"
                and Path(str(python.parents[1]) + ".complete").is_file()
                and Path(sys.executable).resolve(strict=True) == python.resolve(strict=True), "Actual original Python cache is incomplete or different")
        temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        source = temporary / "udp-source"
        require(Path.cwd() == source and source.resolve(strict=True) == source, "Wrong exact source worktree cwd")
        output = temporary / "runtime-scan-precondition"
        output.mkdir(exist_ok=False)
        budget = observer.Budget(started)
        active_budget = budget
        report = {"schema": "same-runtime-precondition-scan-v1", "result": "IN_PROGRESS_NO_ORIGINAL_ACCEPTANCE",
                  "started_utc": observer.now(), "started_monotonic": started, "pid": os.getpid(), "argv": list(sys.argv),
                  "context": context, "host": host, "context_git_commands": [], "bound_files": [], "stage": "actual-runtime-context",
                  "control_commands": [], "errors": [], "phases": {"baseline": {"status": "NOT_RUN"}, "postscan": {"status": "NOT_RUN"}},
                  "formal_candidate_credit": False, "runtime_acceptance": False, "publication_credit": False,
                  "original_preparation_executions": 0, "retirement_executions": 0, "consumer_executions": 0, "product_builds": 0,
                  "query_or_scan_retries": 0, "maximum_runtime_mutation_commands": 1,
                  "owned_add_delete_verify_boot_or_daemon_signal_commands": 0,
                  "observation_phase_budget_seconds": 150, "help_budget_seconds": 10, "scan_budget_seconds": 120,
                  "actual_exit_requires_separate_outer_wrapper_binding": True,
                  "completion_requires_actual_outer_exit_zero_and_no_final_handoff_failure_marker": True,
                  "limitations": ["One global scan is allowed only for an exact known fixed-baseline issue.",
                      "Observed precondition qualification is not original preparation, V2 retirement isolation, or consumer acceptance.",
                      "Shared old Unusable aliases may still fail unchanged original/V2 guards; no success is promised.",
                      "Fixed endpoints do not prove continuous stability; original preparation captures its own later boundary.",
                      "Existing phase/command budgets do not forcibly interrupt blocking OS calls."]}
        legacy = bind_runtime_context(observer, scanner, report, budget, source, control)
        observer.write_new(output / "planned-precondition.json", report)
        active_budget = run_protocol(observer, scanner, source, output, report, legacy, budget)
        report["result"] = "OBSERVED_PRECONDITION_QUALIFIED_NO_ORIGINAL_ACCEPTANCE"
        exit_code = 0
    except BaseException as error:
        if report is None:
            print(json.dumps({"result": "PRECONDITION_INITIALIZATION_FAILED_NO_ORIGINAL_ACCEPTANCE",
                              "error": {"type": type(error).__name__, "message": str(error)}}), file=sys.stderr)
        else:
            report["errors"].append({"stage": report["stage"], **observer.error_record(error)})
            report["result"] = "PRECONDITION_FAILED_NO_ORIGINAL_ACCEPTANCE"
    finally:
        if report is not None:
            exit_code = finalize_report(observer, scanner, output, report, active_budget, exit_code)
        print(json.dumps({"precondition_output": str(output) if output else None,
                          "intended_process_exit_status": exit_code, "formal_candidate_credit": False}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
