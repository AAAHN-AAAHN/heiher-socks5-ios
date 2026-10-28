#!/usr/bin/env python3
"""Compare the exact 4cc UDP7 fixture before and after a fresh Simulator boot."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid

CANDIDATE = "4cc1a53416df1f888603df448126392c611b2bb9"
SOURCES = {
    "Build/ui_review.py": "847cc6ddd3de486e532dcf5cf9c9e6399b3ce180b0a39e0d2b6195bf7c6cd3ce",
    "Build/release_source.py": "c90aee96146fa2fa2ed0dd40bbf4cac9f1b4677506920a4dbb42c6316f80383b",
    "Tests/Background/check_udp_echo_native.py": "c60a73c593167b77ae9988227a83aa8d535022023d8dba6608af886b3a138433",
}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def identity(root):
    assert subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                   text=True, timeout=10).strip() == CANDIDATE
    for args in (("diff", "--exit-code", "HEAD", "--"),
                 ("diff", "--cached", "--exit-code", "HEAD", "--")):
        subprocess.run(["git", "-C", str(root), *args], check=True, timeout=10,
                       stdout=subprocess.DEVNULL)
    actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCES}
    assert actual == SOURCES, actual
    return actual


class StartupObserver:
    """Read-only bounded process snapshots; never delays the fixture's deadlines."""
    def __init__(self, folder):
        self.folder = folder
        self.stop = threading.Event()
        self.records = []
        self.errors = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def snapshot(self, pid, stage):
        started = time.monotonic()
        deadline = started + 1
        pending, pids, errors = [pid], [], []
        while pending and len(pids) < 16 and time.monotonic() < deadline:
            parent = pending.pop(0)
            if parent in pids:
                continue
            pids.append(parent)
            try:
                child = subprocess.run(["/usr/bin/pgrep", "-P", str(parent)], capture_output=True,
                                       text=True, timeout=min(.2, max(.001, deadline - time.monotonic())))
                if child.returncode not in (0, 1):
                    errors.append({"operation": "pgrep", "pid": parent, "returncode": child.returncode})
                pending.extend(int(line) for line in child.stdout.splitlines() if line.isdecimal())
            except Exception as error:
                errors.append({"operation": "pgrep", "pid": parent, "error": repr(error)})
        rows = []
        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                status = subprocess.run(["/bin/ps", "-p", ",".join(map(str, pids)),
                                         "-o", "pid=,ppid=,uid=,state=,comm="],
                                        capture_output=True, text=True, timeout=min(.2, remaining))
                if status.returncode not in (0, 1):
                    errors.append({"operation": "ps", "returncode": status.returncode})
                for line in status.stdout.splitlines():
                    values = line.split(None, 4)
                    if len(values) == 5 and all(v.isdecimal() for v in values[:3]):
                        child_pid, parent_pid, uid = map(int, values[:3])
                        if child_pid in pids:
                            rows.append({"pid": child_pid, "ppid": parent_pid, "uid": uid,
                                         "state": values[3], "comm": values[4]})
            except Exception as error:
                errors.append({"operation": "ps", "error": repr(error)})
        return {"stage": stage, "owned_sudo_pid": pid, "queried_pids": pids,
                "elapsed_seconds": time.monotonic() - started, "processes": rows, "errors": errors,
                "scope": "Only the recorded sudo PID and children discovered with pgrep -P; no arguments or environment."}

    def run(self):
        seen = set()
        while not self.stop.is_set():
            try:
                value = json.loads((self.folder / "udp-echo-helper.json").read_text())
                for stage in value["stages"]:
                    name = stage["stage"]
                    if name in ("spawned", "startup-failed") and name not in seen:
                        seen.add(name)
                        if stage["pid"] is not None and stage["poll"] is None:
                            self.records.append(self.snapshot(stage["pid"], name))
                if any(stage["stage"] == "ready" for stage in value["stages"]):
                    return
            except (FileNotFoundError, json.JSONDecodeError):
                pass  # The owner writes its existing diagnostic JSON in place.
            except Exception as error:
                self.errors.append(repr(error))
                return
            self.stop.wait(.025)

    def finish(self):
        self.stop.set()
        self.thread.join(2)
        if self.thread.is_alive():
            self.errors.append("Diagnostic observer did not finish within2s")
        save(self.folder / "startup-processes.json", {"snapshots": self.records, "errors": self.errors,
                                                      "observer_joined": not self.thread.is_alive()})


