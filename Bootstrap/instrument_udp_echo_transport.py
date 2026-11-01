#!/usr/bin/env python3
"""Insert diagnostic stderr events into a fresh, exact three-file source copy.

This program never compiles or runs the project. The production UDP client is
read and pinned, then left unchanged. Only the test Probe and Python fixture
receive insertions; deleting the recorded byte spans must restore exact inputs.
"""
import argparse
import ast
import datetime
import difflib
import hashlib
import json
from pathlib import Path
import stat

CLIENT = "Socks5/BackgroundKeepAlive/Socks5UDPClient.swift"
PROBE = "Tests/Background/UDPEchoTransportProbe.swift"
FIXTURE = "Tests/Background/UDPEchoTransportTests.py"
PINS = {
    CLIENT: (32767, "57da93313e01f5c3938f0be3b112de58afeeaf0aab5013ca9a8c20278d377465"),
    PROBE: (7108, "f931e5c1ca829642739cece332d26ba7b043a13227fb804b586ebe6b6d3fa91a"),
    FIXTURE: (13674, "9983165ff22ec16b3fcea0ae661f64906939bb4dd006dabae92c7086d4c6f4e6"),
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(path):
    mode = path.lstat().st_mode
    require(stat.S_ISREG(mode), f"Not a regular file: {path}")
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": sha(data),
            "mode": f"{stat.S_IMODE(mode):04o}"}


class Insertions:
    def __init__(self, name, original):
        self.name, self.original, self.items = name, original, []

    def add(self, key, anchor, text, where="after"):
        needle = anchor.encode()
        require(self.original.count(needle) == 1, f"Anchor is not unique: {self.name}:{key}")
        require(where in ("before", "after"), "Unsupported insertion position")
        position = self.original.index(needle) + (len(needle) if where == "after" else 0)
        require(position == 0 or self.original[position - 1:position] == b"\n",
                f"Insertion is not at a line boundary: {key}")
        prefix = "//" if self.name.endswith(".swift") else "#"
        block = (f"{prefix} DIAGNOSTIC_INSERTION_BEGIN:{key}\n" +
                 text.rstrip("\n") + "\n" +
                 f"{prefix} DIAGNOSTIC_INSERTION_END:{key}\n").encode()
        require(key not in {item["key"] for item in self.items}, "Duplicate insertion key")
        self.items.append({"key": key, "original_byte_offset": position,
                           "anchor": anchor, "anchor_sha256": sha(needle),
                           "placement": where, "inserted_text": block.decode(),
                           "inserted_bytes": len(block), "inserted_sha256": sha(block)})

    def render(self):
        items = sorted(self.items, key=lambda item: item["original_byte_offset"])
        require(len({item["original_byte_offset"] for item in items}) == len(items),
                f"Ambiguous same-offset insertions: {self.name}")
        chunks, previous, extra = [], 0, 0
        for item in items:
            position = item["original_byte_offset"]
            block = item["inserted_text"].encode()
            chunks.extend((self.original[previous:position], block))
            item["patched_byte_start"] = position + extra
            item["patched_byte_end"] = position + extra + len(block)
            previous = position
            extra += len(block)
        chunks.append(self.original[previous:])
        patched = b"".join(chunks)
        reversed_bytes = patched
        for item in reversed(items):
            start, end = item["patched_byte_start"], item["patched_byte_end"]
            require(reversed_bytes[start:end] == item["inserted_text"].encode(),
                    "Recorded insertion bytes differ during reversal")
            reversed_bytes = reversed_bytes[:start] + reversed_bytes[end:]
        require(reversed_bytes == self.original, f"Exact reversal failed: {self.name}")
        return patched, items


