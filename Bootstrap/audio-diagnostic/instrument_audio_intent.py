#!/usr/bin/env python3
"""Instrument only a temporary copy of the exact efae8 Integrated application.

The diagnostic copy is not a release candidate. Every original source byte is
recoverable by removing the explicitly recorded inserted blocks. No original
statement, condition, ordering, XCTest source, or test deadline is changed.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path


SOURCE_COMMIT = 'efae8be3f8ccb60fdb447a4175abebbecc2767de'
ORIGINALS = {
    'Socks5/AppRoot.swift': 'cdda09cc9d08d4a0b63bd1e210a1f44fe3f9ef8ae6f09e7bd7effdbd03c5af6d',
    'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift': '23f77795fd16ebd6cea09d95653630fd8b458ed03d19912dd53d7cbf73c0fcfb',
    'Socks5/Settings/SettingsStore.swift': '1fdecaddc321269c0c0b8e782952cdf6acda540a3c9e3b84e8e81f343eaa432f',
}
TESTS = {
    'Tests/Background/AsyncAudioUITests.swift': '14cfa19dbd0c8a167b3ea0f1d7412456a74449cbdd3843e8a15f46d03c34f260',
    'Tests/Integration/IntegrationUITests.swift': 'b193689139fcbe4752eb1cfe73ab4bfd09da75e12b3566fbc74331205a6fb8da',
    'Tests/Statistics/StatisticsUITests.swift': 'e3865c71abf30ca76354cbe585c6ccb15f565bb28d3eb3ff0407da77e3cee574',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


class Insertions:
    def __init__(self, path, original):
        self.path = path
        self.original = original
        self.text = original
        self.operations = []

    def add(self, label, anchor, inserted, *, before=False, expected_count=1):
        require(self.text.count(anchor) == expected_count,
                f'{self.path}: exact anchor count differs for {label}')
        require(inserted.endswith('\n'), f'Insertion must end with newline: {label}')
        indent = inserted[:len(inserted) - len(inserted.lstrip(' '))]
        block = (indent + '// AUDIO_INTENT_DIAGNOSTIC_BEGIN ' + label + '\n' + inserted +
                 indent + '// AUDIO_INTENT_DIAGNOSTIC_END ' + label + '\n')
        require(block not in self.text, 'Repeated diagnostic block: ' + label)
        replacement = block + anchor if before else anchor + block
        self.text = self.text.replace(anchor, replacement)
        self.operations.append({'label': label, 'position': 'before' if before else 'after',
                                'exact_anchor': anchor, 'occurrences': expected_count,
                                'inserted_block': block, 'inserted_block_sha256': sha(block.encode())})

    def prove_original_preserved(self):
        restored = self.text
        for item in reversed(self.operations):
            require(restored.count(item['inserted_block']) == item['occurrences'],
                    'Diagnostic block occurrence changed: ' + item['label'])
            restored = restored.replace(item['inserted_block'], '')
        require(restored == self.original, self.path + ': original statements/bytes changed')


def root_plan(original):
    p = Insertions('Socks5/AppRoot.swift', original)
    p.add('shared-logger', 'import SwiftUI\n', r'''import Foundation

@MainActor
enum AudioIntentDiagnostics {
    private static var sequence: UInt64 = 0
    static func emit(_ event: String, _ detail: String) {
        sequence &+= 1
        NSLog("AUDIO_INTENT_TRACE seq=%llu uptime=%.9f event=%@ %@",
              sequence, ProcessInfo.processInfo.systemUptime, event, detail)
    }
}
''')
    p.add('root-state-logger', '    private func applyAudioIntent(_ enabled: Bool) {\n', r'''    private func diagnosticAudioIntent(_ event: String, requested: Bool? = nil,
                                       expected: SettingsStore.Change? = nil) {
        AudioIntentDiagnostics.emit(event,
            "settings=\(ObjectIdentifier(settings)) facade=\(ObjectIdentifier(keepAlive)) " +
            "requested=\(String(describing: requested)) stored=\(settings.value.background.silentAudio) " +
            "facadeIntent=\(keepAlive.audioEnabled) audioState=\(keepAlive.audioState) " +
            "change=\(String(describing: settings.change)) audioChange=\(String(describing: settings.audioChange)) " +
            "load=\(String(describing: settings.loadState)) accepts=\(settings.acceptsNewIntent) " +
            "applied=\(String(describing: appliedSettingsChange)) expected=\(String(describing: expected))")
    }

''', before=True)
    p.add('root-apply-enter', '    private func applyAudioIntent(_ enabled: Bool) {\n',
          '        diagnosticAudioIntent("root.apply.enter", requested: enabled)\n')
    p.add('root-rejected-on', '        guard !enabled || settings.acceptsNewIntent else {\n',
          '            diagnosticAudioIntent("root.apply.rejected_on", requested: enabled)\n')
    p.add('root-service-return', '        keepAlive.setAudio(enabled)\n',
          '        diagnosticAudioIntent("root.apply.service_return", requested: enabled, expected: previous)\n')
    p.add('root-guard-drop', '        guard settings.audioChange == previous else { return }\n', r'''        if settings.audioChange != previous {
            diagnosticAudioIntent("root.apply.guard_drop", requested: enabled, expected: previous)
        }
''', before=True)
    # This statement also appears in the rejection branch. Its exact method
    # tail identifies the successful commit without modifying either statement.
    tail = '        settings.set(\\.background.silentAudio, enabled, origin: .user)\n'
    full_tail = tail + '    }\n'
    block = ('        // AUDIO_INTENT_DIAGNOSTIC_BEGIN root-settings-return\n'
             '        diagnosticAudioIntent("root.apply.settings_return", requested: enabled, expected: previous)\n'
             '        // AUDIO_INTENT_DIAGNOSTIC_END root-settings-return\n')
    require(p.text.count(full_tail) == 1, 'Root settings-return anchor differs')
    p.text = p.text.replace(full_tail, tail + block + '    }\n')
    p.operations.append({'label': 'root-settings-return', 'position': 'inside_exact_tail_after_set',
                         'exact_anchor': full_tail, 'occurrences': 1,
                         'inserted_block': block, 'inserted_block_sha256': sha(block.encode())})
    p.add('root-restore-enter', '    private func restoreServices() {\n', r'''        diagnosticAudioIntent("root.restore.enter")
        if settings.loadState != .ready { diagnosticAudioIntent("root.restore.skip_not_ready") }
''')
    p.add('root-restore-same', '        guard appliedSettingsChange != change else { return }\n', r'''        if appliedSettingsChange == change { diagnosticAudioIntent("root.restore.skip_same_change", expected: change) }
''', before=True)
    p.add('root-restore-stamp', '        appliedSettingsChange = change\n',
          '        diagnosticAudioIntent("root.restore.applied_stamp", expected: change)\n')
    p.add('root-restore-reentry',
          '        guard settings.loadState == .ready, settings.change == change else { return }\n', r'''        if settings.loadState != .ready || settings.change != change {
            diagnosticAudioIntent("root.restore.skip_superseded", expected: change)
        }
''', before=True, expected_count=3)
    p.add('root-restore-audio-enter', '        keepAlive.syncAudio(value.background.silentAudio)\n',
          '        diagnosticAudioIntent("root.restore.audio_sync_enter", requested: value.background.silentAudio, expected: change)\n',
          before=True)
    p.add('root-restore-audio-return', '        keepAlive.syncAudio(value.background.silentAudio)\n',
          '        diagnosticAudioIntent("root.restore.audio_sync_return", requested: value.background.silentAudio, expected: change)\n')
    p.add('root-restore-return', '        syncEchoServer()\n',
          '        diagnosticAudioIntent("root.restore.return", expected: change)\n')
    return p


def facade_plan(original):
    p = Insertions('Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift', original)
    p.add('facade-state-logger', '    func setAudio(_ enabled: Bool) {\n', r'''    private func diagnosticAudioIntent(_ event: String, requested: Bool? = nil) {
        AudioIntentDiagnostics.emit(event,
            "facade=\(ObjectIdentifier(self)) owner=\(audioOwner) requested=\(String(describing: requested)) " +
            "facadeIntent=\(audioEnabled) audioState=\(audioState)")
    }

''', before=True)
    p.add('facade-observer-enter',
          '        audioOwner = audio.register { [weak self] state in\n            guard let self else { return }\n',
          '            diagnosticAudioIntent("facade.observer.enter")\n')
    p.add('facade-observer-publish', '            audioDetail = state.detail\n',
          '            diagnosticAudioIntent("facade.observer.before_publish")\n')
    p.add('facade-observer-return', '            objectWillChange.send()\n',
          '            diagnosticAudioIntent("facade.observer.after_publish")\n')
    p.add('facade-set-enter', '    func setAudio(_ enabled: Bool) {\n',
          '        diagnosticAudioIntent("facade.set.enter", requested: enabled)\n')
    p.add('facade-service-return', '        audio.setEnabled(enabled, owner: audioOwner)\n',
          '        diagnosticAudioIntent("facade.set.service_return", requested: enabled)\n')
    p.add('facade-show-enter', '    private func showAudioIntent(_ enabled: Bool) {\n',
          '        diagnosticAudioIntent("facade.show.enter", requested: enabled)\n')
    p.add('facade-show-publish', '        if changed || stopping { objectWillChange.send() }\n',
          '        diagnosticAudioIntent("facade.show.before_publish", requested: enabled)\n', before=True)
    p.add('facade-show-return', '        if changed || stopping { objectWillChange.send() }\n',
          '        diagnosticAudioIntent("facade.show.after_publish", requested: enabled)\n')
    return p


def settings_plan(original):
    p = Insertions('Socks5/Settings/SettingsStore.swift', original)
    p.add('settings-state-logger', '    private func publishChanges() {\n', r'''    private func diagnosticAudioIntent(_ event: String) {
        AudioIntentDiagnostics.emit(event,
            "settings=\(ObjectIdentifier(self)) stored=\(value.background.silentAudio) " +
            "revision=\(revision) change=\(String(describing: change)) audioChange=\(String(describing: audioChange)) " +
            "load=\(String(describing: loadState)) accepts=\(acceptsNewIntent) busy=\(busy) " +
            "earlyEdits=\(earlyEdits.count) savePending=\(savePending)")
    }

''', before=True)
    p.add('settings-publish-before', '        objectWillChange.send()\n',
          '        diagnosticAudioIntent("settings.publish.before")\n', before=True)
    p.add('settings-publish-after', '        objectWillChange.send()\n',
          '        diagnosticAudioIntent("settings.publish.after")\n')
    p.add('settings-set-enter',
          '                    origin: Origin = .user) {\n', r'''        if path == \AppSettings.self || path == \AppSettings.background || path == \AppSettings.background.silentAudio {
            diagnosticAudioIntent("settings.set_audio.enter")
        }
''')
    p.add('settings-set-commit', '        markIntent(path)\n', r'''        if path == \AppSettings.self || path == \AppSettings.background || path == \AppSettings.background.silentAudio {
            diagnosticAudioIntent("settings.set_audio.committed")
        }
''')
    p.add('settings-load-callback',
          '            DispatchQueue.main.async { [self] in\n                busy = false\n                guard !revisionExhausted else { pump(); return }\n',
          '                diagnosticAudioIntent("settings.load.callback")\n')
    p.add('settings-load-commit',
          '                    errorMessage = nil\n                    loadState = .ready\n',
          '                    diagnosticAudioIntent("settings.load.committed")\n')
    p.add('settings-pump-enter', '    private func pump() {\n',
          '        diagnosticAudioIntent("settings.pump.enter")\n')
    p.add('settings-import-commit',
          '                markIntent(\\AppSettings.self)\n                loadState = .ready\n',
          '                diagnosticAudioIntent("settings.import.committed")\n')
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    app = args.application.resolve(strict=True)
    receipt_path = args.receipt.resolve()
    require(not (app / '.git').exists(), 'Refusing to instrument a Git worktree root')
    require('/resume/worktrees/' not in app.as_posix(), 'Refusing to instrument restored canonical worktrees')
    require(not receipt_path.exists(), 'Refusing to replace an existing diagnostic receipt')
    originals = {}
    for name, expected in {**ORIGINALS, **TESTS}.items():
        file = app / name
        require(file.is_file() and not file.is_symlink(), 'Missing/nonregular diagnostic source: ' + name)
        raw = file.read_bytes()
        require(sha(raw) == expected, 'Exact original source digest differs: ' + name)
        originals[name] = raw

    plans = [root_plan(originals['Socks5/AppRoot.swift'].decode()),
             facade_plan(originals['Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'].decode()),
             settings_plan(originals['Socks5/Settings/SettingsStore.swift'].decode())]
    for plan in plans:
        plan.prove_original_preserved()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path = receipt_path.with_suffix('.diff')
    require(not diff_path.exists(), 'Refusing to replace an existing diagnostic diff')
    diff = ''.join(''.join(difflib.unified_diff(p.original.splitlines(keepends=True), p.text.splitlines(keepends=True),
        fromfile='original/' + p.path, tofile='diagnostic-only/' + p.path)) for p in plans)
    diff_path.write_text(diff)
    files = []
    for plan in plans:
        raw = plan.text.encode()
        (app / plan.path).write_bytes(raw)
        require((app / plan.path).read_bytes() == raw, 'Diagnostic write differs: ' + plan.path)
        files.append({'path': plan.path, 'before_sha256': ORIGINALS[plan.path], 'after_sha256': sha(raw),
                      'before_bytes': len(originals[plan.path]), 'after_bytes': len(raw),
                      'removing_only_recorded_insertions_exactly_restores_original': True,
                      'operations': plan.operations})
    for name, expected in TESTS.items():
        require(sha((app / name).read_bytes()) == expected, 'Original XCTest source changed: ' + name)
    receipt = {'schema': 1, 'status': 'EPHEMERAL_DIAGNOSTIC_INSTRUMENTATION_ONLY',
               'source_commit': SOURCE_COMMIT, 'application': str(app),
               'logging': {'prefix': 'AUDIO_INTENT_TRACE', 'api': 'Foundation.NSLog',
                           'isolation': 'MainActor; per-process sequence and monotonic uptime',
                           'credentials_or_full_settings_values_logged': False,
                           'mutated_production_state': False,
                           'limitation': 'Logging can perturb scheduling. A diagnostic pass is not a release gate.'},
               'files': files, 'original_test_sources_unchanged': TESTS,
               'diff': {'path': str(diff_path), 'sha256': sha(diff.encode()), 'bytes': len(diff.encode())},
               'test_conditions_changed': False, 'diagnostic_copy_is_release_candidate': False}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'receipt': str(receipt_path), 'sha256': sha(receipt_path.read_bytes()),
                      'modified_files': list(ORIGINALS), 'test_sources_unchanged': list(TESTS)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
