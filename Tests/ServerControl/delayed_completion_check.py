#!/usr/bin/env python3
"""Actual native-return/MainActor-delivery gap regression. No IPA or UI mocks.

Only UI observation types on Linux are substituted. Native code, the current
controller body and the old-controller negative control remain unchanged.
"""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = '011f7f61b2969f7a85708d535d3ad466a9ac148e'
OLD_SHA256 = 'f1e8630315c629fbda7ffb6928aed7d62511c20acf27864ff1030a1904070098'


def main():
    core, output = (Path(p).resolve() for p in sys.argv[1:3])
    output.mkdir(parents=True, exist_ok=True)
    before = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                     BASE + ':Socks5/Server/ServerController.swift'])
    if hashlib.sha256(before).hexdigest() != OLD_SHA256:
        raise AssertionError('The negative control is not the reviewed original controller')
    libs = [core / 'bin/libhev-socks5-server.a', core / 'third-part/yaml/bin/libyaml.a',
            core / 'third-part/hev-task-system/bin/libhev-task-system.a']
    records = []
    with tempfile.TemporaryDirectory() as name:
        temp = Path(name)
        include = temp / 'include'; include.mkdir()
        shutil.copyfile(core / 'src/hev-main.h', include / 'hev-main.h')
        (include / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
        for label, controller in [('original', before), ('current', (ROOT / 'Socks5/Server/ServerController.swift').read_bytes())]:
            folder = temp / label; folder.mkdir()
            sources = [ROOT / 'Socks5/Server/ServerSettings.swift',
                       Path(__file__).with_name('DelayedCompletionHost.swift')]
            code = controller.decode()
            if sys.platform != 'darwin':
                code = code.replace('import SwiftUI\n', 'import Foundation\n', 1)
                ui = folder / 'UI.swift'
                ui.write_text('protocol ObservableObject {}\n@propertyWrapper struct Published<T> { var wrappedValue: T }\n')
                sources.append(ui)
            copied = folder / 'ServerController.swift'; copied.write_text(code); sources.append(copied)
            executable = folder / 'host'
            with (output / (label + '-build.log')).open('w') as log:
                subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', '-I', str(include),
                                *map(str, sources), *map(str, libs), '-Xlinker', '-lpthread', '-o', str(executable)],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
            for workers in ('1', '4'):
                for mode in range(4):
                    with socket.socket() as occupied, socket.socket() as reserve:
                        occupied.bind(('127.0.0.1', 0)); occupied.listen()
                        reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]; reserve.close()
                        result = subprocess.run([str(executable), str(occupied.getsockname()[1]),
                                                 str(port), str(mode), workers],
                                                capture_output=True, text=True, timeout=8)
                    expected = 42 if label == 'original' and mode != 3 else 0
                    record = dict(controller=label, workers=int(workers), mode=mode,
                                  returncode=result.returncode, expected=expected,
                                  stdout=result.stdout, stderr=result.stderr)
                    records.append(record)
                    (output / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
                    if result.returncode != expected:
                        raise AssertionError(record)
        executable = temp / 'prepared-stop'
        with (output / 'prepared-stop-build.log').open('w') as log:
            subprocess.run(['clang', '-std=gnu11', '-O2', '-Wall', '-Werror', '-pthread',
                            '-I' + str(core / 'src'), str(Path(__file__).with_name('PrepareStopProbe.c')),
                            *map(str, libs), '-o', str(executable)],
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        with (output / 'prepared-stop.log').open('w') as log:
            for workers in ('1', '4'):
                with socket.socket() as reserve:
                    reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
                subprocess.run([str(executable), workers, str(port)], stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=12)
    print('PASS: eight current schedules; six original expected failures and two original Stop controls; 100 legacy/prepared early cancellations.')
    print('Scope: native host; deliberately delayed actor callback, not an actual iOS UI stall.')


if __name__ == '__main__':
    main()
