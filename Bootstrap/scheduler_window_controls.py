#!/usr/bin/env python3
"""Bounded real-wire controls for the scheduler observation-window correction."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time

if not __debug__:
    raise SystemExit("Assertions must be enabled")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_result(record, markers=(), observe_cadence=False):
    assert record["returncode"] is not None, record
    rejected = record["returncode"] != 0 and any(
        "SCHEDULER_PREDICATE: " + marker in record["stderr"].splitlines() for marker in markers)
    if markers and not (observe_cadence and record["returncode"] == 0):
        assert rejected, record
    else:
        assert record["returncode"] == 0 and 5 <= record["delivered"] <= record["observed"]["writes"], record
    peer_close = record["setup_peer_close"]
    expected_cancellation = (
        record["label"] == "delayed-original-rejected" and markers == ("ACTIVE_COUNT",) and rejected
        and peer_close is not None and peer_close["kind"] in ("ConnectionResetError", "BrokenPipeError")
        and record["fixture_error"] == peer_close["error"]
        and record["cleanup_error_kind"] == "AssertionError" and record["cleanup_matches_fixture_error"])
    clean = record["fixture_error"] is None and record["cleanup_error"] is None and peer_close is None
    assert record["fixture_joined"] and (clean or expected_cancellation), record
    if observe_cadence:
        return "CADENCE_PREDICATE_REJECTED" if rejected else "NORMAL_CADENCE_OBSERVED"
    return "EXPECTED_SETUP_CANCELLATION" if expected_cancellation else "EXPECTED_REJECTION" if markers else "ACCEPTED"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--swiftc", default=shutil.which("swiftc"))
    parser.add_argument("--require-nonstrict", action="store_true")
    options = parser.parse_args()
    assert options.swiftc
    root, output = options.root.resolve(), options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    here = root / "Tests/Background"
    product = root / "Socks5/BackgroundKeepAlive"
    service = product / "PeriodicUDPEchoService.swift"
    probe = (options.probe or here / "UDPEchoSchedulerProbe.swift").resolve()
    original_sha = "f89e8cbc444d85cbc5abe28188222fa6e70d900655047c3f7010f9f2fe2cf3e3"
    old_bytes = subprocess.check_output([
        "git", "-C", str(root), "show",
        "d6e1d9015ab25400b3ccfdd13ea339faa4fefbbd:Tests/Background/UDPEchoSchedulerProbe.swift"])
    assert hashlib.sha256(old_bytes).hexdigest() == original_sha
    old_probe = output / "old-probe.swift"
    old_probe.write_bytes(old_bytes)
    assert "let setupDeadline = activationTime + 2_000_000_000" in probe.read_text()
    assert 'require(ready, "SETUP_READY")' in probe.read_text()
    source_files = [product / "Socks5UDPClient.swift", product / "PeriodicUDPEchoStore.swift", service,
                    here / "UDPEchoSchedulerProbe.swift", here / "UDPEchoTransportTests.py", probe]
    before = {str(p): sha(p) for p in source_files}
    records, commands = [], []
    spec = importlib.util.spec_from_file_location("scheduler_wire_fixture", here / "UDPEchoTransportTests.py")
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)

    class DelayedFixture(fixtures.Fixture):
        def __init__(self, mode, delay):
            self.delay = delay
            self.delay_applied = False
            self.control_times = []
            self.setup_peer_close = None
            super().__init__(mode, socket.AF_INET6, "::1")

        def send_control(self, connection, value):
            if not self.delay_applied:
                self.delay_applied = True
                self.control_times.append({"phase": "greeting-received", "time_ns": time.monotonic_ns()})
                self.stop.wait(self.delay)
            self.control_times.append({"phase": "response-start", "time_ns": time.monotonic_ns(),
                                       "bytes": len(value)})
            try:
                super().send_control(connection, value)
            except (ConnectionResetError, BrokenPipeError) as error:
                self.setup_peer_close = {"kind": type(error).__name__, "error": repr(error)}
                raise

    def compile_variant(label, candidate_service, candidate_probe):
        executable = output / label
        command = [options.swiftc, "-module-cache-path", str(output / "module-cache"),
                   "-swift-version", "6", "-warnings-as-errors", "-O",
                   str(product / "Socks5UDPClient.swift"), str(product / "PeriodicUDPEchoStore.swift"),
                   str(candidate_service), str(candidate_probe), "-o", str(executable)]
        commands.append({"label": label, "argv": command,
                         "service_sha256": sha(candidate_service), "probe_sha256": sha(candidate_probe)})
        (output / "compile-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        with (output / (label + "-compile.log")).open("w") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
        return executable

    def exercise(label, executable, delay=0, fixture_mode="echo", markers=(), observe_cadence=False):
        fixture = DelayedFixture(fixture_mode, delay)
        command = [str(executable), "echo", fixture.host, str(fixture.listener.getsockname()[1]), "::1"]
        run = None
        cleanup_error = None
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=5)
        finally:
            try:
                fixture.finish()
            except Exception as error:
                cleanup_error = error
            finally:
                record = {"label": label, "command": command, "delay_seconds": delay,
                          "fixture_mode": fixture_mode, "fixture_control_times": fixture.control_times,
                          "fixture_error": fixture.error, "fixture_joined": not fixture.thread.is_alive(),
                          "setup_peer_close": fixture.setup_peer_close,
                          "cleanup_error": repr(cleanup_error) if cleanup_error is not None else None,
                          "cleanup_error_kind": type(cleanup_error).__name__ if cleanup_error is not None else None,
                          "cleanup_matches_fixture_error": (isinstance(cleanup_error, AssertionError)
                                                            and cleanup_error.args == (fixture.error,)),
                          "delivered": len(fixture.datagrams), "expected_markers": list(markers),
                          "returncode": None if run is None else run.returncode,
                          "stdout": None if run is None else run.stdout,
                          "stderr": None if run is None else run.stderr}
                if run is not None and run.stdout.strip():
                    record["observed"] = json.loads(run.stdout)
                records.append(record)
                (output / "results.json").write_text(json.dumps(records, indent=2) + "\n")
        assert run is not None
        record["classification"] = classify_result(record, markers, observe_cadence)
        (output / "results.json").write_text(json.dumps(records, indent=2) + "\n")
        print("PASS", label, "exit", run.returncode, "wire", len(fixture.datagrams), record["classification"], flush=True)
        return record["classification"]

    original = compile_variant("original", service, old_probe)
    corrected = compile_variant("corrected", service, probe)
    exercise("delayed-original-rejected", original, delay=.32, markers=("ACTIVE_COUNT",))
    exercise("delayed-corrected-accepted", corrected, delay=.32)
    exercise("unavailable-setup-rejected", corrected, fixture_mode="setup-timeout", markers=("SETUP_READY",))
    text = service.read_text()
    anchor = "return Plan(targets: targets, interval: milliseconds * 1_000_000)"
    assert text.count(anchor) == 1
    wrong_period = output / "wrong-period-service.swift"
    wrong_period.write_text(text.replace(anchor,
        "return Plan(targets: targets, interval: max(milliseconds, 100) * 1_000_000)", 1))
    slow = compile_variant("wrong-period", wrong_period, probe)
    exercise("wrong-period-rejected", slow, markers=("ACTIVE_COUNT", "INTERVAL_RANGE"))
    strict_result = "NOT_RUN_PLATFORM_SPECIFIC"
    if platform.system() == "Darwin" or options.require_nonstrict:
        anchor = "DispatchSource.makeTimerSource(flags: .strict, queue: queue)"
        assert text.count(anchor) == 1
        nonstrict = output / "nonstrict-service.swift"
        nonstrict.write_text(text.replace(anchor, "DispatchSource.makeTimerSource(queue: queue)", 1))
        plain = compile_variant("nonstrict", nonstrict, probe)
        # Non-strict dispatch timers permit coalescing; they do not require it.
        strict_result = exercise("nonstrict-corrected-probe-observed", plain,
                                 markers=("ACTIVE_COUNT", "INTERVAL_RANGE"), observe_cadence=True)
        exercise("strict-same-host-accepted", corrected)
    after = {str(p): sha(p) for p in source_files}
    assert after == before
    receipt = {"result": "PASS", "platform": platform.platform(),
               "candidate": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
               "original_probe_commit": "d6e1d9015ab25400b3ccfdd13ea339faa4fefbbd",
               "source_sha256": before, "inputs_unchanged_after": True,
               "nonstrict_timer_control": strict_result, "cases": len(records),
               "outer_process_timeout_seconds": 5, "active_observation_ms": 360,
               "setup_bound_ms": 2000, "production_mutated": False}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