def probe_insertions(original):
    p = Insertions(PROBE, original)
    p.add("swift.trace-function", "private final class Probe: @unchecked Sendable {\n", r'''
private func udpTransportDiagnostic(_ event: String, _ fields: String = "") {
    let uptime = DispatchTime.now().uptimeNanoseconds
    let wall = Date().timeIntervalSince1970
    let line = "UDP_ECHO_TRANSPORT_TRACE swift event=\(event) uptime_ns=\(uptime) wall_seconds=\(wall) pid=\(getpid()) main=\(Thread.isMainThread) \(fields)\n"
    FileHandle.standardError.write(Data(line.utf8))
}
''', "before")
    p.add("swift.run-enter", "    func run() {\n", r'''
        udpTransportDiagnostic("run.enter", "mode=\(mode) clock=DispatchTime.uptimeNanoseconds wall=Date.timeIntervalSince1970")
''')
    p.add("swift.client-start-before",
          "            client?.start(configuration: configuration, now: DispatchTime.now().uptimeNanoseconds)\n", r'''
            udpTransportDiagnostic("client.start.before", "mode=\(mode)")
''', "before")
    p.add("swift.client-start-after",
          "            client?.start(configuration: configuration, now: DispatchTime.now().uptimeNanoseconds)\n", r'''
            udpTransportDiagnostic("client.start.after", "mode=\(mode)")
''')
    p.add("swift.finish-schedule-before",
          "        queue.asyncAfter(deadline: .now() + .milliseconds(650)) { [self] in finish() }\n", r'''
        udpTransportDiagnostic("finish.schedule.before", "original_delay_ms=650")
''', "before")
    p.add("swift.finish-schedule-after",
          "        queue.asyncAfter(deadline: .now() + .milliseconds(650)) { [self] in finish() }\n", r'''
        udpTransportDiagnostic("finish.schedule.after", "original_delay_ms=650")
''')
    p.add("swift.wait-returned",
          '        guard done.wait(timeout: .now() + 5) == .success else { fatalError("Transport probe stalled") }\n', r'''
        udpTransportDiagnostic("done.wait.returned", "original_timeout_seconds=5")
''')
    p.add("swift.snapshot-returned",
          '             "greetingOffAcknowledged": greetingOffAcknowledged]\n        }\n', r'''
        udpTransportDiagnostic("snapshot.returned", "attempts=\(result["attempts"] as? Int ?? -1) accepted=\(result["accepted"] as? Int ?? -1) dropped=\(result["dropped"] as? Int ?? -1) datagramWrites=\(result["datagramWrites"] as? Int ?? -1) udpReadBytes=\(result["udpReadBytes"] as? Int ?? -1) writes=\(result["writes"] as? Int ?? -1) reads=\(result["reads"] as? Int ?? -1)")
''')
    p.add("swift.observer-return",
          "        if peer.port != configuration.server.port {\n            if sent { datagramWrites += count } else { udpReadBytes += count }\n        }\n", r'''
        udpTransportDiagnostic("observer.updated", "sent=\(sent) count=\(count) udp=\(peer.port != configuration.server.port) datagramWrites=\(datagramWrites) udpReadBytes=\(udpReadBytes) writes=\(writes) reads=\(reads) finished=\(finished)")
''')
    p.add("swift.ready", "        case .ready:\n", r'''
            udpTransportDiagnostic("event.ready", "attempts=\(attempts) finished=\(finished)")
''')
    p.add("swift.writable", "        case .writable:\n", r'''
            udpTransportDiagnostic("event.writable", "pending=\(pending) attempts=\(attempts)")
''')
    p.add("swift.failed", '            events.append("failed: " + message)\n', r'''
            udpTransportDiagnostic("event.failed", "attempts=\(attempts) accepted=\(accepted) udpReadBytes=\(udpReadBytes)")
''')
    p.add("swift.attempt", "        attempts += 1\n", r'''
        udpTransportDiagnostic("attempt.admitted", "attempts=\(attempts) accepted=\(accepted) pending=\(pending) finished=\(finished)")
''')
    p.add("swift.send-before", "        switch client.send(to: target, payload: [0]) {\n", r'''
        udpTransportDiagnostic("send.before", "attempts=\(attempts) accepted=\(accepted) datagramWrites=\(datagramWrites) udpReadBytes=\(udpReadBytes)")
''', "before")
    p.add("swift.send-return", "        case .closed: break\n        }\n", r'''
        udpTransportDiagnostic("send.returned", "attempts=\(attempts) accepted=\(accepted) dropped=\(dropped) pending=\(pending) datagramWrites=\(datagramWrites) udpReadBytes=\(udpReadBytes)")
''')
    p.add("swift.finish-enter", "    private func finish() {\n        guard !finished else { return }\n", r'''
        udpTransportDiagnostic("finish.enter", "attempts=\(attempts) accepted=\(accepted) datagramWrites=\(datagramWrites) udpReadBytes=\(udpReadBytes) writes=\(writes) reads=\(reads)")
''')
    p.add("swift.off-before", "        finished = true\n", r'''
        udpTransportDiagnostic("off.admission.before", "finished=\(finished)")
''')
    p.add("swift.off-after", "        finished = true\n        admission.begin(enabled: false)\n", r'''
        udpTransportDiagnostic("off.admission.returned", "finished=\(finished) udpReadBytes=\(udpReadBytes)")
''')
    p.add("swift.stop-after", "        client?.stop()\n", r'''
        udpTransportDiagnostic("client.stop.returned", "udpReadBytes=\(udpReadBytes) datagramWrites=\(datagramWrites)")
''')
    p.add("swift.signal-enqueue-before", "        client = nil\n", r'''
        udpTransportDiagnostic("done.signal.enqueue.before", "udpReadBytes=\(udpReadBytes) datagramWrites=\(datagramWrites)")
''')
    return p


