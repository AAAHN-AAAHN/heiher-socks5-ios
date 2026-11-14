#!/usr/bin/env python3
"""Linux real-wire regression: exact old service must fail the named predicate."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASELINE = "c255c520688270f3e867a4048a0cd68183970db9"
SERVICE = "Socks5/BackgroundKeepAlive/PeriodicUDPEchoService.swift"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/background/udp-echo-send-state")
    parser.add_argument("--baseline-ref", default=BASELINE)
    parser.add_argument("--swiftc", default=shutil.which("swiftc"))
    parser.add_argument("--clang", default=shutil.which("clang"))
    args = parser.parse_args()
    assert __debug__ and platform.system() == "Linux", "Linux and assertions required"
    assert args.swiftc and args.clang, "Swift and clang required"
    assert args.baseline_ref == BASELINE, "Regression baseline must remain exact"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").unlink(missing_ok=True)
    baseline = output / "BaselineService.swift"
    baseline.write_bytes(subprocess.check_output(["git", "show", BASELINE + ":" + SERVICE], cwd=ROOT))
    library = output / "socket-faults.so"
    subprocess.run([args.clang, "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared",
                    str(HERE / "UDPEchoTransportIO.c"), "-ldl", "-o", str(library)], check=True, timeout=120)
    spec = importlib.util.spec_from_file_location("send_state_fixture", HERE / "UDPEchoTransportTests.py")
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    sources = [ROOT / "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift",
               ROOT / "Socks5/BackgroundKeepAlive/PeriodicUDPEchoStore.swift",
               HERE / "UDPEchoSendStateProbe.swift"]
    inputs = sources + [ROOT / SERVICE, baseline, HERE / "UDPEchoTransportIO.c",
                        HERE / "UDPEchoTransportTests.py", Path(__file__)]
    report = {"baseline": BASELINE, "hashes": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}, "runs": []}
    for label, service in [("baseline", baseline), ("candidate", ROOT / SERVICE)]:
        executable = output / label
        command = [args.swiftc, "-module-cache-path", str(output / "module-cache"),
                   "-swift-version", "6", "-strict-concurrency=complete", "-warnings-as-errors", "-O",
                   *map(str, sources), str(service), "-o", str(executable)]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=120)
        (output / (label + "-compile.log")).write_text(compiled.stdout + compiled.stderr)
        assert compiled.returncode == 0, (label, "compile failure is not a valid negative", compiled.stderr)
        for multiple in (False, True):
            suffix = "-multiple" if multiple else "-single"
            fixture = fixture_module.Fixture("silence", socket.AF_INET,
                ("127.0.0.1", "127.0.0.2") if multiple else "127.0.0.1", accept_timeout=5)
            environment = os.environ.copy()
            environment.pop("UDP_ECHO_IO_FAULTS", None)
            environment.pop("UDP_ECHO_DROP_ONCE", None)
            environment.update(LD_PRELOAD=str(library), UDP_ECHO_SEND_STATE="1")
            try:
                result = subprocess.run([str(executable), str(fixture.listener.getsockname()[1])] + (["multiple"] if multiple else []),
                                        env=environment, capture_output=True, text=True, timeout=8)
                (output / (label + suffix + "-stdout.log")).write_text(result.stdout)
                (output / (label + suffix + "-stderr.log")).write_text(result.stderr)
            finally:
                fixture.finish()
            assert len(fixture.datagrams) >= 3, (label, "successful wire traffic required")
            expected = 74 if label == "baseline" else 0
            assert result.returncode == expected, (label, result.returncode, result.stderr)
            assert result.stderr == ("SEND_STATE_ERROR_THEN_RECOVERY\n" if label == "baseline" else ""), (label, result.stderr)
            report["runs"].append({"label": label + suffix, "compile_command": command,
                                   "returncode": result.returncode, "wire_datagrams": len(fixture.datagrams)})
            (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print("PASS: exact baseline rejected with named predicate; candidate recovered on real sockets")


if __name__ == "__main__":
    main()
