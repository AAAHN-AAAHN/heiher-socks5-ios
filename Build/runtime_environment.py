#!/usr/bin/env python3
"""Prepare the exact installed runtime once and bind unchanged original consumers.
Derivative source/control and evidence adapters are explicit. No lifecycle or application success is implied.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import grp
import hashlib
import json
import locale
import os
from pathlib import Path
import platform
import re
import select
import signal
import stat
import subprocess
import sys
import time

ORIGIN_PROFILE = {'schema': 'compact-runtime-origin-identity-v1', 'external_provenance_sha256': '1a417fdbd06f1ea10ed8601bc74a08fc236aca0e1ba3c73510e0d9938056f7a6', 'modules': {'watch_runtime_preflight.py': {'sha256': 'e50a7b7d39b8abf80698b9c5401cbe09b9d48b66059c96ee06e6695b32e88c02', 'function_node_AST_sha256': {'unique_object': '32f0d85f57c01fc79a11af44c90e7e74521b0584c427f8de74c6c6686f47fbf0', 'decode': '21c2c6e6bdf5e76c7763d9934dcdd6673ac84703c751b686496b975d982e0d66', 'inventory': 'c5965e2e6ea7b621464b8ff6be843531e3d70d5d7cedc914594195458af6dd10', 'identity': '0b8006b7dd81374cb70d40e86c19946f6ea6fb38cd254843757aa3704a9784d6', 'ios_identities': '01134f33b2a02fc295839b118d3d16aa6346c287065fae13c1843d7fd97e1f94', 'canonical': 'ebc9312cfb16c89b4c78f32d619dd1505d8461a474c3c630601aa6d54cf65ee9'}}, 'simulator_runtime_compare.py': {'sha256': 'a855b4e2cf0481f389776a56876345ffbb43f41b744b69d853c15b17bc80de81', 'function_node_AST_sha256': {'select_exact': '64082f38fb8c340614203acbe6fdf7b395d2cc60577e7e345ec8f8b2b17325d3', 'validate_toolchain': '4ce50a768a97ea5fe33a2ee81658f68d9169502ea47c61205e322c87da617ad5'}}, 'ios_runtime_signature_preflight.py': {'sha256': 'cd8024e1c37a2596ab39b53f6cac4f29c4c625d321e445febf36883d6c0ff3ef', 'function_node_AST_sha256': {'select_target': '9c3dd8a169284955f04db6983265751a6d8f6fbca331ed3d148418795397a97e', 'recording_failure': '7982e18ce9fc36cc7dace14d7a6cfe97f93b1100eb58fee08c08534b221374d2', 'save_preserving_failure': '0cb80fede4dead5152a68631c41be66c171d210fa34cb11009a665e92d4f8f27'}}, 'ios_runtime_staged_preflight.py': {'sha256': '50f18d556978a4274949d34a8dcafe8af1098c9c0ffc3b2912d3f10e4bc0568c', 'function_node_AST_sha256': {'path_snapshot': '993349b2aa58ffe8463214501c081420a4e04c3326a5ddbce1bda8084d9e4227', 'filesystem_snapshot': '7af25018c8bbf235f85023de1d560f0a3002bc3e12621444d0812a2deacaa7c5', 'require_same_filesystem': '990463bdb4562fc1beb84d9f0507c94ba8808460acc830618991f065dbbc0e4f', 'watch_records': 'b54de63f6a7097aab1076dc0faf69f502dff6a4615077c269e0caf5f3b43d11d', 'assess_old_cryptex': 'dd2d766e91e4c9f6b9b209163ad51e9458f3ebe31cbf4e426c4b6c98faae8874', 'assess_scope': 'c2745e8225c4430719f431ece4595cdeab52b0a3136c59b21171430ae213c1db', 'file_identity': '96e7e1b66e9ac9fc24e9d8126576328ccbec0d4cd12c5c59287dd35babdf65fe', 'hash_regular_file': '71a9b3793b05d37a4684188557a841e888f8a2de72c5ae1ed88f2285965263e4', 'same_file': '9159d5b670bc13cb74c10e4968a325dcdcf275d8a9eca41b1c9714c5e6b33715', 'source_dmg': '21a88a6dbcc3620530d2275939f69eace9b5853cbafedd4b0d6b1e5f3698219a', 'staged_dmg': 'f484e45762eb38c534879e4163f3c2e3878355044cd1cb289725322a24f6adf5', 'permission_snapshot': 'f990314fdfd76ac223646109b3cc6ae48f2e11b493ab0c68f9bf951b3694474d', 'require_logical_selection': '004be12cadddfe1a899e7a361b6ae56d3b04e31023522ccb421e0b2a9b3d3b3d', 'main': '775f8aa24c308d8d3697d32df22ff6c76be458d0fdbeaf3372cac624be826c29'}}, 'ios_runtime_service_refresh.py': {'sha256': '11eb509dcfd933eb0f2dd0a7fbf67883e106feb4ca77400bdf516c4071b16c12', 'function_node_AST_sha256': {'ProcBSDInfo': '29a41764609dce67487e2f9715aa3693b3e69b849bbc2d774fbdee8d31586c0d', 'native_identity': 'fdb1353789804b1daf015491fd42410f33947ea439f8e394715101ae5c070981', 'service_rows': '92972f3725991e2b284125f01d10ea6fbb2a2a5517d7b78cb2a106a89576b38d', 'select_owned_service': 'cb1e579d00777266710ce27935dd85e5add9e4f9b92b5e8deaa1a4044e732f69', 'validate_native': '34af88c6c8a3a42b2bdbcb54194870113d75bd542f0c0d0ebd7ce0bb8451562f', 'require_shutdown_devices': '37b2dc0c5191156a9d8d5ef9f7f0864528fa45feef6d9ab7e998712d8a0d2bf8', 'validate_preflight': '2b27c4349475e3a3f2641a9bcb72ed5ac33365393c982c2325a7eca4c6898282', 'validate_runtime': 'c17f412e160554439dfaac18d257268b201097af57dabf0b8b9170f4a8d838bb', 'bound_file_stat': '162657833c398f4920b11e06c93ce3d5d2d0985f34753b00a6b05ace622aef61', 'event_record': 'c42c846ddade983a62acd69da2e95ff86eb68087d45f16299027788663f7d5e0', 'refresh_service': '0729b3bb58a917c203cd30189763bb0f19f7b5074b198ca21491bcd222a48a64', 'main': '99e281444341072fec5df7faed54fe3c9e28d908e9a6bae48f047bb38e19ae10'}}}}
ORIGIN_PROFILE_SHA256 = '99918cd714445c1ccf0cfa5be6388f12ab6e2a0ef9057ed5df43fedb64ae122e'
OWNER_PROFILES = {'server': {'feature_name': 'server-control', 'helper_paths': ['Build/runtime_environment.py'], 'consumers': {'server-ui': {'command': 'python3 Tests/ServerControl/ui_audit.py', 'receipt': 'artifacts/server-control-ui-audit/runtime.json', 'runtime_key': 'runtime', 'device_key': 'deviceType', 'bootstatus_seconds': 120}}, 'original_files': {'Tests/ServerControl/ui_audit.py': {'sha256': 'e037912a1a4a0caad1ea3fe221dd02d9ed2509ce2661727da0fc65dd74438363', 'git_mode': '100644'}}, 'original_consumer_deadlines': {'server-ui': {'create': 60, 'boot': 180, 'bootstatus': 120, 'shutdown': 30, 'delete': 30, 'ui_test': 900}}, 'preparation_root': 'artifacts/server-control-ui-audit/runtime-preparation', 'existing_canonical_job_minutes': 30}, 'statistics': {'feature_name': 'traffic-statistics', 'helper_paths': ['Build/runtime_environment.py'], 'consumers': {'statistics-ui': {'command': 'python3 Tests/Statistics/ui_audit.py', 'receipt': 'artifacts/statistics-ui-audit/runtime.json', 'runtime_key': 'runtime', 'device_key': 'deviceType', 'bootstatus_seconds': 120}}, 'original_files': {'Tests/Statistics/ui_audit.py': {'sha256': 'c94f9b0a87b45140a30252d8e535455fcb383c323c0301456bac9ad8d649a469', 'git_mode': '100644'}}, 'original_consumer_deadlines': {'statistics-ui': {'create': 60, 'boot': 180, 'bootstatus': 120, 'shutdown': 30, 'delete': 30, 'ui_test': 900}}, 'preparation_root': 'artifacts/statistics-ui-audit/runtime-preparation', 'existing_canonical_job_minutes': 35}, 'settings': {'feature_name': 'settings-persistence', 'helper_paths': ['Build/runtime_environment.py'], 'consumers': {'settings-ui': {'command': 'python3 Tests/Settings/ui_audit.py', 'receipt': 'artifacts/settings-persistence-ui-audit/runtime.json', 'runtime_key': 'runtime', 'device_key': 'deviceType', 'bootstatus_seconds': 120}}, 'original_files': {'Tests/Settings/ui_audit.py': {'sha256': '4c336a80d96afbbcd169061987a4a09e976c499f9e833b95e9c857232ac15074', 'git_mode': '100644'}}, 'original_consumer_deadlines': {'settings-ui': {'create': 60, 'boot': 180, 'bootstatus': 120, 'shutdown': 30, 'delete': 30, 'ui_test': 900, 'build_for_testing': 900}}, 'preparation_root': 'artifacts/settings-persistence-ui-audit/runtime-preparation', 'existing_canonical_job_minutes': 30}, 'icon': {'feature_name': 'app-icon', 'helper_paths': ['Tests/AppIcon/runtime_environment.py'], 'consumers': {'icon-ui': {'command': 'bash Tests/AppIcon/run_checks.sh', 'receipt': 'artifacts/icon-checks/runtime.json', 'runtime_key': None, 'device_key': None, 'bootstatus_seconds': 240}}, 'original_files': {'Tests/AppIcon/run_checks.sh': {'sha256': 'deb568cfc732699922a23bfd09dee909d8a0d82e0866ffc0b2a8c879eb02a68b', 'git_mode': '100755'}, 'Tests/AppIcon/check_compiled.py': {'sha256': '2c08bd5dcd416aafa06d1850c134226e8ce7af75eacd386b0c43b44c4ef524ce', 'git_mode': '100644'}}, 'original_consumer_deadlines': {'icon-ui': {'create': 120, 'boot': 120, 'bootstatus': 240, 'shutdown': 30, 'delete': 30}}, 'preparation_root': 'artifacts/icon-checks/runtime-preparation', 'existing_canonical_job_minutes': 20}, 'integrated': {'feature_name': 'integrated', 'helper_paths': ['Build/runtime_environment.py', 'Tests/AppIcon/runtime_environment.py'], 'consumers': {'integrated-ui': {'command': 'python3 Build/ui_review.py > artifacts/integrated/ui-review.log 2>&1', 'receipt': 'artifacts/integrated/ui/environment.json', 'runtime_key': 'runtime', 'device_key': 'device', 'bootstatus_seconds': 120}, 'integrated-simulator': {'command': 'python3 Build/simulator_review.py > artifacts/integrated/simulator-review.log 2>&1', 'receipt': 'artifacts/integrated/simulator/environment.json', 'runtime_key': 'runtime', 'device_key': 'device_type', 'bootstatus_seconds': 240}}, 'original_files': {'Build/ui_review.py': {'sha256': '3a155a9c78b5acdd5f40b3057d3077c309c4a5ff8545a509e8da1d591e50ad30', 'git_mode': '100644'}, 'Build/simulator_review.py': {'sha256': 'e1897dd4aba4702ad6ee28332fa6d614606260e05c98c310ba6a4464c9e4590f', 'git_mode': '100644'}}, 'original_consumer_deadlines': {'integrated-ui': {'create': 60, 'boot': 180, 'bootstatus': 120, 'shutdown': 30, 'delete': 30, 'ui_test': 900, 'build_for_testing': 900}, 'integrated-simulator': {'create': 120, 'boot': 120, 'bootstatus': 240, 'shutdown': 30, 'delete': 30}}, 'preparation_root': 'artifacts/integrated/runtime-preparation', 'existing_canonical_job_minutes': 45}}
ORIGINAL_RESTORER_SHA256 = "228dbcc1e3e28e682e1d956fd91a9100add223e613bb4aa09d47231e16499580"

WATCH = "com.apple.CoreSimulator.SimRuntime.watchOS-27-0"

IOS = "com.apple.CoreSimulator.SimRuntime.iOS-27-0"

UUID = re.compile(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}")

IDENTITY_FIELDS = ("identifier", "runtimeIdentifier", "platformIdentifier", "version", "build",
                   "kind", "state", "path", "parentMountPath", "mountPath", "runtimeBundlePath",
                   "supportedArchitectures")

RUNTIME_PAIRS = {
    "27.0": {"build": "24A434", "device_type": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"},
}

EXPECTED_SDK = "27.0"

EXPECTED_XCODE = "Xcode 27.0\nBuild version 27A266a"

EXPECTED_DEVELOPER_DIR = "/Applications/Xcode_27.app/Contents/Developer"

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

STAGED_READ_COMMANDS = {
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

SERVICE_NAME = "com.apple.CoreSimulator.CoreSimulatorService"

SERVICE_PATH = "/Library/Developer/PrivateFrameworks/CoreSimulator.framework/Versions/A/XPCServices/" + SERVICE_NAME + ".xpc/Contents/MacOS/" + SERVICE_NAME

METADATA_TIMEOUT, EXIT_TIMEOUT = 10, 10

PS_FIELDS = "uid=,ruid=,pid=,ppid=,lstart=,comm="

PS_COMMAND = ["/bin/ps", "-ww", "-A", "-o", PS_FIELDS]

REFRESH_READ_COMMANDS = {
    "source-head": ["git", "rev-parse", "HEAD"],
    "ps-keywords": ["/bin/ps", "-L"],
    "service-before": PS_COMMAND,
    "runtime-images-before": ["xcrun", "simctl", "runtime", "list", "-j"],
    "devices-before": ["xcrun", "simctl", "list", "devices", "-j"],
    "service-before-signal": PS_COMMAND,
    "service-after-exit": PS_COMMAND,
    "runtime-images-after": ["xcrun", "simctl", "runtime", "list", "-j"],
    "logical-runtimes-after": ["xcrun", "simctl", "list", "runtimes", "-j"],
    "device-types-after": ["xcrun", "simctl", "list", "devicetypes", "-j"],
    "devices-after": ["xcrun", "simctl", "list", "devices", "-j"],
    "service-final": PS_COMMAND,
}

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(text):
    return json.loads(text, object_pairs_hook=unique_object)


def inventory(data):
    if not isinstance(data, dict) or not data:
        raise ValueError("Runtime inventory must be a nonempty object")
    for key, row in data.items():
        if (not isinstance(key, str) or not UUID.fullmatch(key)
                or not isinstance(row, dict) or row.get("identifier") != key):
            raise ValueError("Runtime UUID key/identifier is missing, malformed or ambiguous")
    return data


def identity(row):
    missing = [key for key in IDENTITY_FIELDS if key not in row]
    if missing:
        raise ValueError("Incomplete runtime identity: " + repr(missing))
    return {key: row[key] for key in IDENTITY_FIELDS}


def ios_identities(data):
    inventory(data)
    selected = [row for row in data.values() if row.get("runtimeIdentifier") == IOS]
    if len(selected) != 1:
        raise ValueError("Expected exactly one selected iOS 27.0 runtime image")
    row = selected[0]
    if (row.get("build") != "24A434" or row.get("version") != "27.0"
            or row.get("state") != "Ready"
            or row.get("platformIdentifier") != "com.apple.platform.iphonesimulator"
            or "arm64" not in row.get("supportedArchitectures", [])):
        raise ValueError("Selected iOS image differs from the declared Ready arm64 24A434 input")
    return {key: identity(value) for key, value in data.items()
            if value.get("platformIdentifier") == "com.apple.platform.iphonesimulator"}


def canonical(value):
    """Compare complete JSON values without ignoring unknown or volatile fields."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def select_exact(runtimes, device_types, version, build, device_identifier, sdk):
    if RUNTIME_PAIRS.get(version) != {"build": build, "device_type": device_identifier} or sdk != EXPECTED_SDK:
        raise ValueError("Comparison requires the declared runtime/build/device pair and Simulator SDK 27.0")
    identifier = "com.apple.CoreSimulator.SimRuntime.iOS-" + version.replace(".", "-")
    matches = [r for r in runtimes if r.get("identifier") == identifier]
    if len(matches) != 1:
        raise ValueError("Missing or duplicate exact runtime identifier")
    runtime = matches[0]
    if runtime.get("isAvailable") is not True or runtime.get("version") != version or runtime.get("buildversion") != build:
        raise ValueError("Runtime availability/version/build differs from the explicit comparison input")
    if runtime.get("platform") != "iOS" or "arm64" not in runtime.get("supportedArchitectures", []):
        raise ValueError("Expected available arm64 runtime")
    devices = [d for d in device_types if d.get("identifier") == device_identifier]
    if len(devices) != 1 or device_identifier not in {d.get("identifier") for d in runtime.get("supportedDeviceTypes", [])}:
        raise ValueError("Pinned device type is not supported by this runtime")
    return runtime, devices[0]


def validate_toolchain(xcode, sdk, developer_dir, simctl_path, xcodebuild_path):
    """Reject a changed installation before creating any device."""
    if developer_dir != EXPECTED_DEVELOPER_DIR:
        raise ValueError("DEVELOPER_DIR differs from the declared installed Xcode 27.0 path")
    if xcode != EXPECTED_XCODE or sdk != EXPECTED_SDK:
        raise ValueError("Actual Xcode version/build or Simulator SDK differs from the fixed diagnostic input")
    expected = Path(EXPECTED_DEVELOPER_DIR).resolve()
    resolved = {}
    for name, value in (("simctl", simctl_path), ("xcodebuild", xcodebuild_path)):
        tool = Path(value)
        if not tool.is_absolute() or tool.name != name or not tool.resolve().is_relative_to(expected):
            raise ValueError("Selected " + name + " is outside the declared Xcode developer directory")
        resolved[name] = str(tool.resolve())
    return {"developer_directory": str(expected), "resolved_tools": resolved}


def select_target(data, devices):
    """Resolve exactly one current UUID; never fall back to another runtime."""
    ios_identities(data)
    matches = [row for row in data.values() if row.get("runtimeIdentifier") == IOS]
    row = matches[0]
    identity(row)
    architectures = row["supportedArchitectures"]
    if (not isinstance(architectures, list) or "arm64" not in architectures
            or any(not isinstance(value, str) for value in architectures)
            or not isinstance(row.get("signatureState"), str) or not row["signatureState"].strip()):
        raise ValueError("Selected runtime architecture or signature metadata is invalid")
    groups = devices.get("devices") if isinstance(devices, dict) else None
    if not isinstance(groups, dict) or not isinstance(groups.get(IOS), list):
        raise ValueError("Selected iOS device inventory is unavailable")
    if any(not isinstance(device, dict) or device.get("state") != "Shutdown" for device in groups[IOS]):
        raise ValueError("Selected iOS runtime has an active or unknown-state device")
    return {"target_uuid": row["identifier"], "target_before": dict(row),
            "devices_before": groups[IOS],
            "exact_verify_argv": ["xcrun", "simctl", "runtime", "verify", row["identifier"]]}


def recording_failure(primary, error, stage, record):
    """Preserve a command failure when recording that failure also fails."""
    record.setdefault("recording_errors", []).append(
        {"stage": stage, "type": type(error).__name__, "message": str(error)})
    return error if primary is None else primary


def save_preserving_failure(save, primary, stage, record):
    try:
        save()
    except Exception as error:
        primary = recording_failure(primary, error, stage, record)
        if "original_lifecycle_may_run" in record:
            record["original_lifecycle_may_run"] = False
            record["result"] = "PREFLIGHT_FAILED"
            record["failure"] = {"type": type(primary).__name__, "message": str(primary)}
        try:
            print("Preflight evidence persistence failed:", json.dumps(record), file=sys.stderr)
        except Exception:
            pass  # A broken stderr must not replace the original command error.
    return primary


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
        # Derivative classification: only the observed watchOS 27.0 asset may
        # use the special transition rules. Other versions remain protected
        # by exact record and filesystem equality in the calling scope checks.
        if row.get("runtimeIdentifier") != WATCH:
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


class ProcBSDInfo(ctypes.Structure):
    """Public Darwin proc_bsdinfo; require the API's complete 136-byte return."""
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
    _fields_ += [("nice", ctypes.c_int32), ("start_seconds", ctypes.c_uint64), ("start_microseconds", ctypes.c_uint64)]


def native_identity(pid):
    """Read the executable and creation identity from public libproc, not argv[0]."""
    if sys.platform != "darwin" or ctypes.sizeof(ProcBSDInfo) != 136:
        raise ValueError("Require the declared Darwin proc_bsdinfo ABI")
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    info = ProcBSDInfo()
    ctypes.set_errno(0)
    size = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size != ctypes.sizeof(info):
        raise OSError(ctypes.get_errno(), "proc_pidinfo did not return the complete process identity", pid)
    buffer = ctypes.create_string_buffer(4096)
    ctypes.set_errno(0)
    length = lib.proc_pidpath(pid, buffer, len(buffer))
    if length <= 0 or length >= len(buffer) or len(buffer.value) != length:
        raise OSError(ctypes.get_errno(), "proc_pidpath did not return one complete executable path", pid)
    return {"pid": info.pid, "ppid": info.ppid, "uid": info.uid, "ruid": info.ruid, "svuid": info.svuid,
            "start_seconds": info.start_seconds, "start_microseconds": info.start_microseconds,
            "executable": buffer.value.decode("utf-8"), "proc_bsdinfo_bytes": size}


