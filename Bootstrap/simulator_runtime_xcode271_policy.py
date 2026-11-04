#!/usr/bin/env python3
"""Explicit Xcode27.1 policy with the same iOS27.0/24A434 and iPhone16.
Derived from the preserved comparison policy; no executable lifecycle.
"""
from pathlib import Path

RUNTIME_PAIRS = {
    "27.0": {"build": "24A434", "device_type": "com.apple.CoreSimulator.SimDeviceType.iPhone-16"},
}
EXPECTED_SDK = "27.1"
EXPECTED_XCODE = "Xcode 27.1\nBuild version 27A9275"
EXPECTED_DEVELOPER_DIR = "/Applications/Xcode_27.1.app/Contents/Developer"
LIMITS = {"create": 60, "boot": 180, "bootstatus": 120, "shutdown": 30, "delete": 30}


def select_exact(runtimes, device_types, version, build, device_identifier, sdk):
    if RUNTIME_PAIRS.get(version) != {"build": build, "device_type": device_identifier} or sdk != EXPECTED_SDK:
        raise ValueError("Comparison requires the declared runtime/build/device pair and Simulator SDK 27.1")
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
        raise ValueError("DEVELOPER_DIR differs from the declared installed Xcode 27.1 path")
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
