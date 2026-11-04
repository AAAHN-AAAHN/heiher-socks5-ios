#!/usr/bin/env python3
"""Stage the same iOS 27.0 DMG with the explicit Xcode 27.1 policy.

Only official add/verify commands prepare the disposable runner. The original
lifecycle and all of its deadlines remain unchanged and run at most once.
"""
import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time

from ios_runtime_signature_preflight import recording_failure, save_preserving_failure, select_target
from simulator_runtime_xcode271_policy import select_exact, validate_toolchain
from watch_runtime_preflight import IOS, WATCH, canonical, decode, inventory

IOS_ASSET = Path("/System/Library/AssetsV2/com_apple_MobileAsset_iOSSimulatorRuntime/3e800c38767f9f2c5fc86acdad7adf44565e051a.asset/AssetData")
WATCH_ASSET = "/System/Library/AssetsV2/com_apple_MobileAsset_watchOSSimulatorRuntime/3f39f470a745ea5cc62fc1967054b0dcf8fb0875.asset/AssetData"
WATCH_MOUNTS = ("/Library/Developer/CoreSimulator/Volumes/watchOS_24R362",
                "/private/var/run/com.apple.security.cryptexd/mnt/watchOS_24R362")
WATCH_BUNDLE_SUFFIX = "/Library/Developer/CoreSimulator/Profiles/Runtimes/watchOS 27.0.simruntime"
WATCH_FS_FIELDS = ("device", "inode", "mode", "uid", "gid", "is_directory", "is_regular")
IMAGES = Path("/Library/Developer/CoreSimulator/Images")
VOLUMES = Path("/Library/Developer/CoreSimulator/Volumes")
DEVICE = "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
ADD_TIMEOUT, VERIFY_TIMEOUT, METADATA_TIMEOUT, HASH_BUDGET = 180, 120, 10, 60
PATH_FIELDS = ("path", "parentMountPath", "mountPath", "runtimeBundlePath")
SOURCE_FILES = {
    "simulator_runtime_xcode271_policy.py": "dfdb72668e6e8f2e361801bdb766d9b69ded08c1843c3e1ed93cbb9a28e26c3c",
    "simulator_runtime_compare.py": "a855b4e2cf0481f389776a56876345ffbb43f41b744b69d853c15b17bc80de81",
    "simulator_comparison_diagnostics.py": "2674479d846b113204ba0b3c2184f81ba045c5f519c3d1d78c8c04611980e4e0",
    "watch_runtime_preflight.py": "e50a7b7d39b8abf80698b9c5401cbe09b9d48b66059c96ee06e6695b32e88c02",
    "ios_runtime_signature_preflight.py": "cd8024e1c37a2596ab39b53f6cac4f29c4c625d321e445febf36883d6c0ff3ef",
}
READ_COMMANDS = {
    "source-head": ["git", "rev-parse", "HEAD"],
    "xcode-version": ["xcodebuild", "-version"],
    "simulator-sdk": ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"],
    "simctl-path": ["xcrun", "--find", "simctl"],
    "xcodebuild-path": ["xcrun", "--find", "xcodebuild"],
    "runtime-help": ["xcrun", "simctl", "help", "runtime"],
    "process-identity": ["id"],
    "devices-before": ["xcrun", "simctl", "list", "devices", "-j"],
    "runtime-images-before": ["xcrun", "simctl", "runtime", "list", "-j"],
    "runtime-images-after-add": ["xcrun", "simctl", "runtime", "list", "-j"],
    "runtime-images-after-verify": ["xcrun", "simctl", "runtime", "list", "-j"],
    "logical-runtimes-after": ["xcrun", "simctl", "list", "runtimes", "-j"],
    "device-types-after": ["xcrun", "simctl", "list", "devicetypes", "-j"],
    "devices-after": ["xcrun", "simctl", "list", "devices", "-j"],
}


def path_snapshot(value):
    """Missing/transitional metadata is evidence, not a collection exception."""
    row = {"value": value}
    if value is None:
        return dict(row, capture="field_absent")
    if not isinstance(value, str) or not Path(value).is_absolute():
        return dict(row, capture="invalid_path")
    try:
        path = Path(value)
        info = path.stat()
        row.update(capture="observed", resolved_path=str(path.resolve()), device=info.st_dev,
                   inode=info.st_ino, mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid,
                   is_directory=stat.S_ISDIR(info.st_mode), is_regular=stat.S_ISREG(info.st_mode))
    except OSError as error:
        row.update(capture="unavailable", error={"type": type(error).__name__, "message": str(error), "errno": error.errno})
    return row