def service_rows(text):
    """Parse only candidate service rows; retain other-UID services as evidence."""
    rows = []
    for line in text.splitlines():
        if SERVICE_NAME not in line:
            continue
        fields = line.split(maxsplit=9)
        if len(fields) != 10 or any(not value.isdecimal() for value in fields[:4]):
            raise ValueError("Unparseable CoreSimulatorService ps row")
        started = datetime.strptime(" ".join(fields[4:9]), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
        rows.append({"uid": int(fields[0]), "ruid": int(fields[1]), "pid": int(fields[2]), "ppid": int(fields[3]),
                     "lstart_utc": started.isoformat(), "start_seconds": int(started.timestamp()),
                     "ps_comm": fields[9], "raw_line": line})
    return rows


def select_owned_service(rows, uid, allow_absent=False):
    owned = [row for row in rows if row["uid"] == uid or row["ruid"] == uid]
    if allow_absent and not owned:
        return None
    if len(owned) != 1:
        raise ValueError("Require exactly one own-UID CoreSimulatorService")
    row = owned[0]
    if uid <= 0 or row["uid"] != uid or row["ruid"] != uid or row["pid"] <= 1 or row["ps_comm"] != SERVICE_PATH:
        raise ValueError("Service ps identity is outside the exact own-UID executable boundary")
    return row


def validate_native(row, native, uid):
    if (any(native.get(key) != row[key] for key in ("pid", "ppid", "uid", "ruid", "start_seconds"))
            or native.get("svuid") != uid or native.get("executable") != SERVICE_PATH
            or native.get("proc_bsdinfo_bytes") != 136
            or not isinstance(native.get("start_microseconds"), int)
            or not 0 <= native["start_microseconds"] < 1000000 or native["start_seconds"] <= 0):
        raise ValueError("Native service executable, owner or creation identity differs from ps")
    return native


def require_shutdown_devices(data):
    groups = data.get("devices") if isinstance(data, dict) else None
    if not isinstance(groups, dict) or not isinstance(groups.get(IOS), list):
        raise ValueError("Complete device inventory including the selected iOS runtime is required")
    selected = {}
    for runtime, rows in groups.items():
        if not isinstance(runtime, str) or not isinstance(rows, list):
            raise ValueError("Malformed device inventory")
        for row in rows:
            if (not isinstance(row, dict) or row.get("state") != "Shutdown"
                    or not isinstance(row.get("udid"), str) or row["udid"] in selected):
                raise ValueError("An active, unknown-state, malformed or duplicate device prevents service refresh")
            selected[row["udid"]] = {"runtime": runtime, "state": row["state"],
                                     "name": row.get("name"), "deviceTypeIdentifier": row.get("deviceTypeIdentifier")}
    return {"runtime_group_count": len(groups), "device_count": len(selected), "all_shutdown": True,
            "device_identities": selected}


def validate_preflight(p, context):
    if (p.get("result") != "STAGED_RUNTIME_VERIFIED_AND_SELECTED" or p.get("original_lifecycle_may_run") is not True
            or p.get("product_pass") is not False or p.get("candidate_credit") is not False
            or p.get("preflight_sha256") != context["identity"]["own_helper_sha256"]
            or p.get("source_files") != context["identity"]["helper_files"]
            or any(p.get(key) != value for key, value in context.items())
            or any(p.get(key) != 1 for key in ("add_attempts", "add_invocations", "verify_attempts", "verify_invocations"))):
        raise ValueError("Require the unchanged successful staged preflight from this exact run/head/attempt")
    old, new = p["selected_original_runtime"]["target_uuid"], p["scope_after_verify"]["new_uuid"]
    if not re.fullmatch(r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}", new):
        raise ValueError("Staged runtime UUID is malformed")
    source, image = p["source_dmg_after"], p["staged_dmg_after"]
    if (not same_file(p["source_dmg_before"], source)
            or not same_file(p["staged_dmg_before_verify"], image)
            or p.get("source_dmg_unchanged") is not True or p.get("staged_dmg_unchanged_after_capture") is not True
            or source["sha256"] != image["sha256"] or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            or source["identity"]["size"] != image["identity"]["size"] or source["identity"]["size"] <= 0
            or Path(source["path"]).parent != IOS_ASSET / "Restore"
            or Path(source["path"]).suffix != ".dmg" or source["path"] != source["resolved_path"]
            or image["path"] != str(IMAGES / (new + ".dmg")) or image["path"] != image["resolved_path"]):
        raise ValueError("Preflight DMG identity/content receipts do not bind the exact source and new image")
    commands = {row["label"]: row for row in p["commands"]}
    expected = dict(STAGED_READ_COMMANDS)
    expected["add-exact-installed-dmg"] = ["xcrun", "simctl", "runtime", "add", source["path"]]
    expected["verify-new-staged-ios"] = ["xcrun", "simctl", "runtime", "verify", new]
    if len(commands) != len(p["commands"]) or set(commands) != set(expected):
        raise ValueError("Preflight command inventory differs from the unchanged single-add/single-verify sequence")
    for label, argv in expected.items():
        row = commands[label]
        timeout = ADD_TIMEOUT if label == "add-exact-installed-dmg" else VERIFY_TIMEOUT if label == "verify-new-staged-ios" else METADATA_TIMEOUT
        if row["argv"] != argv or row.get("returncode") != 0 or row.get("requested_timeout_seconds") != timeout or row.get("timeout") is True or "error" in row or row.get("recording_errors"):
            raise ValueError("Preflight command failed or differs from the fixed command/deadline: " + label)
    return old, new


def validate_runtime(p, data, filesystem):
    original, final = p["runtime_snapshots"]["before"], p["runtime_snapshots"]["after-verify"]
    old, new = p["selected_original_runtime"]["target_uuid"], p["scope_after_verify"]["new_uuid"]
    scope = assess_scope(original["inventory"], data, old, new,
                                before_fs=original["filesystem"], after_fs=filesystem)
    require_same_filesystem(original["filesystem"], filesystem, scope["protected_uuids"])
    require_same_filesystem(original["filesystem"], filesystem, [old], ("path", "parentMountPath"))
    require_same_filesystem(final["filesystem"], filesystem, [new], ("path", "mountPath", "runtimeBundlePath"))
    if canonical(data[new]) != canonical(final["inventory"][new]) or data[new].get("signatureState") != "Verified":
        raise ValueError("Same new Ready/Verified runtime UUID or its complete identity changed")
    return scope


def bound_file_stat(receipt):
    path = Path(receipt["path"])
    result = {"path": str(path), "capture": "pending",
              "bound_preflight_sha256": receipt["sha256"], "additional_content_hash_performed": False}
    try:
        info = path.lstat()
        result.update(capture="observed", resolved_path=str(path.resolve()), identity=file_identity(info),
                      is_regular=stat.S_ISREG(info.st_mode), is_symlink=stat.S_ISLNK(info.st_mode))
        result["matches_verified_receipt"] = result["is_regular"] and all(result[key] == receipt[key] for key in ("path", "resolved_path", "identity"))
    except OSError as error:
        result.update(capture="unavailable", matches_verified_receipt=False,
                      error={"type": type(error).__name__, "message": str(error), "errno": error.errno})
    return result


def event_record(event):
    return {"ident": event.ident, "filter": event.filter, "flags": event.flags, "fflags": event.fflags,
            "data": event.data, "udata": event.udata}


def refresh_service(old, read_final_identity, report, save):
    """One fixed service SIGTERM, one NOTE_EXIT wait, no process polling/retry."""
    queue, primary = None, None
    observation = report["service_refresh"]
    try:
        queue = select.kqueue()
        event = select.kevent(old["pid"], filter=select.KQ_FILTER_PROC,
                             flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT,
                             fflags=select.KQ_NOTE_EXIT | select.KQ_NOTE_EXEC)
        observation["registration"] = {"started_unix": time.time(), "change": event_record(event), "returned_without_error": False}
        # Darwin returns -1 on registration failure when no output event slot is
        # supplied; Python raises OSError. CPython 3.14 does not export EV_RECEIPT.
        receipts = queue.control([event], 0, 0)
        observation["registration"].update(finished_unix=time.time(), returned_without_error=True,
                                            events=[event_record(row) for row in receipts])
        if receipts:
            raise ValueError("Unexpected output from zero-event registration")
        current = read_final_identity()
        observation["final_native_identity"] = current
        if current != old:
            raise ValueError("Service identity changed after watcher registration")
        save()
        # No subprocess or filesystem work between this final native read and signal.
        immediate = native_identity(old["pid"])
        observation["immediate_native_identity"] = immediate
        if immediate != old:
            raise ValueError("Service identity changed immediately before its one signal")
        pending = queue.control(None, 1, 0)
        observation["events_before_signal"] = [event_record(row) for row in pending]
        if pending:
            raise ValueError("Service exited or executed a new image before the one signal")
        if observation["sigterm_attempts"] or old["pid"] <= 1 or os.getuid() <= 0 or old["uid"] != os.getuid() or old["ruid"] != os.getuid() or old["svuid"] != os.getuid() or old["executable"] != SERVICE_PATH:
            raise ValueError("Service signal identity or at-most-once boundary failed")
        observation["sigterm_attempts"] = 1
        observation["signal_started_unix"] = time.time()
        started = time.monotonic()
        observation["sigterm_invocations"] = 1
        os.kill(old["pid"], signal.SIGTERM)
        observation["signal_returned_successfully"] = True
        observation["signal_returned_unix"] = time.time()
        remaining = max(0, EXIT_TIMEOUT - (time.monotonic() - started))
        events = queue.control(None, 1, remaining)
        observation["wait_returned_unix"], observation["elapsed_seconds"] = time.time(), time.monotonic() - started
        observation["events_after_signal"] = [event_record(row) for row in events]
        if not events:
            raise TimeoutError("Exact service NOTE_EXIT was not delivered within the separate 10-second wait")
        event = events[0]
        if (len(events) != 1 or event.ident != old["pid"] or event.filter != select.KQ_FILTER_PROC
                or event.flags & select.KQ_EV_ERROR or not event.fflags & select.KQ_NOTE_EXIT
                or event.fflags & select.KQ_NOTE_EXEC):
            raise ValueError("Service event did not establish the unchanged target's NOTE_EXIT")
        observation["old_service_exit_observed"] = True
    except Exception as error:
        primary = error
        observation["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if queue is not None:
            try:
                queue.close()
            except Exception as error:
                primary = recording_failure(primary, error, "service-watcher-close", observation)
        primary = save_preserving_failure(save, primary, "service-watcher-result-save", observation)
    if primary is not None:
        raise primary


def stage_installed_runtime(identity_context, out):
    out = Path(out).resolve()
    context = phase_context(identity_context)
    if (not __debug__ or sys.implementation.name != "cpython" or sys.platform != "darwin"
            or platform.machine() != "arm64" or tuple(sys.version_info) != (3, 14, 9, "final", 0)
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or out.exists()):
        raise SystemExit("Use the declared cached interpreter on a hosted macOS job with a fresh output directory")
    out.mkdir(parents=True)
    started = time.monotonic()
    report = {"schema": 2, "started_unix": time.time(), **context,
              "original_consumer_deadlines": OWNER_PROFILES[identity_context["owner"]]["original_consumer_deadlines"],
              "add_timeout_seconds": ADD_TIMEOUT, "verify_timeout_seconds": VERIFY_TIMEOUT,
              "metadata_timeout_seconds": METADATA_TIMEOUT, "hash_processing_budget_seconds": HASH_BUDGET,
              "add_attempts": 0, "add_invocations": 0, "verify_attempts": 0, "verify_invocations": 0,
              "commands": [], "runtime_snapshots": {}, "original_lifecycle_may_run": False,
              "product_pass": False, "candidate_credit": False,
              "scope": "One direct .dmg from the exact installed iOS 24A434 MobileAsset is added once with default copy/clone, then only the one new same-build UUID is verified once. Source DMG identity/content and every other iOS/tvOS/xrOS record/filesystem identity remain unchanged. No move/async, download, runtime delete/unmount, force, reinstall, reset, permission/group change, old-UUID verify, fallback or retry.",
              "watch_scope": "Only the same watchOS27.0/24R362 asset may show Ready/Unusable/Copying/Deleting records or registration additions/removals. Its exact Volumes/watchOS_24R362 and cryptexd/mnt/watchOS_24R362 aliases require unchanged asset identity and the same observed filesystem object at any newly used path. Missing/unavailable mount captures are recorded only for Unusable/Copying/Deleting records. Full raw deltas remain; no watch immutability or independence from staging is claimed.",
              "comparison_limits": "Actual prior run41713042397/a1 reported selected iOS verify exit1/-67054; that does not establish past lifecycle timeout causation. Add/verify and whole-file hashing can warm caches and services. Preflight success proves neither application success nor which image the later unchanged driver ultimately selects; actual lifecycle selected_runtime.bundlePath must be compared with expected_later_lifecycle_bundle_path in the artifacts. No new application or candidate credit.",
              "timing_limits": "One add wait180s, one new-UUID verify wait120s, at most fourteen distinct metadata waits10s, and at most four DMG hash reads with a separate 60s processing check. Own subprocess failure permits only its kill and a one-second reap wait; killing the CLI does not prove server-side staging has stopped. Filesystem reads, process creation and scheduling are not hard wall-clock bounded. Original consumer command deadlines and the existing caller job timeout are unchanged; this phase does not impose the old diagnostic job profile."}
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
        elif label not in STAGED_READ_COMMANDS or argv != STAGED_READ_COMMANDS[label] or timeout != METADATA_TIMEOUT:
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
        data = decode(run(label, STAGED_READ_COMMANDS[label], METADATA_TIMEOUT))
        report["runtime_snapshots"][phase] = {"inventory": data}
        fs = filesystem_snapshot(data)
        report["runtime_snapshots"][phase]["filesystem"] = fs
        return data, fs

    try:
        report["checked_out_sha"] = run("source-head", STAGED_READ_COMMANDS["source-head"], METADATA_TIMEOUT).strip()
        if report["checked_out_sha"] != identity_context["source"]["commit"]:
            raise ValueError("Checked-out source differs from the declared verified source identity")
        report["source_files"] = derivative_source_files(identity_context)
        report["preflight_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if (report["source_files"] != identity_context["helper_files"]
                or report["preflight_sha256"] != identity_context["own_helper_sha256"]):
            raise ValueError("Actual derivative helper differs from its verified Git bytes")
        xcode = run("xcode-version", STAGED_READ_COMMANDS["xcode-version"], METADATA_TIMEOUT).strip()
        sdk = run("simulator-sdk", STAGED_READ_COMMANDS["simulator-sdk"], METADATA_TIMEOUT).strip()
        simctl = run("simctl-path", STAGED_READ_COMMANDS["simctl-path"], METADATA_TIMEOUT).strip()
        xcodebuild = run("xcodebuild-path", STAGED_READ_COMMANDS["xcodebuild-path"], METADATA_TIMEOUT).strip()
        report["xcode"], report["sdk"] = xcode, sdk
        report["toolchain"] = validate_toolchain(xcode, sdk, os.environ.get("DEVELOPER_DIR"), simctl, xcodebuild)
        help_text = run("runtime-help", STAGED_READ_COMMANDS["runtime-help"], METADATA_TIMEOUT)
        help_text += (out / "runtime-help.stderr.log").read_text(encoding="utf-8")
        if not all(re.search(pattern, help_text) for pattern in (r"(?m)^\s*add <path>", r"(?m)^\s*verify <identifier>\s*$")):
            raise ValueError("Selected simctl does not advertise the required official add/verify commands")
        run("process-identity", STAGED_READ_COMMANDS["process-identity"], METADATA_TIMEOUT)
        devices = decode(run("devices-before", STAGED_READ_COMMANDS["devices-before"], METADATA_TIMEOUT))
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
        logical = decode(run("logical-runtimes-after", STAGED_READ_COMMANDS["logical-runtimes-after"], METADATA_TIMEOUT))
        types = decode(run("device-types-after", STAGED_READ_COMMANDS["device-types-after"], METADATA_TIMEOUT))
        report["logical_selection"] = require_logical_selection(logical, types, final_new, sdk)
        final_devices = decode(run("devices-after", STAGED_READ_COMMANDS["devices-after"], METADATA_TIMEOUT))
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
    return report


def refresh_owned_service(identity_context, preflight_directory, output_directory):
    out, incoming = Path(output_directory).resolve(), Path(preflight_directory).resolve()
    if (not __debug__ or sys.implementation.name != "cpython" or sys.platform != "darwin" or platform.machine() != "arm64"
            or tuple(sys.version_info) != (3, 14, 9, "final", 0) or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or os.getuid() != os.geteuid() or os.getuid() <= 0
            or os.environ.get("DEVELOPER_DIR") != EXPECTED_DEVELOPER_DIR or out.exists() or out == incoming):
        raise SystemExit("Require the unchanged hosted Darwin arm64 environment, own non-root UID and a fresh output directory")
    locale.setlocale(locale.LC_TIME, "C")
    out.mkdir(parents=True)
    started, ready, failure, p = time.monotonic(), False, None, None
    used = set()
    context = phase_context(identity_context)
    report = {"schema": 2, "started_unix": time.time(), **context, "own_uid": os.getuid(), "own_euid": os.geteuid(),
              "source_files": {}, "commands": [], "runtime_snapshots": {}, "service_snapshots": {},
              "metadata_timeout_seconds": METADATA_TIMEOUT, "service_exit_wait_seconds": EXIT_TIMEOUT,
              "original_limits_seconds": OWNER_PROFILES[identity_context["owner"]]["original_consumer_deadlines"], "original_lifecycle_may_run": False, "product_pass": False, "candidate_credit": False,
              "service_refresh": {"target_executable": SERVICE_PATH, "sigterm_attempts": 0, "sigterm_invocations": 0,
                                  "old_service_exit_observed": False, "force_fallbacks": 0, "other_infrastructure_service_signals": 0},
              "owned_metadata_child_cleanup_signals": [],
              "success_requires_helper_process_exit_zero": True,
              "scope": "Unchanged staged preflight once, then own-UID exact CoreSimulatorService SIGTERM at most once and one NOTE_EXIT wait. All actual devices must be Shutdown. No launchctl, sudo, runtime/device removal, permission change, service SIGKILL, reset or retry. The original lifecycle runs once only if every preparation guard succeeds.",
              "comparison_limits": "A successful refresh or later lifecycle does not prove sole causation or application correctness. Read-only queries, staging, service respawn and elapsed time can affect state. ps argv[0] is checked against native executable/creation identity. PID signalling is not atomic with identity checks; a narrow exit/reuse race remains despite pre-registered exit/exec observation and immediate native recheck. NOTE_EXIT delivery time is observed, not an exact exit timestamp or non-child exit status.",
              "timing_limits": "Each metadata subprocess waits at most 10 seconds; after a command/wait error only its directly owned child whose exit has not yet been observed may be killed and reaped with a separate one-second wait. Service NOTE_EXIT has its own 10-second wait and no force fallback. Native/FS access, launch and scheduling are not guaranteed hard wall-clock bounds. Original consumer command deadlines and existing caller job timeout remain unchanged and are recorded per consumer.",
              "content_hash_limit": "The source and staged DMGs are not rehashed. Their immediate before/after stat/path identities are bound to the same-run unchanged preflight's already verified content hashes. This is not a new independent content proof.",
              "evidence_persistence_limit": "Result JSON is replaced only after a complete temporary-file write. A final recording or console failure keeps process exit nonzero and the in-memory result failed; a previously committed success file cannot by itself authorize the lifecycle. Actual helper process success and the workflow handoff must also be verified.",
              "after_failure_capture_scope": "After a service signal attempt, remaining allowlisted after snapshots may run once even if NOTE_EXIT fails. These read-only observations can initialize services but are not another signal, a retry, or a force fallback; any capture error remains secondary to the original failure."}

    def save():
        pending = out / "refresh-result.pending.json"
        pending.write_text(json.dumps(report, indent=2) + "\n")
        pending.replace(out / "refresh-result.json")

    def run(label):
        if label not in REFRESH_READ_COMMANDS or label in used:
            raise ValueError("Read command is outside the single-invocation metadata allowlist: " + label)
        used.add(label)
        argv = REFRESH_READ_COMMANDS[label]
        row = {"label": label, "argv": list(argv), "requested_timeout_seconds": METADATA_TIMEOUT,
               "started_unix": time.time(), "stdout_file": label + ".stdout.log", "stderr_file": label + ".stderr.log"}
        report["commands"].append(row)
        begin, process, error = time.monotonic(), None, None
        try:
            with (out / row["stdout_file"]).open("xb") as stdout, (out / row["stderr_file"]).open("xb") as stderr:
                process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, env=dict(os.environ, LC_ALL="C", TZ="UTC"))
                row["pid"] = process.pid
                row["returncode"] = process.wait(timeout=METADATA_TIMEOUT)
                if row["returncode"] != 0:
                    raise subprocess.CalledProcessError(row["returncode"], argv)
        except Exception as caught:
            error = caught
            row["timeout"] = isinstance(caught, subprocess.TimeoutExpired)
            if process is not None and process.returncode is None:
                try:
                    cleanup = {"label": label, "pid": process.pid, "signal": "SIGKILL", "scope": "directly owned metadata child only", "attempted_unix": time.time()}
                    report["owned_metadata_child_cleanup_signals"].append(cleanup)
                    process.kill()
                    cleanup["signal_returned"] = True
                    row["returncode"] = process.wait(timeout=1)
                    cleanup["reaped_returncode"] = row["returncode"]
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
            error = save_preserving_failure(save, error, "metadata-result-save", row)
        if error is not None:
            raise error
        if (out / row["stdout_file"]).stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Refusing oversized command metadata")
        return (out / row["stdout_file"]).read_text(encoding="utf-8")

    def snapshot(phase):
        data = decode(run("runtime-images-" + phase))
        target = report["runtime_snapshots"][phase] = {"inventory": data}
        target["filesystem"] = filesystem_snapshot(data)
        target["scope_validation"] = validate_runtime(p, data, target["filesystem"])
        return data

    def service(label, allow_absent=False):
        rows = service_rows(run(label))
        target = report["service_snapshots"][label] = {"candidate_rows": rows}
        row = select_owned_service(rows, report["own_uid"], allow_absent)
        if row is None:
            target["own_service_observed"] = False
            return None
        target["own_service_observed"] = True
        target["ps_identity"] = row
        target["native_identity"] = native_identity(row["pid"])
        validate_native(row, target["native_identity"], report["own_uid"])
        target["executable_filesystem"] = path_snapshot(SERVICE_PATH)
        if target["executable_filesystem"].get("capture") != "observed" or target["executable_filesystem"].get("is_regular") is not True:
            raise ValueError("Exact service executable filesystem identity unavailable")
        return target["native_identity"]

    def file_stats(phase):
        target = report.setdefault("dmg_stats", {}).setdefault(phase, {})
        for key in ("source_dmg_after", "staged_dmg_after"):
            target[key] = bound_file_stat(p[key])
        if any(row.get("matches_verified_receipt") is not True for row in target.values()):
            raise ValueError("Source or staged DMG stat/path identity differs from its preflight hash receipt")

    try:
        head = run("source-head").strip()
        if head != identity_context["source"]["commit"] or not re.fullmatch(r"[0-9a-f]{40}", head):
            raise ValueError("Actual checked-out source differs from verified source identity")
        report["source_files"] = derivative_source_files(identity_context)
        report["helper_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if (report["source_files"] != identity_context["helper_files"]
                or report["helper_source_sha256"] != identity_context["own_helper_sha256"]):
            raise ValueError("Actual derivative source differs from verified Git bytes")
        raw = (incoming / "preflight-result.json").read_bytes()
        (out / "bound-preflight-result.json").write_bytes(raw)
        report["preflight_binding"] = {"path": str(incoming / "preflight-result.json"), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        p = json.loads(raw)
        old_id, new_id = validate_preflight(p, context)
        report["preflight_binding"].update(old_uuid=old_id, new_uuid=new_id, finished_unix=p["finished_unix"],
                                          age_seconds_at_binding=time.time() - p["finished_unix"])
        report["bound_preflight_command_files"] = []
        for row in p["commands"]:
            for channel in ("stdout", "stderr"):
                name = row[channel + "_file"]
                if Path(name).name != name:
                    raise ValueError("Preflight command evidence path is not a direct filename")
                contents = (incoming / name).read_bytes()
                observed = {"file": name, "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}
                if observed["bytes"] != row[channel + "_file_bytes"] or observed["sha256"] != row[channel + "_file_sha256"]:
                    raise ValueError("Preflight command evidence no longer matches the completed receipt")
                report["bound_preflight_command_files"].append(observed)
        if (incoming / "verify-new-staged-ios.stdout.log").read_text() != "Signature verified, signature is valid.\n" or (incoming / "verify-new-staged-ios.stderr.log").read_bytes():
            raise ValueError("Exact staged UUID verification did not preserve its successful raw result")
        file_stats("before")
        keywords = set(run("ps-keywords").split())
        if not {"uid", "ruid", "pid", "ppid", "lstart", "comm"}.issubset(keywords):
            raise ValueError("Actual ps does not advertise the required identity fields")
        old = service("service-before")
        report["service_refresh"]["target_native_identity"] = old
        snapshot("before")
        report["devices_before"] = require_shutdown_devices(decode(run("devices-before")))
        report["preflight_devices_after"] = require_shutdown_devices(decode((incoming / "devices-after.stdout.log").read_text()))
        if report["devices_before"]["device_identities"] != report["preflight_devices_after"]["device_identities"]:
            raise ValueError("Device identities changed after the staged preflight")
        refresh_service(old, lambda: service("service-before-signal"), report, save)
        immediate = service("service-after-exit", allow_absent=True)
        report["service_refresh"]["replacement_observed_before_reinit"] = immediate is not None
        if immediate is not None and immediate["pid"] == old["pid"]:
            raise ValueError("Old service PID still identifies the service after NOTE_EXIT")
        current = snapshot("after")
        logical = decode(run("logical-runtimes-after"))
        types = decode(run("device-types-after"))
        report["logical_selection"] = require_logical_selection(logical, types, current[new_id], p["sdk"])
        if report["logical_selection"]["expected_later_lifecycle_bundle_path"] != p["logical_selection"]["expected_later_lifecycle_bundle_path"]:
            raise ValueError("Exact later lifecycle bundle binding changed after service refresh")
        report["devices_after"] = require_shutdown_devices(decode(run("devices-after")))
        if report["devices_before"]["device_identities"] != report["devices_after"]["device_identities"]:
            raise ValueError("Device identities changed during service refresh")
        replacement = service("service-final")
        if (replacement["pid"] == old["pid"] or replacement["start_seconds"] * 1000000 + replacement["start_microseconds"] <= old["start_seconds"] * 1000000 + old["start_microseconds"]
                or immediate is not None and replacement != immediate):
            raise ValueError("Replacement is not one distinct newer own-UID service identity")
        if report["service_snapshots"]["service-before"]["executable_filesystem"] != report["service_snapshots"]["service-final"]["executable_filesystem"]:
            raise ValueError("Service executable filesystem identity changed")
        report["service_refresh"]["replacement_native_identity"] = replacement
        report["service_refresh"]["replacement_origin_limit"] = "No launchctl/start command was issued. A replacement seen before simctl reinitialization is consistent with automatic launch-service respawn; exact platform causation is not inferred."
        ready = True
    except Exception as error:
        failure = error
    finally:
        if p is not None:
            try:
                file_stats("after")
            except Exception as error:
                failure = recording_failure(failure, error, "after-DMG-stat", report)
        if report["service_refresh"]["sigterm_invocations"]:
            for label, capture in (("runtime-images-after", lambda: snapshot("after")),
                                   ("devices-after", lambda: report.update(devices_after=require_shutdown_devices(decode(run("devices-after"))))),
                                   ("service-final", lambda: service("service-final", allow_absent=True))):
                if label not in used:
                    try:
                        capture()
                    except Exception as error:
                        failure = recording_failure(failure, error, "after-failure-" + label, report)
        report["result"] = "OWN_SERVICE_REFRESHED_AND_SAME_RUNTIME_SELECTED" if failure is None and ready else "REFRESH_FAILED"
        report["original_lifecycle_may_run"] = failure is None and ready
        if not report["original_lifecycle_may_run"]:
            failure = failure or RuntimeError("Refresh did not establish every required condition")
            report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        report["finished_unix"], report["elapsed_seconds"] = time.time(), time.monotonic() - started
        failure = save_preserving_failure(save, failure, "final-refresh-result-save", report)
        if failure is not None:
            ready = False
            report["original_lifecycle_may_run"], report["result"] = False, "REFRESH_FAILED"
            report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
    try:
        print(report["result"], "service_sigterm_invocations=" + str(report["service_refresh"]["sigterm_invocations"]), "product_pass=false candidate_credit=false")
    except Exception as error:
        failure = recording_failure(failure, error, "final-refresh-console", report)
        report["original_lifecycle_may_run"], report["result"] = False, "REFRESH_FAILED"
        report["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        failure = save_preserving_failure(save, failure, "console-failure-result-save", report)
    if failure is not None:
        raise failure
    return report


"""New derivative adapter: explicit source/control identity and local evidence."""


def require_contract(value, message):
    if not value:
        raise ValueError(message)


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def reject_constant(value):
        raise ValueError("Non-finite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)


def full_sha(value):
    require_contract(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value),
                     "An exact full Git SHA is required")
    return value


def positive_decimal(value):
    require_contract(type(value) in (str, int) and re.fullmatch(r"[1-9][0-9]*", str(value)),
                     "A positive run/attempt/artifact/job ID is required")
    return str(value)


def safe_relative(value):
    require_contract(type(value) is str and value not in ("", ".") and "\\" not in value
                     and not any(ord(c) < 32 or ord(c) == 127 for c in value), "Unsafe relative path")
    path = Path(value)
    require_contract(not path.is_absolute() and path.as_posix() == value and ".." not in path.parts,
                     "Unsafe relative path")
    return value


def unlinked_path(path, root):
    require_contract(path.is_absolute() and root.is_absolute() and path.is_relative_to(root),
                     "Path must be inside the declared absolute source root")
    for item in (path, *path.parents):
        require_contract(not item.is_symlink(), "Symlink in source/evidence path: " + str(item))
        if item == root:
            break
    return path


def absolute_root(value):
    path = Path(value)
    require_contract(path.is_absolute() and path.is_dir() and path.resolve() == path,
                     "Require an existing exact absolute source/control root without aliases")
    for item in (path, *path.parents):
        require_contract(not item.is_symlink(), "Linked source/control root")
    return path


def regular_bytes(path, root, maximum=8 * 1024 * 1024):
    unlinked_path(path, root)
    before = path.lstat()
    require_contract(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum,
                     "Expected a bounded non-symlink regular evidence/source file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require_contract(file_identity(os.fstat(stream.fileno())) == file_identity(before),
                         "File changed before opening")
        raw = stream.read(maximum + 1)
        require_contract(len(raw) <= maximum and file_identity(os.fstat(stream.fileno())) == file_identity(before),
                         "File changed or exceeded its read limit")
    require_contract(file_identity(path.lstat()) == file_identity(before), "File changed during read")
    return raw, {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw),
                 "mode": stat.S_IMODE(before.st_mode)}


def git_read(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments], timeout=METADATA_TIMEOUT)


def git_root_identity(root, declared_commit, declared_tree):
    full_sha(declared_commit); full_sha(declared_tree)
    require_contract(git_read(root, "rev-parse", "--show-toplevel").decode().strip() == str(root),
                     "The declared root is not the exact Git worktree root")
    commit = git_read(root, "rev-parse", "HEAD").decode().strip()
    tree = git_read(root, "rev-parse", "HEAD^{tree}").decode().strip()
    require_contract(commit == declared_commit and tree == declared_tree, "Declared source/control commit or tree differs")
    git_read(root, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--exit-code", commit, "--")
    return {"commit": commit, "tree": tree}


def tracked_regular_file(root, commit, relative, expected_sha256=None, expected_git_mode="100644"):
    relative = safe_relative(relative)
    raw_tree = git_read(root, "ls-tree", "-z", commit, "--", relative)
    rows = [row for row in raw_tree.split(b"\0") if row]
    require_contract(len(rows) == 1, "Require one exact tracked source path")
    meta, name = rows[0].split(b"\t", 1)
    mode, kind, blob = meta.decode().split()
    require_contract(expected_git_mode in ("100644", "100755") and name.decode() == relative
                     and mode == expected_git_mode and kind == "blob",
                     "Helper/config/consumer must match its exact regular Git mode")
    full_sha(blob)
    index = git_read(root, "ls-files", "--stage", "-z", "--", relative)
    require_contract(index == (mode + " " + blob + " 0\t" + relative + "\0").encode(),
                     "Source index entry differs from the exact committed helper/input")
    raw, descriptor = regular_bytes(root / relative, root)
    require_contract(bool(descriptor["mode"] & 0o100) == (mode == "100755"),
                     "Tracked helper/input executable bit differs from Git")
    actual_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require_contract(actual_blob == blob and raw == git_read(root, "cat-file", "blob", blob),
                     "Tracked source bytes differ, including index-flag-hidden changes")
    if expected_sha256 is not None:
        require_contract(descriptor["sha256"] == expected_sha256, "Original consumer/input bytes changed")
    return raw, {**descriptor, "relative_path": relative, "git_mode": mode, "git_blob": blob}


def validate_host():
    require_contract(__debug__ and sys.implementation.name == "cpython" and sys.platform == "darwin"
                     and platform.machine() == "arm64" and tuple(sys.version_info) == (3, 14, 9, "final", 0)
                     and os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
                     and os.environ.get("RUNNER_OS") == "macOS" and os.getuid() == os.geteuid() and os.getuid() > 0
                     and os.environ.get("DEVELOPER_DIR") == EXPECTED_DEVELOPER_DIR,
                     "Require the declared completed CPython cache and hosted Darwin arm64 own-UID environment")
    cache = absolute_root(os.environ["RUNNER_TOOL_CACHE"])
    entry = cache / "Python/3.14.9/arm64"
    require_contract(Path(sys.executable).resolve() == (entry / "bin/python3.14").resolve()
                     and Path(str(entry) + ".complete").is_file(), "Interpreter is not the declared completed cache entry")
    require_contract(sha256_bytes(canonical(ORIGIN_PROFILE).encode()) == ORIGIN_PROFILE_SHA256,
                     "Embedded original-function provenance table changed")


def validate_current_environment(source, control, mode):
    actual_control = full_sha(os.environ["GITHUB_SHA"])
    require_contract(control["commit"] == actual_control, "Actual control checkout differs from GITHUB_SHA")
    if mode == "canonical":
        require_contract(source == control and source["commit"] == actual_control,
                         "Canonical source must be the actual workflow source; do not relabel a different checkout")
    else:
        require_contract(mode == "candidate", "Unknown identity mode")
    repository, job = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_JOB"]
    require_contract(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                     and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job), "Invalid repository/job identity")
    return {"repository": repository, "run_id": positive_decimal(os.environ["GITHUB_RUN_ID"]),
            "attempt": positive_decimal(os.environ["GITHUB_RUN_ATTEMPT"]), "job": job,
            "helper": control, "runner_os": "macOS"}


def git_ref_commit(root, reference):
    # Exact read-only resolution; the input is an argv element, never shell code.
    value = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "--end-of-options",
                            reference + "^{commit}"], capture_output=True, timeout=METADATA_TIMEOUT)
    require_contract(value.returncode in (0, 1), "Git could not inspect the explicit checkout input")
    if value.returncode:
        return None
    return full_sha(value.stdout.decode().strip())


