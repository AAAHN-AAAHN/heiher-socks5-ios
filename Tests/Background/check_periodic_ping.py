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
@MainActor public protocol ObservableObject: AnyObject {}
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
        for flag, mode in [('-Onone', 'debug'), ('-O', 'optimized')]:
            common = ['swiftc', '-swift-version', '5', '-strict-concurrency=complete', '-warnings-as-errors', flag,
                      ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingService.swift']
            for name, model in [('PeriodicPingTests', False), ('PeriodicPingModelTests', True)]:
                output = work / (mode + '-' + name)
                inputs = [ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingModel.swift'] if model else []
                run(mode + '-' + name + '-compile', common + inputs + [HERE / (name + '.swift'), io, *extra, '-o', output])
                run(mode + '-' + name + '-run', [output])
        live = work / 'icmp-loopback'
        run('loopback-compile', ['swiftc', '-swift-version', '5', '-strict-concurrency=complete',
                                '-warnings-as-errors', '-O', ROOT / 'Socks5/BackgroundKeepAlive/PeriodicPingService.swift',
                                HERE / 'PeriodicPingLoopback.swift', '-o', live])
        run('loopback-run', [live], accepted=(0, 77) if platform.system() == 'Linux' else (0,))
    (OUT / 'SUCCESS.txt').write_text('PASS: controlled sender/model tests; loopback result is separate (77 means NOT EXECUTED). No device/SDK/UI claim.\n')
    print(f'PASS: {len(records)} compile/runtime commands; controlled I/O, no product source changes')


if __name__ == '__main__':
    main()
