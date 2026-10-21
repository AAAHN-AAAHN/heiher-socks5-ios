#!/usr/bin/env python3
"""Actual async store, blocked I/O and synchronous reentry in both Swift modes.

Linux substitutes UI/provider types only. Apple uses the actual Combine publisher.
Behavioral negative controls must compile and fail at their named assertion.
A separate compiler control verifies the nonisolated publisher requirement.
"""
import hashlib
import json
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NAME = json.loads((ROOT / 'Build/features.json').read_text())['name']
OUT = ROOT / 'artifacts' / NAME / 'async-storage'
CASES = [
    'normal', 'blocked-load', 'blocked-save', 'same-save', 'early-same-save',
    'early-overlap', 'save-failure', 'flush-retry', 'invalid-import', 'stale-import',
    'cancel-commit', 'cancel-corrupt-commit', 'supersede-commit', 'ordered-imports',
    'load-failure', 'migration', 'reentrant-edit', 'reentrant-load',
    'reentrant-import', 'reentrant-save', 'intent-stamps', 'import-during-load',
]
REVISION_CASES = ['revision-limit', 'revision-load-limit', 'revision-import-limit']
MUTANTS = [
    ('reentrant-publication', 'reentrant-edit', 'reentrant latest edit lost', [
        ('        objectWillChange.send()\n',
         '        objectWillChange.send()\n        value = next.value\n')]),
    ('duplicate-save', 'same-save', 'SAME_SAVE_DUPLICATED', [
        ('pending = next == saving || (saving == nil', 'pending = (saving == nil')]),
    ('early-pending', 'early-same-save', 'EARLY_EQUAL_LOAD_REWROTE_FILE', [
        ('pending = next != durable ? next : nil', 'pending = next != durable ? next : value')]),
    ('early-order', 'early-overlap', 'overlapping early paths must follow acceptance order', [
        ('for edit in earlyEdits { edit.apply(&next) }',
         'for edit in earlyEdits.reversed() { edit.apply(&next) }')]),
    ('stale-intent', 'supersede-commit', 'operation unexpectedly accepted', [
        ('        activeImport?.cancellation.cancel()\n', ''),
        ('guard request.revision == revision, !revisionExhausted else { throw CancellationError() }',
         'guard !revisionExhausted else { throw CancellationError() }')]),
    ('premature-migration-cleanup', 'migration', 'failed migration discarded old defaults', [
        ('let result = Result { try source.write(next.encoded(), target); cleanup?.clear() }',
         'let result = Result { cleanup?.clear(); try source.write(next.encoded(), target) }')]),
    ('unrelated-intent', 'intent-stamps', 'UNRELATED_EDIT_SUPERSEDED_SERVICE_INTENT', [
        ('let whole = path == \\AppSettings.self', 'let whole = true')]),
]


def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    OUT.mkdir(parents=True, exist_ok=True)
    names = ['Socks5/Server/ServerSettings.swift', 'Socks5/Settings/AppSettings.swift',
             'Socks5/Settings/SettingsStore.swift', 'Tests/Settings/AsyncStorageTests.swift',
             'Tests/Settings/HostUI.swift', 'Tests/Settings/HostProvider.swift']
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    results = {'sources': sources, 'head': subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(), 'commands': []}

    def run(label, args, marker=None, compile=False):
        try:
            result = subprocess.run(list(map(str, args)), cwd=ROOT, text=True,
                capture_output=True, timeout=120 if compile else 45, preexec_fn=no_core_dump)
            output = result.stdout + result.stderr
            code = result.returncode
        except subprocess.TimeoutExpired as error:
            output = str(error)
            code = 124
        (OUT / (label + '.log')).write_text(output)
        passed = (code == 0 if marker is None else code not in (0, 124) and marker in output)
        results['commands'].append(dict(label=label, argv=list(map(str, args)),
            returncode=code, expected_marker=marker, passed=passed))
        (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        if not passed:
            print(output[-16000:], file=sys.stderr, flush=True)
            raise RuntimeError('Async storage boundary failed: ' + label)
        detail = ('expected compiler rejection' if compile else 'behavioral negative control') if marker else ''
        print('PASS:', label, detail, flush=True)

    store = (ROOT / 'Socks5/Settings/SettingsStore.swift').read_text()
    if sys.platform != 'darwin':
        store = store.replace('import SwiftUI\n', 'import Foundation\n', 1)
    test = (HERE / 'AsyncStorageTests.swift').read_text()
    declared = []
    for line in test.splitlines():
        if line.strip().startswith('case "'):
            declared.extend(re.findall(r'"([^"]+)"', line.split(':', 1)[0]))
    assert set(CASES + REVISION_CASES) == set(declared), 'Async scenario lacks a runner entry'
    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        for mode in ('-Onone', '-O'):
            def compile_store(label, text, flags=(), expected_error=None):
                source = folder / (label + '.swift')
                source.write_text(text)
                executable = folder / (label + mode)
                results.setdefault('compiled_variants', {})[mode + '-' + label] = hashlib.sha256(text.encode()).hexdigest()
                args = ['swiftc', mode, *flags, '-swift-version', '5', '-strict-concurrency=complete',
                        '-warnings-as-errors', '-parse-as-library',
                        ROOT / names[0], ROOT / names[1], source,
                        HERE / 'HostUI.swift', HERE / 'HostProvider.swift',
                        HERE / 'AsyncStorageTests.swift', '-o', executable]
                run(mode + '-' + label + '-compile', args, marker=expected_error, compile=True)
                return executable

            executable = compile_store('current', store)
            for case in CASES:
                run(mode + '-' + case, [executable, case])
            declaration = 'final class SettingsStore: @MainActor ObservableObject {'
            assert store.count(declaration) == 1, 'Checked observable conformance changed'
            compile_store('unisolated-conformance', store.replace(declaration,
                'final class SettingsStore: ObservableObject {', 1), expected_error=
                "main actor-isolated property 'objectWillChange' cannot satisfy nonisolated requirement")
            boundary = store
            for before, after in [
                ('private var revision: UInt64 = 0', 'private var revision: UInt64 = UInt64.max - 1'),
                ('    func whenLoaded() async {',
                 '    var testStorageIdle: Bool { !busy }\n\n    func whenLoaded() async {'),
            ]:
                assert boundary.count(before) == 1, before
                boundary = boundary.replace(before, after, 1)
            executable = compile_store('revision-boundary', boundary, ['-DSETTINGS_REVISION_BOUNDARY'])
            for case in REVISION_CASES:
                run(mode + '-' + case, [executable, case])
            for label, case, marker, edits in MUTANTS:
                modified = store
                for before, after in edits:
                    assert modified.count(before) == 1, (label, before)
                    modified = modified.replace(before, after, 1)
                executable = compile_store(label, modified)
                run(mode + '-' + label, [executable, case], marker=marker)
    results['passed'] = True
    (OUT / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    print(f'PASS: {(len(CASES) + len(REVISION_CASES)) * 2} async schedules and {len(MUTANTS) * 2} '
          'compiled behavioral negative controls, plus 2 expected conformance compiler rejections; '
          'no physical-device claim')


if __name__ == '__main__':
    main()