def bind_workflow_input_ref(root, supplied, source, resolver=git_ref_commit):
    require_contract(type(supplied) is str and supplied != "" and "\x00" not in supplied,
                     "A nonempty actual workflow input ref is required")
    # Match the pinned actions/checkout11d596 input-helper/ref-helper rules.
    # Preserve the raw input separately. The action's SHA classification uses
    # ASCII trim; branch/tag lookup uses core.getInput's ECMAScript trim.
    ascii_ref = supplied.strip("\t\n\v\f\r ")
    js_whitespace = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
    effective = supplied.strip(js_whitespace)
    if not effective:
        kind, reference, resolved = "action-empty-input-context-default", os.environ["GITHUB_SHA"], full_sha(os.environ["GITHUB_SHA"])
    elif re.fullmatch(r"[0-9a-fA-F]{40}", ascii_ref):
        kind, reference, resolved = "exact-commit", ascii_ref, ascii_ref.lower()
    else:
        upper = effective.upper()
        if upper.startswith("REFS/HEADS/"):
            kind, reference = "qualified-branch", "refs/remotes/origin/" + effective[len("refs/heads/"):]
        elif upper.startswith("REFS/PULL/"):
            kind, reference = "qualified-pull", "refs/remotes/pull/" + effective[len("refs/pull/"):]
        elif upper.startswith("REFS/"):
            kind, reference = "qualified-ref", effective
        else:
            kind, reference = "unqualified-branch", "refs/remotes/origin/" + effective
            resolved = resolver(root, reference)
            if resolved is None:
                kind, reference = "unqualified-tag", "refs/tags/" + effective
            else:
                require_contract(resolved == source["commit"], "Explicit workflow branch does not resolve to actual checkout")
                return {"raw_input_ref": supplied, "action_ascii_trimmed_ref": ascii_ref, "action_effective_ref": effective,
                        "kind": kind, "resolved_local_reference": reference, "resolved_commit": resolved,
                        "actual_source": source, "resolution_scope": "Original checkout already fetched this input; no new fetch or checkout."}
        resolved = resolver(root, reference)
    require_contract(resolved is not None and resolved == source["commit"],
                     "Explicit workflow ref does not resolve to the actual selected source checkout")
    return {"raw_input_ref": supplied, "action_ascii_trimmed_ref": ascii_ref, "action_effective_ref": effective,
            "kind": kind, "resolved_local_reference": reference, "resolved_commit": resolved,
            "actual_source": source, "resolution_scope": "Original checkout already fetched this input; no new fetch or checkout."}


def workflow_input_environment(request, root, source):
    require_contract(request["owner"] == "statistics" and request["mode"] == "workflow-input",
                     "Explicit workflow-input mode is limited to the original Statistics reusable runtime step")
    require_contract(all(request.get(name) is None for name in ("control_root", "control_commit", "control_tree")),
                     "Workflow-input mode must not assert a nonexistent caller control checkout")
    supplied = request.get("workflow_input_ref")
    require_contract(supplied == os.environ.get("RUNTIME_COMMON_SOURCE_REF"),
                     "Declared source ref differs from the actual workflow input environment")
    binding = bind_workflow_input_ref(root, supplied, source)
    repository, job = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_JOB"]
    require_contract(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                     and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job), "Invalid actual caller repository/job context")
    caller = {"github_sha": full_sha(os.environ["GITHUB_SHA"]), "repository": repository,
              "run_id": positive_decimal(os.environ["GITHUB_RUN_ID"]), "attempt": positive_decimal(os.environ["GITHUB_RUN_ATTEMPT"]),
              "job": job, "runner_os": "macOS", "github_workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
              "github_workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
              "binding_kind": "Actual GitHub caller environment; no caller checkout or caller source-tree equality is claimed."}
    if caller["github_workflow_sha"] is not None:
        full_sha(caller["github_workflow_sha"])
    return caller, binding


