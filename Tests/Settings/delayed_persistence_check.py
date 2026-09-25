#!/usr/bin/env python3
"""Verify the inherited late-Stop repair through the unchanged JSON store.

Only delivery timing and Linux UI/provider types are fixtures; the actual store,
controller, file operations and native server execute. This is not a UI/device test.
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
OLD = '011f7f61b2969f7a85708d535d3ad466a9ac148e'


def main():
    core, output = (Path(p).resolve() for p in sys.argv[1:3])
    output.mkdir(parents=True, exist_ok=True)
    old = subprocess.check_output(['git', '-C', str(ROOT), 'show', OLD + ':Socks5/Server/ServerController.swift'])
    assert hashlib.sha256(old).hexdigest() == 'f1e8630315c629fbda7ffb6928aed7d62511c20acf27864ff1030a1904070098'
    libs = [core / 'bin/libhev-socks5-server.a', core / 'third-part/yaml/bin/libyaml.a',
            core / 'third-part/hev-task-system/bin/libhev-task-system.a']
    rows = []
    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        include = folder / 'include'; include.mkdir()
        shutil.copyfile(core / 'src/hev-main.h', include / 'hev-main.h')
        (include / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
        for label in ('original-controller', 'current-controller'):
            part = folder / label; part.mkdir()
            sources = [str(Path(__file__).with_name('PersistenceDelayed.swift'))]
            for path in ('Socks5/Server/ServerSettings.swift', 'Socks5/Server/ServerController.swift',
                         'Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift'):
                data = old if label == 'original-controller' and path.endswith('/ServerController.swift') else (ROOT / path).read_bytes()
                text = data.decode()
                if sys.platform != 'darwin': text = text.replace('import SwiftUI\n', 'import Foundation\n', 1)
                dest = part / Path(path).name; dest.write_text(text); sources.append(str(dest))
            if sys.platform != 'darwin':
                mock = part / 'Platform.swift'
                mock.write_text('''import Foundation
protocol ObservableObject {}
@propertyWrapper struct Published<T> { var wrappedValue: T }
struct Binding<T> { init(get: @escaping () -> T, set: @escaping (T) -> Void) {} }
class NSFileCoordinator {
    init(filePresenter: Any?) {}
    func coordinate(readingItemAt url: URL, options: [Int], error: UnsafeMutablePointer<NSError?>?, byAccessor: (URL) -> Void) { byAccessor(url) }
}
extension URL {
    func startAccessingSecurityScopedResource() -> Bool { true }
    func stopAccessingSecurityScopedResource() {}
}
''')
                sources.append(str(mock))
            executable = part / 'host'
            with (output / (label + '-compile.log')).open('w') as log:
                subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', '-I', str(include),
                                *sources, *map(str, libs), '-Xlinker', '-lpthread', '-o', str(executable)],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
            for workers in ('1', '4'):
                with socket.socket() as occupied, socket.socket() as reserve:
                    occupied.bind(('127.0.0.1', 0)); occupied.listen()
                    reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]; reserve.close()
                    result = subprocess.run([str(executable), str(part / ('settings-' + workers + '.json')),
                        str(occupied.getsockname()[1]), str(port), workers], capture_output=True, text=True, timeout=8)
                expected = 42 if label == 'original-controller' else 0
                row = dict(controller=label, workers=int(workers), returncode=result.returncode,
                           expected=expected, stdout=result.stdout, stderr=result.stderr)
                rows.append(row); (output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
                assert result.returncode == expected, row
    print('PASS: old controller fails both stored-import schedules; current controller passes both; JSON remains complete in all four.')


if __name__ == '__main__':
    if not __debug__: raise SystemExit('Assertions required')
    main()
