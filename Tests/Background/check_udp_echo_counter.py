#!/usr/bin/env python3
"""Verify the actual On-episode counter through production client/service/model."""
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
SOURCES = [
    "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift",
    "Socks5/BackgroundKeepAlive/PeriodicUDPEchoStore.swift",
    "Socks5/BackgroundKeepAlive/PeriodicUDPEchoService.swift",
    "Socks5/BackgroundKeepAlive/PeriodicUDPEchoModel.swift",
    "Tests/Background/UDPEchoObservableMocks.swift",
    "Tests/Background/UDPEchoCounterProbe.swift",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--swiftc", default=shutil.which("swiftc"))
    parser.add_argument("--clang", default=shutil.which("clang"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/background/udp-echo-counter")
    args = parser.parse_args()
    assert __debug__ and args.swiftc, "Assertions and swiftc are required"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "results.json").unlink(missing_ok=True)
    spec = importlib.util.spec_from_file_location("udp_echo_counter_fixture", HERE / "UDPEchoTransportTests.py")
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    executable = args.output / "counter-probe"
    compile_command = [args.swiftc, "-module-cache-path", str(args.output / "module-cache"),
                       "-swift-version", "6", "-strict-concurrency=complete", "-warnings-as-errors", "-O",
                       *[str(ROOT / name) for name in SOURCES], "-o", str(executable)]
    subprocess.run(compile_command, check=True, timeout=120)
    modes = ["silent-relay"]
    fault_library = args.output / "socket-faults.so"
    if platform.system() == "Linux":
        assert args.clang, "clang is required for the dropped-datagram counter case"
        subprocess.run([args.clang, "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared",
                        str(HERE / "UDPEchoTransportIO.c"), "-ldl", "-o", str(fault_library)],
                       check=True, timeout=120)
        modes.append("dropped-datagram")
    inputs = SOURCES + ["Tests/Background/UDPEchoTransportTests.py",
                        "Tests/Background/UDPEchoTransportIO.c", str(Path(__file__).resolve().relative_to(ROOT))]
    report = {"sources": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs},
              "compile_command": compile_command, "runs": []}
    for mode in modes:
        fixtures = [fixture_module.Fixture("silence", socket.AF_INET, "127.0.0.1", accept_timeout=5)
                    for _ in range(5)]
        command = [str(executable), *[str(item.listener.getsockname()[1]) for item in fixtures],
                   *[str(item.relay.getsockname()[1]) for item in fixtures]]
        environment = os.environ.copy()
        if mode == "dropped-datagram":
            environment.update(LD_PRELOAD=str(fault_library.resolve()),
                               UDP_ECHO_IO_FAULTS="1", UDP_ECHO_DROP_ONCE="1")
        result = None
        failure = None
        cleanup_errors = []
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, env=environment)
            assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
        except BaseException as error:
            failure = error
        finally:
            for item in fixtures:
                try:
                    item.finish(timeout=6)
                except BaseException as error:
                    cleanup_errors.append(repr(error))
            record = {"mode": mode, "command": command,
                      "returncode": result.returncode if result else None,
                      "stdout": result.stdout if result else "", "stderr": result.stderr if result else "",
                      "failure": repr(failure) if failure else None, "cleanup_errors": cleanup_errors,
                      "delivered_per_association": [len(item.datagrams) for item in fixtures],
                      "reply_bytes": sum(item.reply_bytes for item in fixtures)}
            report["runs"].append(record)
            (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
        if failure:
            raise failure
        assert not cleanup_errors, cleanup_errors
        data = json.loads(result.stdout)
        assert data["acceptedDatagrams"] == 30 and data["firstEpisode"] == 6, data
        assert data["sameOnAfterServerAndInputChanges"] == 12 and data["newEpisodeFinalCount"] == 6, data
        assert data["coalescedOffOnReset"] and data["staleEpisodeRejected"], data
        assert not data["replyRequired"] and record["reply_bytes"] == 0, record
        assert all(1 <= count <= 6 for count in record["delivered_per_association"]), record
        print("PASS:", mode, "actual accepted sends, same-On retention, Off/On and stale-episode boundaries", flush=True)
    print("PASS: production UDP Echo On-episode counter")


if __name__ == "__main__":
    main()
