"""Exercise real Hev UDP relays; loopback only, no external endpoints."""
import argparse
import json
import pathlib
import platform
import select
import socket
import struct
import subprocess
import threading
import time


def exact(sock, length):
    result = b""
    while len(result) < length:
        part = sock.recv(length - len(result))
        if not part:
            raise EOFError("Control connection closed")
        result += part
    return result


def addr_bytes(host, port):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    return bytes([4 if family == socket.AF_INET6 else 1]) + socket.inet_pton(family, host) + struct.pack("!H", port)


def parse_addr(data, offset=0):
    atyp = data[offset]
    if atyp == 1:
        length, family = 4, socket.AF_INET
    elif atyp == 4:
        length, family = 16, socket.AF_INET6
    else:
        raise ValueError("Unexpected address type: %s" % atyp)
    host = socket.inet_ntop(family, data[offset + 1:offset + 1 + length])
    end = offset + 1 + length
    port = struct.unpack("!H", data[end:end + 2])[0]
    return host, port, end + 2


class Echo:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.1)
        self.address = self.sock.getsockname()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
                self.sock.sendto(data, addr)
            except socket.timeout:
                continue
            except OSError:
                return

    def close(self):
        self.stop.set()
        self.thread.join(1)
        self.sock.close()


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Association:
    def __init__(self, port, request_host, known):
        self.tcp = socket.create_connection(("127.0.0.1", port), 2)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.tcp.sendall(b"\x05\x01\x00")
        if exact(self.tcp, 2) != b"\x05\x00":
            raise ValueError("Authentication rejected")
        client_port = self.udp.getsockname()[1] if known else 0
        self.tcp.sendall(b"\x05\x03\x00" + addr_bytes(request_host, client_port))
        head = exact(self.tcp, 4)
        length = 4 if head[3] == 1 else 16
        address = exact(self.tcp, length + 2)
        self.reply = head[1]
        self.relay_host, self.relay_port, _ = parse_addr(head[3:] + address)
        self.wildcard = self.relay_host in ("::", "0.0.0.0")
        # A wildcard is usable here ONLY because the test runs on the same host.
        host = "127.0.0.1" if self.wildcard else self.relay_host
        if host.startswith("::ffff:"):
            host = host[7:]
        self.udp.setblocking(False)
        self.target = (host, self.relay_port)

    def close(self):
        self.tcp.close()
        self.udp.close()


def exchange(associations, echo, size, round_no):
    expected = {}
    result = {}
    for index, item in enumerate(associations):
        if item.reply:
            continue
        key = ("%02d-%02d:" % (index, round_no)).encode()
        payload = (key + bytes([65 + index]) * size)[:size]
        expected[item.udp] = (index, payload)
        try:
            item.udp.sendto(b"\0\0\0" + addr_bytes(*echo.address) + payload, item.target)
        except OSError as exc:
            result[index] = {"error": str(exc)}
    until = time.monotonic() + 0.4
    while time.monotonic() < until and len(result) < len(expected):
        ready, _, _ = select.select(list(expected), [], [], max(0, until - time.monotonic()))
        for sock in ready:
            index, payload = expected[sock]
            try:
                data, sender = sock.recvfrom(65535)
                remote, port, offset = parse_addr(data, 3)
                body = data[offset:]
                result[index] = {"exact": body == payload, "length": len(body), "source": [remote, port]}
            except (OSError, ValueError, IndexError, struct.error) as exc:
                result[index] = {"error": str(exc)}
    return {str(i): result.get(i, {"timeout": True}) for i, a in enumerate(associations) if a.reply == 0}


def run_case(binary, label, out, echo, number, known=False, count=1, fixed=False, udp_addr=None, request="0.0.0.0", sizes=(64,), close_test=False):
    name = "%s-%02d" % (label, number)
    port = free_port(socket.SOCK_STREAM)
    relay = free_port(socket.SOCK_DGRAM) if fixed else 0
    config = ["main:", "  workers: 4", "  port: %d" % port, "  listen-address: '::'", "  udp-port: %d" % relay,
              "  bind-address-v4: '0.0.0.0'", "  bind-address-v6: '::'", "  listen-ipv6-only: false"]
    if udp_addr is not None:
        config.append("  udp-listen-address: '%s'" % udp_addr)
    config += ["misc:", "  log-level: debug", "  log-file: stderr", "  udp-read-write-timeout: 5000"]
    cfg = out / (name + ".yml")
    cfg.write_text("\n".join(config) + "\n")
    record = {"case": name, "known_port": known, "count": count, "fixed_relay_port": fixed,
              "udp_address": udp_addr, "request_address": request, "exchanges": []}
    associations = []
    with (out / (name + ".log")).open("w") as log:
        process = subprocess.Popen([str(binary), str(cfg)], stdout=log, stderr=log)
        try:
            for attempt in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", port), 0.1):
                        break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError("Server exited with %s" % process.returncode)
                    time.sleep(0.02)
            else:
                raise TimeoutError("Server not ready")
            for _ in range(count):
                associations.append(Association(port, request, known))
            record["replies"] = [{"code": a.reply, "relay": [a.relay_host, a.relay_port], "wildcard": a.wildcard} for a in associations]
            for round_no, size in enumerate(sizes):
                record["exchanges"].append({"size": size, "results": exchange(associations, echo, size, round_no)})
            if close_test and associations and all(a.reply == 0 for a in associations):
                associations[0].tcp.close()
                time.sleep(0.15)
                record["after_control_zero_closed"] = []
                for round_no in range(3):
                    record["after_control_zero_closed"].append(exchange(associations, echo, 64, round_no + 40))
        except Exception as exc:
            record["exception"] = repr(exc)
        finally:
            for a in associations:
                a.close()
            process.terminate()
            try:
                process.wait(2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    parser.add_argument("label")
    parser.add_argument("output")
    args = parser.parse_args()
    binary = pathlib.Path(args.binary).resolve()
    out = pathlib.Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = [
        {},
        {"known": True},
        {"request": "::"},
        {"request": "::1"},
        {"fixed": True},
        {"udp_addr": "::"},
        {"udp_addr": "0.0.0.0"},
        {"count": 4, "sizes": (64, 64, 64), "close_test": True},
        {"count": 4, "fixed": True, "sizes": (64, 64, 64), "close_test": True},
        {"count": 8, "fixed": True, "sizes": (64, 64, 64), "close_test": True},
        {"count": 8, "fixed": True, "known": True, "sizes": (64, 64, 64), "close_test": True},
        {"sizes": (8, 64, 512, 1200, 1392, 1400, 1450, 1490, 1491, 1500, 2048)},
    ]
    echo = Echo()
    records = []
    try:
        for index, case in enumerate(cases, 1):
            result = run_case(binary, args.label, out, echo, index, **case)
            records.append(result)
            print(json.dumps(result), flush=True)
    finally:
        echo.close()
    (out / (args.label + "-results.json")).write_text(json.dumps({"platform": platform.platform(), "results": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
