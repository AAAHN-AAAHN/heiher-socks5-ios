#!/usr/bin/env python3
"""Exercise production SOCKS5 transport against independent real TCP/UDP peers."""
import argparse
import json
import os
from pathlib import Path
import platform
import select
import shutil
import socket
import struct
import subprocess
import threading
import time

if not __debug__:
    raise SystemExit("Assertions must be enabled.")

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def exact(connection, count):
    result = bytearray()
    while len(result) < count:
        data = connection.recv(count - len(result))
        if not data:
            raise EOFError("control connection closed")
        result += data
    return bytes(result)


def address(connection, kind):
    if kind == 1:
        return socket.inet_ntop(socket.AF_INET, exact(connection, 4))
    if kind == 4:
        return socket.inet_ntop(socket.AF_INET6, exact(connection, 16))
    raise AssertionError(("unexpected address type", kind))


class Fixture:
    def __init__(self, mode, family, target):
        self.mode, self.family, self.target = mode, family, target
        self.host = "127.0.0.1" if family == socket.AF_INET else "::1"
        self.listener = socket.socket(family, socket.SOCK_STREAM)
        self.relay = socket.socket(family, socket.SOCK_DGRAM)
        self.listener.bind((self.host, 0))
        self.listener.listen()
        self.listener.settimeout(0.8)
        self.relay.bind((self.host, 0))
        while self.relay.getsockname()[1] == self.listener.getsockname()[1]:
            self.relay.close()
            self.relay = socket.socket(family, socket.SOCK_DGRAM)
            self.relay.bind((self.host, 0))
        self.stop = threading.Event()
        self.datagrams, self.error = [], None
        self.advertised = None
        self.tcp_written = 0
        self.tcp_read = 0
        self.reply_bytes = 0
        self.post_off_byte = None
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def send_control(self, connection, value):
        # Every response is fragmented independently of client implementation.
        for byte in value:
            connection.sendall(bytes([byte]))
            self.tcp_written += 1
            time.sleep(0.001)

    def run(self):
        try:
            connection, peer = self.listener.accept()
            connection.settimeout(2)
            with connection:
                greeting = exact(connection, 3)
                self.tcp_read += 3
                assert greeting[:2] == b"\x05\x01"
                if self.mode == "setup-timeout":
                    self.stop.wait(0.8)
                    return
                if self.mode == "off-during-greeting":
                    try:
                        self.send_control(connection, b"\x05\x00")
                        self.post_off_byte = connection.recv(1).hex()
                        assert self.post_off_byte == "", ("OFF_GREETING_NEXT_BYTE", self.post_off_byte)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                method = greeting[2]
                if self.mode == "reject-method":
                    self.send_control(connection, b"\x05\xff")
                    return
                self.send_control(connection, bytes([5, method]))
                if method == 2:
                    header = exact(connection, 2)
                    username = exact(connection, header[1])
                    length = exact(connection, 1)[0]
                    password = exact(connection, length)
                    self.tcp_read += 3 + len(username) + len(password)
                    assert header[0] == 1
                    assert username == (b"u" * 255 if self.mode == "auth-long" else b"test-user")
                    assert password == (b"p" * 255 if self.mode == "auth-long" else b"test-password")
                    self.send_control(connection, bytes([1, int(self.mode == "reject-auth")]))
                    if self.mode == "reject-auth":
                        return
                header = exact(connection, 4)
                assert header[:3] == b"\x05\x03\x00", header
                source = address(connection, header[3])
                source_port = struct.unpack("!H", exact(connection, 2))[0]
                self.tcp_read += 10 if header[3] == 1 else 22
                assert source == peer[0] and source_port != 0
                self.advertised = (source, source_port)
                relay_port = self.relay.getsockname()[1]
                kind = 1 if self.family == socket.AF_INET else 4
                relay_host = self.host
                if self.mode.startswith("wildcard"):
                    kind = 4 if self.mode == "wildcard6" else 1
                    relay_host = "::" if kind == 4 else "0.0.0.0"
                if self.mode == "domain":
                    encoded = b"\x03\x09localhost"
                else:
                    encoded = bytes([kind]) + socket.inet_pton(
                        socket.AF_INET if kind == 1 else socket.AF_INET6, relay_host)
                response = b"\x05\x00\x00" + encoded + struct.pack("!H", relay_port)
                if self.mode == "bad-version":
                    response = b"\x04" + response[1:]
                elif self.mode == "bad-rsv":
                    response = response[:2] + b"\x01" + response[3:]
                elif self.mode == "bad-type":
                    response = response[:3] + b"\x02"
                elif self.mode == "zero-relay":
                    response = response[:-2] + b"\x00\x00"
                if self.mode.startswith("bad-"):
                    try:
                        self.send_control(connection, response)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                self.send_control(connection, response)
                if self.mode == "zero-relay":
                    return
                if self.mode == "control-data":
                    connection.sendall(b"invalid")
                    self.tcp_written += 7
                while not self.stop.is_set():
                    ready, _, _ = select.select([self.relay, connection], [], [], 0.1)
                    if connection in ready and connection.recv(1) == b"":
                        return
                    if self.relay not in ready:
                        continue
                    packet, sender = self.relay.recvfrom(65_535)
                    assert sender[:2] == self.advertised
                    target_family = socket.AF_INET if packet[3] == 1 else socket.AF_INET6
                    length = 4 if target_family == socket.AF_INET else 16
                    target = socket.inet_ntop(target_family, packet[4:4 + length])
                    assert packet[:3] == b"\x00\x00\x00"
                    assert target == self.target
                    assert packet[4 + length:] == b"\x00\x07\x00"
                    self.datagrams.append(packet)
                    if self.mode == "silence":
                        continue
                    replies = [packet]
                    if self.mode == "burst":
                        replies = [b"", b"\x00", b"\x00\x00\x01\x01"] * 80 + [packet]
                    if self.mode == "foreign":
                        with socket.socket(self.family, socket.SOCK_DGRAM) as stranger:
                            stranger.sendto(b"foreign-data-must-not-count", sender)
                    for reply in replies:
                        self.relay.sendto(reply, sender)
                        self.reply_bytes += len(reply)
                    if self.mode == "control-close":
                        return
        except socket.timeout:
            if self.mode != "off-before-start":
                self.error = "fixture timeout"
        except ConnectionResetError as error:
            if self.mode != "control-data":
                self.error = repr(error)
        except Exception as error:
            self.error = repr(error)
        finally:
            self.listener.close()
            self.relay.close()

    def finish(self):
        self.stop.set()
        self.thread.join(3)
        assert not self.thread.is_alive(), "fixture leaked its thread"
        assert self.error is None, self.error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--swiftc", default=shutil.which("swiftc"))
    parser.add_argument("--clang", default=shutil.which("clang"))
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "udp-echo-transport")
    options = parser.parse_args()
    assert options.swiftc, "swiftc is required"
    options.output.mkdir(parents=True, exist_ok=True)
    executable = options.output / "transport-probe"
    command = [options.swiftc, "-swift-version", "6", "-warnings-as-errors", "-O",
               "-module-cache-path", str(options.output / "module-cache"),
               str(ROOT / "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift"),
               str(HERE / "UDPEchoTransportProbe.swift"), "-o", str(executable)]
    subprocess.run(command, check=True)
    subprocess.run([str(executable), "addresses"], check=True)
    cases = [(mode, socket.AF_INET, "127.0.0.1") for mode in (
        "echo", "silence", "auth", "auth-long", "reject-method", "reject-auth",
        "bad-version", "bad-rsv", "bad-type", "zero-relay", "setup-timeout",
        "off-before-start", "off-during-greeting", "off-before-send",
        "domain", "wildcard4", "wildcard6", "burst", "foreign", "control-close", "control-data")]
    cases += [("echo", socket.AF_INET6, "::1"), ("domain", socket.AF_INET6, "::1"),
              ("echo", socket.AF_INET, "::1"), ("echo", socket.AF_INET6, "127.0.0.1")]
    fault_library = options.output / "socket-faults.so"
    if platform.system() == "Linux":
        assert options.clang, "clang is required for real socket fault boundaries"
        subprocess.run([options.clang, "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared",
                        str(HERE / "UDPEchoTransportIO.c"), "-ldl", "-o", str(fault_library)], check=True)
        cases += [("io-faults", socket.AF_INET, "127.0.0.1"),
                  ("io-drop", socket.AF_INET, "127.0.0.1")]
    if options.case:
        cases = [case for case in cases if case[0] in options.case]
        assert cases, "no matching cases"
    results = []
    for mode, family, target in cases:
        fixture_mode = "auth-long" if mode.startswith("io-") else mode
        fixture = Fixture(fixture_mode, family, target)
        environment = os.environ.copy()
        if mode.startswith("io-"):
            environment["LD_PRELOAD"] = str(fault_library.resolve())
            environment["UDP_ECHO_IO_FAULTS"] = "1"
            if mode == "io-drop":
                environment["UDP_ECHO_DROP_ONCE"] = "1"
        result = subprocess.run([str(executable), fixture_mode, fixture.host,
                                 str(fixture.listener.getsockname()[1]), target],
                                capture_output=True, text=True, timeout=6, env=environment)
        try:
            fixture.finish()
        finally:
            # Preserve final fixture state and process output even when its
            # bounded join or EOF assertion fails.
            (options.output / "last-case.json").write_text(json.dumps({
                "mode": mode, "family": family, "target": target,
                "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
                "fixture_error": fixture.error, "post_off_byte": fixture.post_off_byte,
                "fixture_thread_alive": fixture.thread.is_alive(),
            }, indent=2) + "\n")
        assert result.returncode == 0, (mode, result.stderr, result.stdout)
        data = json.loads(result.stdout)
        failed = [event for event in data["events"] if event.startswith("failed:")]
        negative = mode.startswith("bad-") or mode in {
            "reject-method", "reject-auth", "zero-relay", "setup-timeout",
            "control-close", "control-data"}
        assert bool(failed) == negative, (mode, data)
        off = mode.startswith("off-")
        if off:
            assert not fixture.datagrams and data["datagramWrites"] == 0, (mode, data)
            if mode == "off-during-greeting":
                assert data["greetingOffAcknowledged"] and data["writes"] == 3 and data["reads"] == 0, (mode, data)
        elif not negative:
            expected = 4 if mode == "io-drop" else 5
            assert len(fixture.datagrams) == expected and data["accepted"] == expected, (mode, data)
            assert data["datagramWrites"] == sum(map(len, fixture.datagrams)), (mode, data)
            assert data["udpReadBytes"] == fixture.reply_bytes, (mode, data, fixture.reply_bytes)
            assert data["writes"] == fixture.tcp_read + data["datagramWrites"], (mode, data)
            assert data["reads"] == fixture.tcp_written + data["udpReadBytes"], (mode, data)
            assert data["dropped"] == int(mode == "io-drop"), (mode, data)
        results.append({"mode": mode, "family": family, "target": target, **data})
        (options.output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
        print("PASS:", mode, fixture.host, target, "sent", data["accepted"], flush=True)
    (options.output / "compile-command.json").write_text(json.dumps(command, indent=2) + "\n")
    print(f"PASS: {len(results)} production TCP/UDP cases")


if __name__ == "__main__":
    main()
