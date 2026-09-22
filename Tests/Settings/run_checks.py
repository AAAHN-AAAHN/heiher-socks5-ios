#!/usr/bin/env python3
"""Test production JSON storage and server lifecycle; no test code enters the IPA."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as name:
    temp = Path(name)
    files = ['Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift',
             'Socks5/Server/ServerController.swift']
    for path in files:
        code = (root / path).read_text().replace('import HevSocks5Server\n', '')
        if sys.platform != 'darwin':
            code = code.replace('import SwiftUI\n', 'import Foundation\n')
        (temp / Path(path).name).write_text(code)
    mocks = []
    if sys.platform != 'darwin':
        (temp / 'UIMocks.swift').write_text('''import Foundation
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
        mocks = [str(temp / 'UIMocks.swift')]
    groups = [(['AppSettings.swift', 'SettingsStore.swift'], ['SettingsTests.swift']),
              (['AppSettings.swift', 'ServerController.swift'], ['ServerMocks.swift', 'ServerTests.swift'])]
    for index, (production, tests) in enumerate(groups):
        executable = temp / f'checks-{index}'
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                        *mocks, *[str(temp / p) for p in production],
                        *[str(Path(__file__).with_name(p)) for p in tests],
                        '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