def filesystem_snapshot(data):
    inventory(data)
    return {key: {field: path_snapshot(row.get(field)) for field in PATH_FIELDS} for key, row in data.items()}


def require_same_filesystem(before, after, keys, fields=PATH_FIELDS):
    for key in keys:
        for field in fields:
            old, new = before[key][field], after[key][field]
            if old.get("capture") != "observed" or new.get("capture") != "observed" or old != new:
                raise ValueError("Required unchanged filesystem identity differs: " + key + ":" + field)


def watch_records(data):
    result = {}
    for key, row in data.items():
        if row.get("runtimeIdentifier") != WATCH and row.get("platformIdentifier") != "com.apple.platform.watchsimulator":
            continue
        expected = {"runtimeIdentifier": WATCH, "platformIdentifier": "com.apple.platform.watchsimulator",
                    "version": "27.0", "build": "24R362", "path": WATCH_ASSET, "parentMountPath": WATCH_ASSET,
                    "kind": "Patchable Cryptex Disk Image", "supportedArchitectures": ["arm64"], "signatureState": "Unknown"}
        if any(row.get(field) != value for field, value in expected.items()):
            raise ValueError("Watch record is outside the observed fixed asset identity: " + key)
        if row.get("state") not in ("Ready", "Unusable", "Copying", "Deleting"):
            raise ValueError("Unexpected watch registration state: " + key)
        result[key] = row
    return result


def assess_old_cryptex(before, after):
    if after.get("state") == "Ready":
        if canonical(before) != canonical(after):
            raise ValueError("Original Ready iOS cryptex record changed")
        return "original_ready_record_preserved"
    if (after.get("state") != "Unusable" or after.get("unusableErrorMessage") != "Cryptex Mount Preferred"
            or after.get("unusableSubstate") != "Cryptex Mount Preferred"):
        raise ValueError("Original cryptex did not remain Ready or enter the declared exact Unusable state")
    detail = after.get("unusableErrorDetail")
    if detail is not None and (not isinstance(detail, str) or "Cryptex Mount Preferred" not in detail):
        raise ValueError("Unexpected original cryptex unusable detail")
    for field in ("mountPath", "runtimeBundlePath"):
        if field in after and after[field] != before[field]:
            raise ValueError("Original cryptex mount metadata changed to a different path")
    allowed = {"state", "mountPath", "runtimeBundlePath", "unusableErrorMessage", "unusableSubstate", "unusableErrorDetail"}
    if canonical({k: v for k, v in before.items() if k not in allowed}) != canonical({k: v for k, v in after.items() if k not in allowed}):
        raise ValueError("Original cryptex identity changed beyond its declared registration-state effect")
    return "original_asset_retained_unusable_cryptex_mount_preferred"


