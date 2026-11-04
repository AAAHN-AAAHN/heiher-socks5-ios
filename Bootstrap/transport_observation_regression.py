#!/usr/bin/env python3
"""Run exactly one old/new delayed-reply comparison on the real Swift client.

This optional local/CI recipe is not run by proposal preparation. Compile
failure, unexpected old output, timeout, or an incomplete comparison cannot
count as detection of the observation-order defect. No automatic retries.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.dont_write_bytecode = True


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invoke(arguments, output, timeout):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic_ns()
    record = {"arguments": arguments, "timeout_seconds": timeout,
              "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "started_monotonic_ns": started, "executed": False,
              "returncode": None, "timed_out": False, "launch_or_capture_error": None}
    stdout, stderr = b"", b""
    try:
        process = subprocess.run(arguments, capture_output=True, timeout=timeout)
        record.update(executed=True, returncode=process.returncode)
        stdout, stderr = process.stdout, process.stderr
    except subprocess.TimeoutExpired as error:
        record.update(executed=True, timed_out=True)
        stdout, stderr = error.stdout or b"", error.stderr or b""
    except OSError as error:
        record["launch_or_capture_error"] = repr(error)
    record["finished_monotonic_ns"] = time.monotonic_ns()
    record["elapsed_seconds"] = (record["finished_monotonic_ns"] - started) / 1e9
    for name, data in (("stdout", stdout), ("stderr", stderr)):
        path = output / (name + ".log")
        path.write_bytes(data)
        record[name] = {"path": str(path), "bytes": len(data), "sha256": sha(path)}
    (output / "command.json").write_text(json.dumps(record, indent=2) + "\n")
    return record, stdout, stderr


def delayed_trial(fixture_type, executable, output, expected_argument):
    fixture = fixture_type("wildcard6", socket.AF_INET, "127.0.0.1", delay_last_reply=True)
    arguments = [str(executable), "wildcard6", fixture.host,
                 str(fixture.listener.getsockname()[1]), "127.0.0.1"]
    if expected_argument is not None:
        arguments.append(str(expected_argument))
    command, stdout, stderr = invoke(arguments, output / "process", 6)
    finish_error = None
    try:
        fixture.finish()
    except Exception as error:
        finish_error = repr(error)
    parse_error, data = None, None
    try:
        data = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        parse_error = repr(error)
    checks = {
        "actual_runtime_exit_zero": command["executed"] and command["returncode"] == 0 and not command["timed_out"],
        "fixture_joined_without_error": finish_error is None and fixture.error is None and not fixture.thread.is_alive(),
        "valid_json": isinstance(data, dict),
        "five_independent_packets_received": len(fixture.datagrams) == 5,
        "peer_sendto_accepted_55_bytes": fixture.reply_bytes == 55,
        "delayed_last_reply_recorded": fixture.delayed_reply is not None,
    }
    if fixture.delayed_reply is not None:
        delay = fixture.delayed_reply
        checks.update(
            last_reply_after_four_replies=delay["reply_bytes_before_release"] == 44 and delay["datagrams_received"] == 5,
            last_reply_delay_at_least_700ms=delay["released_monotonic_ns"] - delay["started_monotonic_ns"] >= 700_000_000,
            last_reply_release_after_process_start_plus_650ms=delay["released_monotonic_ns"] - command["started_monotonic_ns"] > 650_000_000)
    if isinstance(data, dict):
        checks.update(
            ready_without_failure=data.get("events") == ["ready"],
            accepted_five_attempts=data.get("accepted") == data.get("attempts") == 5,
            zero_drops=data.get("dropped") == 0,
            written_bytes_exact=data.get("datagramWrites") == sum(map(len, fixture.datagrams)) == 55,
            control_and_udp_write_total=data.get("writes") == fixture.tcp_read + data.get("datagramWrites", -1),
            control_and_udp_read_total=data.get("reads") == fixture.tcp_written + data.get("udpReadBytes", -1),
            observed_bytes_exact=data.get("udpReadBytes") == (44 if expected_argument is None else 55))
    else:
        checks["observed_bytes_exact"] = False
    record = {"command": command, "expected_reply_argument": expected_argument,
              "parsed_stdout": data, "parse_error": parse_error,
              "fixture": {"datagrams_hex": [packet.hex() for packet in fixture.datagrams],
                          "reply_bytes": fixture.reply_bytes, "tcp_read": fixture.tcp_read,
                          "tcp_written": fixture.tcp_written, "delayed_reply": fixture.delayed_reply,
                          "error": fixture.error, "finish_error": finish_error,
                          "thread_alive": fixture.thread.is_alive()},
              "checks": checks,
              "interpretation": ("EXPECTED_RUNTIME_OBSERVATION_MISMATCH" if expected_argument is None
                                 else "EXACT_POSITIVE_BYTE_EQUALITY"),
              "demonstrated": all(checks.values()),
              "clock_scope": "Python monotonic_ns from this runner/peer only; no equality with Swift DispatchTime epochs assumed."}
    (output / "trial.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-root", type=Path, required=True)
    parser.add_argument("--proposed-root", type=Path, required=True)
    parser.add_argument("--swiftc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    roots = {"original": options.original_root.resolve(), "proposed": options.proposed_root.resolve()}
    output = options.output.resolve()
    if output.exists():
        raise SystemExit("Output already exists; no implicit retry/overwrite.")
    if any(root == output or root in output.parents for root in roots.values()):
        raise SystemExit("Output must be outside both source roots.")
    pins = {
        "original": {
            "Tests/Background/UDPEchoTransportProbe.swift": "f931e5c1ca829642739cece332d26ba7b043a13227fb804b586ebe6b6d3fa91a",
            "Tests/Background/UDPEchoTransportTests.py": "9983165ff22ec16b3fcea0ae661f64906939bb4dd006dabae92c7086d4c6f4e6",
            "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift": "57da93313e01f5c3938f0be3b112de58afeeaf0aab5013ca9a8c20278d377465",
        },
        "proposed": {
            "Tests/Background/UDPEchoTransportProbe.swift": "55ca38e6e488beb553d52a7d8b66367d6a5bc03859236656bff16496b43e6a82",
            "Tests/Background/UDPEchoTransportTests.py": "a70b13ced0a114149ed5e3570ad40bf8868022f726982c4c7da5eb311fe87a57",
            "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift": "57da93313e01f5c3938f0be3b112de58afeeaf0aab5013ca9a8c20278d377465",
        },
    }
    inputs = {}
    for label, source_pins in pins.items():
        inputs[label] = []
        for name, expected in source_pins.items():
            path = roots[label] / name
            assert path.is_file() and not path.is_symlink(), path
            assert sha(path) == expected, (label, name)
            inputs[label].append({"path": str(path), "bytes": path.stat().st_size,
                                  "sha256": expected, "mode": path.stat().st_mode & 0o777})
    fixture_path = roots["proposed"] / "Tests/Background/UDPEchoTransportTests.py"
    spec = importlib.util.spec_from_file_location("delayed_reply_fixture", fixture_path)
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    output.mkdir(parents=True)
    receipt = {"schema": "fixed-two-trial-delayed-reply-regression-v2",
               "actual_source_inputs": inputs,
               "planned_compiles": 2, "planned_runtime_trials": 2, "automatic_retries": 0,
               "production_client_unchanged": True, "compiles": [], "trials": [],
               "result": "INCOMPLETE", "scope": "Synthetic peer delay demonstrates the test ordering flaw only; it cannot establish past CI failure timing or replace owner/candidate/canonical gates."}
    try:
        for label in ("original", "proposed"):
            directory = output / label
            executable = directory / "transport-probe"
            directory.mkdir()
            command = [options.swiftc, "-swift-version", "6", "-warnings-as-errors", "-O",
                       "-module-cache-path", str(directory / "module-cache"),
                       str(roots[label] / "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift"),
                       str(roots[label] / "Tests/Background/UDPEchoTransportProbe.swift"),
                       "-o", str(executable)]
            record, _, _ = invoke(command, directory / "compile", 90)
            receipt["compiles"].append({"variant": label, **record})
        for label, expected in (("original", None), ("proposed", 55)):
            compile_record = next(v for v in receipt["compiles"] if v["variant"] == label)
            if compile_record["returncode"] != 0 or compile_record["timed_out"]:
                receipt["trials"].append({"variant": label, "executed": False,
                                          "reason": "COMPILE_DID_NOT_SUCCEED", "demonstrated": False})
                continue
            receipt["trials"].append({"variant": label, "executed": True,
                                      **delayed_trial(fixture_module.Fixture, output / label / "transport-probe",
                                                      output / label / "trial", expected)})
        receipt["result"] = "PASS" if (len(receipt["trials"]) == 2 and all(v["demonstrated"] for v in receipt["trials"])) else "FAIL_OR_INCONCLUSIVE"
    finally:
        (output / "focused-regression.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"result": receipt["result"], "receipt": str(output / "focused-regression.json")}, indent=2))
    raise SystemExit(0 if receipt["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()
