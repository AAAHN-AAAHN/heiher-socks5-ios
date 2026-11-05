#!/usr/bin/env python3
"""Add bounded intent logging only to the original driver's temporary BG app.

This is an explicitly instrumented diagnostic variant, never a source-direct
candidate or formal gate. Native receipts continue to identify original input.
The original XCTest and consumer remain separate, unchanged inputs.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import stat
import subprocess


SOURCE_COMMIT = '60e32211b1edf62c668b549043bf0bc4cdd83608'
SOURCE_TREE = '1ab318d405a516c42a59f1d9280a62639d1810fd'
DRIVER_PATH = 'Tests/Background/check_async_ui.py'
TEST_PATH = 'Tests/Background/AsyncAudioUITests.swift'
ORIGINAL_SHA256 = {
    'Socks5/AppRoot.swift': '113bda1bc09d99bca21c361ec6337afe367525c6fb5e34c375036be2b7854f0d',
    'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift': '23f77795fd16ebd6cea09d95653630fd8b458ed03d19912dd53d7cbf73c0fcfb',
    DRIVER_PATH: '5870ce10232bc22f10da0bb6e6952ae1038cd2742535cedb501e925b5f954b5f',
    TEST_PATH: '14cfa19dbd0c8a167b3ea0f1d7412456a74449cbdd3843e8a15f46d03c34f260',
}


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def file_record(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': sha256(raw),
            'mode': stat.S_IMODE(path.stat().st_mode)}


class Plan:
    def __init__(self, path, original):
        require(sha256(original) == ORIGINAL_SHA256[path],
                'Original source digest differs: ' + path)
        self.path = path
        self.original = original.decode('utf-8')
        self.text = self.original
        self.operations = []

    def replace(self, label, before, after):
        require(self.text.count(before) == 1,
                'Exact source anchor is not unique: ' + self.path + ':' + label)
        require(before != after and after not in self.text,
                'Invalid/repeated transformation: ' + label)
        self.text = self.text.replace(before, after, 1)
        self.operations.append({'kind': 'replace', 'label': label,
                                'before': before, 'after': after})

    def before(self, label, anchor, addition):
        self.replace(label, anchor, addition + anchor)

    def after(self, label, anchor, addition):
        self.replace(label, anchor, anchor + addition)

    def append(self, label, addition):
        require(addition not in self.text, 'Repeated appended block: ' + label)
        self.text += addition
        self.operations.append({'kind': 'append', 'label': label, 'addition': addition})

    def prove_reverse(self):
        restored = self.text
        for item in reversed(self.operations):
            if item['kind'] == 'append':
                require(restored.endswith(item['addition']),
                        'Cannot reverse appended block: ' + item['label'])
                restored = restored[:-len(item['addition'])]
                continue
            require(restored.count(item['after']) == 1,
                    'Cannot reverse exact recorded change: ' + item['label'])
            restored = restored.replace(item['after'], item['before'], 1)
        require(restored == self.original,
                'Reverse projection did not recover every original byte: ' + self.path)


LOGGER = r'''
// AUDIO_INTENT_DIAGNOSTIC_ONLY: added only in the temporary Simulator app.
// Each process has one MainActor sequence. Calls below occur only at intent
// entry/persistence/publication boundaries, never on a polling timer.
@MainActor
enum AudioIntentDiagnosticTrace {
    private static var sequence: UInt64 = 0

    private static func next() -> UInt64 {
        sequence += 1
        return sequence
    }

    static func root(_ point: String, requested: Bool, stored: Bool, live: Bool) {
        NSLog("AUDIO_INTENT_DIAGNOSTIC seq=%llu point=%@ requested=%d stored=%d live=%d",
              next(), point, requested ? 1 : 0, stored ? 1 : 0, live ? 1 : 0)
    }

    static func facade(_ point: String, requested: Bool, live: Bool) {
        NSLog("AUDIO_INTENT_DIAGNOSTIC seq=%llu point=%@ requested=%d live=%d",
              next(), point, requested ? 1 : 0, live ? 1 : 0)
    }

    static func change(_ point: String, previous: Bool, requested: Bool, stored: Bool, live: Bool) {
        NSLog("AUDIO_INTENT_DIAGNOSTIC seq=%llu point=%@ previous=%d requested=%d stored=%d live=%d",
              next(), point, previous ? 1 : 0, requested ? 1 : 0, stored ? 1 : 0, live ? 1 : 0)
    }
}
'''


def make_plans(originals):
    root = Plan('Socks5/AppRoot.swift', originals['Socks5/AppRoot.swift'])
    root.before(
        'binding-entry',
        '                                        keepAlive.setAudio(value)\n',
        '                                        AudioIntentDiagnosticTrace.root("binding.entry", requested: value, stored: audioEnabled, live: keepAlive.audioEnabled)\n')
    root.after(
        'binding-after-service',
        '                                        keepAlive.setAudio(value)\n',
        '                                        AudioIntentDiagnosticTrace.root("binding.after-service", requested: value, stored: audioEnabled, live: keepAlive.audioEnabled)\n')
    root.after(
        'binding-after-store',
        '                                        audioEnabled = keepAlive.audioEnabled\n',
        '                                        AudioIntentDiagnosticTrace.root("binding.after-store", requested: value, stored: audioEnabled, live: keepAlive.audioEnabled)\n')
    root.replace(
        'storage-onchange-entry-exit',
        '        .onChange(of: audioEnabled, initial: true) { _, value in keepAlive.syncAudio(value) }\n',
        '        .onChange(of: audioEnabled, initial: true) { oldValue, value in\n'
        '            AudioIntentDiagnosticTrace.change("onChange.entry", previous: oldValue, requested: value, stored: audioEnabled, live: keepAlive.audioEnabled)\n'
        '            keepAlive.syncAudio(value)\n'
        '            AudioIntentDiagnosticTrace.change("onChange.exit", previous: oldValue, requested: value, stored: audioEnabled, live: keepAlive.audioEnabled)\n'
        '        }\n')

    facade = Plan('Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift',
                  originals['Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'])
    facade.after('logger-foundation-import', 'import AVFAudio\n', 'import Foundation\n')
    facade.after(
        'setaudio-entry',
        '    func setAudio(_ enabled: Bool) {\n',
        '        AudioIntentDiagnosticTrace.facade("setAudio.entry", requested: enabled, live: audioEnabled)\n')
    facade.after(
        'setaudio-after-service',
        '        audio.setEnabled(enabled, owner: audioOwner)\n',
        '        AudioIntentDiagnosticTrace.facade("setAudio.after-service", requested: enabled, live: audioEnabled)\n')
    facade.after(
        'syncaudio-entry-and-return',
        '    func syncAudio(_ enabled: Bool) {\n',
        '        AudioIntentDiagnosticTrace.facade("syncAudio.entry", requested: enabled, live: audioEnabled)\n'
        '        defer { AudioIntentDiagnosticTrace.facade("syncAudio.exit", requested: enabled, live: audioEnabled) }\n')
    facade.before(
        'synchronous-publication-before',
        '        if changed || stopping { objectWillChange.send() }\n',
        '        if changed || stopping { AudioIntentDiagnosticTrace.facade("showAudioIntent.publish.before", requested: enabled, live: audioEnabled) }\n')
    facade.after(
        'synchronous-publication-after',
        '        if changed || stopping { objectWillChange.send() }\n',
        '        if changed || stopping { AudioIntentDiagnosticTrace.facade("showAudioIntent.publish.after", requested: enabled, live: audioEnabled) }\n')
    facade.append('logger-declaration', LOGGER)
    return [root, facade]


def diff_for(plans):
    return ''.join(''.join(difflib.unified_diff(
        plan.original.splitlines(keepends=True), plan.text.splitlines(keepends=True),
        fromfile='original/' + plan.path, tofile='diagnostic-only/' + plan.path))
        for plan in plans)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args],
                                   text=True, timeout=60).strip()


def tracked_files(root):
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'],
                                  timeout=60)
    names = raw.decode('utf-8').split('\0')
    require(names[-1] == '' and len(names[:-1]) == len(set(names[:-1])),
            'Invalid tracked source inventory')
    return names[:-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--application', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, 'Assertions must remain enabled')
    root = args.source_root.resolve(strict=True)
    app = args.application.resolve(strict=True)
    evidence = args.evidence.resolve()
    require(app == root / '.build/audio-async-ui/application',
            'Only the original driver temporary application may be instrumented')
    require(evidence == root / 'artifacts/audio-async-ui/intent-diagnostic',
            'Diagnostic evidence must remain in its separately named output')
    require(not (app / '.git').exists() and not app.is_symlink(),
            'Refusing a Git worktree or linked application')
    require(not evidence.exists(), 'Refusing repeated instrumentation or evidence overwrite')
    require(git(root, 'rev-parse', 'HEAD') == SOURCE_COMMIT and
            git(root, 'rev-parse', 'HEAD^{tree}') == SOURCE_TREE,
            'Original BG source identity changed')

    paths = tracked_files(root)
    snapshot_path = root / 'artifacts/audio-async-ui/source-sha256.json'
    snapshot = json.loads(snapshot_path.read_bytes())
    require(set(snapshot) == set(paths), 'Original driver source inventory changed')
    require(set(path.relative_to(app).as_posix()
                for path in app.rglob('*') if path.is_file()) == set(paths),
            'Temporary app is not the just-extracted original source archive')
    before = {}
    for name in paths:
        for base in (root, app):
            path = base / name
            require(path.is_file() and not path.is_symlink(),
                    'Nonregular original source input: ' + name)
            require(sha256(path.read_bytes()) == snapshot[name],
                    'Original archive/source differs before instrumentation: ' + name)
        before[name] = file_record(app / name)
    for name, digest in ORIGINAL_SHA256.items():
        require(snapshot[name] == digest, 'Pinned original differs: ' + name)
    originals = {name: (app / name).read_bytes()
                 for name in ORIGINAL_SHA256 if name.endswith('.swift') and name != TEST_PATH}
    plans = make_plans(originals)
    for plan in plans:
        plan.prove_reverse()
    patch = diff_for(plans).encode('utf-8')

    evidence.mkdir(parents=True)
    (evidence / 'instrumentation.diff').write_bytes(patch)
    for plan in plans:
        (app / plan.path).write_bytes(plan.text.encode('utf-8'))
    changed = {plan.path for plan in plans}
    for name in paths:
        require(sha256((root / name).read_bytes()) == snapshot[name],
                'Original worktree source changed: ' + name)
        if name not in changed:
            require(file_record(app / name) == before[name],
                    'Instrumentation changed an unrelated temporary input: ' + name)
    records = [{'path': plan.path, 'before': before[plan.path],
                'after': file_record(app / plan.path),
                'reverse_projection_recovers_original_bytes': True,
                'operations': plan.operations} for plan in plans]
    identity_input = {
        'baseline_commit': SOURCE_COMMIT,
        'instrumented_files': {item['path']: item['after']['sha256'] for item in records},
        'transformer_sha256': sha256(Path(__file__).read_bytes()),
    }
    variant_id = sha256(json.dumps(identity_input, sort_keys=True,
                                  separators=(',', ':')).encode())
    receipt = {
        'schema': 1,
        'status': 'INSTRUMENTED_TEMPORARY_APP_DIAGNOSTIC_ONLY',
        'variant_id': 'background-audio-intent-trace-v1:' + variant_id,
        'original_input_baseline_commit': SOURCE_COMMIT,
        'original_input_baseline_tree': SOURCE_TREE,
        'original_driver_tested_commit_is_input_baseline_not_instrumented_app_identity': True,
        'formal_gate_credit': False,
        'source_direct_candidate_pass_credit': False,
        'instrumented_app_is_original_producer_product': False,
        'original_native_inputs_verify_scope': 'Unmodified baseline source and original native producer bytes only.',
        'native_framework_instrumented': False,
        'phase': 'After original git archive extraction; before unchanged native copy/test-target creation.',
        'logging': {
            'api': 'Foundation.NSLog',
            'prefix': 'AUDIO_INTENT_DIAGNOSTIC',
            'fields': 'Fixed boundary name, per-process MainActor UInt64 sequence, previous/requested/stored/live Bool values only.',
            'periodic_observer_logging': False,
            'new_timer_task_poll_retry_tap': False,
            'limitation': 'Logging and additional value reads can affect timing. A diagnostic pass cannot resolve or replace an earlier failure.',
        },
        'original_driver': {'path': DRIVER_PATH, 'sha256': ORIGINAL_SHA256[DRIVER_PATH]},
        'original_test': {'path': TEST_PATH, 'sha256': ORIGINAL_SHA256[TEST_PATH],
                          'assertions_taps_waits_source_unchanged': True},
        'tracked_source_count': len(paths),
        'original_source_archive': file_record(root / 'artifacts/audio-async-ui/source.zip'),
        'files': records,
        'instrumentation_diff': {'bytes': len(patch), 'sha256': sha256(patch)},
        'variant_identity_input': identity_input,
    }
    (evidence / 'IDENTITY.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'diagnostic_only': True, 'formal_gate_credit': False,
                      'variant_id': receipt['variant_id'],
                      'identity_sha256': sha256((evidence / 'IDENTITY.json').read_bytes())}))


if __name__ == '__main__':
    main()
