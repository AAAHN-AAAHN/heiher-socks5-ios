#!/usr/bin/env python3
"""Focused startup-failure and real UDP7 controls; no app or Simulator build."""
import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import traceback
import types

if not __debug__:
    raise SystemExit("Assertions must be enabled")


def load_ui(root, source, name, output):
    module = types.ModuleType(name)
    module.__file__ = str(root / "Build/ui_review.py")
    sys.path.insert(0, str(root / "Build"))
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)
    finally:
        sys.path.pop(0)
    module.OUT = output
    output.mkdir(parents=True, exist_ok=True)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--actual", action="store_true")
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = root / "Build/ui_review.py"
    current = source.read_bytes()
    original = subprocess.check_output(["git", "-C", str(root), "show",
        "eb8ac9a0aac2c092faae462b256fb1cc01ec6426:Build/ui_review.py"])
    assert hashlib.sha256(original).hexdigest() == "31003620b9c34eab0e3b9e5464891c737d51a7a17e6d111c3d0c4249b61fd6be"
    before = ast.parse(original)
    after = ast.parse(current)
    assertions = lambda tree: Counter(ast.dump(x, include_attributes=False)
                                      for x in ast.walk(tree) if isinstance(x, ast.Assert))
    assert assertions(before) == assertions(after)
    old_main = next(x for x in before.body if isinstance(x, ast.FunctionDef) and x.name == "main")
    new_main = next(x for x in after.body if isinstance(x, ast.FunctionDef) and x.name == "main")
    # The only main-body delta clears this attempt's two new diagnostic files.
    for node in ast.walk(new_main):
        if isinstance(node, ast.Tuple):
            node.elts = [x for x in node.elts if not (isinstance(x, ast.Constant) and
                         x.value in ("udp-echo-helper.json", "udp-echo-helper.log"))]
    assert ast.dump(old_main, include_attributes=False) == ast.dump(new_main, include_attributes=False)
    records = []

    def masking(label, code, launch_failure=False):
        folder = output / label
        module = load_ui(root, code, label, folder)
        ready_error = AssertionError("child did not report within deadline")
        launch_error = OSError("controlled Popen failure before child exists")
        cleanup_error = subprocess.TimeoutExpired(["owned-helper"], 5)
        process = types.SimpleNamespace(pid=424242, returncode=None)
        process.poll = lambda: process.returncode
        calls = []

        def deny(*args, **kwargs):
            raise PermissionError("controlled unprivileged UDP7 bind")

        def spawn(argv, **kwargs):
            calls.append({"kind": "spawn", "argv": argv,
                          "stderr_file": getattr(kwargs.get("stderr"), "name", None)})
            if launch_failure:
                raise launch_error
            return process

        def response(_):
            calls.append({"kind": "response", "timeout_seconds": 6})
            raise ready_error

        def finish(_):
            calls.append({"kind": "cleanup", "timeout_seconds": 5})
            process.returncode = -9
            raise cleanup_error

        module.echo_module = lambda: types.SimpleNamespace(Echo=deny, response=response, finish_process=finish)
        module.subprocess = types.SimpleNamespace(Popen=spawn, PIPE=subprocess.PIPE)
        caught = None
        try:
            module.UDPEchoFixture()
        except Exception as error:
            caught = error
        record = {"label": label, "caught": repr(caught), "calls": calls,
                  "primary_ready_preserved": caught is ready_error,
                  "launch_error_preserved": caught is launch_error,
                  "cleanup_masked_primary": caught is cleanup_error}
        if (folder / "udp-echo-helper.json").exists():
            record["helper_diagnostic"] = json.loads((folder / "udp-echo-helper.json").read_text())
        records.append(record)
        (output / "masking-results.json").write_text(json.dumps(records, indent=2) + "\n")
        return record

    old = masking("old-primary-masked", original)
    assert old["cleanup_masked_primary"] and not old["primary_ready_preserved"]
    fixed = masking("new-primary-preserved", current)
    assert fixed["primary_ready_preserved"] and not fixed["cleanup_masked_primary"]
    stages = fixed["helper_diagnostic"]["stages"]
    assert [x["stage"] for x in stages] == ["spawned", "startup-failed", "cleanup-started", "cleanup-failed"]
    assert "child did not report" in stages[1]["error"] and "TimeoutExpired" in stages[-1]["error"]
    assert stages[-1]["pid"] == 424242 and stages[-1]["poll"] == -9
    launch = masking("new-launch-failure-preserved", current, True)
    assert launch["launch_error_preserved"] and [x["kind"] for x in launch["calls"]] == ["spawn"]
    assert launch["helper_diagnostic"]["stages"][0]["pid"] is None
    actual = {"status": "NOT_RUN", "parent_uid": os.geteuid()}

    if options.actual:
        module = load_ui(root, current, "actual_fixture", output / "actual")
        fixture = None
        channels = []
        failure = None
        cleanup = None
        started = time.monotonic()
        try:
            fixture = module.UDPEchoFixture()
            actual.update({"status": "RUNNING", "helper_used": fixture.helper is not None,
                           "helper_pid": fixture.helper.pid if fixture.helper is not None else None})
            if sys.platform == "darwin":
                assert os.geteuid() != 0 and fixture.helper is not None, "Darwin must exercise privileged fallback from ordinary parent"

            def control(value):
                with socket.create_connection(fixture.control.server_address, timeout=5) as stream:
                    stream.settimeout(5)
                    stream.sendall(value.encode() + b"\n")
                    with stream.makefile("rb") as reader:
                        result = json.loads(reader.readline())
                assert "error" not in result and result["valid"], result
                return result

            for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
                channel = socket.socket(family, socket.SOCK_DGRAM)
                channel.bind((host, 0))
                channels.append((channel, host))
            actual["rounds"] = []
            for mode in ("reply", "drop", "reply"):
                changed = control(mode)
                assert changed["counts"] == {"4": 0, "6": 0}, changed
                for channel, host in channels:
                    channel.settimeout(1 if mode == "reply" else .2)
                    channel.sendto(b"\x00", (host, 7))
                    if mode == "reply":
                        packet, peer = channel.recvfrom(100)
                        assert packet == b"\x00" and peer[0] == host and peer[1] == 7
                    else:
                        try:
                            packet = channel.recvfrom(100)
                        except socket.timeout:
                            pass
                        else:
                            raise AssertionError(("unexpected reply in drop mode", packet))
                deadline = time.monotonic() + 3
                observed = control("snapshot")
                while observed["counts"] != {"4": 1, "6": 1} and time.monotonic() < deadline:
                    time.sleep(.02)
                    observed = control("snapshot")
                assert observed["counts"] == {"4": 1, "6": 1} and observed["valid"], observed
                actual["rounds"].append({"mode": mode, "observed": observed})
            actual["status"] = "PASS"
        except Exception as error:
            failure = error
            actual.update({"status": "FAIL", "error": repr(error), "traceback": traceback.format_exc()})
        finally:
            for channel, _ in channels:
                channel.close()
            if fixture is not None:
                try:
                    fixture.close()
                    actual["helper_final_poll"] = fixture.helper.poll() if fixture.helper is not None else None
                    if fixture.helper is not None:
                        assert actual["helper_final_poll"] == 0
                        phases = []
                        for line in (module.OUT / "udp-echo-helper.log").read_text().splitlines():
                            try:
                                value = json.loads(line)
                            except ValueError:
                                continue
                            if "udp_echo_helper_phase" in value:
                                phases.append(value)
                        assert [x["udp_echo_helper_phase"] for x in phases] == ["entry", "module-loaded", "udp7-ready", "stopping", "stopped"], phases
                        assert len({x["pid"] for x in phases}) == 1 and all(x["uid"] == 0 for x in phases), phases
                        actual["child_phases"] = phases
                except Exception as error:
                    cleanup = error
                    actual["status"] = "FAIL"
                    actual["cleanup_error"] = repr(error)
            actual["elapsed_seconds"] = time.monotonic() - started
            (output / "actual-result.json").write_text(json.dumps(actual, indent=2) + "\n")
        if failure is not None:
            raise failure
        if cleanup is not None:
            raise cleanup
    assert source.read_bytes() == current
    receipt = {"result": "PASS", "candidate": subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
        "old_source_sha256": hashlib.sha256(original).hexdigest(),
        "current_source_sha256": hashlib.sha256(current).hexdigest(),
        "all_original_assertions_preserved": True, "main_body_unchanged_except_diagnostic_file_reset": True,
        "readiness_timeout_seconds": 6, "helper_cleanup_timeout_seconds": 5,
        "simulator_cleanup_timeout_seconds": 30, "masking_controls": len(records),
        "actual_fixture": actual, "source_unchanged_after": True,
        "no_product_or_simulator_execution": True}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
