#!/usr/bin/env python3
"""Exact-source client tests and real native loopback; no device claim."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NAME = json.loads((ROOT / 'Build/features.json').read_bytes())['name']
OUT = ROOT / 'artifacts' / NAME / 'periodic-ping'
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
    """Exact UI/iOS-import bodies, controlled provider and one export timing seam."""
    def end(text, opening):
        depth = 0
        for index in range(opening, len(text)):
            depth += (text[index] == '{') - (text[index] == '}')
            if depth == 0:
                return index
        raise AssertionError('Unbalanced import feedback source')

    view = (ROOT / 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift').read_text()
    fixture = (HERE / 'PeriodicPingImportFeedbackTests.swift.in').read_text()
    state = re.findall(r'^    @State private var ([^\n]+)$', view, flags=re.M)
    assert state and fixture.count('// STATE_DECLARATIONS') == 1
    fixture = fixture.replace('// STATE_DECLARATIONS', '\n    '.join('var ' + value for value in state))
    helper_anchor = '    private func beginPingFileRequest() -> UUID {'
    helper = ''
    assert view.count(helper_anchor) <= 1
    if helper_anchor in view:
        first = view.index(helper_anchor)
        helper = view[first:end(view, first + len(helper_anchor) - 1) + 1]
    fixture = fixture.replace('// FILE_REQUEST_HELPER', helper)
    manifest = {'view_sha256': hashlib.sha256(view.encode()).hexdigest(), 'state_declarations': state,
                'helper_sha256': hashlib.sha256(helper.encode()).hexdigest(), 'helper_exact': helper, 'actions': {}}
    for marker, anchor, callback in [
        ('IMPORT_ACTION', '.fileImporter(isPresented: $pingImporting, allowedContentTypes: [.json]) {', True),
        ('EXPORT_ACTION', 'Button("Export ping JSON") {', False),
        ('RETRY_ACTION', 'Button("Retry Save") {', False),
        ('EXPORT_COMPLETION', 'defaultFilename: "periodic-ping") {', True),
        ('IMPORT_OPEN_ACTION', 'Button("Import ping JSON") {', False),
    ]:
        assert view.count(anchor) == 1 and fixture.count('// ' + marker) == 1
        opening = view.index(anchor) + len(anchor) - 1
        action = view[opening + 1:end(view, opening)]
        if callback:
            assert action.startswith(' result in')
            action = action[len(' result in'):]
        manifest['actions'][marker] = {'sha256': hashlib.sha256(action.encode()).hexdigest(), 'exact_body': action}
        if marker not in ('EXPORT_COMPLETION', 'IMPORT_OPEN_ACTION'):
            assert action.count('Task { @MainActor in') == 1
            start = action.index('Task { @MainActor in')
            finish = end(action, action.index('{', start)) + 1
            action = action[:start] + '_ = await ' + action[start:finish] + '.value' + action[finish:]
        fixture = fixture.replace('// ' + marker, action)
    test = work / 'PeriodicPingImportFeedbackTests.swift'
    test.write_text(fixture)
    text = (ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingModel.swift').read_text()
    manifest['model_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    anchor = '    func importFile(_ url: URL) async throws {'
    assert text.count(anchor) == 1
    opening = text.index(anchor) + len(anchor) - 1
    method = text[text.index(anchor):end(text, opening) + 1]
    export_anchor = '    func exportData() async throws -> Data {'
    assert text.count(export_anchor) == 1
    first = text.index(export_anchor)
    export = text[first:end(text, first + len(export_anchor) - 1) + 1]
    before, after = 'try JSONEncoder().encode(snapshot)', 'try PingExportBoundary.shared.encode(snapshot)'
    assert export.count(before) == 1
    text = text.replace(export, export.replace(before, after), 1)
    manifest['export_timing_substitution'] = {'original': before, 'replacement': after, 'count': 1}
    manifest['import_method_sha256'] = hashlib.sha256(method.encode()).hexdigest()
    model = work / 'PeriodicPingModel-with-importFile.swift'
    # Same-file extension preserves private access. The original model remains
    # intact and its exact iOS method is exposed only for this non-iOS harness.
    model.write_text(text + '\n#if !os(iOS)\nextension PeriodicPingModel {\n' + method + '\n}\n#endif\n')
    (work / 'import-feedback-source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return model, test


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, default=Path(os.environ.get('HEV_NATIVE_CORE', ROOT / '.build/server')))
    core = parser.parse_args().core.resolve()
    headers = ['hev-main.h', 'hev-socks5-icmp.h']
    if any(not (core / 'src' / name).is_file() for name in headers):
        raise SystemExit('Prepare the declared native ICMP sources first; expected actual public headers in ' + str(core / 'src'))
    if 'hev_socks5_server_icmp_client_new' not in (core / 'src/hev-socks5-icmp.h').read_text():
        raise SystemExit('Prepared native sources do not expose the ICMP client API')
    module = OUT / 'compiled-headers'
    module.mkdir(exist_ok=True)
    for name in headers:
        (module / name).write_bytes((core / 'src' / name).read_bytes())
    (module / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
    (module / 'SHA256SUMS.txt').write_text(''.join(
        hashlib.sha256((module / name).read_bytes()).hexdigest() + '  ' + name + '\n'
        for name in [*headers, 'module.modulemap']))
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
        run('compile-native-api-double', ['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-pthread',
                                         '-I', module, '-c', HERE / 'PeriodicPingIO.c', '-o', io])
        extra = ['-I', module, '-Xlinker', '-lpthread']
        if platform.system() == 'Linux':
            stub = work / 'Combine.swift'
            stub.write_text(COMBINE_DOUBLE)
            run('compile-publisher-double', ['swiftc', '-warnings-as-errors', '-emit-module', '-emit-library', '-module-name', 'Combine', stub,
                                           '-o', work / 'libCombine.so'])
            extra += ['-I', work, '-L', work, '-lCombine', '-Xlinker', '-rpath', '-Xlinker', work,
                      '-Xlinker', '-ldl']
        feedback = import_feedback_sources(work)
        (OUT / 'import-feedback-source-manifest.json').write_bytes(
            (work / 'import-feedback-source-manifest.json').read_bytes())
        for flag, mode in [('-Onone', 'debug'), ('-O', 'optimized')]:
            common = ['swiftc', '-swift-version', '6', '-strict-concurrency=complete', '-warnings-as-errors', flag,
                      ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingService.swift']
            for name, model in [('PeriodicPingTests', False), ('PeriodicPingModelTests', True)]:
                output = work / (mode + '-' + name)
                inputs = [ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingModel.swift'] if model else []
                run(mode + '-' + name + '-compile', common + inputs + [HERE / (name + '.swift'), io, *extra, '-o', output])
                run(mode + '-' + name + '-run', [output])
            feedback_binary = work / (mode + '-import-feedback')
            run(mode + '-import-feedback-compile', common + [*feedback, io, *extra, '-o', feedback_binary])
            for case in [
                'delayed-export-alone', 'delayed-export-new-import-picker',
                'normal-success', 'normal-invalid', 'normal-provider-failure', 'normal-storage-failure', 'normal-retry-success',
                'old-success-new-invalid', 'old-failure-new-invalid', 'old-failure-new-export',
                'old-provider-failure-new-success', 'old-cancel-new-success', 'old-provider-failure-new-export',
                'old-provider-failure-new-retry', 'current-cancel-off',
            ]:
                run(mode + '-import-feedback-' + case, [feedback_binary, case])
        live = work / 'icmp-loopback'
        run('native-library-build', ['make', '-C', core, '-j3', 'ENABLE_IO_SPLICE_SYSCALL=0', 'static'])
        libraries = [core / 'bin/libhev-socks5-server.a', core / 'third-part/yaml/bin/libyaml.a',
                     core / 'third-part/hev-task-system/bin/libhev-task-system.a']
        run('loopback-compile', ['swiftc', '-swift-version', '6', '-strict-concurrency=complete',
                                '-warnings-as-errors', '-O', '-I', module,
                                ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingService.swift',
                                HERE / 'PeriodicPingLoopback.swift', *libraries, '-Xlinker', '-lpthread', '-o', live])
        run('loopback-run', [live], accepted=(0, 77) if platform.system() == 'Linux' else (0,))
    (OUT / 'SUCCESS.txt').write_text('PASS: controlled native client/model tests; actual native loopback result is separate (77 means NOT EXECUTED). No device/SDK/UI claim.\n')
    print(f'PASS: {len(records)} compile/runtime commands; actual native header/ABI, controlled callbacks and separate real loopback')


if __name__ == '__main__':
    main()