def fixture_insertions(original):
    p = Insertions(FIXTURE, original)
    p.add("python.trace-function", "if not __debug__:\n", '''
def udp_transport_diagnostic(event, **fields):
    value = {
        "event": event,
        "python_monotonic_ns": time.monotonic_ns(),
        "python_wall_time_ns": time.time_ns(),
        "pid": os.getpid(),
        "thread_id": threading.get_ident(),
        **fields,
    }
    line = "UDP_ECHO_TRANSPORT_TRACE python " + json.dumps(value, sort_keys=True) + "\\n"
    os.write(2, line.encode("utf-8"))

''', "before")
    p.add("python.fixture-thread-before", "        self.thread.start()\n", '''
        udp_transport_diagnostic("fixture.thread.start.before", mode=self.mode, family=int(self.family),
                                 listener_port=self.listener.getsockname()[1],
                                 relay_port=self.relay.getsockname()[1])
''', "before")
    p.add("python.control-before", "    def send_control(self, connection, value):\n", '''
        udp_transport_diagnostic("control.send.before", mode=self.mode, bytes=len(value),
                                 tcp_written=self.tcp_written)
''')
    p.add("python.control-after", "            time.sleep(0.001)\n", '''
        udp_transport_diagnostic("control.send.returned", mode=self.mode, bytes=len(value),
                                 tcp_written=self.tcp_written)
''')
    p.add("python.worker-enter", "    def run(self):\n", '''
        udp_transport_diagnostic("fixture.worker.enter", mode=self.mode)
''')
    p.add("python.accept-returned", "            connection, peer = self.listener.accept()\n", '''
            udp_transport_diagnostic("control.accept.returned", mode=self.mode, peer_port=peer[1])
''')
    p.add("python.associate-validated", "                self.advertised = (source, source_port)\n", '''
                udp_transport_diagnostic("associate.validated", mode=self.mode,
                                         request_address_type=header[3], source_port=source_port)
''')
    p.add("python.relay-response-before",
          '                self.send_control(connection, response)\n                if self.mode == "zero-relay":\n', '''
                udp_transport_diagnostic("relay.response.before", mode=self.mode, bytes=len(response),
                                         relay_address_type=kind, relay_port=relay_port)
''', "before")
    p.add("python.relay-response-after",
          "                    return\n                self.send_control(connection, response)\n", '''
                udp_transport_diagnostic("relay.response.returned", mode=self.mode, bytes=len(response),
                                         tcp_written=self.tcp_written)
''')
    p.add("python.select-before",
          "                    ready, _, _ = select.select([self.relay, connection], [], [], 0.1)\n", '''
                    udp_transport_diagnostic("relay.select.before", mode=self.mode,
                                             datagrams=len(self.datagrams), reply_bytes=self.reply_bytes)
''', "before")
    p.add("python.select-after",
          "                    ready, _, _ = select.select([self.relay, connection], [], [], 0.1)\n", '''
                    udp_transport_diagnostic("relay.select.returned", mode=self.mode,
                                             relay_ready=self.relay in ready, control_ready=connection in ready)
''')
    p.add("python.control-eof",
          '                    if connection in ready and connection.recv(1) == b"":\n', '''
                        udp_transport_diagnostic("control.eof", mode=self.mode,
                                                 datagrams=len(self.datagrams), reply_bytes=self.reply_bytes)
''')
    p.add("python.relay-recv-before", "                    packet, sender = self.relay.recvfrom(65_535)\n", '''
                    udp_transport_diagnostic("relay.recv.before", mode=self.mode,
                                             datagrams=len(self.datagrams), reply_bytes=self.reply_bytes)
''', "before")
    p.add("python.relay-recv-after", "                    packet, sender = self.relay.recvfrom(65_535)\n", '''
                    udp_transport_diagnostic("relay.recv.returned", mode=self.mode,
                                             packet_bytes=len(packet), sender_port=sender[1])
''')
    p.add("python.relay-packet-validated", "                    self.datagrams.append(packet)\n", '''
                    udp_transport_diagnostic("relay.packet.validated", mode=self.mode,
                                             datagrams=len(self.datagrams), packet_bytes=len(packet))
''')
    p.add("python.relay-send-before", "                        self.relay.sendto(reply, sender)\n", '''
                        udp_transport_diagnostic("relay.sendto.before", mode=self.mode,
                                                 reply_length=len(reply), reply_bytes=self.reply_bytes,
                                                 datagrams=len(self.datagrams))
''', "before")
    p.add("python.relay-send-after", "                        self.reply_bytes += len(reply)\n", '''
                        udp_transport_diagnostic("relay.sendto.returned", mode=self.mode,
                                                 reply_length=len(reply), reply_bytes=self.reply_bytes,
                                                 datagrams=len(self.datagrams))
''')
    p.add("python.worker-finally", "        finally:\n            self.listener.close()\n", '''
            udp_transport_diagnostic("fixture.listener.closed", mode=self.mode,
                                     datagrams=len(self.datagrams), reply_bytes=self.reply_bytes,
                                     error_present=self.error is not None)
''')
    p.add("python.finish-enter", "    def finish(self):\n", '''
        udp_transport_diagnostic("fixture.finish.enter", mode=self.mode)
''')
    p.add("python.stop-after", "        self.stop.set()\n", '''
        udp_transport_diagnostic("fixture.stop.returned", mode=self.mode)
        udp_transport_diagnostic("fixture.join.before", mode=self.mode, original_timeout_seconds=3)
''')
    p.add("python.join-after", "        self.thread.join(3)\n", '''
        udp_transport_diagnostic("fixture.join.returned", mode=self.mode,
                                 worker_alive=self.thread.is_alive())
''')
    p.add("python.joined-snapshot", "        assert self.error is None, self.error\n", '''
        udp_transport_diagnostic("fixture.joined.validated", mode=self.mode,
                                 datagrams=len(self.datagrams), reply_bytes=self.reply_bytes,
                                 tcp_read=self.tcp_read, tcp_written=self.tcp_written)
''')
    p.add("python.main-clock", "def main():\n", '''
    clock = time.get_clock_info("monotonic")
    udp_transport_diagnostic("main.clock", implementation=clock.implementation,
                             monotonic=clock.monotonic, adjustable=clock.adjustable,
                             resolution_seconds=clock.resolution,
                             cross_process_epoch_equality_assumed=False)
''')
    p.add("python.process-before",
          "        result = subprocess.run([str(executable), fixture_mode, fixture.host,\n", '''
        udp_transport_diagnostic("probe.process.before", mode=mode, family=int(family),
                                 original_timeout_seconds=6)
''', "before")
    p.add("python.process-after",
          "                                capture_output=True, text=True, timeout=6, env=environment)\n", '''
        udp_transport_diagnostic("probe.process.returned", mode=mode,
                                 returncode=result.returncode, stdout_bytes=len(result.stdout.encode()),
                                 stderr_bytes=len(result.stderr.encode()))
''')
    p.add("python.comparison-before",
          '            assert data["udpReadBytes"] == fixture.reply_bytes, (mode, data, fixture.reply_bytes)\n', '''
            udp_transport_diagnostic("comparison.udp_bytes.before", mode=mode,
                                     accepted=data["accepted"], datagram_writes=data["datagramWrites"],
                                     observed_udp_bytes=data["udpReadBytes"],
                                     fixture_reply_bytes=fixture.reply_bytes,
                                     fixture_datagrams=len(fixture.datagrams))
''', "before")
    p.add("python.case-assertions-passed",
          '        results.append({"mode": mode, "family": family, "target": target, **data})\n', '''
        udp_transport_diagnostic("case.assertions.passed", mode=mode, family=int(family),
                                 observed_udp_bytes=data["udpReadBytes"],
                                 fixture_reply_bytes=fixture.reply_bytes)
''', "before")
    return p


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--diff", type=Path, required=True)
    args = parser.parse_args()
    require(not args.overlay.is_symlink(), "Overlay root must not be a symlink")
    root = args.overlay.resolve(strict=True)
    require(root.is_dir(), "Overlay must already exist")
    seen = []
    for path in root.rglob("*"):
        require(not path.is_symlink(), f"Symlink in overlay: {path}")
        if path.is_file():
            seen.append(path.relative_to(root).as_posix())
        else:
            require(path.is_dir(), f"Special object in overlay: {path}")
    require(set(seen) == set(PINS), "Overlay must be a fresh copy containing exactly the three pinned files")
    require(args.receipt.resolve() != args.diff.resolve(), "Receipt and diff must differ")
    for path in (args.receipt, args.diff):
        require(not path.exists() and not path.is_symlink(), f"Existing output: {path}")
        require(root != path.resolve() and root not in path.resolve().parents,
                "Receipt/diff must be outside the three-file overlay")
    before, originals = {}, {}
    for name, (size, digest) in PINS.items():
        before[name] = identity(root / name)
        require(before[name] == {"bytes": size, "sha256": digest, "mode": "0644"},
                f"Pinned original bytes/mode differ: {name}")
        originals[name] = (root / name).read_bytes()
    modified = {}
    patches = {}
    for name, plan in ((PROBE, probe_insertions(originals[PROBE])),
                       (FIXTURE, fixture_insertions(originals[FIXTURE]))):
        modified[name], patches[name] = plan.render()
    ast.parse(modified[FIXTURE].decode(), filename=FIXTURE)
    differences = "".join(
        "".join(difflib.unified_diff(originals[name].decode().splitlines(keepends=True),
                                    modified[name].decode().splitlines(keepends=True),
                                    fromfile="original/" + name, tofile="traced-copy/" + name))
        for name in (PROBE, FIXTURE))
    for name in (PROBE, FIXTURE):
        with (root / name).open("wb") as stream:
            stream.write(modified[name])
    after = {name: identity(root / name) for name in PINS}
    require(after[CLIENT] == before[CLIENT], "Production client was changed")
    for name in (PROBE, FIXTURE):
        require((root / name).read_bytes() == modified[name], "Written overlay differs")
        require(after[name]["mode"] == before[name]["mode"], "Overlay mode changed")
    args.diff.parent.mkdir(parents=True, exist_ok=True)
    with args.diff.open("x", encoding="utf-8") as stream:
        stream.write(differences)
    record = {
        "schema": "udp-echo-transport-diagnostic-insertion-only-v1",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "patcher": {"path": str(Path(__file__).resolve()), **identity(Path(__file__))},
        "overlay": str(root), "original_inputs": before, "patched_files": after,
        "production_client_unchanged": True,
        "insertions": patches,
        "insertion_count": sum(len(value) for value in patches.values()),
        "reversal": {name: {"original_sha256": before[name]["sha256"],
                             "reversed_sha256": before[name]["sha256"],
                             "recorded_spans_removed_match_original_bytes": True}
                     for name in (PROBE, FIXTURE)},
        "diff": {"path": str(args.diff.resolve()), **identity(args.diff)},
        "original_contract_unchanged": [
            "Production client bytes and mode.",
            "All original test statements and their order; only recorded new statements/comments inserted.",
            "Swift finish is still scheduled using the original .now()+650ms statement.",
            "Swift done.wait still uses five seconds; Python subprocess timeout is still six seconds.",
            "Original ready-first send and four index*60ms sends, one-byte payload, and fragmented 1ms replies.",
            "Original Swift6 warnings-as-errors optimized compiler command and every assertion.",
            "Fixture stop, three-second join, no-live-thread/error checks, then existing byte equality.",
        ],
        "observation_safety": [
            "Swift mutable Probe fields are read only in original Probe queue callbacks; main snapshot logs read only the returned immutable dictionary.",
            "Python main thread logs no worker-owned counters before its original join and both original completion assertions.",
            "Worker logs use worker-owned counters and locals; no new shared mutable trace counter or lock.",
            "No credentials, environment values, payload contents, error messages, or token values are logged.",
        ],
        "clock_and_timing_limits": [
            "Swift DispatchTime uptimeNanoseconds and Date wall seconds are paired in each event.",
            "Python monotonic_ns and time_ns are paired; get_clock_info metadata is emitted separately.",
            "Cross-process monotonic epochs are not assumed equal; wall clocks and bracketed event relationships support correlation.",
            "Synchronous stderr writes and clock reads perturb timing. A traced success cannot retrospectively explain either original failure.",
            "Scheduled-deadline logging brackets the untouched original deadline expression; it does not claim a new exact deadline variable.",
        ],
        "validation_scope": {
            "insertion_and_exact_reversal_checked": True,
            "patched_python_ast_parse": True,
            "swift_compiles": 0, "project_test_executions": 0,
            "remote_operations": 0, "canonical_gate_credit": 0,
        },
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"receipt": str(args.receipt.resolve()),
                      "receipt_sha256": sha(args.receipt.read_bytes()),
                      "insertion_count": record["insertion_count"],
                      "production_client_unchanged": True,
                      "project_test_executions": 0}))


if __name__ == "__main__":
    main()
