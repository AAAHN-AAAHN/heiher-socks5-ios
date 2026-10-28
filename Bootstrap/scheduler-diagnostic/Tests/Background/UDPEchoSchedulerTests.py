#!/usr/bin/env python3
"""Verify periodic operation and Off against the independent SOCKS5 wire fixture."""
import argparse
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def record_process(output, label, command, result):
    (output / (label + "-process.json")).write_text(json.dumps({
        "command": command, "returncode": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--swiftc", default=shutil.which("swiftc"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/background/udp-echo-scheduler")
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    (options.output / "results.json").unlink(missing_ok=True)
    if not __debug__:
        raise SystemExit("Assertions must be enabled")
    if not options.swiftc:
        raise SystemExit("swiftc is required for real UDP Echo scheduling tests")
    spec = importlib.util.spec_from_file_location("udp_echo_fixture", HERE / "UDPEchoTransportTests.py")
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    executable = options.output / "scheduler-probe"
    command = [options.swiftc, "-module-cache-path", str(options.output / "module-cache"),
               "-swift-version", "6", "-warnings-as-errors", "-O",
               str(ROOT / "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift"),
               str(ROOT / "Socks5/BackgroundKeepAlive/PeriodicUDPEchoStore.swift"),
               str(ROOT / "Socks5/BackgroundKeepAlive/PeriodicUDPEchoService.swift"),
               str(HERE / "UDPEchoSchedulerProbe.swift"), "-o", str(executable)]
    subprocess.run(command, check=True, timeout=120)
    inputs = [Path(value) for value in command if value.endswith(".swift")]
    inputs += [Path(__file__), HERE / "UDPEchoTransportTests.py"]
    (options.output / "source-sha256.json").write_text(json.dumps(
        {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}, indent=2) + "\n")
    (options.output / "compile-command.json").write_text(json.dumps(command, indent=2) + "\n")
    results = []
    for mode, family, target in [
            ("silence", socket.AF_INET, "127.0.0.1"), ("echo", socket.AF_INET, "127.0.0.1"),
            ("silence", socket.AF_INET6, "::1"), ("echo", socket.AF_INET6, "::1"),
            ("burst", socket.AF_INET, "127.0.0.1"), ("invalid-input", socket.AF_INET, "127.0.0.1"),
            ("statistics-wait", socket.AF_INET, "127.0.0.1")]:
        fixture_mode = "off-before-start" if mode == "statistics-wait" else mode
        fixture = fixture_module.Fixture(fixture_mode, family, target)
        try:
            command = [str(executable), mode, fixture.host,
                       str(fixture.listener.getsockname()[1]), target]
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            record_process(options.output, mode + "-" + str(family), command, result)
        finally:
            fixture.finish()
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
        data = json.loads(result.stdout)
        assert len(fixture.datagrams) == data["writes"], (mode, len(fixture.datagrams), data)
        results.append({"mode": mode, "family": family, **data})
        (options.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print("PASS:", mode, fixture.host, "wire datagrams", data["writes"], flush=True)
    command = [str(executable), "resolver-wait", "127.0.0.1", "1", "127.0.0.1"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    record_process(options.output, "resolver-wait", command, result)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    results.append({"mode": "resolver-wait", **json.loads(result.stdout)})
    (options.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print("PASS: readiness polling stops after Off; eight scheduler boundaries verified")


if __name__ == "__main__":
    main()