def load_fixture(root, folder):
    folder.mkdir()
    spec = importlib.util.spec_from_file_location("exact_ui_fixture", root / "Build/ui_review.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(root / "Build"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    module.OUT = folder
    return module


def start_fixture(module, record):
    observer = StartupObserver(module.OUT)
    observer.thread.start()
    started = time.monotonic()
    try:
        return module.UDPEchoFixture()
    finally:
        record["constructor_elapsed_seconds"] = time.monotonic() - started
        try:
            observer.finish()
        except Exception as error:
            record["observer_error"] = repr(error)  # Never replaces the constructor failure.


def exercise(fixture):
    assert os.geteuid() != 0 and fixture.helper is not None
    assert fixture.helper.poll() is None

    def control(value):
        with socket.create_connection(fixture.control.server_address, timeout=5) as stream:
            stream.settimeout(5)
            stream.sendall(value.encode() + b"\n")
            with stream.makefile("rb") as reader:
                result = json.loads(reader.readline(65536))
        assert "error" not in result and result["valid"], result
        return result

    channels, rounds = [], []
    try:
        for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            channel = socket.socket(family, socket.SOCK_DGRAM)
            channels.append((channel, host))
            channel.bind((host, 0))
        for mode in ("reply", "drop", "reply"):
            changed = control(mode)
            assert changed["counts"] == {"4": 0, "6": 0}, changed
            for channel, host in channels:
                channel.settimeout(1 if mode == "reply" else .2)
                channel.sendto(b"\x00", (host, 7))
                if mode == "reply":
                    payload, peer = channel.recvfrom(100)
                    assert payload == b"\x00" and peer[0] == host and peer[1] == 7
                else:
                    try:
                        unexpected = channel.recvfrom(100)
                    except socket.timeout:
                        pass
                    else:
                        raise AssertionError(("unexpected reply in drop mode", unexpected))
            deadline = time.monotonic() + 3
            observed = control("snapshot")
            while observed["counts"] != {"4": 1, "6": 1} and time.monotonic() < deadline:
                time.sleep(.02)
                observed = control("snapshot")
            assert observed["counts"] == {"4": 1, "6": 1} and observed["valid"], observed
            rounds.append({"mode": mode, "observed": observed})
        return {"helper_pid": fixture.helper.pid, "rounds": rounds}
    finally:
        for channel, _ in channels:
            channel.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    if not __debug__ or sys.platform != "darwin" or os.geteuid() == 0:
        raise SystemExit("Use assertions and an ordinary macOS account; Linux/root is not this proof")
    output.mkdir(parents=True, exist_ok=True)
    assert not any((output / name).exists() for name in ("receipt.json", "before-boot", "after-boot"))
    before = identity(root)
    result = {"candidate": CANDIDATE, "source_sha256": before, "parent_uid": os.geteuid(),
              "status": "RUNNING", "stages": [], "cleanup_errors": [],
              "scope": "Fixture and fresh Simulator only; no app build, app execution or owner PASS."}
    identifier, fixture, failure = None, None, None
    started = time.monotonic()

    def command(args, name, timeout):
        with (output / (name + ".log")).open("w") as log:
            completed = subprocess.run(args, stdout=log, stderr=subprocess.STDOUT,
                                       text=True, check=True, timeout=timeout)
        return completed

    def output_command(args, name, timeout=60):
        command(args, name, timeout)
        return (output / (name + ".log")).read_text().strip()

    def stage(name):
        value = {"name": name, "status": "RUNNING", "elapsed_start_seconds": time.monotonic() - started}
        result["stages"].append(value)
        save(output / "progress.json", result)
        return value

    def finish_fixture(value, record, folder):
        value.close()
        record["helper_final_poll"] = value.helper.poll() if value.helper is not None else None
        assert record["helper_final_poll"] == 0
        phases = [json.loads(line) for line in (folder / "udp-echo-helper.log").read_text().splitlines()]
        assert [entry["udp_echo_helper_phase"] for entry in phases] == [
            "entry", "module-loaded", "udp7-ready", "stopping", "stopped"], phases
        assert len({entry["pid"] for entry in phases}) == 1 and all(entry["uid"] == 0 for entry in phases)
        record["child_phases"] = phases

    try:
        current = stage("fixture-before-boot")
        module = load_fixture(root, output / "before-boot")
        fixture = start_fixture(module, current)
        current.update(exercise(fixture), status="PASS")
        original_pid = fixture.helper.pid
        current = stage("fresh-simulator-boot")
        runtimes = json.loads(output_command(["xcrun", "simctl", "list", "runtimes", "-j"], "runtimes"))["runtimes"]
        runtime = next(value for value in runtimes if value.get("isAvailable") and
                       value["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27"))
        types = json.loads(output_command(["xcrun", "simctl", "list", "devicetypes", "-j"], "device-types"))["devicetypes"]
        device = next(value for value in types if value["name"] == "iPhone 16")
        identifier = str(uuid.UUID(output_command(["xcrun", "simctl", "create", "UDP Echo Fixture Order",
                                                   device["identifier"], runtime["identifier"]], "create")))
        result["simulator"] = {"udid": identifier, "runtime": runtime, "device": device}
        command(["xcrun", "simctl", "boot", identifier], "boot", 120)
        command(["xcrun", "simctl", "bootstatus", identifier, "-b"], "ready", 120)
        current["status"] = "PASS"
        current = stage("held-fixture-after-boot")
        assert fixture.helper.pid == original_pid
        current.update(exercise(fixture), status="PASS")
        previous, fixture = fixture, None
        finish_fixture(previous, current, module.OUT)
        current = stage("new-fixture-after-boot")
        module = load_fixture(root, output / "after-boot")
        fixture = start_fixture(module, current)
        current.update(exercise(fixture), status="PASS")
        previous, fixture = fixture, None
        finish_fixture(previous, current, module.OUT)
    except Exception as error:
        failure = error
        if result["stages"]:
            result["stages"][-1]["status"] = "FAIL"
        result["primary_error"] = repr(error)
        result["primary_traceback"] = traceback.format_exc()
    finally:
        if fixture is not None:
            try:
                fixture.close()
            except Exception as error:
                result["cleanup_errors"].append({"operation": "fixture.close", "error": repr(error)})
        if identifier is not None:
            for action in ("shutdown", "delete"):
                try:
                    command(["xcrun", "simctl", action, identifier], "cleanup-" + action, 30)
                except Exception as error:
                    result["cleanup_errors"].append({"operation": "simulator-" + action, "error": repr(error)})
        try:
            assert identity(root) == before
            result["source_unchanged_after"] = True
        except Exception as error:
            result["source_unchanged_after"] = False
            result["cleanup_errors"].append({"operation": "source-identity", "error": repr(error)})
        result["status"] = "FAIL" if failure is not None or result["cleanup_errors"] else "PASS"
        result["elapsed_seconds"] = time.monotonic() - started
        result["deadlines_seconds"] = {"fixture_ready": 6, "fixture_cleanup": 5, "boot": 120, "bootstatus": 120,
                                        "simulator_cleanup_each": 30, "observer_snapshot_total": 1}
        try:
            save(output / "receipt.json", result)
            save(output / "progress.json", result)
        except Exception as error:
            print("Receipt write failed: " + repr(error), file=sys.stderr)
            if failure is None:
                raise
    if failure is not None:
        raise failure
    if result["cleanup_errors"]:
        raise RuntimeError("Diagnostic cleanup failed: " + repr(result["cleanup_errors"]))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