def assess_scope(before, after, old_id, new_id=None, *, before_fs, after_fs):
    inventory(before)
    inventory(after)
    before_watch, after_watch = watch_records(before), watch_records(after)
    if any(key in after and key not in after_watch for key in before_watch):
        raise ValueError("An existing watch UUID changed runtime/platform classification")
    watch_dynamic = {"identifier", "state", "mountPath", "runtimeBundlePath",
                     "unusableErrorMessage", "unusableSubstate", "unusableErrorDetail"}
    watch_templates = {canonical({field: value for field, value in row.items() if field not in watch_dynamic})
                       for row in before_watch.values()}
    for row in (*before_watch.values(), *after_watch.values()):
        for field, paths in (("mountPath", WATCH_MOUNTS),
                             ("runtimeBundlePath", tuple(path + WATCH_BUNDLE_SUFFIX for path in WATCH_MOUNTS))):
            if field in row and row[field] not in paths:
                raise ValueError("Watch path is outside the two actually observed exact mount aliases")
        if ("mountPath" in row and "runtimeBundlePath" in row
                and row["runtimeBundlePath"] != row["mountPath"] + WATCH_BUNDLE_SUFFIX):
            raise ValueError("Watch mount and bundle paths name different aliases")
    for key, row in after_watch.items():
        stable = canonical({field: value for field, value in row.items() if field not in watch_dynamic})
        if stable not in watch_templates:
            raise ValueError("Watch metadata changed beyond the observed same-asset transition fields: " + key)
        for field in ("path", "parentMountPath"):
            current = after_fs[key][field]
            if (current.get("capture") != "observed"
                    or not any(current == before_fs[old_key][field] for old_key in before_watch)):
                raise ValueError("Watch asset filesystem identity changed: " + key + ":" + field)
        for field in ("mountPath", "runtimeBundlePath"):
            observed_paths = {value[field] for value in before_watch.values() if isinstance(value.get(field), str)}
            current = after_fs[key][field]
            if current.get("capture") in ("field_absent", "unavailable"):
                if row["state"] not in ("Unusable", "Copying", "Deleting"):
                    raise ValueError("Ready watch mount/bundle filesystem identity is unavailable: " + key)
                continue
            if (current.get("capture") != "observed" or current.get("value") != row.get(field)
                    or current.get("resolved_path") != row.get(field)):
                raise ValueError("Watch mount/bundle capture does not name its exact path: " + key)
            if row[field] not in observed_paths:
                # Run417180/a1 observed the same device/inode at these two paths.
                # Admit that exact relocation only with its before/after FS proof.
                matches = [before_fs[old_key][field] for old_key in before_watch
                           if before_fs[old_key][field].get("capture") == "observed"
                           and before_fs[old_key][field].get("resolved_path") == before_watch[old_key].get(field)]
                if not any(all(current.get(name) == old.get(name) for name in WATCH_FS_FIELDS) for old in matches):
                    raise ValueError("Watch new mount alias does not preserve the observed filesystem object: " + key + ":" + field)
    protected = set(before) - set(before_watch) - {old_id}
    if any(key not in after or canonical(before[key]) != canonical(after[key]) for key in protected):
        raise ValueError("Another iOS/tvOS/xrOS or unrelated runtime changed or disappeared")
    if old_id not in after:
        raise ValueError("Original selected cryptex UUID disappeared")
    old_effect = assess_old_cryptex(before[old_id], after[old_id])
    additions = set(after) - set(before) - set(after_watch)
    if len(additions) != 1 or (new_id is not None and additions != {new_id}):
        raise ValueError("Expected exactly one new selected-iOS image registration")
    selected_id = next(iter(additions))
    row = after[selected_id]
    expected = {"runtimeIdentifier": IOS, "platformIdentifier": "com.apple.platform.iphonesimulator",
                "version": "27.0", "build": "24A434", "state": "Ready", "supportedArchitectures": ["arm64"]}
    if any(row.get(field) != value for field, value in expected.items()):
        raise ValueError("New image is not the exact Ready arm64 iOS 27.0 build 24A434")
    if not isinstance(row.get("kind"), str) or "cryptex" in row["kind"].lower() or not row["kind"]:
        raise ValueError("New registration is not a staged disk image")
    if not isinstance(row.get("signatureState"), str) or not row["signatureState"]:
        raise ValueError("New image has no signature state")
    return {"new_uuid": selected_id, "new_record": row, "old_cryptex_effect": old_effect,
            "protected_uuids": sorted(protected), "watch_before": before_watch, "watch_after": after_watch,
            "watch_records_changed": canonical(before_watch) != canonical(after_watch)}


def file_identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid, "gid": info.st_gid, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def hash_regular_file(path):
    """Hash one exact non-symlink regular file and detect changes during reading."""
    started = time.monotonic()
    original = path.lstat()
    if not stat.S_ISREG(original.st_mode) or original.st_size <= 0:
        raise ValueError("DMG must be a nonempty non-symlink regular file: " + str(path))
    flags = os.O_RDONLY | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if file_identity(os.fstat(stream.fileno())) != file_identity(original):
            raise ValueError("DMG identity changed before opening")
        digest = hashlib.sha256()
        while True:
            if time.monotonic() - started > HASH_BUDGET:
                raise TimeoutError("DMG hashing exceeded its separate 60-second processing budget")
            chunk = stream.read(4 * 1024 * 1024)
            if time.monotonic() - started > HASH_BUDGET:
                raise TimeoutError("DMG hashing exceeded its separate 60-second processing budget")
            if not chunk:
                break
            digest.update(chunk)
        final = os.fstat(stream.fileno())
    if file_identity(original) != file_identity(final) or file_identity(path.lstat()) != file_identity(original):
        raise ValueError("DMG changed while being hashed")
    return {"path": str(path), "resolved_path": str(path.resolve()), "identity": file_identity(final),
            "sha256": digest.hexdigest(), "elapsed_seconds": time.monotonic() - started}