def validate_candidate_receipt(value, owner, source, pins, consumer, matrix):
    require_contract(consumer["job"] == "runtime", "Candidate preparation belongs to the unchanged runtime job")
    matches = [row for row in matrix["matrix"] if row["name"] == owner and row["os"] == "xcode-27"]
    require_contract(len(matches) == 1 and matches[0]["sha"] == source["commit"] and matches[0].get("runtime") is True,
                     "Candidate matrix differs from actual source and required runtime coverage")
    require_contract(value.get("status") == "VERIFIED_RUNTIME_INPUT_RESTORED" and value.get("consumer") == consumer,
                     "Original restored consumer context differs from this source/control/run/attempt/job")
    manifest = value["manifest"]
    require_contract(type(manifest["schema"]) is int and manifest["schema"] == 1
                     and manifest["candidate"] == owner and manifest["source"] == source
                     and manifest["native_pins"] == pins and isinstance(manifest["files"], dict) and manifest["files"],
                     "Original restored manifest source/pins/files differ")
    for name, entry in manifest["files"].items():
        safe_relative(name)
        require_contract(type(entry) is dict and set(entry) == {"size", "sha256", "mode"}
                         and type(entry["size"]) is int and entry["size"] >= 0
                         and type(entry["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                         and type(entry["mode"]) is int and entry["mode"] in (0o644, 0o755),
                         "Original restored manifest file identity is malformed")
    producer = manifest["producer"]
    attempt = positive_decimal(producer["attempt"])
    require_contract(int(attempt) <= int(consumer["attempt"])
                     and producer == {**consumer, "attempt": attempt, "job": "build"},
                     "Original producer source/control/run/job or attempt differs")
    job = value["producer_job"]
    positive_decimal(job["id"])
    require_contract(job["name"] == f"build ({owner}, {source['commit']}, xcode-27, true)"
                     and positive_decimal(job["run_id"]) == producer["run_id"]
                     and positive_decimal(job["run_attempt"]) == attempt
                     and job["head_sha"] == consumer["helper"]["commit"]
                     and job["status"] == "completed" and job["conclusion"] == "success",
                     "Original numeric producer job identity/result differs")
    steps = [row for row in job["steps"] if row["name"] == "Execute the exact candidate owner gates"]
    require_contract(len(steps) == 1 and steps[0]["conclusion"] == "success", "Original producer gate step did not succeed")
    positive_decimal(value["input_artifact_id"]); positive_decimal(value["input_artifact_size"])
    require_contract(type(value["input_artifact_digest"]) is str
                     and re.fullmatch(r"sha256:[0-9a-f]{64}", value["input_artifact_digest"])
                     and type(value["archive_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["archive_sha256"]),
                     "Original restored immutable archive identity is malformed")
    return {"producer": producer, "producer_job_id": job["id"], "input_artifact_id": value["input_artifact_id"],
            "input_artifact_digest": value["input_artifact_digest"], "input_artifact_size": value["input_artifact_size"],
            "archive_sha256": value["archive_sha256"], "matrix_row": matches[0],
            "scope": "Rebind the original successful restorer result; this adapter neither restores nor grants runtime success."}


def context_for(request):
    validate_host()
    owner = request["owner"]
    require_contract(owner in OWNER_PROFILES, "Owner has no reviewed runtime preparation profile")
    profile = OWNER_PROFILES[owner]
    root = absolute_root(request["source_root"])
    require_contract(Path.cwd() == root, "Invoke from the explicitly verified source root, independent of helper depth")
    source = git_root_identity(root, request["source_commit"], request["source_tree"])
    if request["mode"] == "workflow-input":
        control_root = control = None
        consumer, input_binding = workflow_input_environment(request, root, source)
    else:
        require_contract(request.get("workflow_input_ref") is None,
                         "Canonical/candidate modes do not accept an unbound extra workflow source ref")
        control_root = absolute_root(request["control_root"])
        control = source if request["mode"] == "canonical" and control_root == root else git_root_identity(
            control_root, request["control_commit"], request["control_tree"])
        require_contract(control == {"commit": request["control_commit"], "tree": request["control_tree"]},
                         "Declared control tuple differs")
        consumer = validate_current_environment(source, control, request["mode"])
    helpers = {}
    for relative in profile["helper_paths"]:
        raw, info = tracked_regular_file(root, source["commit"], relative)
        helpers[relative] = info
    active = profile["helper_paths"][0]
    require_contract(Path(__file__).resolve() == root / active,
                     "Invoke the actual owner helper path, not a control copy or inherited alternate")
    require_contract(len({(row["sha256"], row["git_blob"], row["git_mode"]) for row in helpers.values()}) == 1,
                     "Integrated owned/inherited helper entries are not the same blob/mode")
    raw_features, features_info = tracked_regular_file(root, source["commit"], "Build/features.json")
    features = strict_json(raw_features)
    require_contract(features["name"] == profile["feature_name"], "Wrong actual source owner composition")
    pins = features["sources"]
    require_contract(type(pins) is dict and pins, "Native source pins are missing")
    for path, commit in pins.items():
        if path != ".":
            safe_relative(path)
        full_sha(commit)
    consumers = {}
    for relative, expected in profile["original_files"].items():
        _, consumers[relative] = tracked_regular_file(root, source["commit"], relative,
                                                      expected["sha256"], expected["git_mode"])
    result = {"mode": request["mode"], "source_root": str(root), "control_root": str(control_root) if control_root is not None else None,
              "owner": owner, "source": source, "control": control, "consumer": consumer,
              "own_helper_relative_path": active, "own_helper_sha256": helpers[active]["sha256"],
              "helper_files": {name: row["sha256"] for name, row in helpers.items()},
              "helper_git_entries": helpers, "features_file": features_info, "native_pins": pins,
              "original_consumer_files": consumers, "origin_profile_sha256": ORIGIN_PROFILE_SHA256}
    if request["mode"] == "workflow-input":
        result["actual_caller_environment"] = consumer
        result["workflow_input_binding"] = input_binding
    if request["mode"] == "candidate":
        raw_matrix, matrix_info = tracked_regular_file(control_root, control["commit"], "Bootstrap/candidates.json")
        _, restorer_info = tracked_regular_file(control_root, control["commit"], "Bootstrap/runtime_handoff.py",
                                                ORIGINAL_RESTORER_SHA256)
        receipt_path = root / "artifacts/runtime-input" / owner / "consumer.json"
        raw_receipt, receipt_info = regular_bytes(receipt_path, root, maximum=64 * 1024 * 1024)
        result["original_restorer_binding"] = {"matrix": matrix_info, "restorer": restorer_info, "receipt": receipt_info,
            "identity": validate_candidate_receipt(strict_json(raw_receipt), owner, source, pins, consumer, strict_json(raw_matrix))}
    return result


def phase_context(identity_context):
    consumer = identity_context["consumer"]
    if identity_context.get("mode") == "workflow-input":
        return {"helper_sha": identity_context["actual_caller_environment"]["github_sha"],
                "checked_out_sha": identity_context["source"]["commit"],
                "run_id": consumer["run_id"], "attempt": consumer["attempt"], "identity": identity_context,
                "derivative_schema": "common-runtime-environment-v1",
                "control_binding_kind": "Actual caller GITHUB_SHA; helper bytes belong to the independently verified input source."}
    return {"helper_sha": identity_context["control"]["commit"],
            "checked_out_sha": identity_context["source"]["commit"],
            "run_id": consumer["run_id"], "attempt": consumer["attempt"],
            "identity": identity_context, "derivative_schema": "common-runtime-environment-v1"}


def derivative_source_files(identity_context):
    root = Path(identity_context["source_root"])
    actual = {}
    for relative, expected in identity_context["helper_files"].items():
        _, info = regular_bytes(root / relative, root)
        require_contract(info["sha256"] == expected, "Actual derivative helper bytes changed after Git binding")
        actual[relative] = info["sha256"]
    return actual


def recheck_context(request, expected):
    require_contract(context_for(request) == expected, "Actual source/control/evidence identity changed between phases")


def preparation_root(context):
    root = Path(context["source_root"])
    return unlinked_path(root / OWNER_PROFILES[context["owner"]]["preparation_root"], root)


def write_new_json(path, value, root):
    unlinked_path(path, root)
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
    return regular_bytes(path, root, maximum=max(len(raw), 8 * 1024 * 1024))[1]


def read_bound_json(path, root, expected=None):
    raw, descriptor = regular_bytes(path, root, maximum=64 * 1024 * 1024)
    if expected is not None:
        require_contract(descriptor == expected, "Saved evidence bytes/mode/path differ from their exact descriptor")
    return strict_json(raw), descriptor


"""New derivative adapter: prepare once, preserve each original consumer."""


def command_files(directory, report, root):
    result = []
    labels = set()
    for row in report["commands"]:
        require_contract(row["label"] not in labels, "Duplicate command label")
        labels.add(row["label"])
        for channel in ("stdout", "stderr"):
            name = row[channel + "_file"]
            require_contract(type(name) is str and Path(name).name == name
                             and name == row["label"] + "." + channel + ".log", "Command output is not its exact direct filename")
            raw, info = regular_bytes(directory / name, root, maximum=64 * 1024 * 1024)
            require_contract(info["bytes"] == row[channel + "_file_bytes"]
                             and info["sha256"] == row[channel + "_file_sha256"], "Raw command evidence differs from receipt")
            result.append(info)
    return result


def raw_command_json(directory, label, root):
    return strict_json(regular_bytes(directory / (label + ".stdout.log"), root)[0])


def validate_service_evidence(p, value, context, stage_dir, service_dir, root):
    require_contract(value.get("result") == "OWN_SERVICE_REFRESHED_AND_SAME_RUNTIME_SELECTED"
                     and value.get("original_lifecycle_may_run") is True and value.get("product_pass") is False
                     and value.get("candidate_credit") is False and value.get("success_requires_helper_process_exit_zero") is True
                     and all(value.get(key) == item for key, item in phase_context(context).items())
                     and value.get("helper_source_sha256") == context["own_helper_sha256"]
                     and value.get("source_files") == context["helper_files"], "Service receipt is not the successful same-context derivative")
    require_contract(value["own_uid"] == value["own_euid"] == os.getuid() and os.getuid() > 0,
                     "Service evidence belongs to another UID")
    raw_preflight, pinfo = regular_bytes(stage_dir / "preflight-result.json", root)
    require_contract(regular_bytes(service_dir / "bound-preflight-result.json", root)[0] == raw_preflight
                     and value["preflight_binding"]["path"] == pinfo["path"]
                     and value["preflight_binding"]["bytes"] == pinfo["bytes"]
                     and value["preflight_binding"]["sha256"] == pinfo["sha256"], "Service bound another preflight")
    commands = {row["label"]: row for row in value["commands"]}
    require_contract(len(commands) == len(value["commands"]) and set(commands) == set(REFRESH_READ_COMMANDS),
                     "Service read command inventory differs")
    for label, argv in REFRESH_READ_COMMANDS.items():
        row = commands[label]
        require_contract(row["argv"] == argv and row.get("returncode") == 0
                         and row.get("requested_timeout_seconds") == METADATA_TIMEOUT and row.get("timeout") is not True
                         and "error" not in row and not row.get("recording_errors"), "Service metadata command failed or changed")
    files = command_files(service_dir, value, root)
    require_contract(not value.get("owned_metadata_child_cleanup_signals") and not value.get("recording_errors")
                     and "failure" not in value, "Successful service evidence contains a failure/cleanup signal")
    for phase in ("before", "after"):
        current = value["runtime_snapshots"][phase]
        require_contract(current["inventory"] == raw_command_json(service_dir, "runtime-images-" + phase, root),
                         "Service runtime snapshot differs from raw stdout")
        require_contract(validate_runtime(p, current["inventory"], current["filesystem"]) == current["scope_validation"],
                         "Service runtime scope no longer validates")
    before = require_shutdown_devices(raw_command_json(service_dir, "devices-before", root))
    after = require_shutdown_devices(raw_command_json(service_dir, "devices-after", root))
    preflight_devices = require_shutdown_devices(raw_command_json(stage_dir, "devices-after", root))
    require_contract(before == value["devices_before"] and after == value["devices_after"]
                     and preflight_devices == value["preflight_devices_after"]
                     and before["device_identities"] == after["device_identities"] == preflight_devices["device_identities"],
                     "Device identities were not preserved through the one service refresh")
    natives = {}
    for label in ("service-before", "service-before-signal", "service-after-exit", "service-final"):
        text = regular_bytes(service_dir / (label + ".stdout.log"), root)[0].decode()
        rows = service_rows(text)
        saved = value["service_snapshots"][label]
        require_contract(saved["candidate_rows"] == rows, "Service ps candidates differ from raw stdout")
        chosen = select_owned_service(rows, value["own_uid"], allow_absent=label == "service-after-exit")
        require_contract(saved["own_service_observed"] == (chosen is not None), "Service presence differs")
        if chosen is not None:
            require_contract(saved["ps_identity"] == chosen, "Selected ps identity differs")
            natives[label] = validate_native(chosen, saved["native_identity"], value["own_uid"])
            require_contract(saved["executable_filesystem"].get("capture") == "observed"
                             and saved["executable_filesystem"].get("is_regular") is True, "Missing service executable filesystem evidence")
        else:
            natives[label] = None
    refresh = value["service_refresh"]
    old, replacement = natives["service-before"], natives["service-final"]
    require_contract(refresh["target_native_identity"] == refresh["final_native_identity"] == refresh["immediate_native_identity"]
                     == natives["service-before-signal"] == old
                     and refresh["replacement_native_identity"] == replacement,
                     "Immediate target or replacement native identity changed")
    require_contract(refresh["target_executable"] == SERVICE_PATH and refresh["sigterm_attempts"] == refresh["sigterm_invocations"] == 1
                     and refresh["signal_returned_successfully"] is True and refresh["old_service_exit_observed"] is True
                     and refresh["force_fallbacks"] == refresh["other_infrastructure_service_signals"] == 0
                     and not refresh.get("failure") and not refresh.get("recording_errors") and not refresh["events_before_signal"],
                     "Service refresh is not the exact single successful owned SIGTERM")
    registration = refresh["registration"]
    change = registration["change"]
    require_contract(registration["returned_without_error"] is True and registration["events"] == []
                     and change["ident"] == old["pid"] and change["filter"] == select.KQ_FILTER_PROC
                     and change["flags"] == select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_ONESHOT
                     and change["fflags"] == select.KQ_NOTE_EXIT | select.KQ_NOTE_EXEC,
                     "Service watcher registration differs from the original boundary")
    events = refresh["events_after_signal"]
    require_contract(len(events) == 1 and events[0]["ident"] == old["pid"] and events[0]["filter"] == select.KQ_FILTER_PROC
                     and not events[0]["flags"] & select.KQ_EV_ERROR and events[0]["fflags"] & select.KQ_NOTE_EXIT
                     and not events[0]["fflags"] & select.KQ_NOTE_EXEC, "Exact target NOTE_EXIT evidence is missing")
    require_contract(value["service_exit_wait_seconds"] == EXIT_TIMEOUT == 10
                     and value["metadata_timeout_seconds"] == METADATA_TIMEOUT == 10
                     and replacement["pid"] != old["pid"]
                     and replacement["start_seconds"] * 1000000 + replacement["start_microseconds"]
                         > old["start_seconds"] * 1000000 + old["start_microseconds"]
                     and (natives["service-after-exit"] is None or natives["service-after-exit"] == replacement)
                     and value["service_snapshots"]["service-before"]["executable_filesystem"]
                         == value["service_snapshots"]["service-final"]["executable_filesystem"],
                     "Service replacement or original deadlines differ")
    for phase in ("before", "after"):
        for key in ("source_dmg_after", "staged_dmg_after"):
            bound = value["dmg_stats"][phase][key]
            expected = p[key]
            require_contract(bound.get("capture") == "observed" and bound.get("is_regular") is True
                             and bound.get("is_symlink") is False and bound.get("matches_verified_receipt") is True
                             and bound.get("additional_content_hash_performed") is False
                             and bound["bound_preflight_sha256"] == expected["sha256"]
                             and all(bound[field] == expected[field] for field in ("path", "resolved_path", "identity")),
                             "DMG stat binding differs from actual same-run hash proof")
    new = p["scope_after_verify"]["new_uuid"]
    selection = require_logical_selection(raw_command_json(service_dir, "logical-runtimes-after", root),
                                         raw_command_json(service_dir, "device-types-after", root),
                                         value["runtime_snapshots"]["after"]["inventory"][new], p["sdk"])
    require_contract(selection == value["logical_selection"]
                     and selection["expected_later_lifecycle_bundle_path"] == p["logical_selection"]["expected_later_lifecycle_bundle_path"],
                     "Logical service selection differs from its exact staged bundle")
    return files


# Source-owned reconstructed V6 retirement: frozen shared-Watch and ambient tvOS roles, saved replay and terminal host binding.
RETIREMENT_DELETE_SECONDS = 120
RETIREMENT_MAX_TARGETS = 3
RETIREMENT_SETTLEMENT_SECONDS = 120
RETIREMENT_SAMPLE_INTERVAL_SECONDS = 2
RETIREMENT_MAX_SCHEDULED_SNAPSHOTS = 60
RETIREMENT_UNUSABLE_FIELDS = ('unusableErrorDetail', 'unusableErrorMessage', 'unusableSubstate')
RETIREMENT_UUID = re.compile(r'[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}')

RETIREMENT_PLAN_SCHEMA = 'common-runtime-retirement-watch-ambient-tvos-observation-plan-v6'
RETIREMENT_ALIAS_ROLES_SCHEMA = 'common-runtime-watch-and-ambient-tvos-protected-alias-roles-v6'
RETIREMENT_KNOWN_SHARED_WATCH_IDS = frozenset(('4E2A8325-62E2-427F-A198-FFEE1E5EF15A',
                                  '61FE15D4-6286-4FC9-B531-8FFEAAD0E8D8'))
RETIREMENT_SHARED_WATCH_MOUNT = '/private/var/run/com.apple.security.cryptexd/mnt/watchOS_24R362'
RETIREMENT_SHARED_WATCH_BUNDLE = RETIREMENT_SHARED_WATCH_MOUNT + '/Library/Developer/CoreSimulator/Profiles/Runtimes/watchOS 27.0.simruntime'
RETIREMENT_EXACT_UNUSABLE_DETAIL = ('Error Domain=SimDiskImageErrorDomain Code=7 "Cryptex Mount Preferred" '
                         'UserInfo={NSLocalizedDescription=Cryptex Mount Preferred, unusableErrorDetail=}')


RETIREMENT_PROGRESS_SCHEMA = 'common-runtime-watch-and-ambient-tvos-observation-ledger-v6'
RETIREMENT_AMBIENT_POLICY_SCHEMA = 'common-runtime-known-old-tvos-observation-policy-v6'
RETIREMENT_AMBIENT_PROGRESS_SCHEMA = 'common-runtime-known-old-tvos-monotone-observation-ledger-v6'
RETIREMENT_MAX_AMBIENT_OBSERVERS = 1
RETIREMENT_AMBIENT_TVOS_UUID = '54D35026-7325-4069-BF3A-FDFEA26D5885'
RETIREMENT_AMBIENT_TVOS_RUNTIME = 'com.apple.CoreSimulator.SimRuntime.tvOS-27-0'
RETIREMENT_AMBIENT_TVOS_ASSET = '/System/Library/AssetsV2/com_apple_MobileAsset_appleTVOSSimulatorRuntime/f6a3a9321156c52c0d245f50953d9867b2b139ab.asset/AssetData'
RETIREMENT_AMBIENT_TVOS_MOUNT = '/private/var/run/com.apple.security.cryptexd/mnt/tvOS_24J360'
RETIREMENT_AMBIENT_TVOS_BUNDLE = RETIREMENT_AMBIENT_TVOS_MOUNT + '/Library/Developer/CoreSimulator/Profiles/Runtimes/tvOS 27.0.simruntime'
RETIREMENT_AMBIENT_TVOS_DMG = RETIREMENT_AMBIENT_TVOS_ASSET + '/Restore/043-16887-522.dmg'


def retirement_unusable_duplicate(row):
    return (row.get('state') == 'Unusable'
            and row.get('unusableErrorMessage') == 'Cryptex Mount Preferred'
            and row.get('unusableSubstate') == 'Cryptex Mount Preferred'
            and ('unusableErrorDetail' not in row or
                 isinstance(row['unusableErrorDetail'], str) and 'Cryptex Mount Preferred' in row['unusableErrorDetail']))

def retirement_enoent_path(row, path):
    """Only the original path_snapshot's concrete FileNotFoundError is missing."""
    return row == {'value': path, 'capture': 'unavailable',
                   'error': {'type': 'FileNotFoundError', 'errno': 2,
                             'message': str(FileNotFoundError(2, os.strerror(2), path))}}

def retirement_paths_overlap(left, right):
    a, b = Path(left), Path(right)
    return a.is_relative_to(b) or b.is_relative_to(a)

def retirement_fixed_paths(records, old, watches):
    """Key the ledger by literal path; both watch UUIDs may share one alias."""
    paths = {}
    for key in [old, *watches]:
        fields = ('mountPath',) if key == old else ('mountPath', 'runtimeBundlePath', 'path', 'parentMountPath')
        for field in fields:
            value = records[key][field]
            require_contract(isinstance(value, str) and Path(value).is_absolute() and Path(value).as_posix() == value
                    and '..' not in Path(value).parts, 'Malformed frozen path')
            paths.setdefault(value, []).append({'uuid': key, 'field': field})
    return paths

def retirement_runtime_mount_rows(data, mounts, keys):
    paths = {data[key][field] for key in keys for field in ('mountPath', 'runtimeBundlePath')}
    return {path: mounts.get(path, []) for path in sorted(paths)}

def retirement_watch_state(frozen, current):
    if current is None:
        return 'Absent'
    if canonical(current) == canonical(frozen) and retirement_unusable_duplicate(current):
        return 'Unusable'
    deleting = {key: value for key, value in frozen.items() if key not in RETIREMENT_UNUSABLE_FIELDS}
    deleting['state'] = 'Deleting'
    require_contract(canonical(current) == canonical(deleting), 'Watch record changed beyond the exact observed Deleting transition')
    return 'Deleting'

def check_retirement_delete_request(plan, attempted, invoked, target, argv, timeout):
    require_contract(plan is not None and target == plan['old_ios_uuid'] and plan['mutation_target_ids'] == [target]
            and not attempted and not invoked, 'Only the frozen old iOS may receive one total mutation attempt')
    require_contract(argv == ['xcrun', 'simctl', 'runtime', 'delete', target, '--keep-asset']
            and timeout == RETIREMENT_DELETE_SECONDS, 'Mutation is outside the single old-iOS keep-asset command')

def retirement_watch_literal_pair(row):
    """Freeze one complete Watch pair; absence cannot choose another flavor."""
    canonical_mount = RETIREMENT_SHARED_WATCH_MOUNT
    volumes_mount = '/Library/Developer/CoreSimulator/Volumes/watchOS_24R362'
    mount = row.get('mountPath')
    require_contract(mount in (canonical_mount, volumes_mount), 'Shared Watch mount is outside its literal pair set')
    bundle = mount + '/Library/Developer/CoreSimulator/Profiles/Runtimes/watchOS 27.0.simruntime'
    require_contract(row.get('runtimeBundlePath') == bundle, 'Shared Watch mount/bundle pair is mixed or indirect')
    return {'schema': 'common-runtime-watch-literal-pair-v6',
            'flavor': 'canonical' if mount == canonical_mount else 'Volumes',
            'mountPath': mount, 'runtimeBundlePath': bundle}


def retirement_watch_volumes_closure(common, plan, current, preflight, pair, shared_ids):
    """Only new Volumes sharing adds original-preflight raw equality and both-alias closure."""
    data, ready = plan['baseline_inventory'], plan['ready_watch_uuid']
    require_contract(pair['flavor'] == 'Volumes' and 1 <= len(shared_ids) <= 2
            and set(shared_ids) <= RETIREMENT_KNOWN_SHARED_WATCH_IDS
            and set(shared_ids) == set(plan['watch_observation_ids'])
            and set(common.watch_records(data)) == {ready, *shared_ids},
            'Volumes Watch requires one or two known old registrations and its sole Ready')
    before = preflight['runtime_snapshots']['before']['inventory']
    require_contract(all(key in before and canonical(before[key]) == canonical(data[key]) for key in (ready, *shared_ids)),
            'Volumes Watch was not the exact typed original preflight registration set')
    roots = (RETIREMENT_SHARED_WATCH_MOUNT, '/Library/Developer/CoreSimulator/Volumes/watchOS_24R362', common.WATCH_ASSET)
    fields = {'mountPath': pair['mountPath'], 'runtimeBundlePath': pair['runtimeBundlePath'],
              'path': common.WATCH_ASSET, 'parentMountPath': common.WATCH_ASSET}
    closure = []
    for key, record in sorted(data.items()):
        for location, value in retirement_absolute_path_values(record):
            require_contract(Path(value).as_posix() == value and '..' not in Path(value).parts and '\0' not in value and '//' not in value,
                    'Volumes Watch recursive absolute reference is not a direct literal path')
            if any(retirement_paths_overlap(root, value) for root in roots):
                require_contract(key in (ready, *shared_ids) and len(location) == 1 and location[0] in fields
                        and value == fields[location[0]],
                        'Volumes Watch canonical/Volumes aliases or asset overlap another runtime, nested field or ancestor')
                closure.append({'uuid': key, 'field': location[0], 'value': value})
    for path in dict.fromkeys(fields.values()):
        observation = current['fixed_path_observations'][path]
        captured = observation['filesystem']
        require_contract(set(observation) == {'filesystem', 'resolved_path', 'symlink_components',
                                             'os_path_ismount', 'related_mount_rows'}
                and observation['resolved_path'] == path and observation['symlink_components'] == [],
                'Volumes Watch lacks a direct fixed physical observation')
        require_contract(set(captured) == {'value', 'capture', 'resolved_path', 'device', 'inode', 'mode', 'uid', 'gid',
                                          'is_directory', 'is_regular'}
                and captured['value'] == captured['resolved_path'] == path and captured['capture'] == 'observed'
                and captured['is_directory'] is True and captured['is_regular'] is False
                and all(type(captured[key]) is int and captured[key] >= 0 for key in ('device', 'inode', 'mode', 'uid', 'gid'))
                and captured['device'] > 0 and captured['inode'] > 0,
                'Volumes Watch physical identity is unavailable, indirect or not typed')
        for key in (ready, *shared_ids):
            for field, value in fields.items():
                if value == path:
                    require_contract(canonical(captured) == canonical(current['filesystem'][key][field]),
                            'Volumes Watch shared asset/alias reads disagree')
        is_mount = path == pair['mountPath']
        rows = {path: current['mount_table'].get(path, [])} if is_mount else {}
        require_contract(observation['os_path_ismount'] is is_mount
                and canonical(observation['related_mount_rows']) == canonical(rows)
                and (not is_mount or len(rows[path]) == 1),
                'Volumes Watch requires one literal mount and no descendant/bundle/asset mount')
    return closure


def retirement_exact_shared_watch_record(common, key, row, *, ready):
    """A narrower complete record contract applies only to the new shared case."""
    pair = retirement_watch_literal_pair(row)
    expected = {'identifier': key, 'runtimeIdentifier': common.WATCH,
                'platformIdentifier': 'com.apple.platform.watchsimulator',
                'version': '27.0', 'build': '24R362', 'kind': 'Patchable Cryptex Disk Image',
                'state': 'Ready' if ready else 'Unusable', 'signatureState': 'Unknown',
                'deletable': True, 'sizeBytes': 3814435665, 'supportedArchitectures': ['arm64'],
                'path': common.WATCH_ASSET, 'parentMountPath': common.WATCH_ASSET,
                'mountPath': pair['mountPath'], 'runtimeBundlePath': pair['runtimeBundlePath']}
    if not ready:
        require_contract(key in RETIREMENT_KNOWN_SHARED_WATCH_IDS, 'Shared alias belongs to an unknown old Watch UUID')
        expected.update(unusableErrorMessage='Cryptex Mount Preferred',
                        unusableSubstate='Cryptex Mount Preferred', unusableErrorDetail=RETIREMENT_EXACT_UNUSABLE_DETAIL)
    require_contract(canonical(row) == canonical(expected), 'Shared Watch complete metadata differs: ' + key)


def freeze_retirement_alias_roles(common, plan, current, preflight):
    """Classify literal paths once; no disappearance can later change a role."""
    def path_values(value, location=()):
        if isinstance(value, str) and Path(value).is_absolute():
            yield location, value
        elif isinstance(value, dict):
            for key, child in sorted(value.items()):
                yield from path_values(child, (*location, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from path_values(child, (*location, index))

    data, ready = plan['baseline_inventory'], plan['ready_watch_uuid']
    frozen_pair = retirement_watch_literal_pair(data[ready])
    pair = {field: frozen_pair[field] for field in ('mountPath', 'runtimeBundlePath')}
    shared_ids = sorted(key for key in plan['watch_observation_ids']
                        if all(data[key].get(field) == data[ready].get(field) for field in pair))
    if shared_ids:
        retirement_exact_shared_watch_record(common, ready, data[ready], ready=True)
        for key in shared_ids:
            retirement_exact_shared_watch_record(common, key, data[key], ready=False)
    volumes_closure = None
    if shared_ids and frozen_pair['flavor'] == 'Volumes':
        volumes_closure = retirement_watch_volumes_closure(common, plan, current, preflight, frozen_pair, shared_ids)
    roles = {}
    for path, references in plan['fixed_paths'].items():
        alias = any(ref['field'] in pair for ref in references)
        role = {'role': 'exclusive_alias' if alias else 'retained_asset',
                'frozen_references': references}
        if shared_ids and path in pair.values():
            field = next(name for name, value in pair.items() if value == path)
            expected_refs = [{'uuid': key, 'field': field} for key in shared_ids]
            require_contract(references == expected_refs, 'Shared path has a nonmatching frozen field or mutation target')
            closure = []
            for key, record in sorted(data.items()):
                for location, value in path_values(record):
                    if retirement_paths_overlap(path, value):
                        # Only the exact matching pair is admitted. Its own
                        # mount contains its own bundle; no other nesting is allowed.
                        require_contract(key in [ready, *shared_ids] and len(location) == 1
                                and location[0] in pair and value == pair[location[0]],
                                'Shared Watch path overlaps an unrelated runtime, field or alias')
                        closure.append({'uuid': key, 'field': location[0], 'value': value})
            if volumes_closure is not None:
                closure = volumes_closure
            observation = current['fixed_path_observations'][path]
            captured = observation['filesystem']
            require_contract(observation['resolved_path'] == path and observation['symlink_components'] == []
                    and captured.get('capture') == 'observed' and captured.get('value') == path
                    and captured.get('resolved_path') == path and captured.get('is_directory') is True
                    and canonical(captured) == canonical(current['filesystem'][ready][field]),
                    'Shared Watch path lacks direct protected filesystem identity')
            expected_rows = {path: current['mount_table'].get(path, [])} if field == 'mountPath' else {}
            require_contract(observation['os_path_ismount'] is (field == 'mountPath')
                    and canonical(observation['related_mount_rows']) == canonical(expected_rows)
                    and (field != 'mountPath' or len(expected_rows[path]) == 1),
                    'Shared Watch mount must be unique and its bundle must have no descendant mount')
            proofs = [row for row in current['mount_proofs'] if row['uuid'] == ready]
            require_contract(len(proofs) == 1 and proofs[0]['mount'] == pair['mountPath']
                    and proofs[0]['bundle'] == pair['runtimeBundlePath']
                    and proofs[0]['os_path_ismount'] is True
                    and type(proofs[0]['mount_device']) is int and type(proofs[0]['bundle_device']) is int
                    and proofs[0]['mount_device'] == proofs[0]['bundle_device'] == captured['device']
                    and canonical(proofs[0]['mount_table']) == canonical(current['mount_table'][pair['mountPath']][0]),
                    'Shared Watch protected mount proof differs')
            role.update(role='shared_protected', protected_reference={'uuid': ready, 'field': field},
                        reference_closure=closure, initial_observation=observation)
        roles[path] = role
    return {'schema': RETIREMENT_ALIAS_ROLES_SCHEMA, 'paths': roles,
            'shared_watch_pair': ({'schema': 'common-runtime-shared-watch-pair-v3',
                'literal_pair': frozen_pair, 'ready_uuid': ready, 'old_uuids': shared_ids,
                'new_volumes_reference_closure': volumes_closure} if shared_ids else None)}


def validate_retirement_shared_path(plan, current, progress, path, role):
    """Preserve a fixed protected object even if every old reference is absent."""
    observation = current['fixed_path_observations'][path]
    reference = role['protected_reference']
    require_contract(path not in progress['missing_paths'], 'A shared protected path cannot enter the missing-path ledger')
    require_contract(canonical(observation) == canonical(role['initial_observation'])
            and canonical(observation['filesystem']) == canonical(plan['path_baselines'][path])
            and canonical(observation['filesystem']) == canonical(current['filesystem'][reference['uuid']][reference['field']]),
            'Shared protected Watch path, physical observation or mount rows changed: ' + path)
    for ref in role['frozen_references']:
        if ref['uuid'] in current['inventory']:
            require_contract(canonical(observation['filesystem']) == canonical(current['filesystem'][ref['uuid']][ref['field']]),
                    'Two reads of one shared protected path disagree')


def retirement_absolute_path_values(value, location=()):
    if isinstance(value, str) and Path(value).is_absolute():
        yield location, value
    elif isinstance(value, dict):
        for key, child in sorted(value.items()):
            yield from retirement_absolute_path_values(child, (*location, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from retirement_absolute_path_values(child, (*location, index))


def retirement_tvos_literal_pair(row):
    """Freeze one closed tvOS pair before the old UUID can disappear."""
    canonical_mount = RETIREMENT_AMBIENT_TVOS_MOUNT
    volumes_mount = '/Library/Developer/CoreSimulator/Volumes/tvOS_24J360'
    mount = row.get('mountPath')
    require_contract(mount in (canonical_mount, volumes_mount), 'Ambient tvOS mount is outside its literal pair set')
    bundle = mount + '/Library/Developer/CoreSimulator/Profiles/Runtimes/tvOS 27.0.simruntime'
    require_contract(row.get('runtimeBundlePath') == bundle, 'Ambient tvOS mount/bundle pair is mixed or indirect')
    return {'schema': 'common-runtime-tvos-literal-pair-v5',
            'flavor': 'canonical' if mount == canonical_mount else 'Volumes',
            'mountPath': mount, 'runtimeBundlePath': bundle}


def retirement_exact_ambient_tvos_record(key, row, *, ready):
    """Only the observed 27.0/24J360 pair receives the new ambient policy."""
    require_contract(RETIREMENT_UUID.fullmatch(key) is not None, 'Malformed tvOS UUID')
    pair = retirement_tvos_literal_pair(row)
    expected = {'identifier': key, 'runtimeIdentifier': RETIREMENT_AMBIENT_TVOS_RUNTIME,
                'platformIdentifier': 'com.apple.platform.appletvsimulator',
                'version': '27.0', 'build': '24J360', 'kind': 'Patchable Cryptex Disk Image',
                'state': 'Ready' if ready else 'Unusable', 'signatureState': 'Unknown',
                'deletable': True, 'sizeBytes': 3697822545, 'supportedArchitectures': ['arm64'],
                'path': RETIREMENT_AMBIENT_TVOS_ASSET, 'parentMountPath': RETIREMENT_AMBIENT_TVOS_ASSET,
                'mountPath': pair['mountPath'], 'runtimeBundlePath': pair['runtimeBundlePath']}
    if not ready:
        require_contract(key == RETIREMENT_AMBIENT_TVOS_UUID, 'Unknown old tvOS cannot become ambient')
        expected.update(unusableErrorMessage='Cryptex Mount Preferred',
                        unusableSubstate='Cryptex Mount Preferred', unusableErrorDetail=RETIREMENT_EXACT_UNUSABLE_DETAIL)
    require_contract(canonical(row) == canonical(expected), 'Ambient tvOS complete typed metadata differs: ' + key)


def retirement_ambient_tvos_identity(preflight, data):
    """Freeze zero or one known observer; it is never an absence or delete target."""
    tvos = {key: row for key, row in data.items()
            if row.get('platformIdentifier') == 'com.apple.platform.appletvsimulator'
            or str(row.get('runtimeIdentifier', '')).startswith('com.apple.CoreSimulator.SimRuntime.tvOS-')}
    require_contract(all(row.get('state') == 'Ready' or key == RETIREMENT_AMBIENT_TVOS_UUID for key, row in tvos.items()),
            'Unknown non-Ready tvOS registration is outside the ambient policy')
    if RETIREMENT_AMBIENT_TVOS_UUID not in data or data[RETIREMENT_AMBIENT_TVOS_UUID].get('state') == 'Ready':
        return None
    retirement_exact_ambient_tvos_record(RETIREMENT_AMBIENT_TVOS_UUID, data[RETIREMENT_AMBIENT_TVOS_UUID], ready=False)
    before = preflight['runtime_snapshots']['before']['inventory']
    require_contract(RETIREMENT_AMBIENT_TVOS_UUID in before
            and canonical(before[RETIREMENT_AMBIENT_TVOS_UUID]) == canonical(data[RETIREMENT_AMBIENT_TVOS_UUID]),
            'Ambient old tvOS was not the exact original preflight registration')
    same_runtime = [key for key, row in data.items() if row.get('runtimeIdentifier') == RETIREMENT_AMBIENT_TVOS_RUNTIME]
    ready = [key for key in same_runtime if data[key].get('state') == 'Ready']
    require_contract(len(ready) == 1 and set(same_runtime) == {RETIREMENT_AMBIENT_TVOS_UUID, ready[0]},
            'Ambient tvOS requires its sole exact Ready counterpart')
    retirement_exact_ambient_tvos_record(ready[0], data[ready[0]], ready=True)
    pair = retirement_tvos_literal_pair(data[RETIREMENT_AMBIENT_TVOS_UUID])
    require_contract(canonical(pair) == canonical(retirement_tvos_literal_pair(data[ready[0]])),
            'Ambient tvOS old and sole Ready do not share one complete literal pair')
    return {'schema': RETIREMENT_AMBIENT_POLICY_SCHEMA, 'uuid': RETIREMENT_AMBIENT_TVOS_UUID,
            'ready_uuid': ready[0], 'dmg_path': RETIREMENT_AMBIENT_TVOS_DMG, 'literal_pair': pair,
            'absence_required': False, 'delete_invocations_allowed': 0}


def extend_retirement_ambient_paths(paths, ambient, data):
    if ambient is None:
        return paths
    original = tuple(paths)
    for field in ('mountPath', 'runtimeBundlePath', 'path', 'parentMountPath'):
        value = data[ambient['uuid']][field]
        require_contract(isinstance(value, str) and Path(value).is_absolute() and Path(value).as_posix() == value
                and '..' not in Path(value).parts and not any(retirement_paths_overlap(value, other) for other in original),
                'Ambient tvOS path overlaps an old iOS/Watch role or is indirect')
        paths.setdefault(value, []).append({'uuid': ambient['uuid'], 'field': field})
    return paths


def freeze_retirement_ambient_roles(plan, current):
    """Bind the full recursive reference closure and direct physical evidence."""
    ambient = plan['ambient_tvos']
    if ambient is None:
        require_contract('tvos_dmg' not in current['asset_files'], 'Unexpected ambient DMG evidence')
        return
    old, ready = ambient['uuid'], ambient['ready_uuid']
    data = plan['baseline_inventory']
    frozen_pair = ambient['literal_pair']
    pair = {field: frozen_pair[field] for field in ('mountPath', 'runtimeBundlePath')}
    require_contract(canonical(frozen_pair) == canonical(retirement_tvos_literal_pair(data[old]))
            == canonical(retirement_tvos_literal_pair(data[ready])), 'Ambient frozen literal pair differs')
    closure_roots = [*pair.values(), RETIREMENT_AMBIENT_TVOS_ASSET]
    if frozen_pair['flavor'] == 'Volumes':
        closure_roots.extend((RETIREMENT_AMBIENT_TVOS_MOUNT, RETIREMENT_AMBIENT_TVOS_BUNDLE))
    fields = dict(pair, path=RETIREMENT_AMBIENT_TVOS_ASSET, parentMountPath=RETIREMENT_AMBIENT_TVOS_ASSET)
    for path in dict.fromkeys(fields.values()):
        same_fields = [field for field, value in fields.items() if value == path]
        references = [{'uuid': old, 'field': field} for field in same_fields]
        require_contract(plan['fixed_paths'][path] == references, 'Ambient path has mixed frozen roles')
        closure = []
        for key, record in sorted(data.items()):
            for location, value in retirement_absolute_path_values(record):
                if frozen_pair['flavor'] == 'Volumes':
                    require_contract(Path(value).as_posix() == value and '..' not in Path(value).parts and '\0' not in value and '//' not in value,
                            'Ambient Volumes tvOS recursive absolute reference is not a direct literal path')
                if (any(retirement_paths_overlap(root, value) for root in closure_roots)
                        if frozen_pair['flavor'] == 'Volumes' else retirement_paths_overlap(path, value)):
                    require_contract(key in (old, ready) and len(location) == 1 and location[0] in fields
                            and value == fields[location[0]],
                            'Ambient tvOS path overlaps an unrelated runtime, nested field or alias')
                    closure.append({'uuid': key, 'field': location[0], 'value': value})
        observation = current['fixed_path_observations'][path]
        captured = observation['filesystem']
        require_contract(set(observation) == {'filesystem', 'resolved_path', 'symlink_components',
                                     'os_path_ismount', 'related_mount_rows'}
                and observation['resolved_path'] == path and observation['symlink_components'] == [],
                'Ambient tvOS path lacks a direct fixed physical observation')
        require_contract(set(captured) == {'value', 'capture', 'resolved_path', 'device', 'inode', 'mode', 'uid', 'gid',
                                  'is_directory', 'is_regular'}
                and captured['value'] == captured['resolved_path'] == path and captured['capture'] == 'observed'
                and captured['is_directory'] is True and captured['is_regular'] is False
                and all(type(captured[key]) is int and captured[key] >= 0 for key in ('device', 'inode', 'mode', 'uid', 'gid'))
                and captured['device'] > 0 and captured['inode'] > 0,
                'Ambient tvOS fixed filesystem metadata is unavailable, indirect or malformed')
        for key in (old, ready):
            for field in same_fields:
                require_contract(canonical(captured) == canonical(current['filesystem'][key][field]),
                        'Ambient tvOS shared filesystem reads disagree')
        is_mount = path == pair['mountPath']
        expected_rows = {path: current['mount_table'].get(path, [])} if is_mount else {}
        require_contract(observation['os_path_ismount'] is is_mount
                and canonical(observation['related_mount_rows']) == canonical(expected_rows)
                and (not is_mount or len(expected_rows[path]) == 1),
                'Ambient tvOS mount must be unique; bundle/asset cannot contain another mount')
        plan['alias_roles']['paths'][path] = {
            'role': 'ambient_shared_protected' if path in pair.values() else 'ambient_retained_asset',
            'frozen_references': references, 'protected_uuid': ready,
            'protected_fields': same_fields, 'reference_closure': closure,
            'initial_observation': observation}
    proofs = [row for row in current['mount_proofs'] if row['uuid'] == ready]
    require_contract(len(proofs) == 1, 'Ambient Ready tvOS lacks one actual mount proof')
    proof = proofs[0]
    fs = current['filesystem'][ready]
    require_contract(set(proof) == {'uuid', 'mount', 'bundle', 'mount_table', 'os_path_ismount', 'mount_device', 'bundle_device'}
            and proof['mount'] == pair['mountPath'] and proof['bundle'] == pair['runtimeBundlePath']
            and proof['os_path_ismount'] is True
            and type(proof['mount_device']) is int and type(proof['bundle_device']) is int
            and proof['mount_device'] == proof['bundle_device'] == fs['mountPath']['device'] == fs['runtimeBundlePath']['device']
            and canonical(proof['mount_table']) == canonical(current['mount_table'][pair['mountPath']][0]),
            'Ambient Ready tvOS actual mount identity or membership differs')
    dmg = current['asset_files'].get('tvos_dmg')
    require_contract(isinstance(dmg, dict) and set(dmg) == {'path', 'resolved_path', 'identity', 'is_regular',
                                                 'is_symlink', 'symlink_components', 'nlink'}
            and dmg['path'] == dmg['resolved_path'] == RETIREMENT_AMBIENT_TVOS_DMG
            and dmg['is_regular'] is True and dmg['is_symlink'] is False and dmg['symlink_components'] == []
            and type(dmg['nlink']) is int and dmg['nlink'] > 0,
            'Ambient tvOS requires a new direct DMG stat observation')
    identity = dmg['identity']
    require_contract(set(identity) == {'device', 'inode', 'mode', 'uid', 'gid', 'size', 'mtime_ns', 'ctime_ns'}
            and all(type(value) is int and value >= 0 for value in identity.values())
            and identity['device'] == fs['path']['device'] and identity['inode'] > 0
            and identity['size'] == data[old]['sizeBytes'],
            'Ambient tvOS DMG stat identity or declared size differs')


def retirement_ambient_tvos_state(frozen, current):
    if current is None:
        return 'Absent'
    if canonical(current) == canonical(frozen):
        return 'Unusable'
    deleting = {key: value for key, value in frozen.items() if key not in RETIREMENT_UNUSABLE_FIELDS}
    deleting['state'] = 'Deleting'
    require_contract(canonical(current) == canonical(deleting), 'Ambient tvOS changed beyond its exact typed Deleting transition')
    return 'Deleting'


def validate_retirement_ambient_tvos(plan, current, progress, missing_paths):
    """Continue the frozen guard after ambient absence; do not rediscover a role."""
    require_contract(progress.get('schema') == RETIREMENT_AMBIENT_PROGRESS_SCHEMA
            and set(progress['states']) == set(plan['ambient_observation_ids']), 'Ambient observation ledger differs')
    updated = strict_json(canonical(progress))
    ambient = plan['ambient_tvos']
    if ambient is None:
        require_contract(plan['ambient_observation_ids'] == [], 'Unexpected ambient observation identity')
        return updated
    old, ready = ambient['uuid'], ambient['ready_uuid']
    require_contract(plan['ambient_observation_ids'] == [RETIREMENT_AMBIENT_TVOS_UUID] and old == RETIREMENT_AMBIENT_TVOS_UUID
            and old not in plan['target_ids'] and ready in plan['protected_ids'], 'Ambient role became a target or lost its Ready guard')
    data = current['inventory']
    phase = retirement_ambient_tvos_state(plan['baseline_inventory'][old], data.get(old))
    previous = progress['states'][old]
    allowed = {'Unusable': {'Unusable', 'Deleting', 'Absent'}, 'Deleting': {'Deleting', 'Absent'}, 'Absent': {'Absent'}}
    require_contract(previous in allowed and phase in allowed[previous], 'Ambient tvOS regressed or its UUID reappeared')
    if old in data:
        require_contract(canonical(current['filesystem'][old]) == canonical(plan['baseline_filesystem'][old]),
                'Ambient tvOS surviving filesystem changed')
    if phase == 'Deleting' and old not in updated['deleting_observed']:
        updated['deleting_observed'].append(old)
    if phase != previous:
        updated['transitions'].append({'uuid': old, 'from': previous, 'to': phase, 'snapshot': current['label'],
                                       'observed_unix': current['finished_unix'], 'tvos_delete_invoked': False})
    updated['states'][old] = phase
    if phase == 'Absent' and old not in updated['absence_dispositions']:
        updated['absence_dispositions'][old] = (
            'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AFTER_OBSERVED_DELETING' if old in updated['deleting_observed'] else
            'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AND_WITHOUT_OBSERVED_DELETING')
    pair = ambient['literal_pair']
    require_contract(pair['schema'] == 'common-runtime-tvos-literal-pair-v5', 'Frozen tvOS pair schema differs')
    for path in (pair['mountPath'], pair['runtimeBundlePath'], RETIREMENT_AMBIENT_TVOS_ASSET):
        role = plan['alias_roles']['paths'][path]
        expected_role = 'ambient_retained_asset' if path == RETIREMENT_AMBIENT_TVOS_ASSET else 'ambient_shared_protected'
        require_contract(role['role'] == expected_role and role['protected_uuid'] == ready,
                'Frozen ambient physical role differs')
        observation = current['fixed_path_observations'][path]
        require_contract(path not in missing_paths
                and canonical(observation) == canonical(role['initial_observation'])
                and canonical(observation['filesystem']) == canonical(plan['path_baselines'][path]),
                'Ambient protected fixed path or physical identity changed: ' + path)
        for field in role['protected_fields']:
            require_contract(canonical(observation['filesystem']) == canonical(current['filesystem'][ready][field]),
                    'Ambient protected Ready filesystem reads disagree')
        for ref in role['frozen_references']:
            if ref['uuid'] in data:
                require_contract(canonical(observation['filesystem']) == canonical(current['filesystem'][ref['uuid']][ref['field']]),
                        'Ambient fixed path and surviving old registration disagree')
    return updated


def replay_retirement_plan(common, preflight, service, initial, saved_plan):
    """Recompute a saved V6 plan from bound original inputs; grant no run credit."""
    require_contract(saved_plan.get('schema') == RETIREMENT_PLAN_SCHEMA, 'Saved retirement plan is not explicit V6')
    replayed = freeze_retirement_plan(common, preflight, service, initial)
    require_contract(canonical(saved_plan) == canonical(replayed), 'Saved V6 plan or alias-role ledger differs from replay')
    return replayed


def freeze_retirement_plan(common, preflight, service, current):
    """Pure planning: freeze existing identities, never discover replacement targets."""
    inventory, filesystem = current['inventory'], current['filesystem']
    expected = service['runtime_snapshots']['after']
    require_contract(canonical(inventory) == canonical(expected['inventory']),
            'Runtime registrations changed since completed original preparation')
    require_contract(canonical(filesystem) == canonical(expected['filesystem']),
            'Runtime filesystem identities changed since completed original preparation')
    common.validate_runtime(preflight, inventory, filesystem)
    old = preflight['selected_original_runtime']['target_uuid']
    new = preflight['scope_after_verify']['new_uuid']
    require_contract(old != new and retirement_unusable_duplicate(inventory[old]), 'Exactly the original old iOS duplicate must be Unusable')
    require_contract(inventory[new]['state'] == 'Ready' and inventory[new]['signatureState'] == 'Verified',
            'New staged iOS image is not Ready/Verified')
    watches = common.watch_records(inventory)
    ready = [key for key, row in watches.items() if row['state'] == 'Ready']
    retired_watches = sorted(key for key, row in watches.items() if retirement_unusable_duplicate(row))
    require_contract(len(ready) == 1 and len(retired_watches) <= 2 and set(watches) == set(ready + retired_watches),
            'Require one exact Ready watch27.0 and at most two exact Unusable duplicates; no Copying/Deleting')
    original_watch_ids = set(common.watch_records(preflight['runtime_snapshots']['before']['inventory']))
    require_contract(set(retired_watches) <= original_watch_ids, 'A new or unrelated watch UUID cannot become a target')
    targets = [old, *retired_watches]
    require_contract(1 <= len(targets) <= RETIREMENT_MAX_TARGETS and len(set(targets)) == len(targets)
            and all(RETIREMENT_UUID.fullmatch(key) for key in targets) and new not in targets and ready[0] not in targets,
            'Invalid bounded target set')
    for key in targets:
        require_contract(retirement_unusable_duplicate(inventory[key]), 'Target is not the exact Unusable duplicate class')
    require_contract(all(all(field in inventory[key] for field in RETIREMENT_UNUSABLE_FIELDS) for key in retired_watches),
            'Watch freeze requires all three actual Unusable fields')
    ambient = retirement_ambient_tvos_identity(preflight, inventory)
    ambient_ids = [ambient['uuid']] if ambient else []
    require_contract(len(ambient_ids) <= RETIREMENT_MAX_AMBIENT_OBSERVERS and not set(ambient_ids) & set(targets),
            'Ambient identity cannot enlarge the frozen target set')
    plan = {'schema': RETIREMENT_PLAN_SCHEMA, 'old_ios_uuid': old, 'new_ios_uuid': new, 'ready_watch_uuid': ready[0],
            'target_ids': targets, 'target_records': {key: inventory[key] for key in targets},
            'mutation_target_ids': [old], 'watch_observation_ids': retired_watches,
            'ambient_observation_ids': ambient_ids, 'ambient_tvos': ambient,
            'baseline_inventory': inventory, 'baseline_filesystem': filesystem,
            'protected_ids': sorted(set(inventory) - set(targets) - set(ambient_ids)),
            'devices': current['devices'], 'asset_files': current['asset_files'],
            'protected_mount_paths': [inventory[new]['mountPath'], inventory[ready[0]]['mountPath']],
            'target_order': 'One old-iOS delete, then only scheduled read-only watch observations; no causal claim.'}
    if ambient:
        plan['protected_mount_paths'].append(inventory[ambient['ready_uuid']]['mountPath'])
    plan['fixed_paths'] = extend_retirement_ambient_paths(retirement_fixed_paths(plan['target_records'], old, retired_watches),
                                               ambient, inventory)
    require_contract(set(current['fixed_path_observations']) == set(plan['fixed_paths']), 'Initial literal path ledger differs')
    plan['alias_roles'] = freeze_retirement_alias_roles(common, plan, current, preflight)
    freeze_retirement_ambient_roles(plan, current)
    plan['path_baselines'] = {}
    protected_aliases = [inventory[key][field] for key in plan['protected_ids']
                         for field in ('mountPath', 'runtimeBundlePath')]
    for path, references in plan['fixed_paths'].items():
        baseline = current['fixed_path_observations'][path]['filesystem']
        require_contract(all(baseline == filesystem[ref['uuid']][ref['field']] for ref in references),
                'Shared literal-path observations disagree with the original preparation')
        plan['path_baselines'][path] = baseline
        if plan['alias_roles']['paths'][path]['role'] in ('shared_protected', 'ambient_shared_protected', 'ambient_retained_asset'):
            continue
        if any(ref['field'] in ('mountPath', 'runtimeBundlePath') for ref in references):
            require_contract(not any(retirement_paths_overlap(path, protected) for protected in protected_aliases),
                    'A target alias overlaps a protected runtime mount or bundle')
            require_contract((baseline.get('capture') == 'observed' and baseline.get('is_directory') is True)
                    or retirement_enoent_path(baseline, path), 'Unsupported initial old runtime alias filesystem')
    expected_proof_ids = [new, ready[0], *([ambient['ready_uuid']] if ambient else [])]
    require_contract([row['uuid'] for row in current['mount_proofs']] == expected_proof_ids,
            'Protected actual mount proof identities or order differ')
    plan['protected_mount_proofs'] = current['mount_proofs']
    plan['protected_mount_rows'] = retirement_runtime_mount_rows(inventory, current['mount_table'], plan['protected_ids'])
    plan['initial_alias_limit'] = ('Exclusive aliases retain the V2 non-mount rule. Only the two known observation-only Watch UUIDs '
                                 'may share the sole exact Ready Watch closed canonical/Volumes pair; those paths remain protected and never removable. '
                                 'The separate exact known old tvOS observer is not a target; its Ready counterpart, shared physical '
                                 'paths and direct retained DMG stat stay protected even if its UUID is absent.')
    progress = initial_retirement_progress(plan)
    validate_retirement_snapshot_and_progress(common, plan, current, progress, old_deleted=False)
    return plan

def initial_retirement_progress(plan):
    return {'schema': RETIREMENT_PROGRESS_SCHEMA,
            'ambient_tvos': {'schema': RETIREMENT_AMBIENT_PROGRESS_SCHEMA,
                             'states': {key: 'Unusable' for key in plan['ambient_observation_ids']},
                             'deleting_observed': [], 'absence_dispositions': {}, 'transitions': []},
            'watch_states': {key: 'Unusable' for key in plan['watch_observation_ids']},
            'deleting_observed': [], 'absence_dispositions': {}, 'transitions': [],
            'missing_paths': sorted(path for path, row in plan['path_baselines'].items() if retirement_enoent_path(row, path))}

def validate_retirement_snapshot_and_progress(common, plan, current, progress, *, old_deleted, final=False):
    """Read-only validation; progress is committed only after every guard passes."""
    require_contract(plan.get('schema') == RETIREMENT_PLAN_SCHEMA and plan['alias_roles']['schema'] == RETIREMENT_ALIAS_ROLES_SCHEMA
            and set(plan['alias_roles']['paths']) == set(plan['fixed_paths'])
            and progress.get('schema') == RETIREMENT_PROGRESS_SCHEMA, 'V6 alias-role plan or observation ledger is incomplete')
    data, baseline = current['inventory'], plan['baseline_inventory']
    require_contract(set(data) <= set(baseline), 'New runtime registration appeared; never select a substitute')
    require_contract(set(baseline) - set(data) <= set(plan['target_ids']) | set(plan['ambient_observation_ids']), 'A protected runtime disappeared')
    require_contract(set(current['filesystem']) == set(data), 'Runtime filesystem inventory differs')
    require_contract(common.require_shutdown_devices(current['raw_devices']) == current['devices'], 'Raw device normalization differs')
    require_contract(current['devices'] == plan['devices'], 'Device identities or Shutdown states changed')
    require_contract(canonical(current['asset_files']) == canonical(plan['asset_files']), 'A retained asset/DMG identity changed')
    for key in plan['protected_ids']:
        require_contract(key in data and canonical(data[key]) == canonical(baseline[key]), 'Protected runtime record changed: ' + key)
        require_contract(canonical(current['filesystem'][key]) == canonical(plan['baseline_filesystem'][key]),
                'Protected runtime filesystem changed: ' + key)
    old = plan['old_ios_uuid']
    if old_deleted:
        require_contract(old not in data, 'Own successful old-iOS delete must be followed by its exact UUID absence')
    else:
        require_contract(old in data and data[old] == plan['target_records'][old] and retirement_unusable_duplicate(data[old]),
                'The one old-iOS mutation target is absent or changed before its invocation')
        require_contract(current['filesystem'][old] == plan['baseline_filesystem'][old], 'Old iOS filesystem changed before deletion')
    updated = strict_json(canonical(progress))
    updated['ambient_tvos'] = validate_retirement_ambient_tvos(plan, current, progress['ambient_tvos'], progress['missing_paths'])
    phases = {}
    allowed = {'Unusable': {'Unusable', 'Deleting', 'Absent'}, 'Deleting': {'Deleting', 'Absent'}, 'Absent': {'Absent'}}
    require_contract(set(progress['watch_states']) == set(plan['watch_observation_ids']), 'Watch observation identities differ')
    for key in plan['watch_observation_ids']:
        phase = retirement_watch_state(plan['target_records'][key], data.get(key))
        previous = progress['watch_states'][key]
        require_contract(previous in allowed and phase in allowed[previous], 'Watch state regressed or its frozen UUID reappeared: ' + key)
        phases[key] = phase
        if phase == 'Deleting' and key not in updated['deleting_observed']:
            updated['deleting_observed'].append(key)
        if phase != previous:
            updated['transitions'].append({'uuid': key, 'from': previous, 'to': phase, 'snapshot': current['label'],
                                           'observed_unix': current['finished_unix'], 'watch_delete_invoked': False})
        updated['watch_states'][key] = phase
        if phase == 'Absent' and key not in updated['absence_dispositions']:
            updated['absence_dispositions'][key] = (
                'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AFTER_OBSERVED_DELETING' if key in updated['deleting_observed'] else
                'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AND_WITHOUT_OBSERVED_DELETING')
    require_contract(set(current['fixed_path_observations']) == set(plan['fixed_paths']), 'Fixed old path ledger changed')
    for path, references in plan['fixed_paths'].items():
        role = plan['alias_roles']['paths'][path]
        require_contract(role['frozen_references'] == references
                and role['role'] in ('exclusive_alias', 'retained_asset', 'shared_protected',
                                     'ambient_shared_protected', 'ambient_retained_asset'), 'Frozen alias role differs')
        if role['role'] in ('ambient_shared_protected', 'ambient_retained_asset'):
            continue
        if role['role'] == 'shared_protected':
            validate_retirement_shared_path(plan, current, progress, path, role)
            continue
        observation = current['fixed_path_observations'][path]
        require_contract(observation['resolved_path'] == path and observation['symlink_components'] == [],
                'An old path is an indirect alias: ' + path)
        # This narrowly supported diagnostic starts with old aliases already
        # unmounted. No alias is allowed to appear at any later observation.
        require_contract(observation['os_path_ismount'] is False and observation['related_mount_rows'] == {},
                'An old path or a child acquired an actual mount: ' + path)
        captured, original = observation['filesystem'], plan['path_baselines'][path]
        require_contract(captured.get('value') == path, 'Fixed path observation refers to another path')
        for ref in references:
            if ref['uuid'] in data:
                require_contract(canonical(captured) == canonical(current['filesystem'][ref['uuid']][ref['field']]), 'Two reads of one old path disagree')
        watch_refs = [ref for ref in references if ref['uuid'] in phases]
        removable = (all(ref['field'] in ('mountPath', 'runtimeBundlePath') for ref in references)
                     and ((bool(watch_refs) and all(phases[ref['uuid']] in ('Deleting', 'Absent') for ref in watch_refs))
                          or (not watch_refs and old_deleted)))
        require_contract(canonical(captured) == canonical(original) or (removable and retirement_enoent_path(captured, path)),
                'Old path changed beyond exact identity or permitted ENOENT: ' + path)
        require_contract(path not in progress['missing_paths'] or retirement_enoent_path(captured, path), 'An absent old path reappeared: ' + path)
        if retirement_enoent_path(captured, path) and path not in updated['missing_paths']:
            updated['missing_paths'].append(path)
    new = data[plan['new_ios_uuid']]
    require_contract(new['state'] == 'Ready' and new['signatureState'] == 'Verified', 'Selected iOS lost Ready/Verified')
    watches = common.watch_records(data)
    ready = [key for key, row in watches.items() if row['state'] == 'Ready']
    require_contract(ready == [plan['ready_watch_uuid']], 'Sole Ready watch identity changed; a new Ready UUID is not accepted')
    require_contract(current['mounted_paths'] == plan['protected_mount_paths'], 'Protected actual mount proof is incomplete')
    require_contract(canonical(current['mount_proofs']) == canonical(plan['protected_mount_proofs']), 'Protected actual mount identity, source or options changed')
    require_contract(retirement_runtime_mount_rows(data, current['mount_table'], plan['protected_ids']) == plan['protected_mount_rows'],
            'Non-target runtime mount membership or rows changed')
    if final:
        require_contract(old_deleted, 'No successful own old-iOS deletion was bound')
        require_contract(not (set(plan['target_ids']) & set(data)), 'A frozen duplicate remains')
        require_contract(set(watches) == {plan['ready_watch_uuid']}, 'Watch27.0 is not a single unchanged Ready registration')
        ios = [key for key, row in data.items() if row.get('runtimeIdentifier') == common.IOS]
        require_contract(ios == [plan['new_ios_uuid']], 'Selected iOS runtime still has duplicate registrations')
    return updated

def retirement_common_primitives():
    from types import SimpleNamespace
    return SimpleNamespace(validate_runtime=validate_runtime, watch_records=watch_records,
                           require_shutdown_devices=require_shutdown_devices, IOS=IOS, WATCH=WATCH, WATCH_ASSET=WATCH_ASSET)


def retirement_mount_table(raw):
    rows = {}
    for line in raw.decode().splitlines():
        match = re.fullmatch(r'(.+) on (/.*) \(([^\n]*)\)', line)
        require_contract(match is not None, 'Unparseable actual mount-table row')
        rows.setdefault(match[2], []).append({'source': match[1], 'options': match[3], 'raw_line': line})
    return rows


def retirement_context_groups(context):
    source_entries = {**context['helper_git_entries'], **context['original_consumer_files'],
                      'Build/features.json': context['features_file']}
    groups = [('final-source', context['source_root'], context['source'], source_entries)]
    if context['mode'] == 'candidate':
        binding = context['original_restorer_binding']
        control_entries = {binding[key]['relative_path']: binding[key] for key in ('matrix', 'restorer')}
        groups.append(('final-control', context['control_root'], context['control'], control_entries))
    return groups


def retirement_context_commands(context):
    rows = []
    for prefix, root, identity, entries in retirement_context_groups(context):
        names = sorted(entries)
        rows.extend([(prefix + '-root', ['git', '-C', root, 'rev-parse', '--show-toplevel']),
                     (prefix + '-head', ['git', '-C', root, 'rev-parse', 'HEAD', 'HEAD^{tree}']),
                     (prefix + '-entries', ['git', '-C', root, 'ls-tree', '-r', '-z', 'HEAD', '--', *names]),
                     (prefix + '-index', ['git', '-C', root, 'ls-files', '--stage', '-z', '--', *names]),
                     (prefix + '-cached-diff', ['git', '-C', root, 'diff', '--cached', '--no-ext-diff',
                                               '--no-textconv', '--exit-code', identity['commit'], '--'])])
    if context['mode'] == 'workflow-input':
        reference = context['workflow_input_binding']['resolved_local_reference']
        rows.append(('final-input-ref', ['git', '-C', context['source_root'], 'rev-parse', '--verify',
                                        '--quiet', '--end-of-options', reference + '^{commit}']))
    return rows


def retirement_current_environment(context):
    if context['mode'] != 'workflow-input':
        return validate_current_environment(context['source'], context['control'], context['mode'])
    require_contract(os.environ.get('RUNTIME_COMMON_SOURCE_REF') == context['workflow_input_binding']['raw_input_ref'],
                     'Actual workflow input ref changed during preparation')
    caller = {'github_sha': full_sha(os.environ['GITHUB_SHA']),
              'repository': os.environ['GITHUB_REPOSITORY'],
              'run_id': positive_decimal(os.environ['GITHUB_RUN_ID']),
              'attempt': positive_decimal(os.environ['GITHUB_RUN_ATTEMPT']),
              'job': os.environ['GITHUB_JOB'], 'runner_os': 'macOS',
              'github_workflow_ref': os.environ.get('GITHUB_WORKFLOW_REF'),
              'github_workflow_sha': os.environ.get('GITHUB_WORKFLOW_SHA'),
              'binding_kind': context['consumer']['binding_kind']}
    if caller['github_workflow_sha'] is not None:
        full_sha(caller['github_workflow_sha'])
    return caller


def retirement_asset_files(preflight, watch_dmg, ambient, remaining):
    result = {name: bound_file_stat(preflight[name]) for name in ('source_dmg_after', 'staged_dmg_after')}
    require_contract(all(row['matches_verified_receipt'] for row in result.values()), 'Verified iOS DMG identity changed')
    result['ios_asset'], result['watch_asset'] = path_snapshot(str(IOS_ASSET)), path_snapshot(WATCH_ASSET)
    require_contract(all(result[key].get('capture') == 'observed' and result[key].get('is_directory') is True
                         for key in ('ios_asset', 'watch_asset')), 'Retained asset directory is unavailable')
    info = watch_dmg.lstat()
    require_contract(stat.S_ISREG(info.st_mode) and not watch_dmg.is_symlink() and info.st_size > 0
                     and watch_dmg.resolve() == watch_dmg, 'Retained watch DMG is unavailable or indirect')
    result['watch_dmg'] = {'path': str(watch_dmg), 'resolved_path': str(watch_dmg.resolve()),
                           'is_regular': True, 'is_symlink': False, 'identity': file_identity(info)}
    if ambient is not None:
        remaining()
        path = Path(RETIREMENT_AMBIENT_TVOS_DMG)
        links = [str(item) for item in (path, *path.parents) if item.is_symlink()]
        info = path.lstat()
        require_contract(stat.S_ISREG(info.st_mode) and not links and path.resolve() == path
                         and file_identity(info) == file_identity(path.stat()),
                         'Retained ambient tvOS DMG is unavailable or indirect')
        result['tvos_dmg'] = {'path': str(path), 'resolved_path': str(path.resolve()),
                              'identity': file_identity(info), 'is_regular': True,
                              'is_symlink': False, 'symlink_components': links, 'nlink': info.st_nlink}
        remaining()
    return result


def retirement_filesystem_observation(data, mounts, preflight, plan, watch_dmg, remaining):
    """Live stat-only portion; no device enumeration and no host mutation."""
    remaining()
    ambient = plan['ambient_tvos'] if plan else retirement_ambient_tvos_identity(preflight, data)
    entry = {'inventory': data, 'filesystem': filesystem_snapshot(data),
             'mount_table': mounts, 'mount_paths': sorted(mounts),
             'asset_files': retirement_asset_files(preflight, watch_dmg, ambient, remaining),
             'mounted_paths': [], 'mount_proofs': []}
    new = preflight['scope_after_verify']['new_uuid']
    watches = watch_records(data)
    ready = [key for key, row in watches.items() if row['state'] == 'Ready']
    ready_watch = plan['ready_watch_uuid'] if plan else (ready[0] if len(ready) == 1 else None)
    require_contract(new in data and ready_watch in data, 'A required protected runtime is absent')
    expected_tvos = [ambient['ready_uuid']] if ambient else []
    for key in (new, ready_watch, *expected_tvos):
        remaining()
        row = data[key]
        mount, bundle = Path(row['mountPath']), Path(row['runtimeBundlePath'])
        require_contract(mount.is_absolute() and mount.resolve() == mount and bundle.resolve() == bundle
                         and bundle.is_relative_to(mount), 'Protected mount/bundle is indirect or misplaced')
        require_contract(len(mounts.get(str(mount), [])) == 1 and os.path.ismount(mount),
                         'Protected runtime does not have one actual mount')
        mi, bi = mount.stat(), bundle.stat()
        require_contract(stat.S_ISDIR(mi.st_mode) and stat.S_ISDIR(bi.st_mode) and mi.st_dev == bi.st_dev,
                         'Protected bundle is not on the declared mounted filesystem')
        entry['mounted_paths'].append(str(mount))
        entry['mount_proofs'].append({'uuid': key, 'mount': str(mount), 'bundle': str(bundle),
                                     'mount_table': mounts[str(mount)][0], 'os_path_ismount': True,
                                     'mount_device': mi.st_dev, 'bundle_device': bi.st_dev})
    if plan is None:
        old = preflight['selected_original_runtime']['target_uuid']
        require_contract(old in data, 'The old iOS UUID is absent before the frozen plan')
        paths = retirement_fixed_paths(data, old, sorted(key for key, row in watches.items()
                                                        if retirement_unusable_duplicate(row)))
        paths = extend_retirement_ambient_paths(paths, ambient, data)
    else:
        paths = plan['fixed_paths']
    entry['fixed_path_observations'] = {}
    for value in paths:
        remaining()
        path = Path(value)
        require_contract(len(path.parts) <= 64, 'Fixed old path exceeds the bounded depth')
        links = []
        for component in (path, *path.parents):
            try:
                if stat.S_ISLNK(component.lstat().st_mode):
                    links.append(str(component))
            except FileNotFoundError:
                pass
        entry['fixed_path_observations'][value] = {
            'filesystem': path_snapshot(value), 'resolved_path': str(path.resolve(strict=False)),
            'symlink_components': links, 'os_path_ismount': os.path.ismount(path),
            'related_mount_rows': {key: rows for key, rows in mounts.items() if Path(key).is_relative_to(path)}}
    remaining()
    return entry


def validate_retired_host_invariants(plan, final_ledger, observation):
    """Pure terminal host guard. No device, historical clock or current-host reads."""
    require_contract(plan.get('schema') == RETIREMENT_PLAN_SCHEMA
                     and plan['alias_roles']['schema'] == RETIREMENT_ALIAS_ROLES_SCHEMA
                     and set(plan['alias_roles']['paths']) == set(plan['fixed_paths'])
                     and final_ledger.get('schema') == RETIREMENT_PROGRESS_SCHEMA,
                     'Terminal host requires a fully replayed V6 alias-role plan and ledger')
    data, baseline = observation['inventory'], plan['baseline_inventory']
    require_contract(set(data) - set(plan['ambient_observation_ids']) == set(plan['protected_ids']), 'A frozen duplicate reappeared or protected/new UUID changed')
    require_contract(set(observation['filesystem']) == set(data), 'Terminal filesystem membership differs')
    require_contract(canonical(observation['asset_files']) == canonical(plan['asset_files']), 'A retained asset/DMG identity changed')
    for key in plan['protected_ids']:
        require_contract(canonical(data[key]) == canonical(baseline[key]), 'Protected runtime record changed: ' + key)
        require_contract(canonical(observation['filesystem'][key]) == canonical(plan['baseline_filesystem'][key]),
                         'Protected runtime filesystem changed: ' + key)
    require_contract(set(final_ledger['watch_states']) == set(plan['watch_observation_ids'])
                     and all(v == 'Absent' for v in final_ledger['watch_states'].values()),
                     'The bound preparation did not retire every frozen duplicate')
    require_contract(set(observation['fixed_path_observations']) == set(plan['fixed_paths']), 'Terminal fixed path set differs')
    ambient_progress = validate_retirement_ambient_tvos(plan, observation, final_ledger['ambient_tvos'],
                                                         final_ledger['missing_paths'])
    for path, references in plan['fixed_paths'].items():
        role = plan['alias_roles']['paths'][path]
        require_contract(role['frozen_references'] == references
                         and role['role'] in ('exclusive_alias', 'retained_asset', 'shared_protected',
                                             'ambient_shared_protected', 'ambient_retained_asset'),
                         'Terminal frozen alias role differs')
        if role['role'] in ('ambient_shared_protected', 'ambient_retained_asset'):
            continue
        if role['role'] == 'shared_protected':
            # Exact protected raw membership above preserves the frozen recursive
            # reference closure after all old Watch UUIDs are absent. Never
            # reclassify the shared object as an exclusive/removable old alias.
            validate_retirement_shared_path(plan, observation, final_ledger, path, role)
            continue
        value = observation['fixed_path_observations'][path]
        require_contract(value['resolved_path'] == path and value['symlink_components'] == []
                         and value['os_path_ismount'] is False and value['related_mount_rows'] == {},
                         'A terminal old alias became linked, indirect or mounted: ' + path)
        current = value['filesystem']
        removable = all(ref['field'] in ('mountPath', 'runtimeBundlePath') for ref in references)
        require_contract(canonical(current) == canonical(plan['path_baselines'][path])
                         or removable and retirement_enoent_path(current, path), 'Terminal old path identity changed: ' + path)
        require_contract(path not in final_ledger['missing_paths'] or retirement_enoent_path(current, path),
                         'An absent old path reappeared after preparation: ' + path)
    new = data[plan['new_ios_uuid']]
    require_contract(new['state'] == 'Ready' and new['signatureState'] == 'Verified', 'Selected iOS lost Ready/Verified')
    require_contract(list(watch_records(data)) == [plan['ready_watch_uuid']], 'Ready watch identity changed')
    require_contract([key for key, row in data.items() if row.get('runtimeIdentifier') == IOS] == [plan['new_ios_uuid']],
                     'Selected iOS acquired another registration')
    require_contract(observation['mounted_paths'] == plan['protected_mount_paths']
                     and canonical(observation['mount_proofs']) == canonical(plan['protected_mount_proofs']), 'Protected mount identity/source/options changed')
    require_contract(retirement_runtime_mount_rows(data, observation['mount_table'], plan['protected_ids'])
                     == plan['protected_mount_rows'], 'Protected mount membership changed')
    updated = strict_json(canonical(final_ledger))
    updated['ambient_tvos'] = ambient_progress
    updated['missing_paths'] = sorted(set(final_ledger['missing_paths']) | {
        path for path,value in observation['fixed_path_observations'].items()
        if retirement_enoent_path(value['filesystem'],path)})
    return updated


class RetirementPhase:
    """One source-owned phase; no hardcoded owner, source SHA or caller mode."""
    def __init__(self, request, context, preflight, service, output, descriptors):
        self.request, self.context, self.preflight, self.service = request, context, preflight, service
        self.root, self.output = Path(context['source_root']), output
        self.plan, self.progress, self.deadline = None, None, None
        self.labels, self.attempted, self.invoked = set(), set(), set()
        self.watch_dmg = None
        self.report = {'schema': 'common-runtime-retirement-watch-shared-alias-ambient-tvos-settlement-v6',
            'identity': context, 'original_preflight': descriptors['staged'], 'original_service': descriptors['service'],
            'started_unix': time.time(), 'commands': [], 'snapshots': [], 'intervals': [],
            'application_consumer_invocations': 0, 'candidate_credit': False, 'product_pass': False,
            'watch_delete_attempts': 0, 'watch_delete_invocations': 0, 'replacement_targets': 0,
            'tvos_delete_attempts': 0, 'tvos_delete_invocations': 0, 'ambient_absence_required': False,
            'source_or_ref_modified': False, 'service_signals': 0, 'retries': 0,
            'limits': {'metadata_seconds': METADATA_TIMEOUT, 'delete_seconds': RETIREMENT_DELETE_SECONDS,
                       'settlement_seconds': RETIREMENT_SETTLEMENT_SECONDS,
                       'max_frozen_targets': RETIREMENT_MAX_TARGETS,
                       'max_ambient_observers': RETIREMENT_MAX_AMBIENT_OBSERVERS,
                       'max_scheduled_snapshots': RETIREMENT_MAX_SCHEDULED_SNAPSHOTS,
                       'sample_interval_seconds': RETIREMENT_SAMPLE_INTERVAL_SECONDS}}

    def remaining(self):
        if self.deadline is None:
            return None
        value = self.deadline - time.monotonic()
        require_contract(value > 0, 'The single retirement settlement deadline expired')
        return value

    def save(self):
        pending = unlinked_path(self.output / 'result.pending.json', self.root)
        raw = (json.dumps(self.report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
        with pending.open('xb') as stream:
            stream.write(raw)
        pending.replace(self.output / 'result.json')

    def allowed_read(self, label, argv):
        common = {'simctl-path': ['xcrun', '--find', 'simctl'],
                  'final-logical-runtimes': ['xcrun', 'simctl', 'list', 'runtimes', '-j'],
                  'final-device-types': ['xcrun', 'simctl', 'list', 'devicetypes', '-j']}
        common.update(dict(retirement_context_commands(self.context)))
        if label in common:
            return argv == common[label]
        match = re.fullmatch(r'(initial|old-ios-before|settlement-[0-9]{3}|settlement-final)-(runtimes|devices|mounts)', label)
        if match is None:
            return False
        return argv == {'runtimes': ['xcrun', 'simctl', 'runtime', 'list', '-j'],
                        'devices': ['xcrun', 'simctl', 'list', 'devices', '-j'], 'mounts': ['/sbin/mount']}[match[2]]

    def run(self, label, argv, timeout=METADATA_TIMEOUT, target=None):
        require_contract(label not in self.labels, 'Retirement command cannot be retried: ' + label)
        self.labels.add(label)
        if target is None:
            require_contract(timeout == METADATA_TIMEOUT and self.allowed_read(label, argv), 'Retirement read allowlist differs')
        else:
            check_retirement_delete_request(self.plan, self.attempted, self.invoked, target, argv, timeout)
            require_contract(label == 'old-ios-delete', 'The sole mutation has one exact label')
        row = {'label': label, 'argv': argv, 'requested_timeout_seconds': timeout,
               'started_unix': time.time(), 'returncode': None, 'timed_out': False,
               'stdout_file': label + '.stdout.log', 'stderr_file': label + '.stderr.log'}
        self.report['commands'].append(row)
        process, failure = None, None
        try:
            self.remaining()
            self.save()
            with (self.output / row['stdout_file']).open('xb') as out, (self.output / row['stderr_file']).open('xb') as err:
                launched = time.monotonic()
                deadline = min(launched + timeout, self.deadline) if self.deadline is not None else launched + timeout
                row.update(launched_monotonic=launched, command_deadline_monotonic=deadline,
                           effective_timeout_seconds=deadline-launched,
                           settlement_remaining_at_launch_seconds=None if self.deadline is None else self.deadline-launched)
                require_contract(deadline > launched, 'No remaining launch budget')
                if target is not None:
                    self.attempted.add(target)
                    row['mutation_attempted'] = True
                process = subprocess.Popen(argv, cwd=self.root, stdout=out, stderr=err,
                                           env=dict(os.environ, LC_ALL='C', TZ='UTC'))
                row['pid'] = process.pid
                if target is not None:
                    self.invoked.add(target)
                    row['mutation_invoked'] = True
                wait = deadline - time.monotonic()
                if wait <= 0:
                    raise subprocess.TimeoutExpired(argv, row['effective_timeout_seconds'])
                row['returncode'] = process.wait(timeout=wait)
                completed = time.monotonic()
                row['command_finished_monotonic'] = completed
                if row['returncode']:
                    raise subprocess.CalledProcessError(row['returncode'], argv)
                require_contract(completed <= deadline, 'Command completed outside its bounded deadline')
                if target is not None:
                    require_contract(self.deadline is None, 'The settlement clock cannot be restarted')
                    self.deadline = completed + RETIREMENT_SETTLEMENT_SECONDS
                    self.report['settlement_clock'] = {'starts_after_successful_command': label, 'command_returncode': 0,
                        'started_monotonic': completed, 'deadline_monotonic': self.deadline,
                        'budget_seconds': RETIREMENT_SETTLEMENT_SECONDS, 'reset_count': 0}
                self.remaining()
        except Exception as error:
            failure = error
            row['failure'] = {'type': type(error).__name__, 'message': str(error)}
            row['timed_out'] = isinstance(error, subprocess.TimeoutExpired)
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                    row['owned_cli_kill_requested'] = True
                    budget = min(1, max(0, self.deadline-time.monotonic())) if self.deadline is not None else 1
                    row['reaped_returncode'] = process.wait(timeout=budget)
                except Exception as cleanup:
                    row['owned_cli_cleanup_error'] = str(cleanup)
                row['server_side_operation_stopped_claimed'] = False
        finally:
            row['finished_unix'] = time.time()
            for channel in ('stdout', 'stderr'):
                try:
                    _, row[channel] = regular_bytes(self.output / row[channel+'_file'], self.root, maximum=64*1024*1024)
                except Exception as error:
                    row.setdefault('recording_errors', []).append(str(error))
                    failure = failure or error
            try:
                self.save()
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure
        raw = regular_bytes(self.output / row['stdout_file'], self.root, maximum=4*1024*1024)[0]
        self.remaining()
        return raw

    def snapshot(self, label):
        self.remaining()
        entry = {'label': label, 'started_unix': time.time(), 'started_monotonic': time.monotonic()}
        self.report['snapshots'].append(entry)
        data = inventory(strict_json(self.run(label+'-runtimes', ['xcrun','simctl','runtime','list','-j'])))
        raw_devices = strict_json(self.run(label+'-devices', ['xcrun','simctl','list','devices','-j']))
        mounts = retirement_mount_table(self.run(label+'-mounts', ['/sbin/mount']))
        entry.update(retirement_filesystem_observation(data, mounts, self.preflight, self.plan, self.watch_dmg, self.remaining))
        entry['raw_devices'], entry['devices'] = raw_devices, require_shutdown_devices(raw_devices)
        self.remaining()
        entry.update(finished_unix=time.time(), finished_monotonic=time.monotonic())
        self.save()
        self.remaining()
        return entry

    def bind_final_context(self):
        self.remaining()
        validate_host()
        require_contract(Path.cwd()==self.root,'The actual source working directory changed')
        self.remaining()
        actual_environment = retirement_current_environment(self.context)
        require_contract(actual_environment == self.context['consumer'], 'Caller identity changed during preparation')
        by_label = {}
        for label, argv in retirement_context_commands(self.context):
            by_label[label] = self.run(label, argv)
        validate_retirement_context_records(self.context, by_label)
        for _, root, _, entries in retirement_context_groups(self.context):
            for name, expected in entries.items():
                self.remaining()
                raw, info = regular_bytes(Path(root)/name, Path(root))
                blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
                require_contract(info['bytes']==expected['bytes'] and info['sha256']==expected['sha256']
                                 and blob==expected['git_blob']
                                 and bool(info['mode'] & 0o100)==(expected['git_mode']=='100755'),
                                 'Source/control byte or mode changed during retirement: '+name)
        input_receipt=None
        if self.context['mode']=='candidate':
            expected=self.context['original_restorer_binding']['receipt']
            self.remaining()
            _,input_receipt=regular_bytes(Path(expected['path']),self.root,maximum=64*1024*1024)
            require_contract(input_receipt==expected,'Actual candidate input/restorer receipt changed during preparation')
            self.remaining()
        self.report['final_context_binding'] = {'identity': self.context, 'actual_environment': actual_environment,
            'workflow_input_binding': self.context.get('workflow_input_binding'),
            'candidate_restorer_receipt':input_receipt,
            'validated_monotonic': time.monotonic()}
        self.remaining()

    def execute(self):
        help_raw, help_info = regular_bytes(preparation_root(self.context)/'staged/runtime-help.stderr.log', self.root)
        require_contract(b'delete (<identifier>|' in help_raw and b'--keep-asset' in help_raw
                         and b'Keep the associated mobile asset' in help_raw, 'Actual official runtime help lacks keep-asset')
        self.report['official_runtime_help'] = help_info
        actual = self.run('simctl-path', ['xcrun','--find','simctl']).decode().strip()
        resolved = str(Path(actual).resolve())
        require_contract(resolved == self.preflight['toolchain']['resolved_tools']['simctl'], 'Actual simctl changed')
        self.report['simctl_binding'] = {'actual_path':actual,'resolved_path':resolved}
        for profile in OWNER_PROFILES[self.context['owner']]['consumers'].values():
            require_contract(not (self.root/profile['receipt']).exists(), 'An original consumer already began')
        require_contract(not (preparation_root(self.context)/'consumers').exists(), 'Prior consumer binding exists')
        restore = Path(WATCH_ASSET)/'Restore'
        require_contract(restore.is_dir() and restore.resolve()==restore
                         and not any(p.is_symlink() for p in (restore,*restore.parents)), 'Watch Restore directory is indirect')
        children=list(restore.iterdir())
        dmgs=[p for p in children if p.suffix=='.dmg']
        require_contract(len(children)<=64 and len(dmgs)==1, 'Require one direct watch asset DMG')
        self.watch_dmg=dmgs[0]
        current=self.snapshot('initial')
        self.plan=freeze_retirement_plan(retirement_common_primitives(),self.preflight,self.service,current)
        self.progress=initial_retirement_progress(self.plan)
        self.report['frozen_plan']=self.plan
        before=self.snapshot('old-ios-before')
        self.progress=validate_retirement_snapshot_and_progress(retirement_common_primitives(),self.plan,before,self.progress,old_deleted=False)
        old=self.plan['old_ios_uuid']
        self.run('old-ios-delete',['xcrun','simctl','runtime','delete',old,'--keep-asset'],RETIREMENT_DELETE_SECONDS,target=old)
        for number in range(1,RETIREMENT_MAX_SCHEDULED_SNAPSHOTS+1):
            after=self.snapshot('settlement-'+str(number).zfill(3))
            self.progress=validate_retirement_snapshot_and_progress(retirement_common_primitives(),self.plan,after,self.progress,old_deleted=True)
            if number==1:
                self.report['own_delete_completed_uuids']=[old]
            if all(v=='Absent' for v in self.progress['watch_states'].values()):
                break
            require_contract(number<RETIREMENT_MAX_SCHEDULED_SNAPSHOTS,'Scheduled settlement samples exhausted')
            require_contract(self.remaining()>RETIREMENT_SAMPLE_INTERVAL_SECONDS,'Insufficient interval budget')
            started=time.monotonic()
            time.sleep(RETIREMENT_SAMPLE_INTERVAL_SECONDS)
            self.report['intervals'].append({'after_snapshot':after['label'],'started_monotonic':started,
                'finished_monotonic':time.monotonic(),'requested_seconds':RETIREMENT_SAMPLE_INTERVAL_SECONDS})
            self.remaining()
        runtimes=strict_json(self.run('final-logical-runtimes',['xcrun','simctl','list','runtimes','-j']))
        types=strict_json(self.run('final-device-types',['xcrun','simctl','list','devicetypes','-j']))
        selections,pairs={},{}
        for consumer in OWNER_PROFILES[self.context['owner']]['consumers']:
            selection=original_selection(consumer,runtimes['runtimes'],types['devicetypes'])
            check_selection(selection,self.service['logical_selection'],consumer)
            selections[consumer]=selection
            pairs[consumer]={'selected':str(Path(selection['runtime']['bundlePath']).resolve()),
                'prepared':str(Path(self.service['logical_selection']['expected_later_lifecycle_bundle_path']).resolve())}
            self.remaining()
        self.report['actual_original_first_choice']=selections
        self.report['resolved_selection_paths']=pairs
        self.bind_final_context()
        final=self.snapshot('settlement-final')
        self.progress=validate_retirement_snapshot_and_progress(retirement_common_primitives(),self.plan,final,self.progress,old_deleted=True,final=True)
        self.remaining()
        self.report.update(result='RETIREMENT_VALIDATED_PENDING_PREPARATION_PROCESS_EXIT',
            delete_attempted_uuids=sorted(self.attempted),delete_invoked_uuids=sorted(self.invoked),
            watch_observations=self.progress,externally_observed_watch_absent_uuids=sorted(self.plan['watch_observation_ids']),
            ambient_tvos_final_states=self.progress['ambient_tvos']['states'],
            live_guard_checkpoint_monotonic=time.monotonic(),
            limitation='Frozen watch absence is external observation, not owned deletion or a cause claim. The exact ambient tvOS may finish Unusable, Deleting or Absent; its Ready counterpart, shared paths and DMG stat remain protected. No tvOS deletion, content hash, causal attribution, continuous stability, physical-device or application result is inferred.')


def validate_retirement_context_records(context, raw):
    for prefix, root, identity, entries in retirement_context_groups(context):
        require_contract(raw[prefix+'-root'].decode().strip()==root and raw[prefix+'-cached-diff']==b'',
                         'Final exact worktree root or complete cached index changed')
        require_contract(raw[prefix+'-head'].decode().splitlines()==[identity['commit'],identity['tree']],
                         'Final source/control HEAD/tree differs')
        tree,index=[],[]
        for name in sorted(entries):
            item=entries[name]
            safe_relative(name)
            full_sha(item['git_blob'])
            require_contract(item['git_mode'] in ('100644','100755'),'Invalid bound source Git mode')
            tree.append((item['git_mode']+' blob '+item['git_blob']+'\t'+name+'\0').encode())
            index.append((item['git_mode']+' '+item['git_blob']+' 0\t'+name+'\0').encode())
        require_contract(raw[prefix+'-entries']==b''.join(tree) and raw[prefix+'-index']==b''.join(index),
                         'Final source/control tree or index proof differs')
    if context['mode']=='workflow-input':
        require_contract(raw['final-input-ref'].decode().strip()==context['source']['commit'],
                         'Final actual workflow input ref resolves to another commit')


def retirement_finite_number(value):
    require_contract(type(value) in (int, float) and value == value and abs(value) < float('inf'),
                     'Saved clock value must be a finite real number')
    return value


def retirement_raw_commands(directory, commands, root):
    """Byte-bound saved files only; no process or current runtime inspection."""
    files, raw, labels = [], {}, []
    for row in commands:
        label = row['label']
        require_contract(type(label) is str and re.fullmatch(r'[a-z0-9-]+', label)
                         and label not in labels, 'Missing/duplicate/unsafe saved command label')
        labels.append(label)
        require_contract(type(row.get('returncode')) is int and row['returncode'] == 0
                         and row.get('timed_out') is False and type(row.get('pid')) is int and row['pid'] > 0,
                         'A required command did not actually complete successfully')
        require_contract(not any(key in row for key in ('failure','error','recording_errors',
                         'owned_cli_kill_requested','owned_cli_cleanup_error','reaped_returncode',
                         'owned_process_kill_requested')), 'Success command includes failure/cleanup evidence')
        for channel in ('stdout','stderr'):
            name = label + '.' + channel + '.log'
            require_contract(row[channel+'_file'] == name and Path(name).name == name,
                             'Raw command filename is not its exact direct filename')
            content, info = regular_bytes(directory/name, root, maximum=64*1024*1024)
            require_contract(info == row[channel], 'Saved raw command descriptor differs')
            files.append(info)
            if channel == 'stdout':
                raw[label] = content
    expected = {r['label']+'.'+channel+'.log' for r in commands for channel in ('stdout','stderr')}
    require_contract({p.name for p in directory.iterdir()} == expected | {'result.json'},
                     'Unexpected/missing command or result file in the owned evidence directory')
    return files, raw


def validate_retirement_physical_evidence(sample, preflight, plan):
    """Independently connect saved stat attestations to raw mounts and stage identity."""
    data, filesystem, mounts = sample['inventory'], sample['filesystem'], sample['mount_table']
    require_contract(set(filesystem)==set(data), 'Saved physical filesystem membership differs')
    for key,row in data.items():
        require_contract(set(filesystem[key])==set(PATH_FIELDS), 'Runtime filesystem fields differ')
        for field in PATH_FIELDS:
            require_contract(filesystem[key][field].get('value')==row.get(field), 'Saved filesystem field names another path')
    ambient=plan['ambient_tvos']
    protected=[plan['new_ios_uuid'],plan['ready_watch_uuid'], *([ambient['ready_uuid']] if ambient else [])]
    require_contract(len(sample['mount_proofs'])==len(protected) and [r['uuid'] for r in sample['mount_proofs']]==protected,
                     'All frozen independently bound actual protected mounts are required')
    require_contract(sample['mounted_paths']==[data[key]['mountPath'] for key in protected], 'Protected mounted path list differs')
    for proof,key in zip(sample['mount_proofs'],protected):
        row=data[key]
        mount,bundle=row['mountPath'],row['runtimeBundlePath']
        mi,bi=filesystem[key]['mountPath'],filesystem[key]['runtimeBundlePath']
        require_contract(Path(mount).is_absolute() and Path(bundle).is_relative_to(Path(mount))
                         and '..' not in Path(mount).parts and '..' not in Path(bundle).parts
                         and len(mounts.get(mount,[]))==1, 'Protected mount/bundle structure differs')
        require_contract(mi.get('capture')==bi.get('capture')=='observed'
                         and mi.get('is_directory') is True and bi.get('is_directory') is True
                         and mi.get('resolved_path')==mount and bi.get('resolved_path')==bundle
                         and type(mi.get('device')) is int and mi['device']==bi.get('device'),
                         'Protected recorded filesystem device/resolution differs')
        require_contract(canonical(proof)==canonical({'uuid':key,'mount':mount,'bundle':bundle,'mount_table':mounts[mount][0],
            'os_path_ismount':True,'mount_device':mi['device'],'bundle_device':bi['device']}),
            'Protected actual mount attestation differs from raw mount row or filesystem device')
    assets=sample['asset_files']
    expected_assets={'source_dmg_after','staged_dmg_after','ios_asset','watch_asset','watch_dmg'} | ({'tvos_dmg'} if ambient else set())
    require_contract(set(assets)==expected_assets,
                     'Retained asset evidence set differs')
    for key in ('source_dmg_after','staged_dmg_after'):
        expected=preflight[key]
        require_contract(assets[key]=={'path':expected['path'],'capture':'observed',
            'bound_preflight_sha256':expected['sha256'],'additional_content_hash_performed':False,
            'resolved_path':expected['resolved_path'],'identity':expected['identity'],
            'is_regular':True,'is_symlink':False,'matches_verified_receipt':True},
            'Saved retained iOS DMG does not match the exact verified preflight identity')
    if ambient:
        require_contract(canonical(assets['tvos_dmg'])==canonical(plan['asset_files']['tvos_dmg']),
                         'Saved ambient tvOS DMG differs from its replayed initial physical identity')
    old=plan['old_ios_uuid']
    original_ios=plan['baseline_filesystem'][old]['parentMountPath']
    original_watch=plan['baseline_filesystem'][plan['ready_watch_uuid']]['path']
    for key,path,expected in [('ios_asset',str(IOS_ASSET),original_ios),('watch_asset',WATCH_ASSET,original_watch)]:
        require_contract(assets[key]==expected and assets[key].get('value')==path
                         and assets[key].get('resolved_path')==path and assets[key].get('capture')=='observed'
                         and assets[key].get('is_directory') is True, 'Saved retained asset directory is not the bound filesystem object')
    watch=assets['watch_dmg']
    path=Path(watch['path'])
    identity=watch['identity']
    require_contract(path.is_absolute() and path.parent==Path(WATCH_ASSET)/'Restore' and path.suffix=='.dmg'
                     and path.as_posix()==watch['path'] and '..' not in path.parts
                     and watch.get('resolved_path')==watch['path'] and watch.get('is_regular') is True
                     and watch.get('is_symlink') is False
                     and set(identity)=={'device','inode','mode','uid','gid','size','mtime_ns','ctime_ns'}
                     and all(type(v) is int and v>=0 for v in identity.values()) and identity['size']>0
                     and identity['device']==assets['watch_asset']['device'], 'Saved watch DMG stat attestation is malformed or misplaced')
    for path,value in sample['fixed_path_observations'].items():
        expected={key:rows for key,rows in mounts.items() if Path(key).is_relative_to(Path(path))}
        require_contract(value['related_mount_rows']==expected,'Saved old-alias mount membership differs from raw mount stdout')
    return True


def validate_retirement_evidence(preflight, service, receipt, context, retirement_dir, root, *, require_terminal=True):
    """Pure replay of saved phase records; current clock/runtime FS are not used.

    Reading the exact bound evidence files is intentional. No runtime-path
    resolve/stat, live devices, sleeping, Git or simctl command occurs here.
    The unsealed option is private to the live phase's first raw readback.
    """
    require_contract(retirement_dir == preparation_root(context)/'retirement', 'Wrong phase evidence directory')
    require_contract(receipt.get('schema') == 'common-runtime-retirement-watch-shared-alias-ambient-tvos-settlement-v6'
                     and receipt.get('identity') == context
                     and receipt.get('result') == 'RETIREMENT_VALIDATED_PENDING_PREPARATION_PROCESS_EXIT',
                     'Phase receipt is not the source-owned successful shared-Watch/ambient-tvos V6 schema/context')
    require_contract(not any(key in receipt for key in ('failure','final_recording_error','recording_errors')),
                     'Successful phase contains an error')
    for key in ('application_consumer_invocations','watch_delete_attempts','watch_delete_invocations',
                'replacement_targets','service_signals','retries','tvos_delete_attempts','tvos_delete_invocations'):
        require_contract(type(receipt.get(key)) is int and receipt[key] == 0, 'Forbidden phase action/credit: '+key)
    require_contract(receipt.get('candidate_credit') is False and receipt.get('product_pass') is False
                     and receipt.get('source_or_ref_modified') is False and receipt.get('ambient_absence_required') is False, 'Phase claims application credit or source mutation')
    require_contract(receipt['limits'] == {'metadata_seconds':METADATA_TIMEOUT,
        'delete_seconds':RETIREMENT_DELETE_SECONDS,'settlement_seconds':RETIREMENT_SETTLEMENT_SECONDS,
        'max_frozen_targets':RETIREMENT_MAX_TARGETS,'max_ambient_observers':RETIREMENT_MAX_AMBIENT_OBSERVERS,
        'max_scheduled_snapshots':RETIREMENT_MAX_SCHEDULED_SNAPSHOTS,
        'sample_interval_seconds':RETIREMENT_SAMPLE_INTERVAL_SECONDS}, 'Phase limits changed')
    prep=preparation_root(context)
    p,_=read_bound_json(prep/'staged/preflight-result.json',root,receipt['original_preflight'])
    s,_=read_bound_json(prep/'service/refresh-result.json',root,receipt['original_service'])
    require_contract(p==preflight and s==service,'Phase bound different original preparation evidence')
    help_raw,help_info=regular_bytes(prep/'staged/runtime-help.stderr.log',root)
    require_contract(help_info==receipt['official_runtime_help'] and b'delete (<identifier>|' in help_raw
                     and b'--keep-asset' in help_raw and b'Keep the associated mobile asset' in help_raw,
                     'Official same-run keep-asset operation is not bound')
    files,raw=retirement_raw_commands(retirement_dir,receipt['commands'],root)
    snapshots=receipt['snapshots']
    require_contract(type(snapshots) is list and 4<=len(snapshots)<=RETIREMENT_MAX_SCHEDULED_SNAPSHOTS+3,
                     'Phase snapshot count differs')
    count=len(snapshots)-3
    labels=['initial','old-ios-before',*['settlement-'+str(n).zfill(3) for n in range(1,count+1)],'settlement-final']
    require_contract([r['label'] for r in snapshots]==labels,'Snapshot order/sequence differs')
    expected=[('simctl-path',['xcrun','--find','simctl'])]
    def add_snapshot(label):
        expected.extend([(label+'-runtimes',['xcrun','simctl','runtime','list','-j']),
                         (label+'-devices',['xcrun','simctl','list','devices','-j']),
                         (label+'-mounts',['/sbin/mount'])])
    add_snapshot('initial'); add_snapshot('old-ios-before')
    old=preflight['selected_original_runtime']['target_uuid']
    expected.append(('old-ios-delete',['xcrun','simctl','runtime','delete',old,'--keep-asset']))
    for label in labels[2:-1]:
        add_snapshot(label)
    expected.extend([('final-logical-runtimes',['xcrun','simctl','list','runtimes','-j']),
                     ('final-device-types',['xcrun','simctl','list','devicetypes','-j'])])
    expected.extend(retirement_context_commands(context))
    add_snapshot('settlement-final')
    require_contract([(r['label'],r['argv']) for r in receipt['commands']]==expected,
                     'Raw command allowlist/order is incomplete, additional or changed')
    rows={r['label']:r for r in receipt['commands']}
    clock=receipt['settlement_clock']
    started=retirement_finite_number(clock['started_monotonic'])
    deadline=retirement_finite_number(clock['deadline_monotonic'])
    require_contract(clock=={'starts_after_successful_command':'old-ios-delete','command_returncode':0,
        'started_monotonic':started,'deadline_monotonic':started+RETIREMENT_SETTLEMENT_SECONDS,
        'budget_seconds':RETIREMENT_SETTLEMENT_SECONDS,'reset_count':0}
        and started==rows['old-ios-delete']['command_finished_monotonic'], 'Single settlement clock is not tied to successful delete completion')
    last=None
    deletion_index=[r['label'] for r in receipt['commands']].index('old-ios-delete')
    for index,row in enumerate(receipt['commands']):
        launch=retirement_finite_number(row['launched_monotonic'])
        finish=retirement_finite_number(row['command_finished_monotonic'])
        command_deadline=retirement_finite_number(row['command_deadline_monotonic'])
        requested=RETIREMENT_DELETE_SECONDS if row['label']=='old-ios-delete' else METADATA_TIMEOUT
        expected_deadline=min(launch+requested,deadline) if index>deletion_index else launch+requested
        require_contract(row['requested_timeout_seconds']==requested and command_deadline==expected_deadline
            and row['effective_timeout_seconds']==command_deadline-launch and command_deadline>launch
            and launch<=finish<=command_deadline and (last is None or launch>=last),
            'Saved command crossed its original/effective shared deadline or time order')
        remaining=deadline-launch if index>deletion_index else None
        require_contract(row['settlement_remaining_at_launch_seconds']==remaining,'Shared remaining budget changed')
        if row['label']=='old-ios-delete':
            check_retirement_delete_request(receipt['frozen_plan'],set(),set(),old,row['argv'],requested)
            require_contract(row.get('mutation_attempted') is True and row.get('mutation_invoked') is True,
                             'Actual old-iOS mutation attempt/invocation is missing')
        else:
            require_contract('mutation_attempted' not in row and 'mutation_invoked' not in row,
                             'Metadata row carries a mutation')
        last=finish
    require_contract(receipt['delete_attempted_uuids']==receipt['delete_invoked_uuids']
                     ==receipt['own_delete_completed_uuids']==[old], 'Exactly one old-iOS deletion must complete')
    simctl=receipt['simctl_binding']
    require_contract(raw['simctl-path'].decode().strip()==simctl['actual_path']
                     and simctl['resolved_path']==preflight['toolchain']['resolved_tools']['simctl'],
                     'Recorded live simctl resolution differs from original toolchain')
    for sample in snapshots:
        label=sample['label']
        require_contract(canonical(inventory(strict_json(raw[label+'-runtimes'])))==canonical(sample['inventory'])
                         and strict_json(raw[label+'-devices'])==sample['raw_devices']
                         and retirement_mount_table(raw[label+'-mounts'])==sample['mount_table']
                         and sorted(sample['mount_table'])==sample['mount_paths'], 'Snapshot does not match exact raw streams')
        require_contract(retirement_finite_number(sample['started_monotonic'])<=rows[label+'-runtimes']['launched_monotonic']
            and retirement_finite_number(sample['finished_monotonic'])>=rows[label+'-mounts']['command_finished_monotonic'],
            'Snapshot clock does not enclose its raw metadata')
        require_contract(sample['started_monotonic']<=sample['finished_monotonic'], 'Snapshot time order regressed')
        if label.startswith('settlement-'):
            require_contract(started<=sample['started_monotonic']<=sample['finished_monotonic']<deadline,
                             'Settlement snapshot crossed its single shared clock')
    for left,right in zip(snapshots,snapshots[1:]):
        require_contract(left['finished_monotonic']<=right['started_monotonic'], 'Snapshot event order overlapped or regressed')
    require_contract(rows['simctl-path']['command_finished_monotonic']<=snapshots[0]['started_monotonic']
                     and snapshots[1]['finished_monotonic']<=rows['old-ios-delete']['launched_monotonic']
                     and snapshots[-2]['finished_monotonic']<=rows['final-logical-runtimes']['launched_monotonic'],
                     'Snapshot filesystem/guard work crossed the following phase boundary')
    common=retirement_common_primitives()
    plan=replay_retirement_plan(common,preflight,service,snapshots[0],receipt['frozen_plan'])
    for sample in snapshots:
        validate_retirement_physical_evidence(sample,preflight,plan)
    progress=initial_retirement_progress(plan)
    progress=validate_retirement_snapshot_and_progress(common,plan,snapshots[1],progress,old_deleted=False)
    for index,sample in enumerate(snapshots[2:-1]):
        if index:
            require_contract(not all(v=='Absent' for v in progress['watch_states'].values()),
                             'Settlement continued after completion instead of its first terminal observation')
        progress=validate_retirement_snapshot_and_progress(common,plan,sample,progress,old_deleted=True)
    require_contract(all(value=='Absent' for value in progress['watch_states'].values()),
                     'Scheduled settlement did not reach its actual terminal break condition before final selection')
    require_contract(len(receipt['intervals'])==count-1,'Fixed read-only interval count differs')
    for index,interval in enumerate(receipt['intervals']):
        left,right=snapshots[index+2:index+4]
        a,b=retirement_finite_number(interval['started_monotonic']),retirement_finite_number(interval['finished_monotonic'])
        require_contract(interval['after_snapshot']==left['label']
                         and interval['requested_seconds']==RETIREMENT_SAMPLE_INTERVAL_SECONDS
                         and left['finished_monotonic']<=a and b-a>=RETIREMENT_SAMPLE_INTERVAL_SECONDS
                         and b<=right['started_monotonic'] and b<deadline, 'Scheduled interval changed, reset or overran')
    final=snapshots[-1]
    progress=validate_retirement_snapshot_and_progress(common,plan,final,progress,old_deleted=True,final=True)
    require_contract(canonical(progress)==canonical(receipt['watch_observations'])
                     and canonical(receipt['ambient_tvos_final_states'])==canonical(progress['ambient_tvos']['states'])
                     and receipt['externally_observed_watch_absent_uuids']==sorted(plan['watch_observation_ids']),
                     'Final external-watch disposition or path ledger differs from replay')
    validate_retired_host_invariants(plan,progress,final)
    runtimes=strict_json(raw['final-logical-runtimes'])['runtimes']
    types=strict_json(raw['final-device-types'])['devicetypes']
    consumers=OWNER_PROFILES[context['owner']]['consumers']
    require_contract(set(receipt['actual_original_first_choice'])==set(receipt['resolved_selection_paths'])==set(consumers),
                     'Final selection omitted or substituted an owner consumer')
    resolved=final['filesystem'][plan['new_ios_uuid']]['runtimeBundlePath']['resolved_path']
    for consumer in consumers:
        selection=original_selection(consumer,runtimes,types)
        require_contract(selection==receipt['actual_original_first_choice'][consumer], 'Saved first choice differs from raw original order')
        same_logical_runtime(selection['runtime'],service['logical_selection']['logical_runtime'])
        expected_device=service['logical_selection']['device_type']
        if consumer in ('icon-ui','integrated-simulator'):
            expected_device=expected_device['identifier']
        require_contract(selection['device']==expected_device,'Saved original device form differs')
        # Pure saved replay: the live check_selection call recorded both resolved
        # paths. Do not call it here; its Path.resolve inspects the current host.
        require_contract(receipt['resolved_selection_paths'][consumer]=={'selected':resolved,'prepared':resolved},
                         'Recorded live resolved paths are not the final selected filesystem object')
    validate_retirement_context_records(context,raw)
    binding=receipt['final_context_binding']
    require_contract(binding['identity']==context and binding['actual_environment']==context['consumer']
                     and binding['workflow_input_binding']==context.get('workflow_input_binding'),
                     'Final source/control/caller binding changed')
    expected_input=context['original_restorer_binding']['receipt'] if context['mode']=='candidate' else None
    require_contract(binding['candidate_restorer_receipt']==expected_input,'Final candidate restorer input binding is missing')
    if expected_input is not None:
        require_contract(regular_bytes(Path(expected_input['path']),root,maximum=64*1024*1024)[1]==expected_input,
                         'The exact candidate restorer evidence receipt changed')
    context_last=retirement_context_commands(context)[-1][0]
    require_contract(rows[context_last]['command_finished_monotonic']<=retirement_finite_number(binding['validated_monotonic'])
                     <=final['started_monotonic'],'Final context check is outside its declared event order')
    guard=retirement_finite_number(receipt['live_guard_checkpoint_monotonic'])
    require_contract(final['finished_monotonic']<=guard<deadline,'Terminal live guard crossed the one deadline')
    if require_terminal:
        terminal=retirement_finite_number(receipt['raw_readback_validated_monotonic'])
        require_contract(guard<=terminal<deadline,'Complete raw readback was not validated within the shared budget')
    return files


def retire_old_ios_and_observe_watch(request, context, preflight, service, output, descriptors):
    root=Path(context['source_root'])
    require_contract(output==preparation_root(context)/'retirement' and not output.exists(),
                     'Retirement must use one fresh source-owned phase directory')
    unlinked_path(output,root).mkdir(mode=0o700)
    phase=RetirementPhase(request,context,preflight,service,output,descriptors)
    failure=None
    try:
        phase.execute()
        phase.report['finished_unix']=time.time()
        phase.save()
        saved,_=read_bound_json(output/'result.json',root)
        validate_retirement_evidence(preflight,service,saved,context,output,root,require_terminal=False)
        phase.remaining()
        phase.report['raw_readback_validated_monotonic']=time.monotonic()
        phase.remaining()
        phase.save()
        saved,info=read_bound_json(output/'result.json',root)
        files=validate_retirement_evidence(preflight,service,saved,context,output,root)
        phase.remaining()
        return saved,info,files
    except Exception as error:
        failure=error
        phase.report.update(result='RETIREMENT_FAILED_CLOSED',failure={'type':type(error).__name__,'message':str(error)},
                            delete_attempted_uuids=sorted(phase.attempted),delete_invoked_uuids=sorted(phase.invoked),
                            finished_unix=time.time())
        try:
            phase.save()
        except Exception as recording:
            failure=recording_failure(failure,recording,'retirement-failure-save',phase.report)
        raise failure


def post_retirement_physical_command(output, label, argv, root):
    allowed={'runtime-images':['xcrun','simctl','runtime','list','-j'],'mounts':['/sbin/mount']}
    require_contract(allowed.get(label)==argv,'Post-retirement physical reader has only its two read operations')
    row={'label':label,'argv':argv,'requested_timeout_seconds':METADATA_TIMEOUT,
         'started_unix':time.time(),'stdout_file':label+'.stdout.log','stderr_file':label+'.stderr.log',
         'timed_out':False,'returncode':None}
    process,failure=None,None
    try:
        with (output/row['stdout_file']).open('xb') as out,(output/row['stderr_file']).open('xb') as err:
            launch=time.monotonic()
            row.update(launched_monotonic=launch,command_deadline_monotonic=launch+METADATA_TIMEOUT)
            process=subprocess.Popen(argv,cwd=root,stdout=out,stderr=err,env=dict(os.environ,LC_ALL='C',TZ='UTC'))
            row['pid']=process.pid
            remaining=row['command_deadline_monotonic']-time.monotonic()
            if remaining<=0:
                raise subprocess.TimeoutExpired(argv,METADATA_TIMEOUT)
            row['returncode']=process.wait(timeout=remaining)
            row['command_finished_monotonic']=time.monotonic()
            if row['returncode']:
                raise subprocess.CalledProcessError(row['returncode'],argv)
            require_contract(row['command_finished_monotonic']<=row['command_deadline_monotonic'],'Physical read exceeded metadata cap')
    except Exception as error:
        failure=error
        row['failure']={'type':type(error).__name__,'message':str(error)}
        row['timed_out']=isinstance(error,subprocess.TimeoutExpired)
        if process is not None and process.returncode is None:
            try:
                process.kill()
                row['owned_cli_kill_requested']=True
                row['reaped_returncode']=process.wait(timeout=1)
            except Exception as cleanup:
                row['owned_cli_cleanup_error']=str(cleanup)
    finally:
        row['finished_unix']=time.time()
        for channel in ('stdout','stderr'):
            try:
                _,row[channel]=regular_bytes(output/row[channel+'_file'],root,maximum=64*1024*1024)
            except Exception as error:
                row.setdefault('recording_errors',[]).append(str(error))
                failure=failure or error
    return row,failure


def selected_runtime_usage_state(record):
    """The sole consumer-usage field has an exact UTC-second spelling."""
    if 'lastUsedAt' not in record:
        return {'present': False, 'value': None, 'utc_second': None}
    value = record['lastUsedAt']
    require_contract(type(value) is str
                     and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value),
                     'Selected iOS lastUsedAt must be an exact UTC-second string')
    parsed = datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    second = int(parsed.timestamp())
    require_contract(parsed.isoformat(timespec='seconds') == value[:-1] + '+00:00',
                     'Selected iOS lastUsedAt is not a canonical valid UTC timestamp')
    return {'present': True, 'value': value, 'utc_second': second}


def selected_runtime_usage_event(previous, observed, consumer, phase, label, finished, preceding):
    """Replay one boundary using recorded times; never consult a live clock."""
    for state in (previous, observed):
        require_contract(type(state) is dict and set(state) == {'present', 'value', 'utc_second'},
                         'Selected iOS usage state shape differs')
        expected = selected_runtime_usage_state({'lastUsedAt': state['value']} if state['present'] is True else {})
        require_contract(canonical(state) == canonical(expected), 'Selected iOS usage state is not typed canonical data')
    finish = retirement_finite_number(finished)
    require_contract(phase in ('before', 'after'), 'Selected iOS usage boundary is unknown')
    require_contract(observed['present'] is False or observed['utc_second'] <= int(finish // 1),
                     'Selected iOS usage is in the future of its actual observation')
    if preceding is not None:
        require_contract(retirement_finite_number(preceding['observed_finished_unix']) <= finish,
                         'Selected iOS usage observation clock regressed')
    changed = canonical(previous) != canonical(observed)
    window = None
    if phase == 'before':
        require_contract(not changed, 'Selected iOS usage changed before the original consumer')
    else:
        require_contract(preceding is not None and preceding['consumer'] == consumer
                         and preceding['phase'] == 'before',
                         'Selected iOS AFTER requires the same consumer actual BEFORE')
        start = retirement_finite_number(preceding['observed_finished_unix'])
        window = {'before_finished_unix': start, 'after_finished_unix': finish,
                  'earliest_utc_second': int(start // 1), 'latest_utc_second': int(finish // 1),
                  'precision': 'UTC whole-second bucket; floor both actual observation endpoints; no extra tolerance'}
        if changed:
            require_contract(observed['present'] is True, 'Selected iOS usage may not disappear')
            require_contract(previous['present'] is False or observed['utc_second'] > previous['utc_second'],
                             'Selected iOS usage regressed or changed without increasing')
            require_contract(window['earliest_utc_second'] <= observed['utc_second'] <= window['latest_utc_second'],
                             'Selected iOS usage lies outside the actual consumer observation interval')
    return {'consumer': consumer, 'phase': phase, 'label': label, 'observed_finished_unix': finish,
            'previous_usage': previous, 'observed_usage': observed, 'changed': changed,
            'changed_value_interval': window}


def validate_consumer_retired_host_invariants(plan, final_ledger, observation, context, relative_output):
    """Only selected staged iOS usage can advance at a bound consumer AFTER."""
    profile = OWNER_PROFILES[context['owner']]
    consumers = list(profile['consumers'])
    require_contract(consumers == ['integrated-ui', 'integrated-simulator'] if context['owner'] == 'integrated'
                     else len(consumers) == 1, 'Original owner consumer order differs')
    boundaries = [(consumer, phase) for consumer in consumers for phase in ('before', 'after')]
    labels = [str(Path(profile['preparation_root']) / 'consumers' / consumer / (phase + '-host'))
              for consumer, phase in boundaries]
    require_contract(type(relative_output) is str and relative_output in labels
                     and observation.get('label') == relative_output,
                     'Selected iOS usage must be tied to an exact owner consumer boundary')
    boundary_index = labels.index(relative_output)
    consumer, phase = boundaries[boundary_index]
    key = plan['new_ios_uuid']
    frozen, current = plan['baseline_inventory'][key], observation['inventory'][key]
    require_contract(key in plan['protected_ids'] and key not in plan['target_ids']
                     and frozen.get('identifier') == key and frozen.get('runtimeIdentifier') == IOS
                     and frozen.get('kind') == 'Disk Image' and frozen.get('state') == 'Ready'
                     and frozen.get('signatureState') == 'Verified',
                     'Consumer usage exception requires the frozen selected verified staged iOS')
    require_contract(canonical({k: v for k, v in current.items() if k != 'lastUsedAt'})
                     == canonical({k: v for k, v in frozen.items() if k != 'lastUsedAt'}),
                     'Selected iOS changed outside its single usage field')
    baseline_usage = selected_runtime_usage_state(frozen)
    current_usage = selected_runtime_usage_state(current)
    path_ledger = strict_json(canonical(final_ledger))
    usage = path_ledger.pop('selected_runtime_usage', None)
    history = []
    previous = baseline_usage
    if boundary_index == 0:
        require_contract(usage is None and 'selected_runtime_usage' not in final_ledger
                         and canonical(current) == canonical(frozen),
                         'First consumer BEFORE must retain the whole frozen selected runtime record')
    else:
        require_contract(type(usage) is dict
                         and set(usage) == {'schema', 'owner', 'selected_uuid', 'baseline_usage', 'events'}
                         and usage['schema'] == 'common-selected-ios-consumer-usage-ledger-v1'
                         and usage['owner'] == context['owner'] and usage['selected_uuid'] == key
                         and canonical(usage['baseline_usage']) == canonical(baseline_usage)
                         and type(usage['events']) is list and len(usage['events']) == boundary_index,
                         'Selected iOS usage lacks its exact preceding consumer ledger')
        for index, saved in enumerate(usage['events']):
            require_contract(type(saved) is dict and set(saved) == {
                'consumer', 'phase', 'label', 'observed_finished_unix', 'previous_usage',
                'observed_usage', 'changed', 'changed_value_interval'}, 'Saved usage event shape differs')
            event = selected_runtime_usage_event(previous, saved['observed_usage'], *boundaries[index],
                labels[index], saved['observed_finished_unix'], None if not history else history[-1])
            require_contract(canonical(saved) == canonical(event), 'Saved selected iOS usage transition differs from replay')
            history.append(event)
            previous = event['observed_usage']
    event = selected_runtime_usage_event(previous, current_usage, consumer, phase, relative_output,
                                        observation['finished_unix'], None if not history else history[-1])
    # This local expectation copy changes no actual frozen plan/raw receipt.
    # The full selected-row comparison above permits only the checked usage field;
    # the original strict guard below retains every other raw/physical invariant.
    expected_plan = strict_json(canonical(plan))
    expected_plan['baseline_inventory'][key] = strict_json(canonical(current))
    updated = validate_retired_host_invariants(expected_plan, path_ledger, observation)
    updated['selected_runtime_usage'] = {'schema': 'common-selected-ios-consumer-usage-ledger-v1',
        'owner': context['owner'], 'selected_uuid': key, 'baseline_usage': baseline_usage,
        'events': [*history, event]}
    return updated


def validate_post_retirement_observation(receipt, retirement, context, binding, output, root, prior_ledger=None):
    require_contract(receipt.get('schema')=='common-runtime-retired-host-selected-ios-usage-observation-v1'
                     and receipt.get('identity')==context and receipt.get('preparation_binding')==binding
                     and receipt.get('result')=='RETIRED_HOST_INVARIANTS_OBSERVED'
                     and not any(key in receipt for key in ('failure','recording_errors','final_recording_error')),
                     'Terminal host observation is missing/failed or bound to another preparation')
    require_contract(receipt.get('device_inventory_read') is False and receipt.get('mutation_attempts')==0,
                     'Before/after may not apply preparation device guards or perform mutations')
    require_contract(receipt.get('candidate_credit') is False and receipt.get('product_pass') is False,
                     'Terminal observation carries false application credit')
    commands=receipt['commands']
    require_contract([(r['label'],r['argv']) for r in commands]==[
        ('runtime-images',['xcrun','simctl','runtime','list','-j']),('mounts',['/sbin/mount'])],
        'Terminal physical observation command scope changed')
    files,raw=retirement_raw_commands(output,commands,root)
    for row in commands:
        launch=retirement_finite_number(row['launched_monotonic'])
        finish=retirement_finite_number(row['command_finished_monotonic'])
        require_contract(row['requested_timeout_seconds']==METADATA_TIMEOUT
                         and row['command_deadline_monotonic']==launch+METADATA_TIMEOUT
                         and launch<=finish<=row['command_deadline_monotonic'], 'Physical read deadline changed')
        require_contract(retirement_finite_number(receipt['started_unix'])<=retirement_finite_number(row['started_unix'])
                         <=retirement_finite_number(row['finished_unix'])<=retirement_finite_number(receipt['finished_unix']),
                         'Physical command lies outside its terminal receipt time interval')
    require_contract(commands[0]['command_finished_monotonic']<=commands[1]['launched_monotonic'],
                     'Terminal physical commands overlap or are out of order')
    observed=receipt['observation']
    require_contract('devices' not in observed and 'raw_devices' not in observed
                     and canonical(inventory(strict_json(raw['runtime-images'])))==canonical(observed['inventory'])
                     and retirement_mount_table(raw['mounts'])==observed['mount_table']
                     and observed['mount_paths']==sorted(observed['mount_table']),
                     'Terminal observation differs from raw runtime/mount evidence')
    require_contract(observed.get('label')==str(output.relative_to(root))
                     and retirement_finite_number(commands[-1]['finished_unix'])
                     <=retirement_finite_number(observed['finished_unix'])
                     <=retirement_finite_number(receipt['finished_unix']),
                     'Terminal ambient ledger lacks its actual boundary label or observation time')
    prior=retirement['watch_observations'] if prior_ledger is None else prior_ledger
    require_contract(canonical(receipt['prior_terminal_path_ledger'])==canonical(prior),'Terminal observation changed its preceding path ledger')
    require_contract(canonical(validate_consumer_retired_host_invariants(retirement['frozen_plan'],prior,observed,context,str(output.relative_to(root))))
                     ==canonical(receipt['terminal_path_ledger']),'Terminal missing-path accumulation differs')
    # The terminal observation shares the independently checked phase assets,
    # devices and raw mount relationships; preparation device guards are absent.
    for proof in observed['mount_proofs']:
        key=proof['uuid']
        require_contract(proof['os_path_ismount'] is True
                         and observed['mount_table'].get(proof['mount'])==[proof['mount_table']]
                         and proof['mount_device']==proof['bundle_device']==observed['filesystem'][key]['mountPath']['device']
                         ==observed['filesystem'][key]['runtimeBundlePath']['device'],
                         'Terminal actual mount attestation differs from raw mount/FS evidence')
    for path,value in observed['fixed_path_observations'].items():
        require_contract(value['related_mount_rows']=={key:rows for key,rows in observed['mount_table'].items()
                                                      if Path(key).is_relative_to(Path(path))},
                         'Terminal alias mount membership differs from raw evidence')
    return files


def capture_post_retirement_observation(context, preflight, retirement, binding, output, prior_ledger=None):
    root=Path(context['source_root'])
    require_contract(not output.exists(),'Terminal host observation is once per consumer boundary')
    unlinked_path(output,root).mkdir()
    prior=retirement['watch_observations'] if prior_ledger is None else prior_ledger
    report={'schema':'common-runtime-retired-host-selected-ios-usage-observation-v1','identity':context,
            'preparation_binding':binding,'started_unix':time.time(),'commands':[],
            'prior_terminal_path_ledger':prior,
            'device_inventory_read':False,'mutation_attempts':0,'product_pass':False,'candidate_credit':False}
    failure=None
    try:
        for label,argv in [('runtime-images',['xcrun','simctl','runtime','list','-j']),('mounts',['/sbin/mount'])]:
            row,error=post_retirement_physical_command(output,label,argv,root)
            report['commands'].append(row)
            if error is not None:
                raise error
        data=inventory(raw_command_json(output,'runtime-images',root))
        mounts=retirement_mount_table(regular_bytes(output/'mounts.stdout.log',root)[0])
        watch_dmg=Path(retirement['frozen_plan']['asset_files']['watch_dmg']['path'])
        report['observation']=retirement_filesystem_observation(data,mounts,preflight,retirement['frozen_plan'],watch_dmg,lambda:None)
        report['observation'].update(label=str(output.relative_to(root)), finished_unix=time.time())
        report['terminal_path_ledger']=validate_consumer_retired_host_invariants(retirement['frozen_plan'],prior,report['observation'],context,str(output.relative_to(root)))
        report['result']='RETIRED_HOST_INVARIANTS_OBSERVED'
    except Exception as error:
        failure=error
        report['result']='RETIRED_HOST_OBSERVATION_FAILED'
        report['failure']={'type':type(error).__name__,'message':str(error)}
    report['finished_unix']=time.time()
    try:
        info=write_new_json(output/'result.json',report,root)
        if failure is None:
            saved,_=read_bound_json(output/'result.json',root,info)
            validate_post_retirement_observation(saved,retirement,context,binding,output,root,prior)
    except Exception as error:
        failure=recording_failure(failure,error,'terminal-host-readback',report)
    if failure is not None:
        raise failure
    return info


def retirement_preceding_consumer_ledger(context,retirement,binding,consumer):
    """Bind the UI before→after ledger before Integrated Simulator may begin."""
    if consumer!='integrated-simulator':
        return retirement['watch_observations'],None
    root,prep=Path(context['source_root']),preparation_root(context)
    output=prep/'consumers/integrated-ui'
    after,info=read_bound_json(output/'after.json',root)
    require_contract(after.get('schema')=='common-runtime-consumer-after-v2'
                     and after['identity']==context and after['consumer']=='integrated-ui'
                     and type(after['original_status']) is int and after['original_status']==0
                     and type(after['effective_status']) is int and after['effective_status']==0
                     and after['result']=='ORIGINAL_RECEIPT_MATCHED'
                     and not any(key in after for key in ('failure','recording_errors','final_recording_error'))
                     and after['preparation_binding']==binding and after['retirement_binding']==binding['retirement'],
                     'Second Integrated consumer requires successful first consumer and identical V2 binding')
    before,_=read_bound_json(output/'before.json',root,after['before_binding'])
    require_contract(before['schema']=='common-runtime-consumer-before-v2' and before['identity']==context
                     and before['consumer']=='integrated-ui' and before['result']=='BOUND_BEFORE_ORIGINAL_CONSUMER'
                     and not any(key in before for key in ('failure','recording_errors','final_recording_error'))
                     and before['preparation_binding']==binding and before['retirement_binding']==binding['retirement'],
                     'Preceding UI before binding differs')
    initial,_=read_bound_json(output/'before-host/result.json',root,before['terminal_host_observation'])
    validate_post_retirement_observation(initial,retirement,context,binding,output/'before-host',root)
    terminal,_=read_bound_json(output/'after-host/result.json',root,after['terminal_host_observation'])
    validate_post_retirement_observation(terminal,retirement,context,binding,output/'after-host',root,initial['terminal_path_ledger'])
    return terminal['terminal_path_ledger'],info


PRECONDITIONING_MODULE_BASENAME = "runtime_preconditioning.py"
PRECONDITIONING_MODULE_SHA256 = "0a72fe7df8bb29748b695c1ea1b424509d6b6ad3ea455f7d90806a2db128eb8a"


def load_preconditioning_module(context):
    import types
    root = Path(context['source_root'])
    for directory in {root, *([Path(context['control_root'])] if context['control_root'] is not None else [])}:
        git_read(directory, 'diff', '--no-ext-diff', '--no-textconv', '--exit-code', 'HEAD', '--')
        git_read(directory, 'diff', '--cached', '--no-ext-diff', '--no-textconv', '--exit-code', 'HEAD', '--')
    paths = [str(Path(relative).with_name(PRECONDITIONING_MODULE_BASENAME))
             for relative in OWNER_PROFILES[context['owner']]['helper_paths']]
    active = str(Path(context['own_helper_relative_path']).with_name(PRECONDITIONING_MODULE_BASENAME))
    require_contract(active == paths[0] and len(set(paths)) == len(paths), 'Wrong active owner module path')
    copies, sources = {}, {}
    for relative in paths:
        raw, info = tracked_regular_file(root, context['source']['commit'], relative, PRECONDITIONING_MODULE_SHA256)
        require_contract(info['mode'] == 0o644 and (root / relative).lstat().st_nlink == 1,
                         'Every source preconditioning module copy must be exact unlinked0644')
        copies[relative], sources[relative] = info, raw
    require_contract(len({(info['sha256'], info['git_blob'], info['git_mode']) for info in copies.values()}) == 1,
                     'Owned/inherited preconditioning module copies differ in exact blob/mode')
    binding = {'schema': 'source-runtime-preconditioning-module-set-v1', 'active_relative_path': active,
               'sha256': PRECONDITIONING_MODULE_SHA256, 'copies': copies}
    common_raw, common_info = tracked_regular_file(root, context['source']['commit'], context['own_helper_relative_path'],
                                                   context['own_helper_sha256'])
    require_contract(common_info == context['helper_git_entries'][context['own_helper_relative_path']],
                     'Actual common descriptor changed before source module import')
    module = types.ModuleType('_source_owned_runtime_preconditioning')
    module.__file__ = str(root / active)
    exec(compile(sources[active], module.__file__, 'exec'), vars(module))
    module.validate_context_axes(context, os.environ)
    return module, binding, common_raw


def validate_preconditioning_receipt(report, context):
    root, output = Path(context['source_root']), preparation_root(context)
    module, module_info, common_raw = load_preconditioning_module(context)
    require_contract(report['preconditioning_module'] == module_info,
                     'Preparation references another source preconditioning module')
    value, info = read_bound_json(output / 'preconditioning/precondition.json', root, report['preconditioning_result'])
    raw_files = module.validate_evidence(value, context, module_info, common_raw, root, output / 'preconditioning')
    require_contract(raw_files == report['preconditioning_raw_files'],
                     'Complete preparation observation/scan raw replay inventory changed')
    return info


def validate_preparation_success_shape(report, context):
    phases = report.get('phase_function_return_codes')
    require_contract(report.get('schema') == 'common-runtime-preparation-v3' and report.get('identity') == context
        and report.get('result') == 'PREPARATION_FUNCTIONS_COMPLETED_PENDING_ACTUAL_PROCESS_EXIT'
        and type(phases) is dict and set(phases) == {'preconditioning', 'staged', 'service', 'retirement'}
        and all(type(code) is int and code == 0 for code in phases.values())
        and type(report.get('preconditioning_result')) is dict and type(report.get('preconditioning_module')) is dict
        and type(report.get('preconditioning_raw_files')) is list and report['preconditioning_raw_files']
        and report.get('candidate_credit') is False and report.get('product_pass') is False
        and type(report.get('lifecycle_executions')) is int and report['lifecycle_executions'] == 0
        and report.get('actual_helper_process_exit_requires_separate_caller_binding') is True
        and not any(key in report for key in ('failure', 'recording_errors', 'final_recording_error')),
        'V3 preparation is incomplete, failed or carries false application credit')


def prepare_environment(request, context):
    root = Path(context['source_root'])
    output = preparation_root(context)
    require_contract(not output.exists(), 'Preparation is once per source/control/run/attempt/job; no reuse or retry')
    output.mkdir(parents=True)
    report = {'schema': 'common-runtime-preparation-v3', 'identity': context, 'request': request,
              'started_unix': time.time(), 'phase_function_return_codes': {}, 'product_pass': False,
              'candidate_credit': False, 'lifecycle_executions': 0,
              'actual_helper_process_exit_requires_separate_caller_binding': True}
    failure = None
    try:
        started = time.monotonic()
        module, module_info, common_raw = load_preconditioning_module(context)
        report['preconditioning_module'] = module_info
        precondition, observed_info, raw_files = module.run_source_preconditioning(context, module_info, common_raw,
                                                                                   output / 'preconditioning', started)
        raw, info = regular_bytes(output / 'preconditioning/precondition.json', root, maximum=64 * 1024 * 1024)
        require_contract({key: info[key] for key in ('path', 'bytes', 'sha256')} == observed_info
                         and strict_json(raw) == precondition
                         and time.monotonic() < precondition['final_active_phase_budget']['deadline_monotonic'],
                         'Common receipt binding changed or exceeded the precondition active phase')
        report['preconditioning_result'], report['preconditioning_raw_files'] = info, raw_files
        report['phase_function_return_codes']['preconditioning'] = 0
        recheck_context(request, context)
        stage_installed_runtime(context, output / 'staged')
        report['phase_function_return_codes']['staged'] = 0
        recheck_context(request, context)
        refresh_owned_service(context, output / 'staged', output / 'service')
        report['phase_function_return_codes']['service'] = 0
        recheck_context(request, context)
        p, pinfo = read_bound_json(output / 'staged/preflight-result.json', root)
        s, sinfo = read_bound_json(output / 'service/refresh-result.json', root)
        validate_preflight(p, phase_context(context))
        report['staged_raw_command_files'] = command_files(output / 'staged', p, root)
        report['service_raw_command_files'] = validate_service_evidence(p, s, context, output / 'staged', output / 'service', root)
        report['staged_result'], report['service_result'] = pinfo, sinfo
        report['logical_selection'] = s['logical_selection']
        retirement, rinfo, raw = retire_old_ios_and_observe_watch(request, context, p, s, output / 'retirement',
                                                                 {'staged': pinfo, 'service': sinfo})
        report['retirement_result'], report['retirement_raw_command_files'] = rinfo, raw
        report['phase_function_return_codes']['retirement'] = 0
        report['result'] = 'PREPARATION_FUNCTIONS_COMPLETED_PENDING_ACTUAL_PROCESS_EXIT'
    except Exception as error:
        failure = error
        report['result'] = 'PREPARATION_FAILED'
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        report['finished_unix'] = time.time()
        try:
            write_new_json(output / 'prepare-result.json', report, root)
        except Exception as error:
            failure = recording_failure(failure, error, 'prepare-result-save', report)
    if failure is not None:
        raise failure
    return report


def record_preparation_exit(context, actual_status):
    require_contract(type(actual_status) is int and 0 <= actual_status <= 255, 'Invalid actual shell exit status')
    root, output = Path(context['source_root']), preparation_root(context)
    report = {'schema': 'common-runtime-actual-caller-exit-v3', 'identity': context,
              'actual_shell_status_argument': actual_status,
              'status_provenance': 'Reviewed caller passes the immediately captured actual $?; no success constant is permitted.',
              'candidate_credit': False, 'product_pass': False}
    if (output / 'prepare-result.json').exists():
        value, info = read_bound_json(output / 'prepare-result.json', root)
        require_contract(value['identity'] == context and value['schema'] == 'common-runtime-preparation-v3',
                         'Preparation receipt belongs to another context/schema')
        if actual_status == 0:
            validate_preparation_success_shape(value, context)
            validate_preconditioning_receipt(value, context)
            p, _ = read_bound_json(output / 'staged/preflight-result.json', root, value['staged_result'])
            s, _ = read_bound_json(output / 'service/refresh-result.json', root, value['service_result'])
            r, _ = read_bound_json(output / 'retirement/result.json', root, value['retirement_result'])
            require_contract(validate_retirement_evidence(p, s, r, context, output / 'retirement', root)
                             == value['retirement_raw_command_files'], 'Caller proof lacks exact retirement evidence')
        report['prepare_result'] = info
    else:
        require_contract(actual_status != 0, 'Successful process must have its complete preparation receipt')
        output.mkdir(parents=True, exist_ok=True)
        report['prepare_result'] = None
    return write_new_json(output / 'prepare-exit.json', report, root)


def load_preparation(context):
    root, output = Path(context['source_root']), preparation_root(context)
    actual_exit, exit_info = read_bound_json(output / 'prepare-exit.json', root)
    require_contract(actual_exit.get('schema') == 'common-runtime-actual-caller-exit-v3'
                     and actual_exit['identity'] == context and type(actual_exit['actual_shell_status_argument']) is int
                     and actual_exit['actual_shell_status_argument'] == 0
                     and actual_exit.get('candidate_credit') is False and actual_exit.get('product_pass') is False
                     and not any(key in actual_exit for key in ('failure', 'recording_errors', 'final_recording_error')),
                     'Same actual V3 preparation process must have completed with exit zero')
    report, info = read_bound_json(output / 'prepare-result.json', root, actual_exit['prepare_result'])
    validate_preparation_success_shape(report, context)
    preconditioning_info = validate_preconditioning_receipt(report, context)
    p, _ = read_bound_json(output / 'staged/preflight-result.json', root, report['staged_result'])
    s, _ = read_bound_json(output / 'service/refresh-result.json', root, report['service_result'])
    validate_preflight(p, phase_context(context))
    require_contract(command_files(output / 'staged', p, root) == report['staged_raw_command_files'],
                     'Staged raw command inventory changed')
    require_contract(validate_service_evidence(p, s, context, output / 'staged', output / 'service', root)
                     == report['service_raw_command_files'], 'Service raw command inventory changed')
    r, rinfo = read_bound_json(output / 'retirement/result.json', root, report['retirement_result'])
    require_contract(validate_retirement_evidence(p, s, r, context, output / 'retirement', root)
                     == report['retirement_raw_command_files'], 'Retirement raw command inventory changed')
    return report, {'preparation': info, 'actual_exit': exit_info, 'retirement': rinfo,
                    'preconditioning': preconditioning_info}, p, s


def original_selection(consumer, runtimes, types):
    if consumer in ("server-ui", "statistics-ui", "settings-ui"):
        runtime = next(r for r in runtimes if r.get("isAvailable") and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27-"))
        device = next(d for d in types if d["name"] == "iPhone 16")
    elif consumer == "integrated-ui":
        runtime = next(r for r in runtimes if r.get("isAvailable") and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27"))
        device = next(d for d in types if d["name"] == "iPhone 16")
    elif consumer == "integrated-simulator":
        runtime = next(r for r in runtimes if r["isAvailable"] and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27"))
        device = next(t["identifier"] for t in types if t["name"] == "iPhone 16")
    elif consumer == "icon-ui":
        runtime = next(r for r in runtimes if r["isAvailable"] and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27"))
        device = "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
    else:
        raise ValueError("Unknown original consumer")
    return {"runtime": runtime, "device": device}


def logical_runtime_identity(runtime):
    require_contract(type(runtime) is dict, "Logical runtime must be an object")
    if "lastUsage" in runtime:
        value = runtime["lastUsage"]
        require_contract(type(value) is dict and set(value) == set(runtime["supportedArchitectures"])
                         and all(type(stamp) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z", stamp)
                                 for stamp in value.values()), "Unknown logical runtime lastUsage schema")
    # The first original consumer can update its last-use observation. Preserve
    # that complete raw field in every receipt; every other field stays exact.
    return {name: value for name, value in runtime.items() if name != "lastUsage"}


def same_logical_runtime(actual, expected):
    require_contract(logical_runtime_identity(actual) == logical_runtime_identity(expected),
                     "Runtime identity changed beyond its explicitly recorded lastUsage observation")


def check_selection(selection, prepared, consumer):
    same_logical_runtime(selection["runtime"], prepared["logical_runtime"])
    expected_device = prepared["device_type"]
    expected = expected_device["identifier"] if consumer in ("icon-ui", "integrated-simulator") else expected_device
    require_contract(selection["device"] == expected, "Original-selected device differs from prepared exact device")
    require_contract(Path(selection["runtime"]["bundlePath"]).resolve() == Path(prepared["expected_later_lifecycle_bundle_path"]).resolve(),
                     "Original-selected runtime names a different Simulator bundle")


def binding_command(output, label, argv, root):
    require_contract({"logical-runtimes": ["xcrun", "simctl", "list", "runtimes", "-j"],
                      "device-types": ["xcrun", "simctl", "list", "devicetypes", "-j"]}.get(label) == argv,
                     "Binding command is outside its separate two-read allowlist")
    row = {"label": label, "argv": argv, "requested_timeout_seconds": METADATA_TIMEOUT,
           "stdout_file": label + ".stdout.log", "stderr_file": label + ".stderr.log", "started_unix": time.time()}
    failure, process = None, None
    try:
        with (output / row["stdout_file"]).open("xb") as stdout, (output / row["stderr_file"]).open("xb") as stderr:
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
            row["pid"] = process.pid
            row["returncode"] = process.wait(timeout=METADATA_TIMEOUT)
            if row["returncode"]:
                raise subprocess.CalledProcessError(row["returncode"], argv)
    except Exception as error:
        failure = error
        row["timeout"] = isinstance(error, subprocess.TimeoutExpired)
        if process is not None and process.returncode is None:
            try:
                process.kill()
                row["owned_process_kill_requested"] = True
                row["returncode"] = process.wait(timeout=1)
            except Exception as capture:
                failure = recording_failure(failure, capture, "binding-owned-child-cleanup", row)
    finally:
        row["finished_unix"] = time.time()
        for channel in ("stdout", "stderr"):
            try:
                _, info = regular_bytes(output / row[channel + "_file"], root)
                row[channel + "_file_bytes"], row[channel + "_file_sha256"] = info["bytes"], info["sha256"]
            except Exception as error:
                failure = recording_failure(failure, error, "binding-" + channel, row)
        if failure is not None:
            row["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        try:
            write_new_json(output / (label + ".command.json"), row, root)
        except Exception as error:
            failure = recording_failure(failure, error, "binding-command-result", row)
    if failure is not None:
        raise failure
    return raw_command_json(output, label, root), row


def consumer_profile(context, name):
    rows = OWNER_PROFILES[context["owner"]]["consumers"]
    require_contract(name in rows, "Consumer is outside the actual owner profile")
    return rows[name]


def before_consumer(request, context, consumer):
    profile = consumer_profile(context,consumer)
    root,prep = Path(context['source_root']),preparation_root(context)
    prepared,binding,p,service = load_preparation(context)
    retirement,_ = read_bound_json(prep/'retirement/result.json',root,binding['retirement'])
    original_receipt = unlinked_path(root/profile['receipt'],root)
    require_contract(not original_receipt.exists(),'Refusing a stale original consumer receipt; it is never deleted by the adapter')
    prior_ledger,prior_binding = retirement_preceding_consumer_ledger(context,retirement,binding,consumer)
    output = unlinked_path(prep/'consumers'/consumer,root)
    require_contract(not output.exists(),'Each original consumer has one fresh before binding')
    output.mkdir(parents=True)
    report = {'schema':'common-runtime-consumer-before-v2','identity':context,'consumer':consumer,
              'preparation_binding':binding,'retirement_binding':binding['retirement'],
              'preceding_consumer_after_binding':prior_binding,
              'started_unix':time.time(),'commands':[],'original_receipt_must_be_new':str(original_receipt),
              'product_pass':False,'candidate_credit':False}
    failure = None
    try:
        runtimes,row = binding_command(output,'logical-runtimes',['xcrun','simctl','list','runtimes','-j'],root)
        report['commands'].append(row)
        types,row = binding_command(output,'device-types',['xcrun','simctl','list','devicetypes','-j'],root)
        report['commands'].append(row)
        selection = original_selection(consumer,runtimes['runtimes'],types['devicetypes'])
        check_selection(selection,prepared['logical_selection'],consumer)
        report['selection'] = selection
        report['dmg_stat_binding'] = {name:bound_file_stat(p[name]) for name in ('source_dmg_after','staged_dmg_after')}
        require_contract(all(value['matches_verified_receipt'] is True for value in report['dmg_stat_binding'].values()),
                         'Prepared DMG stat identity changed before original consumer')
        new = p['scope_after_verify']['new_uuid']
        current_bundle = path_snapshot(p['scope_after_verify']['new_record']['runtimeBundlePath'])
        require_contract(current_bundle.get('resolved_path')==str(Path(selection['runtime']['bundlePath']).resolve()),
                         'Logical and staged runtime bundle filesystem paths differ')
        require_contract(current_bundle==service['runtime_snapshots']['after']['filesystem'][new]['runtimeBundlePath'],
                         'Selected bundle filesystem identity changed before original consumer')
        report['bundle_filesystem'] = current_bundle
        report['terminal_host_observation'] = capture_post_retirement_observation(context,p,retirement,binding,output/'before-host',prior_ledger)
        recheck_context(request,context)
        report['result'] = 'BOUND_BEFORE_ORIGINAL_CONSUMER'
    except Exception as error:
        failure = error
        report['result'] = 'BEFORE_BINDING_FAILED'
        report['failure'] = {'type':type(error).__name__,'message':str(error)}
    finally:
        report['finished_unix'] = time.time()
        try:
            write_new_json(output/'before.json',report,root)
        except Exception as error:
            failure = recording_failure(failure,error,'before-result-save',report)
    if failure is not None:
        raise failure
    return report


def validate_original_receipt(value, before, profile, consumer):
    if profile["runtime_key"] is None:
        actual_runtime = value
    else:
        actual_runtime = value[profile["runtime_key"]]
    same_logical_runtime(actual_runtime, before["selection"]["runtime"])
    if profile["device_key"] is not None:
        require_contract(value[profile["device_key"]] == before["selection"]["device"],
                         "Actual original runtime/environment receipt selected another device")
        require_contract(type(value.get("udid")) is str and UUID.fullmatch(value["udid"]),
                         "Original consumer receipt lacks its actual created device identity")
    require_contract(type(actual_runtime.get("bundlePath")) is str
                     and actual_runtime["bundlePath"] == before["selection"]["runtime"]["bundlePath"],
                     "Actual original runtime bundle path differs")
    return {"runtime": actual_runtime, "device": None if profile["device_key"] is None else value[profile["device_key"]],
            "scope": "Icon's original receipt contains only the runtime; its device argument remains fixed in the byte-bound original driver." if consumer == "icon-ui"
                     else "Exact original runtime/device/created-UUID receipt; no application assertion result is inferred."}


def after_consumer(request, context, consumer, original_status):
    require_contract(type(original_status) is int and 0<=original_status<=255,'Invalid original shell exit status')
    root,prep = Path(context['source_root']),preparation_root(context)
    output = unlinked_path(prep/'consumers'/consumer,root)
    report = {'schema':'common-runtime-consumer-after-v2','identity':context,'consumer':consumer,
              'original_status':original_status,'started_unix':time.time(),'product_pass':False,'candidate_credit':False}
    failure = None
    try:
        profile = consumer_profile(context,consumer)
        prepared,binding,p,_ = load_preparation(context)
        retirement,_ = read_bound_json(prep/'retirement/result.json',root,binding['retirement'])
        before,before_info = read_bound_json(output/'before.json',root)
        require_contract(before.get('schema')=='common-runtime-consumer-before-v2'
                         and before['identity']==context and before['consumer']==consumer
                         and before['result']=='BOUND_BEFORE_ORIGINAL_CONSUMER'
                         and not any(key in before for key in ('failure','recording_errors','final_recording_error'))
                         and before['preparation_binding']==binding and before['retirement_binding']==binding['retirement'],
                         'Before binding is missing, failed or belongs to another V2 preparation')
        prior_ledger,prior_binding = retirement_preceding_consumer_ledger(context,retirement,binding,consumer)
        require_contract(before['preceding_consumer_after_binding']==prior_binding,'Preceding consumer after receipt changed')
        before_observation,_ = read_bound_json(output/'before-host/result.json',root,before['terminal_host_observation'])
        validate_post_retirement_observation(before_observation,retirement,context,binding,output/'before-host',root,prior_ledger)
        check_selection(before['selection'],prepared['logical_selection'],consumer)
        value,info = read_bound_json(root/profile['receipt'],root)
        report['original_receipt'],report['before_binding'] = info,before_info
        report['preparation_binding'],report['retirement_binding'] = binding,binding['retirement']
        report['selection'] = validate_original_receipt(value,before,profile,consumer)
        report['terminal_host_observation'] = capture_post_retirement_observation(context,p,retirement,binding,output/'after-host',before_observation['terminal_path_ledger'])
        recheck_context(request,context)
        report['result'] = 'ORIGINAL_RECEIPT_MATCHED'
    except Exception as error:
        failure = error
        report['result'] = 'AFTER_BINDING_FAILED'
        report['failure'] = {'type':type(error).__name__,'message':str(error)}
    report['effective_status'] = original_status if original_status else (1 if failure else 0)
    report['finished_unix'] = time.time()
    try:
        write_new_json(output/'after.json',report,root)
    except Exception as error:
        failure = recording_failure(failure,error,'after-result-save',report)
        report['effective_status'] = original_status or 1
        try:
            print('Original status preserved; after-binding evidence write failed:',str(error),file=sys.stderr)
        except Exception:
            pass
    return report['effective_status']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "record-prepare-exit", "before", "after"))
    parser.add_argument("--mode", required=True, choices=("canonical", "candidate", "workflow-input"))
    parser.add_argument("--owner", required=True, choices=tuple(OWNER_PROFILES))
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--control-root")
    parser.add_argument("--control-commit")
    parser.add_argument("--control-tree")
    parser.add_argument("--workflow-input-ref")
    parser.add_argument("--consumer")
    parser.add_argument("--actual-status", type=int)
    args = parser.parse_args()
    request = {name: getattr(args, name) for name in ("mode", "owner", "source_root", "source_commit", "source_tree", "control_root", "control_commit", "control_tree", "workflow_input_ref")}
    try:
        context = context_for(request)
        if args.action == "prepare":
            require_contract(args.consumer is None and args.actual_status is None, "Unexpected prepare arguments")
            prepare_environment(request, context)
        elif args.action == "record-prepare-exit":
            require_contract(args.consumer is None and args.actual_status is not None, "Require actual preparation process status")
            record_preparation_exit(context, args.actual_status)
        elif args.action == "before":
            require_contract(args.consumer is not None and args.actual_status is None, "Require one original consumer")
            before_consumer(request, context, args.consumer)
        else:
            require_contract(args.consumer is not None and args.actual_status is not None, "Require original consumer and its immediately captured actual status")
            return after_consumer(request, context, args.consumer, args.actual_status)
    except Exception as error:
        try:
            print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        except Exception:
            pass
        if args.action == "after" and type(args.actual_status) is int and 0 < args.actual_status <= 255:
            return args.actual_status
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
