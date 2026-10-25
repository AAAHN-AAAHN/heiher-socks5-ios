#!/usr/bin/env python3
"""Exact-source ping tests: real Dispatch, controlled ICMP syscalls, no device claim."""
import json
import platform
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'artifacts/periodic-ping'
COMBINE_DOUBLE = '''
public protocol ObservableObject: AnyObject {
    var objectWillChange: ObservableObjectPublisher { get }
}
@MainActor public final class AnyCancellable {
    private let finish: () -> Void
    public init(_ finish: @escaping () -> Void) { self.finish = finish }
    public func cancel() { finish() }
}
@MainActor public final class ObservableObjectPublisher {
    private var callback: ((()) -> Void)?
    public init() {}
    public func send() { callback?(()) }
    public func sink(receiveValue: @escaping (()) -> Void) -> AnyCancellable {
        callback = receiveValue
        return AnyCancellable { [weak self] in self?.callback = nil }
    }
}
'''


def import_feedback_sources(work):
    """Exercise exact UI actions and iOS import code with a controlled provider."""
    def end(text, opening):
        depth = 0
        for index in range(opening, len(text)):
            depth += (text[index] == '{') - (text[index] == '}')
            if depth == 0:
                return index
        raise AssertionError('Unbalanced import feedback source')

    view = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift').read_text()
    fixture = (HERE / 'PeriodicPingImportFeedbackTests.swift.in').read_text()
    for marker, anchor, callback in [
        ('IMPORT_ACTION', '.fileImporter(isPresented: $pingImporting, allowedContentTypes: [.json]) {', True),
        ('EXPORT_ACTION', 'Button("Export ping JSON") {', False),
        ('RETRY_ACTION', 'Button("Retry Save") {', False),
        ('EXPORT_COMPLETION', 'defaultFilename: "periodic-ping") {', True),
    ]:
        assert view.count(anchor) == 1 and fixture.count('// ' + marker) == 1
        opening = view.index(anchor) + len(anchor) - 1
        action = view[opening + 1:end(view, opening)]
        if callback:
            assert action.startswith(' result in')
            action = action[len(' result in'):]
        if marker != 'EXPORT_COMPLETION':
            assert action.count('Task { @MainActor in') == 1
            start = action.index('Task { @MainActor in')
            finish = end(action, action.index('{', start)) + 1
            action = action[:start] + '_ = await ' + action[start:finish] + '.value' + action[finish:]
        fixture = fixture.replace('// ' + marker, action)
    test = work / 'PeriodicPingImportFeedbackTests.swift'
    test.write_text(fixture)
    text = (ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingModel.swift').read_text()
    anchor = '    func importFile(_ url: URL) async throws {'
    assert text.count(anchor) == 1
    opening = text.index(anchor) + len(anchor) - 1
    method = text[text.index(anchor):end(text, opening) + 1]
    model = work / 'PeriodicPingModel-with-importFile.swift'
    # Same-file extension preserves private access. The original model remains
    # intact and its exact iOS method is exposed only for this non-iOS harness.
    model.write_text(text + '\n#if !os(iOS)\nextension PeriodicPingModel {\n' + method + '\n}\n#endif\n')
    return model, test


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix='periodic-ping-') as folder:
        work = Path(folder)

        def run(label, command, accepted=(0,)):
            result = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, text=True, timeout=120)
            (OUT / (label + '.log')).write_text(result.stdout + result.stderr)
            records.append({'label': label, 'command': list(map(str, command)), 'returncode': result.returncode})
            (OUT / 'commands.json').write_text(json.dumps(records, indent=2) + '\n')
            if result.returncode not in accepted:
                result.check_returncode()

        io = work / 'io.o'
        run('compile-syscall-double', ['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-c', HERE / 'PeriodicPingIO.c', '-o', io])
        extra = []
        if platform.system() == 'Linux':
            stub = work / 'Combine.swift'
            stub.write_text(COMBINE_DOUBLE)
            run('compile-publisher-double', ['swiftc', '-warnings-as-errors', '-emit-module', '-emit-library', '-module-name', 'Combine', stub,
                                           '-o', work / 'libCombine.so'])
            extra = ['-I', work, '-L', work, '-lCombine', '-Xlinker', '-rpath', '-Xlinker', work]
        feedback = import_feedback_sources(work)
        for flag, mode in [('-Onone', 'debug'), ('-O', 'optimized')]:
            common = ['swiftc', '-swift-version', '5', '-strict-concurrency=complete', '-warnings-as-errors', flag,
                      ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingService.swift']
            for name, model in [('PeriodicPingTests', False), ('PeriodicPingModelTests', True)]:
                output = work / (mode + '-' + name)
                inputs = [ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingModel.swift'] if model else []
                run(mode + '-' + name + '-compile', common + inputs + [HERE / (name + '.swift'), io, *extra, '-o', output])
                run(mode + '-' + name + '-run', [output])
            feedback_binary = work / (mode + '-import-feedback')
            run(mode + '-import-feedback-compile', common + [*feedback, io, *extra, '-o', feedback_binary])
            for case in [
                'normal-success', 'normal-invalid', 'normal-provider-failure', 'normal-storage-failure', 'normal-retry-success',
                'old-success-new-invalid', 'old-failure-new-invalid', 'old-failure-new-export',
                'old-provider-failure-new-success', 'old-cancel-new-success', 'old-provider-failure-new-export',
                'old-provider-failure-new-retry', 'current-cancel-off',
            ]:
                run(mode + '-import-feedback-' + case, [feedback_binary, case])
        live = work / 'icmp-loopback'
        run('loopback-compile', ['swiftc', '-swift-version', '5', '-strict-concurrency=complete',
                                '-warnings-as-errors', '-O', ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingService.swift',
                                HERE / 'PeriodicPingLoopback.swift', '-o', live])
        run('loopback-run', [live], accepted=(0, 77) if platform.system() == 'Linux' else (0,))
    (OUT / 'SUCCESS.txt').write_text('PASS: controlled sender/model tests; loopback result is separate (77 means NOT EXECUTED). No device/SDK/UI claim.\n')
    print(f'PASS: {len(records)} compile/runtime commands; controlled I/O, no product source changes')


if __name__ == '__main__':
    main()