def same_file(before, after):
    return all(before[field] == after[field] for field in ("path", "resolved_path", "identity", "sha256"))


def source_dmg(row):
    if (row.get("path") != str(IOS_ASSET) or row.get("parentMountPath") != str(IOS_ASSET)
            or row.get("kind") != "Patchable Cryptex Disk Image" or row.get("supportedArchitectures") != ["arm64"]
            or row.get("signatureState") != "Unknown"
            or IOS_ASSET.resolve() != IOS_ASSET):
        raise ValueError("Selected MobileAsset is not the exact observed iOS 24A434 source")
    restore = IOS_ASSET / "Restore"
    if restore.is_symlink() or not restore.is_dir() or restore.resolve() != restore:
        raise ValueError("Exact selected Restore directory is unavailable or indirect")
    candidates = [path for path in restore.iterdir() if path.suffix == ".dmg"]
    if len(candidates) != 1 or not stat.S_ISREG(candidates[0].lstat().st_mode):
        raise ValueError("Require exactly one direct non-symlink regular .dmg in the selected Restore directory")
    return candidates[0]


def staged_dmg(row):
    value = row.get("path")
    if not isinstance(value, str):
        raise ValueError("New staged image has no path")
    path = Path(value)
    if (not path.is_absolute() or path.suffix != ".dmg" or path.is_symlink()
            or not path.resolve().is_relative_to(IMAGES.resolve())):
        raise ValueError("New staged DMG is outside CoreSimulator managed image storage")
    mount, bundle = row.get("mountPath"), row.get("runtimeBundlePath")
    if (not isinstance(mount, str) or not isinstance(bundle, str)
            or not Path(mount).is_absolute() or not Path(bundle).is_absolute()
            or not Path(mount).is_dir() or not Path(bundle).is_dir()
            or not Path(mount).resolve().is_relative_to(VOLUMES.resolve())
            or not Path(bundle).resolve().is_relative_to(Path(mount).resolve())):
        raise ValueError("New staged mount/bundle is not in managed Simulator volumes")
    return path


def permission_snapshot(paths):
    selected = set()
    for path in paths:
        selected.add(path)
        selected.update(path.parents)
    rows = []
    for path in sorted(selected, key=str):
        row = path_snapshot(str(path))
        row["read_access_real_ids"] = os.access(path, os.R_OK)
        row["traverse_access_real_ids"] = os.access(path, os.X_OK)
        rows.append(row)
    try:
        daemon_gid = grp.getgrnam("daemon").gr_gid
    except KeyError:
        daemon_gid = None
    groups = os.getgroups()
    return {"uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(), "egid": os.getegid(),
            "supplementary_groups": groups, "daemon_gid": daemon_gid,
            "member_of_daemon": daemon_gid is not None and daemon_gid in {os.getgid(), os.getegid(), *groups},
            "ancestors": rows, "permission_or_group_mutations": 0}


