#!/usr/bin/env python3
"""Test production JSON/storage/lifecycle code without app archives or IPA output."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
baseline = len(sys.argv) == 2 and sys.argv[1] == '--baseline-import'
if sys.argv[1:] and not baseline:
    raise SystemExit('Only --baseline-import is supported.')
reference = '9c2e76afcde7a20ff1bbdcf2a1f7e9092e1a98fd'
with tempfile.TemporaryDirectory() as name:
    temp = Path(name)
    files = ['Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift']
    if not baseline:
        files.insert(0, 'Socks5/Server/ServerSettings.swift')
    for path in files:
        raw = (subprocess.check_output(['git', '-C', str(root), 'show', reference + ':' + path])
               if baseline else (root / path).read_bytes())
        print('SOURCE', path, hashlib.sha256(raw).hexdigest(), flush=True)
        code = raw.decode().replace('import HevSocks5Server\n', '')
        if sys.platform != 'darwin':
            code = code.replace('import SwiftUI\n', 'import Foundation\n')
        (temp / Path(path).name).write_text(code)
    ui, provider = [], []
    if sys.platform != 'darwin':
        (temp / 'UIMocks.swift').write_text('''import Foundation
protocol ObservableObject {}
@propertyWrapper struct Published<T> { var wrappedValue: T }
struct Binding<T> { init(get: @escaping () -> T, set: @escaping (T) -> Void) {} }
''')
        (temp / 'ProviderMocks.swift').write_text('''import Foundation
class NSFileCoordinator {
    init(filePresenter: Any?) {}
    func coordinate(readingItemAt url: URL, options: [Int], error: UnsafeMutablePointer<NSError?>?, byAccessor: (URL) -> Void) { byAccessor(url) }
}
extension URL {
    func startAccessingSecurityScopedResource() -> Bool { true }
    func stopAccessingSecurityScopedResource() {}
}
''')
        ui = [str(temp / 'UIMocks.swift')]
        provider = [str(temp / 'ProviderMocks.swift')]
    groups = [(['AppSettings.swift', 'SettingsStore.swift'], ['SettingsTests.swift'], provider),
              (['AppSettings.swift', 'SettingsStore.swift'], ['ValidationTests.swift'], provider),
              (['AppSettings.swift', 'SettingsStore.swift'], ['CoordinationMocks.swift', 'ImportTests.swift'], [])]
    if baseline:
        groups = groups[-1:]
    if not baseline:
        groups = [(['ServerSettings.swift'] + production, tests, platform)
                  for production, tests, platform in groups]
    for index, (production, tests, platform) in enumerate(groups):
        executable = temp / f'checks-{index}'
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                        *ui, *platform, *[str(temp / p) for p in production],
                        *[str(Path(__file__).with_name(p)) for p in tests],
                        '-o', str(executable)], check=True, timeout=120)
        result = subprocess.run([str(executable)], text=True, capture_output=True, timeout=45)
        print(result.stdout, end='', flush=True)
        print(result.stderr, end='', file=sys.stderr, flush=True)
        if baseline:
            if result.returncode != 1 or '15 import/migration assertions; 13 failed' not in result.stdout:
                raise RuntimeError('Original-store negative control did not reproduce the expected defects')
            print('NEGATIVE CONTROL CONFIRMED: original production store fails the same 13 postconditions.')
        else:
            result.check_returncode()
