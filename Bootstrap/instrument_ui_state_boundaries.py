#!/usr/bin/env python3
"""Insert bounded OSLog observations into an exact temporary Integrated app copy.

Diagnostic namespace only; this does not produce a release candidate. Original
statements, conditions, test bytes, harness bytes and their ordering are retained.
Every inserted byte is identified and independently removable. No compilation,
test, Simulator operation, network request or credential access is performed.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat


SOURCE_SHA = "8bec30de328543f8f23b79a736385ed0e80aaa88"
SUBSYSTEM = "hev.Socks5.StateBoundaryDiagnostic"
MARKER = "UI_STATE_TRACE"
TARGETS = {
    "Socks5/AppRoot.swift": "cdda09cc9d08d4a0b63bd1e210a1f44fe3f9ef8ae6f09e7bd7effdbd03c5af6d",
    "Socks5/Settings/SettingsStore.swift": "1fdecaddc321269c0c0b8e782952cdf6acda540a3c9e3b84e8e81f343eaa432f",
    "Socks5/BackgroundKeepAlive/PeriodicUDPEchoModel.swift": "109d412c91177efd0367a2c4e57836e2f1f8fc09267ea8f799cda89297d44c1c",
    "Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift": "796c6cc16a48a1368835fd77c79b462f4dd8407f64208804659f8a43d9015968",
}
UNCHANGED_PINS = {
    "Build/ui_review.py": "0a452e8f665644a1ac950045fe33aaa59d63c639df9b4d0c6b2f7aebab33c09a",
    "Tests/Background/AsyncAudioUITests.swift": "14cfa19dbd0c8a167b3ea0f1d7412456a74449cbdd3843e8a15f46d03c34f260",
    "Tests/Integration/IntegrationUITests.swift": "b193689139fcbe4752eb1cfe73ab4bfd09da75e12b3566fbc74331205a6fb8da",
    "Tests/Statistics/StatisticsUITests.swift": "e3865c71abf30ca76354cbe585c6ccb15f565bb28d3eb3ff0407da77e3cee574",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


class Insertions:
    def __init__(self, path, original):
        self.path, self.original, self.text = path, original, original
        self.operations = []

    def add(self, label, anchor, code, *, before=False, inline=False, indent="        "):
        require(self.text.count(anchor) == 1, f"{self.path}: anchor count differs: {label}")
        require(code.endswith("\n"), f"Insertion must end in newline: {label}")
        require(not any(x["label"] == label for x in self.operations), "Duplicate label")
        block = (("\n" if inline else "") + indent + "// UI_STATE_DIAGNOSTIC_BEGIN " + label + "\n" +
                 code + indent + "// UI_STATE_DIAGNOSTIC_END " + label + "\n" +
                 (indent if inline else ""))
        require(block not in self.text, "Repeated block")
        offset = self.text.index(anchor) + (0 if before else len(anchor))
        self.text = self.text[:offset] + block + self.text[offset:]
        self.operations.append({"label": label, "anchor": anchor,
            "side": "before" if before else "after", "inline": inline,
            "block": block, "block_sha256": sha(block.encode()),
            "insertion_offset_in_then_current_utf8": len(self.text[:offset].encode())})

    def finalize(self):
        restored = self.text
        for item in reversed(self.operations):
            require(restored.count(item["block"]) == 1, "Reversal occurrence differs: " + item["label"])
            restored = restored.replace(item["block"], "", 1)
        require(restored == self.original, self.path + ": original bytes changed")
        for item in self.operations:
            require(self.text.count(item["block"]) == 1, "Final block occurrence differs")
            start = len(self.text[:self.text.index(item["block"])].encode())
            item["final_utf8_span"] = [start, start + len(item["block"].encode())]
        return self.text.encode(), {"path": self.path,
            "before_bytes": len(self.original.encode()), "before_sha256": sha(self.original.encode()),
            "after_bytes": len(self.text.encode()), "after_sha256": sha(self.text.encode()),
            "insertion_count": len(self.operations), "insertions": self.operations,
            "reverse_removal_equals_original": True, "reversed_sha256": sha(restored.encode())}


def root_plan(original):
    p = Insertions("Socks5/AppRoot.swift", original)
    p.add("shared-notice-logger", "import SwiftUI\n", r'''import Foundation
import OSLog

// Diagnostic-only shared immutable Logger. No mutable sequence, new queue, lock,
// file operation, forced lazy owner evaluation, or cross-actor state read.
enum UIStateBoundaryDiagnostics {
    private static let logger = Logger(subsystem: "hev.Socks5.StateBoundaryDiagnostic", category: "state")
    static func emit(_ event: String, _ detail: String) {
        let uptime = DispatchTime.now().uptimeNanoseconds
        let pid = ProcessInfo.processInfo.processIdentifier
        logger.notice("UI_STATE_TRACE uptime_ns=\(uptime) pid=\(pid) event=\(event, privacy: .public) \(detail, privacy: .public)")
    }
}

''', indent="")
    p.add("root-lazy-owner-created", "        let owner = DeferredSettings()\n", r'''        UIStateBoundaryDiagnostics.emit("root.init.owner", "owner=\(ObjectIdentifier(owner))")
''')
    p.add("root-state-observer", "    private var audioEnabled: Binding<Bool> {\n", r'''    private func diagnosticRoot(_ event: String, requested: Bool? = nil) {
        UIStateBoundaryDiagnostics.emit(event,
            "store=\(ObjectIdentifier(settings)) load=\(String(describing: settings.loadState)) " +
            "revision=\(settings.change.revision) origin=\(String(describing: settings.change.origin)) " +
            "audioRevision=\(settings.audioChange.revision) echoRevision=\(settings.echoChange.revision) " +
            "audio=\(settings.value.background.silentAudio) echo=\(settings.value.background.periodicUDPEcho.enabled) " +
            "requested=\(String(describing: requested)) savePending=\(settings.savePending)")
    }

''', before=True, indent="    ")
    p.add("root-audio-binding-enter", "self.applyAudioIntent(enabled)", r'''            self.diagnosticRoot("root.audio.binding.enter", requested: enabled)
''', before=True, inline=True, indent="            ")
    p.add("root-audio-binding-return", "self.applyAudioIntent(enabled)", r'''            self.diagnosticRoot("root.audio.binding.return", requested: enabled)
''', inline=True, indent="            ")
    p.add("root-audio-intent-enter", "    private func applyAudioIntent(_ enabled: Bool) {\n", r'''        diagnosticRoot("root.audio.apply.enter", requested: enabled)
        defer { diagnosticRoot("root.audio.apply.return", requested: enabled) }
''')
    p.add("root-audio-service-return", "        keepAlive.setAudio(enabled)\n", r'''        UIStateBoundaryDiagnostics.emit("root.audio.service.return",
            "store=\(ObjectIdentifier(settings)) facade=\(ObjectIdentifier(keepAlive)) requested=\(enabled) " +
            "facadeAudio=\(keepAlive.audioEnabled) storedAudio=\(settings.value.background.silentAudio) " +
            "audioRevision=\(settings.audioChange.revision) expectedRevision=\(previous.revision)")
''')
    p.add("root-audio-superseded", "        guard settings.audioChange == previous else { return }\n", r'''        if settings.audioChange != previous { diagnosticRoot("root.audio.guard_drop", requested: enabled) }
''', before=True)
    p.add("root-echo-save-enter", "            let settings = owner.value\n", r'''            UIStateBoundaryDiagnostics.emit("root.echo.save.enter",
                "store=\(ObjectIdentifier(settings)) requested=\(value.enabled) " +
                "storedEcho=\(settings.value.background.periodicUDPEcho.enabled) " +
                "load=\(String(describing: settings.loadState)) revision=\(settings.change.revision)")
            defer {
                UIStateBoundaryDiagnostics.emit("root.echo.save.return",
                    "store=\(ObjectIdentifier(settings)) requested=\(value.enabled) " +
                    "storedEcho=\(settings.value.background.periodicUDPEcho.enabled) " +
                    "load=\(String(describing: settings.loadState)) revision=\(settings.change.revision)")
            }
''', indent="            ")
    p.add("root-restore-enter", "    private func restoreServices() {\n", r'''        diagnosticRoot("root.restore.enter")
        defer { diagnosticRoot("root.restore.return") }
        if settings.loadState != .ready { diagnosticRoot("root.restore.skip_loading_or_failed") }
''')
    p.add("root-restore-same", "        guard appliedSettingsChange != change else { return }\n", r'''        if appliedSettingsChange == change { diagnosticRoot("root.restore.skip_same_change") }
''', before=True)
    p.add("root-restore-commit", "        appliedSettingsChange = change\n", r'''        diagnosticRoot("root.restore.change_accepted")
''')
    p.add("root-restore-audio-return", "        keepAlive.syncAudio(value.background.silentAudio)\n", r'''        UIStateBoundaryDiagnostics.emit("root.restore.audio.return",
            "store=\(ObjectIdentifier(settings)) facade=\(ObjectIdentifier(keepAlive)) " +
            "requested=\(value.background.silentAudio) facadeAudio=\(keepAlive.audioEnabled) " +
            "storedAudio=\(settings.value.background.silentAudio) " +
            "revision=\(settings.change.revision) expectedRevision=\(change.revision)")
''')
    p.add("root-restore-echo-return", "        if udpEcho.settings != restored { udpEcho.restore(restored) }\n", r'''        UIStateBoundaryDiagnostics.emit("root.restore.echo.return",
            "store=\(ObjectIdentifier(settings)) model=\(ObjectIdentifier(udpEcho)) " +
            "requested=\(restored.enabled) modelEcho=\(udpEcho.enabled) " +
            "storedEcho=\(settings.value.background.periodicUDPEcho.enabled) " +
            "revision=\(settings.change.revision) expectedRevision=\(change.revision)")
''')
    for kind, anchor in [
        ("change", ".onChange(of: settings.change, initial: true) { _, _ in "),
        ("load", ".onChange(of: settings.loadState) { _, _ in ")]:
        p.add("root-onchange-" + kind, anchor,
              '            diagnosticRoot("root.onChange.' + kind + '")\n',
              inline=True, indent="            ")
    return p


def settings_plan(original):
    p = Insertions("Socks5/Settings/SettingsStore.swift", original)
    p.add("settings-state-observer", "    private func publishChanges() {\n", r'''    private func diagnosticSettings(_ event: String, field: String = "-") {
        UIStateBoundaryDiagnostics.emit(event,
            "store=\(ObjectIdentifier(self)) field=\(field) load=\(String(describing: loadState)) " +
            "revision=\(revision) origin=\(String(describing: change.origin)) " +
            "audioRevision=\(audioChange.revision) echoRevision=\(echoChange.revision) " +
            "audio=\(value.background.silentAudio) echo=\(value.background.periodicUDPEcho.enabled) " +
            "tab=\(value.selectedTab.rawValue) busy=\(busy) savePending=\(savePending) " +
            "pending=\(pending != nil) saving=\(saving != nil) error=\(storageFailure != nil) " +
            "durableAudio=\(String(describing: durable?.background.silentAudio)) " +
            "durableEcho=\(String(describing: durable?.background.periodicUDPEcho.enabled))")
    }

    private func diagnosticField(_ path: PartialKeyPath<AppSettings>) -> String {
        if path == \AppSettings.background.silentAudio { return "audio" }
        if path == \AppSettings.background.periodicUDPEcho { return "echo" }
        if path == \AppSettings.background.periodicUDPEcho.enabled { return "echo_enabled" }
        if path == \AppSettings.selectedTab { return "tab" }
        if path == \AppSettings.serverRunning { return "server_running" }
        return "other"
    }

''', before=True, indent="    ")
    p.add("settings-publish-before", "        objectWillChange.send()\n", r'''        diagnosticSettings("settings.publish.before")
''', before=True)
    p.add("settings-publish-return", "        objectWillChange.send()\n", r'''        diagnosticSettings("settings.publish.return")
''')
    p.add("settings-init-before-load", "        self.storage = storage\n", r'''        diagnosticSettings("settings.init")
''')
    p.add("settings-set-entry", "                    origin: Origin = .user) {\n", r'''        let diagnosticPath = diagnosticField(path)
        UIStateBoundaryDiagnostics.emit("settings.set.enter",
            "store=\(ObjectIdentifier(self)) field=\(diagnosticPath) " +
            "bool=\(String(describing: newValue as? Bool)) " +
            "echoValue=\(String(describing: (newValue as? AppSettings.Background.UDPEcho)?.enabled)) " +
            "revision=\(revision) load=\(String(describing: loadState))")
        defer { diagnosticSettings("settings.set.return", field: diagnosticPath) }
''')
    p.add("settings-set-commit", "        markIntent(path)\n", r'''        diagnosticSettings("settings.set.committed", field: diagnosticPath)
''')
    p.add("settings-load-entry", "    private func load() {\n", r'''        diagnosticSettings("settings.load.enter")
''')
    p.add("settings-load-queued", "        let target = fileURL, source = storage, legacy = legacy\n", r'''        let diagnosticStoreID = String(describing: ObjectIdentifier(self))
        diagnosticSettings("settings.load.queued")
''')
    p.add("settings-load-utility-entry", "        io.async { [self] in\n            let result = Result { () throws -> Loaded in\n", r'''                UIStateBoundaryDiagnostics.emit("settings.load.utility.enter", "store=\(diagnosticStoreID)")
''', indent="                ")
    p.add("settings-load-utility-result", "            DispatchQueue.main.async { [self] in\n                busy = false\n                guard !revisionExhausted else { pump(); return }\n", r'''            switch result {
            case .success(let diagnosticLoaded):
                UIStateBoundaryDiagnostics.emit("settings.load.utility.result",
                    "store=\(diagnosticStoreID) success=true audio=\(diagnosticLoaded.value.background.silentAudio) " +
                    "echo=\(diagnosticLoaded.value.background.periodicUDPEcho.enabled) migrated=\(diagnosticLoaded.migrated)")
            case .failure:
                UIStateBoundaryDiagnostics.emit("settings.load.utility.result", "store=\(diagnosticStoreID) success=false")
            }
''', before=True, indent="            ")
    p.add("settings-load-main-entry", "            DispatchQueue.main.async { [self] in\n                busy = false\n                guard !revisionExhausted else { pump(); return }\n", r'''                diagnosticSettings("settings.load.main.before_merge")
                defer { diagnosticSettings("settings.load.main.return") }
''', indent="                ")
    p.add("settings-load-main-committed", "                    errorMessage = nil\n                    loadState = .ready\n", r'''                    diagnosticSettings("settings.load.main.committed")
''', indent="                    ")
    p.add("settings-save-captured-id", "            let target = fileURL, source = storage, cleanup = migrationPending ? legacy : nil\n", r'''            let diagnosticStoreID = String(describing: ObjectIdentifier(self))
            diagnosticSettings("settings.save.queued")
''', indent="            ")
    p.add("settings-save-utility-before", "                let result = Result { try source.write(next.encoded(), target); cleanup?.clear() }\n", r'''                UIStateBoundaryDiagnostics.emit("settings.save.utility.enter",
                    "store=\(diagnosticStoreID) audio=\(next.background.silentAudio) echo=\(next.background.periodicUDPEcho.enabled)")
''', before=True, indent="                ")
    p.add("settings-save-utility-result", "                let result = Result { try source.write(next.encoded(), target); cleanup?.clear() }\n", r'''                switch result {
                case .success:
                    UIStateBoundaryDiagnostics.emit("settings.save.utility.result",
                        "store=\(diagnosticStoreID) success=true audio=\(next.background.silentAudio) echo=\(next.background.periodicUDPEcho.enabled)")
                case .failure:
                    UIStateBoundaryDiagnostics.emit("settings.save.utility.result", "store=\(diagnosticStoreID) success=false")
                }
''', indent="                ")
    p.add("settings-save-main-entry", "                DispatchQueue.main.async { [self] in\n                    busy = false\n                    saving = nil\n", r'''                    diagnosticSettings("settings.save.main.enter")
                    defer { diagnosticSettings("settings.save.main.return") }
''', indent="                    ")
    return p


def echo_plan(original):
    p = Insertions("Socks5/BackgroundKeepAlive/PeriodicUDPEchoModel.swift", original)
    p.add("echo-state-observer", "    func setEnabled(_ value: Bool) {\n", r'''    private func diagnosticEcho(_ event: String, requested: Bool? = nil) {
        UIStateBoundaryDiagnostics.emit(event,
            "model=\(ObjectIdentifier(self)) enabled=\(settings.enabled) revision=\(intentRevision) " +
            "requested=\(String(describing: requested)) stateOff=\(state == "Off") " +
            "stateSending=\(state == "Sending UDP Echo") savePending=\(savePending) error=\(storageError != nil)")
    }

''', before=True, indent="    ")
    p.add("echo-init", "        self.store?.load { [weak self] result in\n", r'''        diagnosticEcho("echo.init")
''', before=True)
    p.add("echo-setenabled-entry", "    func setEnabled(_ value: Bool) {\n", r'''        diagnosticEcho("echo.setEnabled.enter", requested: value)
        defer { diagnosticEcho("echo.setEnabled.return", requested: value) }
''')
    p.add("echo-restore-entry", "    func restore(_ value: PeriodicUDPEchoSettings, ifRevision expected: UInt64? = nil) {\n", r'''        diagnosticEcho("echo.restore.enter", requested: value.enabled)
        defer { diagnosticEcho("echo.restore.return", requested: value.enabled) }
''')
    p.add("echo-apply-entry", "    private func apply(_ value: PeriodicUDPEchoSettings, persist shouldPersist: Bool) {\n", r'''        diagnosticEcho("echo.apply.enter", requested: value.enabled)
        UIStateBoundaryDiagnostics.emit("echo.apply.mode", "model=\(ObjectIdentifier(self)) persist=\(shouldPersist)")
''')
    p.add("echo-settings-committed", "        intentRevision &+= 1\n", r'''        diagnosticEcho("echo.apply.settings_committed", requested: value.enabled)
''')
    p.add("echo-service-before", "            service.update(value)\n", r'''            diagnosticEcho("echo.service_update.before", requested: value.enabled)
''', before=True, indent="            ")
    p.add("echo-service-return", "            service.update(value)\n", r'''            diagnosticEcho("echo.service_update.return", requested: value.enabled)
''', indent="            ")
    p.add("echo-publish-before", "        // Every field is settled before reentrant observers can accept a newer intent.\n        objectWillChange.send()\n", r'''        diagnosticEcho("echo.apply.publish.before", requested: value.enabled)
''', before=True)
    p.add("echo-publish-return", "        // Every field is settled before reentrant observers can accept a newer intent.\n        objectWillChange.send()\n", r'''        diagnosticEcho("echo.apply.publish.return", requested: value.enabled)
''')
    p.add("echo-save-callback-before", "            save(value)\n", r'''            diagnosticEcho("echo.save_callback.before", requested: value.enabled)
''', before=True, indent="            ")
    p.add("echo-save-callback-return", "            save(value)\n", r'''            diagnosticEcho("echo.save_callback.return", requested: value.enabled)
''', indent="            ")
    return p


def view_plan(original):
    p = Insertions("Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift", original)
    p.add("view-echo-binding-enter", "udpEcho.setEnabled($0)", r'''                                                                UIStateBoundaryDiagnostics.emit("view.echo.binding.enter",
                                                                    "model=\(ObjectIdentifier(udpEcho)) requested=\($0) enabled=\(udpEcho.enabled)")
''', before=True, inline=True, indent="                                                                ")
    p.add("view-echo-binding-return", "udpEcho.setEnabled($0)", r'''                                                                UIStateBoundaryDiagnostics.emit("view.echo.binding.return",
                                                                    "model=\(ObjectIdentifier(udpEcho)) requested=\($0) enabled=\(udpEcho.enabled)")
''', inline=True, indent="                                                                ")
    return p


def inventory(root):
    result = {}
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            p = Path(folder) / name
            relative = p.relative_to(root).as_posix()
            mode = p.lstat().st_mode
            if stat.S_ISLNK(mode):
                result[relative] = {"kind": "symlink", "mode": stat.S_IMODE(mode), "target": os.readlink(p)}
            elif stat.S_ISREG(mode):
                raw = p.read_bytes()
                result[relative] = {"kind": "file", "mode": stat.S_IMODE(mode), "bytes": len(raw), "sha256": sha(raw)}
            elif stat.S_ISDIR(mode):
                result[relative] = {"kind": "directory", "mode": stat.S_IMODE(mode)}
            else:
                raise RuntimeError("Unexpected application node type: " + relative)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--diff", type=Path, required=True)
    a = parser.parse_args()
    require(not a.application.is_symlink(), "Application root cannot be a symlink")
    application = a.application.resolve(strict=True)
    require(application.is_dir() and not (application / ".git").exists(), "Use only a temporary non-Git application copy")
    require(not a.receipt.is_symlink() and not a.diff.is_symlink(), "Output cannot be a symlink")
    outputs = [a.receipt.resolve(), a.diff.resolve()]
    require(outputs[0] != outputs[1], "Receipt and diff must differ")
    for output in outputs:
        require(not output.exists() and not output.is_symlink(), "Output already exists: " + str(output))
        require(not output.is_relative_to(application), "Diagnostic outputs must be outside the application copy")
    before = inventory(application)
    for path, expected in {**TARGETS, **UNCHANGED_PINS}.items():
        current = application / path
        for parent in [current, *current.parents]:
            if parent == application:
                break
            require(not parent.is_symlink(), "Pinned path has a symlink: " + path)
        require(before.get(path, {}).get("sha256") == expected, "Exact input SHA differs: " + path)
    generated_test = application / "StatisticsUITests.swift"
    require(generated_test.is_file() and not generated_test.is_symlink(), "Original stitched UI test source must already exist")
    stitched = ((application / "Tests/Integration/IntegrationUITests.swift").read_bytes() + b"\n" +
                (application / "Tests/Background/AsyncAudioUITests.swift").read_bytes() + b"\n" +
                (application / "Tests/Statistics/StatisticsUITests.swift").read_bytes())
    require(generated_test.read_bytes() == stitched, "Original test concatenation differs")
    plans = [fn((application / path).read_text()) for path, fn in [
        ("Socks5/AppRoot.swift", root_plan),
        ("Socks5/Settings/SettingsStore.swift", settings_plan),
        ("Socks5/BackgroundKeepAlive/PeriodicUDPEchoModel.swift", echo_plan),
        ("Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift", view_plan)]]
    patches, records, differences = {}, [], []
    for plan in plans:
        raw, record = plan.finalize()
        patches[plan.path] = raw
        records.append(record)
        differences.extend(difflib.unified_diff(plan.original.splitlines(keepends=True), plan.text.splitlines(keepends=True),
                           fromfile="original/" + plan.path, tofile="instrumented-diagnostic/" + plan.path))
    # All identities, exact anchors and reversals are checked before any source write.
    for path, raw in patches.items():
        (application / path).write_bytes(raw)
    after = inventory(application)
    require(set(before) == set(after), "Application node membership changed")
    changed = [n for n in before if before[n] != after[n]]
    require(set(changed) == set(TARGETS), "Modification outside the four allowed Swift files")
    for path in TARGETS:
        require(before[path]["mode"] == after[path]["mode"], "Source mode changed")
    for record in records:
        raw = (application / record["path"]).read_bytes()
        require(sha(raw) == record["after_sha256"], "Written patch differs")
        for item in sorted(record["insertions"], key=lambda r: r["final_utf8_span"][0], reverse=True):
            start, end = item["final_utf8_span"]
            require(raw[start:end] == item["block"].encode(), "Byte span differs")
            raw = raw[:start] + raw[end:]
        require(sha(raw) == TARGETS[record["path"]], "Independent span deletion did not restore source")
    diff_bytes = "".join(differences).encode()
    receipt = {"schema": "integrated-temporary-ui-state-instrumentation-v1", "source_sha": SOURCE_SHA,
        "namespace": "instrumented diagnostic application only; never canonical product evidence",
        "application": str(application), "subsystem": SUBSYSTEM, "marker": MARKER,
        "logging": {"level": "notice", "category": "state", "clock": "DispatchTime uptimeNanoseconds",
                    "global_mutable_counter": False, "new_queues_or_locks": False,
                    "privacy": "Only fixed event names, owner identities, boolean/enum/revision/count state; no credentials, paths, endpoints or configuration text"},
        "changed_paths": sorted(changed), "file_count": len(records),
        "insertion_count": sum(r["insertion_count"] for r in records), "files": records,
        "unchanged_pins": UNCHANGED_PINS,
        "stitched_test_source": {"path": "StatisticsUITests.swift", "bytes": len(stitched), "sha256": sha(stitched), "unchanged": True},
        "all_other_application_nodes_unchanged": True, "source_modes_unchanged": True,
        "before_inventory": before, "after_inventory": after,
        "diff": {"path": str(outputs[1]), "bytes": len(diff_bytes), "sha256": sha(diff_bytes)},
        "patcher": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__).read_bytes())},
        "compiler_executed": False, "tests_executed": False, "remote_operations": False,
        "limitations": ["Logging is observational but adds allocation, formatting and OSLog timing overhead; a non-reproduction cannot repair historical failure.",
                        "OSLog delivery and retention are not guaranteed. Missing/failed extraction or incomplete event coverage is diagnostic inconclusive.",
                        "No synchronous callback or async queue ordering is intentionally changed. Added code does not mutate product state, force a lazy settings value in root init, or read MainActor state on the utility queue."]}
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
    with outputs[1].open("xb") as f:
        f.write(diff_bytes)
    with outputs[0].open("x", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({"receipt": str(outputs[0]), "diff": str(outputs[1]),
                      "modified_files": len(records), "insertions": receipt["insertion_count"],
                      "source_reversal_passed": True}))


if __name__ == "__main__":
    main()