def require_logical_selection(data, types, row, sdk):
    logical, device = select_exact(data["runtimes"], types["devicetypes"], "27.0", "24A434", DEVICE, sdk)
    if (not isinstance(logical.get("bundlePath"), str)
            or Path(logical["bundlePath"]).resolve() != Path(row["runtimeBundlePath"]).resolve()):
        raise ValueError("Logical iOS runtime is not the newly staged verified bundle")
    return {"logical_runtime": logical, "device_type": device,
            "expected_later_lifecycle_bundle_path": row["runtimeBundlePath"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    out = parser.parse_args().output.resolve()
    if (not __debug__ or sys.implementation.name != "cpython" or sys.platform != "darwin"
            or platform.machine() != "arm64" or tuple(sys.version_info) != (3, 14, 9, "final", 0)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or out.exists()):
        raise SystemExit("Use the declared cached interpreter on a hosted macOS job with a fresh output directory")
    out.mkdir(parents=True)
    started = time.monotonic()
    report = {"schema": 1, "started_unix": time.time(), "helper_sha": os.environ.get("GITHUB_SHA"),
              "run_id": os.environ.get("GITHUB_RUN_ID"), "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
              "add_timeout_seconds": ADD_TIMEOUT, "verify_timeout_seconds": VERIFY_TIMEOUT,
              "metadata_timeout_seconds": METADATA_TIMEOUT, "hash_processing_budget_seconds": HASH_BUDGET,
              "add_attempts": 0, "add_invocations": 0, "verify_attempts": 0, "verify_invocations": 0,
              "commands": [], "runtime_snapshots": {}, "original_lifecycle_may_run": False,
              "product_pass": False, "candidate_credit": False,
              "scope": "One direct .dmg from the exact installed iOS 24A434 MobileAsset is added once with default copy/clone, then only the one new same-build UUID is verified once. Source DMG identity/content and every other iOS/tvOS/xrOS record/filesystem identity remain unchanged. No move/async, download, runtime delete/unmount, force, reinstall, reset, permission/group change, old-UUID verify, fallback or retry.",
              "watch_scope": "Only the same watchOS27.0/24R362 asset may show Ready/Unusable/Copying/Deleting records or registration additions/removals. Its exact Volumes/watchOS_24R362 and cryptexd/mnt/watchOS_24R362 aliases require unchanged asset identity and the same observed filesystem object at any newly used path. Missing/unavailable mount captures are recorded only for Unusable/Copying/Deleting records. Full raw deltas remain; no watch immutability or independence from staging is claimed.",
              "comparison_limits": "Actual prior run41713042397/a1 reported selected iOS verify exit1/-67054; that does not establish past lifecycle timeout causation. Add/verify and whole-file hashing can warm caches and services. Preflight success proves neither application success nor which image the later unchanged driver ultimately selects; actual lifecycle selected_runtime.bundlePath must be compared with expected_later_lifecycle_bundle_path in the artifacts. No new application or candidate credit.",
              "timing_limits": "One add wait180s, one new-UUID verify wait120s, at most fourteen distinct metadata waits10s, and at most four DMG hash reads with a separate 60s processing check. Own subprocess failure permits only its kill and a one-second reap wait; killing the CLI does not prove server-side staging has stopped. Filesystem reads, process creation and scheduling are not hard wall-clock bounded. Original lifecycle and 15-minute job timeouts are unchanged."}
    used = set()
    chosen = before = before_fs = source_before = new_before = new_fs = None
    source_path = new_path = new_id = None
    failure = None
    ready = False

    def save():
        (out / "preflight-result.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(label, argv, timeout):
        if label in used:
            raise ValueError("No command may be retried: " + label)
        mutation = None
        if label == "add-exact-installed-dmg":
            if source_path is None or argv != ["xcrun", "simctl", "runtime", "add", str(source_path)] or timeout != ADD_TIMEOUT:
                raise ValueError("Only the selected installed DMG may be added")
            mutation = "add"
        elif label == "verify-new-staged-ios":
            if new_id is None or argv != ["xcrun", "simctl", "runtime", "verify", new_id] or timeout != VERIFY_TIMEOUT:
                raise ValueError("Only the exact new staged UUID may be verified")
            mutation = "verify"
        elif label not in READ_COMMANDS or argv != READ_COMMANDS[label] or timeout != METADATA_TIMEOUT:
            raise ValueError("Command is outside the fixed preflight allowlist")
        if mutation:
            if report[mutation + "_attempts"]:
                raise ValueError("Mutation already attempted: " + mutation)
            report[mutation + "_attempts"] = 1
        used.add(label)
        row = {"label": label, "argv": list(argv), "requested_timeout_seconds": timeout,
               "started_unix": time.time(), "stdout_file": label + ".stdout.log", "stderr_file": label + ".stderr.log"}
        report["commands"].append(row)
        begin, process, error = time.monotonic(), None, None
        try:
            with (out / row["stdout_file"]).open("xb") as stdout, (out / row["stderr_file"]).open("xb") as stderr:
                process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
                row["pid"] = process.pid
                if mutation:
                    report[mutation + "_invocations"] = 1
                row["returncode"] = process.wait(timeout=timeout)
                if row["returncode"] != 0:
                    raise subprocess.CalledProcessError(row["returncode"], argv)
        except Exception as caught:
            error = caught
            row["timeout"] = isinstance(caught, subprocess.TimeoutExpired)
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                    row["owned_process_kill_requested"] = True
                    row["returncode"] = process.wait(timeout=1)
                except Exception as cleanup_error:
                    row["cleanup_error"] = {"type": type(cleanup_error).__name__, "message": str(cleanup_error)}
        finally:
            row["finished_unix"], row["elapsed_seconds"] = time.time(), time.monotonic() - begin
            for field in ("stdout_file", "stderr_file"):
                try:
                    path = out / row[field]
                    if path.exists():
                        row[field + "_bytes"] = path.stat().st_size
                        with path.open("rb") as stream:
                            row[field + "_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                except Exception as recording_error:
                    error = recording_failure(error, recording_error, field, row)
            if error is not None:
                row["error"] = {"type": type(error).__name__, "message": str(error)}
            error = save_preserving_failure(save, error, "command-result-save", row)
        if error is not None:
            raise error
        if (out / row["stdout_file"]).stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Refusing oversized command metadata")
        return (out / row["stdout_file"]).read_text(encoding="utf-8")

    def snapshot(phase):
        label = "runtime-images-" + phase
        data = decode(run(label, READ_COMMANDS[label], METADATA_TIMEOUT))
        report["runtime_snapshots"][phase] = {"inventory": data}
        fs = filesystem_snapshot(data)
        report["runtime_snapshots"][phase]["filesystem"] = fs
        return data, fs

    try:
        report["checked_out_sha"] = run("source-head", READ_COMMANDS["source-head"], METADATA_TIMEOUT).strip()
        if report["checked_out_sha"] != report["helper_sha"]:
            raise ValueError("Checked-out source differs from actual run head")
        report["source_files"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCE_FILES}
        report["preflight_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if report["source_files"] != SOURCE_FILES:
            raise ValueError("Pinned original sources or read-only helpers changed")
        xcode = run("xcode-version", READ_COMMANDS["xcode-version"], METADATA_TIMEOUT).strip()
        sdk = run("simulator-sdk", READ_COMMANDS["simulator-sdk"], METADATA_TIMEOUT).strip()
        simctl = run("simctl-path", READ_COMMANDS["simctl-path"], METADATA_TIMEOUT).strip()
        xcodebuild = run("xcodebuild-path", READ_COMMANDS["xcodebuild-path"], METADATA_TIMEOUT).strip()
        report["xcode"], report["sdk"] = xcode, sdk
        report["toolchain"] = validate_toolchain(xcode, sdk, os.environ.get("DEVELOPER_DIR"), simctl, xcodebuild)
        help_text = run("runtime-help", READ_COMMANDS["runtime-help"], METADATA_TIMEOUT)
        help_text += (out / "runtime-help.stderr.log").read_text(encoding="utf-8")
        if not all(re.search(pattern, help_text) for pattern in (r"(?m)^\s*add <path>", r"(?m)^\s*verify <identifier>\s*$")):
            raise ValueError("Selected simctl does not advertise the required official add/verify commands")
        run("process-identity", READ_COMMANDS["process-identity"], METADATA_TIMEOUT)
        devices = decode(run("devices-before", READ_COMMANDS["devices-before"], METADATA_TIMEOUT))
        before, before_fs = snapshot("before")
        chosen = select_target(before, devices)
        old_id = chosen["target_uuid"]
        report["selected_original_runtime"] = chosen
        watch_records(before)
        source_path = source_dmg(chosen["target_before"])
        report["permissions_before"] = permission_snapshot([source_path, Path(chosen["target_before"]["mountPath"]), Path(chosen["target_before"]["runtimeBundlePath"])])
        require_same_filesystem(before_fs, before_fs, set(before) - set(watch_records(before)) - {old_id})
        require_same_filesystem(before_fs, before_fs, [old_id], ("path", "parentMountPath"))
        source_before = hash_regular_file(source_path)
        report["source_dmg_before"] = source_before
        if source_before["resolved_path"] != str(source_path):
            raise ValueError("Source DMG became indirect after exact asset selection")
        save()
        run("add-exact-installed-dmg", ["xcrun", "simctl", "runtime", "add", str(source_path)], ADD_TIMEOUT)
        added, added_fs = snapshot("after-add")
        scope = assess_scope(before, added, old_id, before_fs=before_fs, after_fs=added_fs)
        report["scope_after_add"] = scope
        new_id = scope["new_uuid"]
        require_same_filesystem(before_fs, added_fs, scope["protected_uuids"])
        require_same_filesystem(before_fs, added_fs, [old_id], ("path", "parentMountPath"))
        new_path = staged_dmg(scope["new_record"])
        new_before = hash_regular_file(new_path)
        report["staged_dmg_before_verify"] = new_before
        if new_before["sha256"] != source_before["sha256"] or new_before["identity"]["size"] != source_before["identity"]["size"]:
            raise ValueError("New managed DMG bytes differ from the exact installed source DMG")
        new_fs = added_fs[new_id]
        run("verify-new-staged-ios", ["xcrun", "simctl", "runtime", "verify", new_id], VERIFY_TIMEOUT)
        final, final_fs = snapshot("after-verify")
        final_scope = assess_scope(before, final, old_id, new_id, before_fs=before_fs, after_fs=final_fs)
        report["scope_after_verify"] = final_scope
        require_same_filesystem(before_fs, final_fs, final_scope["protected_uuids"])
        require_same_filesystem(before_fs, final_fs, [old_id], ("path", "parentMountPath"))
        require_same_filesystem({new_id: new_fs}, final_fs, [new_id], ("path", "mountPath", "runtimeBundlePath"))
        old_new, final_new = scope["new_record"], final_scope["new_record"]
        if canonical({k: v for k, v in old_new.items() if k != "signatureState"}) != canonical({k: v for k, v in final_new.items() if k != "signatureState"}):
            raise ValueError("New staged runtime changed identity after its one verification")
        if final_new.get("signatureState") != "Verified":
            raise ValueError("New staged runtime did not report exactly Verified")
        logical = decode(run("logical-runtimes-after", READ_COMMANDS["logical-runtimes-after"], METADATA_TIMEOUT))
        types = decode(run("device-types-after", READ_COMMANDS["device-types-after"], METADATA_TIMEOUT))
        report["logical_selection"] = require_logical_selection(logical, types, final_new, sdk)
        final_devices = decode(run("devices-after", READ_COMMANDS["devices-after"], METADATA_TIMEOUT))
        groups = final_devices.get("devices") if isinstance(final_devices, dict) else None
        if not isinstance(groups, dict) or not isinstance(groups.get(IOS), list) or any(not isinstance(row, dict) or row.get("state") != "Shutdown" for row in groups[IOS]):
            raise ValueError("Selected runtime has an active or unknown-state device after staging")
        report["selected_devices_after"] = groups[IOS]
        ready = True
    except Exception as error:
        failure = error
    finally:
        if report["add_invocations"]:
            phase = "after-verify" if report["verify_invocations"] else "after-add"
            if "runtime-images-" + phase not in used:
                try:
                    snapshot(phase)
                except Exception as error:
                    failure = recording_failure(failure, error, "after-failure-inventory", report)
            if source_before is not None:
                try:
                    report["source_dmg_after"] = hash_regular_file(source_path)
                    if not same_file(source_before, report["source_dmg_after"]):
                        raise ValueError("Original source DMG path, identity or bytes changed")
                    report["source_dmg_unchanged"] = True
                except Exception as error:
                    failure = recording_failure(failure, error, "source-dmg-after", report)
            if new_before is not None:
                try:
                    report["staged_dmg_after"] = hash_regular_file(new_path)
                    if not same_file(new_before, report["staged_dmg_after"]):
                        raise ValueError("Staged DMG path, identity or bytes changed after verification")
                    report["staged_dmg_unchanged_after_capture"] = True
                except Exception as error:
                    failure = recording_failure(failure, error, "staged-dmg-after", report)
        if failure is None and ready:
            report["result"] = "STAGED_RUNTIME_VERIFIED_AND_SELECTED"
            report["original_lifecycle_may_run"] = True
        else:
            failure = failure or RuntimeError("Preflight did not establish every required readiness condition")
            report["result"] = "PREFLIGHT_FAILED"
            report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        report["finished_unix"], report["elapsed_seconds"] = time.time(), time.monotonic() - started
        failure = save_preserving_failure(save, failure, "final-result-save", report)
    try:
        print(report["result"], "add_invocations=" + str(report["add_invocations"]),
              "verify_invocations=" + str(report["verify_invocations"]), "product_pass=false candidate_credit=false")
    except Exception as error:
        failure = recording_failure(failure, error, "final-console-output", report)
        report["original_lifecycle_may_run"] = False
        report["result"] = "PREFLIGHT_FAILED"
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        failure = save_preserving_failure(save, failure, "console-failure-result-save", report)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
