#!/usr/bin/env python3
"""Production Swift client/service -> patched Hev -> actual UDP port 7."""
import argparse
import hashlib
import ipaddress
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

if not __debug__:
    raise SystemExit("Assertions must be enabled.")

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def response(process, timeout=6):
    assert select.select([process.stdout], [], [], timeout)[0], "child did not report within deadline"
    line = process.stdout.readline()
    assert line, ("child exited", process.poll())
    return json.loads(line)


def command(process, value):
    process.stdin.write(value + "\n")
    process.stdin.flush()
    return response(process)


def endpoint(info):
    parsed = ipaddress.ip_address(info["address"])
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        parsed = parsed.ipv4_mapped
    if parsed.is_unspecified:
        return "::1" if parsed.version == 6 else "127.0.0.1"
    return str(parsed)


class Echo:
    def __init__(self, replies, elevate=True):
        self.replies = replies
        self.helper = None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.received = {4: [], 6: []}
        self.sockets = []
        try:
            for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
                channel = socket.socket(family, socket.SOCK_DGRAM)
                self.sockets.append(channel)
                if family == socket.AF_INET6:
                    channel.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                channel.bind((host, 7))
        except PermissionError:
            for channel in self.sockets:
                channel.close()
            if not elevate or not shutil.which("sudo"):
                raise
            # Only the UDP7 test responder is privileged. Product server/client
            # subprocesses retain the ordinary runner's identity.
            self.helper = subprocess.Popen(
                ["sudo", "-n", sys.executable, str(Path(__file__).resolve()),
                 "--echo-helper", str(int(replies))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
            assert response(self.helper)["ready"]
            return
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            ready, _, _ = select.select(self.sockets, [], [], 0.02)
            for channel in ready:
                payload, sender = channel.recvfrom(65_535)
                with self.lock:
                    self.received[4 if channel.family == socket.AF_INET else 6].append(
                        (payload.hex(), sender[0], sender[1], time.monotonic()))
                if self.replies:
                    channel.sendto(payload, sender)

    def snapshot(self):
        if self.helper is not None:
            return {int(family): values for family, values in command(self.helper, "snapshot").items()}
        with self.lock:
            return {family: list(values) for family, values in self.received.items()}

    def finish(self):
        if self.helper is not None:
            finish_process(self.helper)
            return
        self.stop.set()
        self.thread.join(3)
        assert not self.thread.is_alive()
        for channel in self.sockets:
            channel.close()


def server_config(path, host, udp_host, workers, auth, fixed_port=0):
    value = (f"main:\n  workers: {workers}\n  port: {fixed_port}\n  udp-port: 0\n"
             f"  listen-address: '{host}'\n  udp-listen-address: '{udp_host}'\n"
             f"  listen-ipv6-only: {'true' if host == '::1' else 'false'}\n"
             "  bind-address-v4: '127.0.0.1'\n  bind-address-v6: '::1'\n"
             "misc:\n  log-file: null\n")
    if auth:
        value += "auth:\n  username: test-user\n  password: test-password\n"
    path.write_text(value)


def launch_server(executable, config, log, record=None):
    process = subprocess.Popen([str(executable), str(config)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
    try:
        info = response(process)
        if record is not None:
            record(stage="listener-reported", listener=info,
                   server_pid=process.pid, server_poll=process.poll())
        assert info["state"] == "ready" and info["port"] != 0
    except BaseException as error:
        if record is not None:
            record(stage="listener-failed", server_poll=process.poll(), error=repr(error))
        process.kill()
        process.wait()
        if record is not None:
            record(server_final_poll=process.returncode)
        raise
    return process, info


def stop_server(process):
    assert command(process, "stop")["state"] == "stopped"


def finish_process(process):
    if process.poll() is None:
        process.stdin.close()
        try:
            result = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        assert result == 0, result


def compile_probes(options):
    libraries = [options.native / path for path in (
        "bin/libhev-socks5-server.a",
        "third-part/hev-task-system/bin/libhev-task-system.a",
        "third-part/yaml/bin/libyaml.a")]
    commands = []
    if not all(path.is_file() for path in libraries):
        build = ["make", "-C", str(options.native), "-j", str(min(4, os.cpu_count() or 1)),
                 "CC=" + options.cc, "static"]
        commands.append(build)
        with (options.output / "native-build.log").open("w") as log:
            subprocess.run(build, stdout=log, stderr=subprocess.STDOUT, check=True)
    source = ROOT / "Socks5/BackgroundKeepAlive"
    common = [options.swiftc, "-swift-version", "6", "-warnings-as-errors", "-O",
              "-module-cache-path", str(options.output / "module-cache")]
    transport = options.output / "transport"
    scheduler = options.output / "scheduler"
    interactive = options.output / "interactive"
    production = [str(source / name) for name in (
        "Socks5UDPClient.swift", "PeriodicUDPEchoStore.swift", "PeriodicUDPEchoService.swift")]
    commands += [common + production[:1] + [str(HERE / "UDPEchoTransportProbe.swift"),
                                            "-o", str(transport)],
                 common + production + [str(HERE / "UDPEchoSchedulerProbe.swift"),
                                        "-o", str(scheduler)],
                 common + production + [str(HERE / "UDPEchoNativeProbe.swift"),
                                        "-o", str(interactive)]]
    native = options.output / "server"
    commands.append([options.cc, "-Wall", "-Wextra", "-Werror", "-pthread",
                     "-I" + str(options.native / "src"), str(HERE / "UDPEchoNativeServer.c"),
                     *map(str, libraries), "-o", str(native)])
    (options.output / "compile-commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    for command_line in commands[-4:]:
        subprocess.run(command_line, check=True)
    return transport, scheduler, interactive, native


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--swiftc", default=shutil.which("swiftc"))
    parser.add_argument("--cc", default=shutil.which("cc"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/udp-echo-native")
    options = parser.parse_args()
    assert options.swiftc and options.cc
    options.output.mkdir(parents=True, exist_ok=True)
    transport, scheduler, interactive, native = compile_probes(options)
    results = []
    cases = [
        ("127.0.0.1", "127.0.0.1", 1, False, "127.0.0.1", True),
        ("127.0.0.1", "127.0.0.1", 1, True, "127.0.0.1", True),
        ("::1", "::1", 1, False, "::1", True),
        ("::1", "::1", 1, True, "::1", True),
        ("::", "::", 2, False, "127.0.0.1", True),
        ("::", "::", 2, True, "::1", True),
        ("0.0.0.0", "::", 2, False, "::1", True),
        ("127.0.0.1", "127.0.0.1", 1, False, "127.0.0.1", False),
    ]
    for index, (host, udp_host, workers, auth, target, replies) in enumerate(cases):
        config = options.output / f"transport-{index}.yml"
        server_config(config, host, udp_host, workers, auth)
        diagnostic = {"case": index, "config": config.read_text(), "target": target,
                      "replies": replies, "listener": None, "endpoint": None,
                      "server_poll": None, "client": None, "received": None}
        diagnostic_path = options.output / f"transport-{index}-diagnostic.json"

        def record(**values):
            diagnostic.update(values)
            diagnostic_path.write_text(json.dumps(diagnostic, indent=2) + "\n")

        record(stage="configured")
        echo = Echo(replies)
        server = None
        try:
            with (options.output / f"transport-{index}-server.log").open("w") as log:
                server, info = launch_server(native, config, log, record)
                mode = "auth" if auth else ("echo" if replies else "silence")
                address = endpoint(info)
                record(stage="client-starting", endpoint={"host": address, "port": info["port"]},
                       server_poll=server.poll())
                run = subprocess.run([str(transport), mode, address, str(info["port"]), target],
                                     text=True, capture_output=True, timeout=6)
                record(stage="client-returned", server_poll=server.poll(),
                       client={"returncode": run.returncode, "stdout": run.stdout, "stderr": run.stderr})
                assert run.returncode == 0, run.stderr
                data = json.loads(run.stdout)
                received = echo.snapshot()
                record(stage="checking-packets", probe=data, received=received, server_poll=server.poll())
                packets = received[ipaddress.ip_address(target).version]
                assert len(packets) == data["accepted"] == 5, (index, data, received)
                assert all(packet[0] == "00" for packet in packets)
                assert data["events"] == ["ready"], (index, data)
                assert (data["udpReadBytes"] > 0) == replies, (index, data)
                rejected = None
                if auth:
                    before = echo.snapshot()
                    denied = subprocess.run(
                        [str(transport), "wrong-auth", endpoint(info), str(info["port"]), target],
                        text=True, capture_output=True, timeout=6)
                    assert denied.returncode == 0, denied.stderr
                    rejected = json.loads(denied.stdout)
                    assert rejected["accepted"] == rejected["datagramWrites"] == 0
                    assert len(rejected["events"]) == 1 and rejected["events"][0].startswith("failed:")
                    assert echo.snapshot() == before
                stop_server(server)
                results.append({"kind": "transport", "case": index, "listener": info,
                                "auth": auth, "target": target, "replies": replies,
                                "probe": data, "rejected": rejected, "received": received})
                record(stage="passed", server_poll=server.poll())
        except BaseException as error:
            failure = {"error": repr(error)}
            if server is not None:
                failure["server_poll"] = server.poll()
            if isinstance(error, subprocess.TimeoutExpired):
                failure["timeout_output"] = {
                    name: value.decode(errors="replace") if isinstance(value, bytes) else value
                    for name, value in (("stdout", error.stdout), ("stderr", error.stderr))}
            record(**failure)
            raise
        finally:
            try:
                try:
                    if server is not None:
                        finish_process(server)
                finally:
                    echo.finish()
            except BaseException as error:
                record(cleanup_error=repr(error))
                raise
            finally:
                if server is not None:
                    record(server_final_poll=server.poll())
        print("PASS: native transport", index, host, target, "echo", replies, flush=True)

    for index, (host, workers, auth, replies) in enumerate([
        ("127.0.0.1", 1, False, True),
        ("::", 4, True, True),
        ("127.0.0.1", 2, False, False),
    ]):
        config = options.output / f"mixed-{index}.yml"
        server_config(config, host, "::", workers, auth)
        echo = Echo(replies)
        server = None
        try:
            with (options.output / f"mixed-{index}-server.log").open("w") as log:
                server, info = launch_server(native, config, log)
                mode = "auth" if auth else ("echo" if replies else "silence")
                run = subprocess.run([str(scheduler), mode, endpoint(info), str(info["port"]),
                                      "127.0.0.1,::1"], text=True, capture_output=True, timeout=6)
                assert run.returncode == 0, run.stderr
                data = json.loads(run.stdout)
                received = echo.snapshot()
                assert all(len(packets) >= 5 for packets in received.values()), (data, received)
                assert all(packet[0] == "00" for packets in received.values() for packet in packets)
                assert sum(map(len, received.values())) == data["writes"], (data, received)
                assert (data["readBytes"] > 0) == replies
                stop_server(server)
                results.append({"kind": "mixed", "case": index, "listener": info,
                                "probe": data, "received": received})
        finally:
            if server is not None:
                finish_process(server)
            echo.finish()
        print("PASS: native mixed families", index, "echo", replies, flush=True)

    config = options.output / "restart.yml"
    server_config(config, "127.0.0.1", "::", 2, True)
    echo = Echo(True)
    server = probe = None
    try:
        with (options.output / "restart-server.log").open("w") as log:
            server, info = launch_server(native, config, log)
            probe = subprocess.Popen([str(interactive), "auth", "127.0.0.1,::1"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1)
            command(probe, f"server {endpoint(info)} {info['port']}")
            time.sleep(0.3)
            initial = echo.snapshot()
            assert all(len(values) >= 5 for values in initial.values())
            # Lose TCP control without a new app profile. Rebind the same TCP
            # endpoint and require ordinary transport retry to recover.
            server_config(config, "127.0.0.1", "::", 2, True, fixed_port=info["port"])
            stop_server(server)
            time.sleep(0.08)
            interrupted = echo.snapshot()
            time.sleep(0.15)
            assert echo.snapshot() == interrupted
            recovered_info = command(server, "start")
            assert recovered_info["port"] == info["port"]
            time.sleep(1.3)
            recovered = echo.snapshot()
            assert all(len(recovered[family]) >= len(interrupted[family]) + 5 for family in recovered)
            # An explicit app Stop clears the profile. A later server run uses
            # its newly discovered ephemeral endpoint and a new run identity.
            command(probe, "absent")
            stop_server(server)
            time.sleep(0.08)
            stopped = echo.snapshot()
            time.sleep(0.15)
            assert echo.snapshot() == stopped
            server_config(config, "127.0.0.1", "::", 2, True)
            info = command(server, "start")
            command(probe, f"server {endpoint(info)} {info['port']}")
            time.sleep(0.3)
            resumed = echo.snapshot()
            assert all(len(resumed[family]) >= len(stopped[family]) + 5 for family in resumed)
            command(probe, "off")
            time.sleep(0.05)
            off = command(probe, "snapshot")
            packets = echo.snapshot()
            time.sleep(0.15)
            assert command(probe, "snapshot")["writes"] == off["writes"]
            assert echo.snapshot() == packets
            assert "Sending UDP Echo" in off["states"] and "Off" in off["states"]
            stop_server(server)
            results.append({"kind": "restart", "initial": initial, "stopped": stopped,
                            "interrupted": interrupted, "recovered": recovered,
                            "resumed": resumed, "probe": off})
    finally:
        if probe is not None:
            finish_process(probe)
        if server is not None:
            finish_process(server)
        echo.finish()
    print("PASS: native Stop/restart, changed ephemeral endpoint, mixed families, final Off", flush=True)
    (options.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    paths = [ROOT / "Socks5/BackgroundKeepAlive" / name for name in (
        "Socks5UDPClient.swift", "PeriodicUDPEchoService.swift", "PeriodicUDPEchoStore.swift")]
    paths += [options.native / "src/core/src/hev-socks5-udp.c", options.native / "src/hev-main.c",
              options.native / "src/hev-socks5-proxy.c", options.native / "bin/libhev-socks5-server.a"]
    paths += [HERE / name for name in ("check_udp_echo_native.py", "UDPEchoNativeServer.c",
                                       "UDPEchoNativeProbe.swift", "UDPEchoTransportProbe.swift",
                                       "UDPEchoSchedulerProbe.swift")]
    (options.output / "source-identities.json").write_text(json.dumps(
        {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}, indent=2) + "\n")
    print(f"PASS: {len(results)} actual native end-to-end cases")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--echo-helper":
        echo = Echo(sys.argv[2] == "1", elevate=False)
        try:
            print(json.dumps({"ready": True}), flush=True)
            for line in sys.stdin:
                assert line == "snapshot\n"
                print(json.dumps(echo.snapshot()), flush=True)
        finally:
            echo.finish()
    else:
        main()
