#!/usr/bin/env python3
"""Compile and exercise the actual UDP Echo policy, storage and model."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift",
    "Socks5/BackgroundKeepAlive/PeriodicUDPEchoStore.swift",
    "Socks5/BackgroundKeepAlive/PeriodicUDPEchoService.swift",
    "Socks5/BackgroundKeepAlive/PeriodicUDPEchoModel.swift",
    "Tests/Background/UDPEchoObservableMocks.swift",
    "Tests/Background/UDPEchoServiceTests.swift",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--swiftc", default=shutil.which("swiftc"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/background/udp-echo")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").unlink(missing_ok=True)
    if not __debug__:
        raise SystemExit("Assertions must be enabled")
    if not args.swiftc:
        raise SystemExit("swiftc is required for UDP Echo verification")
    report = {"sources": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES},
              "runs": []}
    for version, optimization in (("5", "-Onone"), ("5", "-O"), ("6", "-Onone")):
        name = "swift" + version + optimization
        executable = args.output / name
        command = [args.swiftc, "-module-cache-path", str(args.output / "module-cache"),
                   "-swift-version", version, "-strict-concurrency=complete",
                   "-warnings-as-errors", optimization, *[str(ROOT / source) for source in SOURCES],
                   "-o", str(executable)]
        for label, invocation in (("compile", command), ("run", [str(executable)])):
            log = args.output / (name + "-" + label + ".log")
            with log.open("w") as stream:
                result = subprocess.run(invocation, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=120 if label == "compile" else 30)
            report["runs"].append({"name": name, "phase": label, "command": invocation,
                                   "exit_code": result.returncode, "log": str(log)})
            (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
            if result.returncode:
                raise SystemExit(log.read_text())
    print("PASS: UDP Echo debug, optimized and Swift 6 policy/storage/model tests")


if __name__ == "__main__":
    main()
