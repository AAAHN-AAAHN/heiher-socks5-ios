#!/usr/bin/env python3
"""Exercise real loopback ICMP error delivery; only the injector uses sudo."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("--probe-only", action="store_true")
args = parser.parse_args()
source = args.source.resolve()
engine = source / "src/core/src/hev-icmp-engine.c"
with tempfile.TemporaryDirectory(prefix="icmp-live-errors-") as folder:
    binary = Path(folder) / "live-errors"
    command = [
        "cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
        "-I" + str(engine.parent),
        "-I" + str(source / "third-part/hev-task-system/include"),
        '-DICMP_ENGINE_SOURCE="' + str(engine) + '"',
        str(Path(__file__).with_suffix(".c")),
        str(source / "third-part/hev-task-system/bin/libhev-task-system.a"),
        "-o", str(binary),
    ]
    subprocess.run(command, check=True, timeout=90)
    if not shutil.which("sudo") or os.geteuid() == 0:
        print(json.dumps({"result": "UNAVAILABLE", "reason": "Requires a non-root engine process and a separate noninteractive sudo injector", "engine_euid": os.geteuid()}), flush=True)
        raise SystemExit(77)
    probe = subprocess.run(["sudo", "-n", "--", str(binary), "--probe-raw"],
                           capture_output=True, text=True, timeout=10)
    print(probe.stdout + probe.stderr, end="", flush=True)
    if probe.returncode:
        print(json.dumps({"result": "UNAVAILABLE", "reason": "Separate raw injector capability is unavailable", "returncode": probe.returncode}), flush=True)
        raise SystemExit(77)
    if args.probe_only:
        raise SystemExit(0)
    print(json.dumps({"scope": "Actual IPv4/IPv6 loopback error delivery after fixture consumption of automatic Echo Reply", "engine_euid": os.geteuid(), "production_receive_operations_replaced": 0, "external_destinations": 0, "system_network_settings_changed": False}), flush=True)
    subprocess.run([str(binary)], check=True, timeout=25)
