#!/usr/bin/env python3
"""Test actual JSON/storage code; no app archive or IPA. Host access tests are unprivileged."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
mode = sys.argv[1] if len(sys.argv) == 2 else ''
if len(sys.argv) > 2 or mode not in ('', '--baseline-import', '--previous-store'):
    raise SystemExit('Only --baseline-import or --previous-store is supported.')
baseline = mode == '--baseline-import'
previous = mode == '--previous-store'
reference = '9c2e76afcde7a20ff1bbdcf2a1f7e9092e1a98fd'
previous_ref = '633c04905ed7ca4acd7272fb040c8d1c66cb38e3'


def drop_privileges():
    # CI already runs as a normal user. Root-based local containers must not bypass
    # directory permissions and report an invalid filesystem test as successful.
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)


with tempfile.TemporaryDirectory() as name:
    temp = Path(name)
    files = ['Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift',
             'Socks5/Server/ServerSettings.swift']
    for path in files:
        if baseline and path.endswith('ServerSettings.swift'):
            continue
        ref = reference if baseline else (previous_ref if previous and path.endswith('SettingsStore.swift') else None)
        raw = (subprocess.check_output(['git', '-C', str(root), 'show', ref + ':' + path])
               if ref else (root / path).read_bytes())
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
struct Binding<T> {
    let get: () -> T; let set: (T) -> Void
    init(get: @escaping () -> T, set: @escaping (T) -> Void) { self.get = get; self.set = set }
    var wrappedValue: T { get { get() } nonmutating set { set(newValue) } }
}
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
    groups = [(['SettingsTests.swift'], provider, None),
              (['ValidationTests.swift'], provider, None),
              (['CoordinationMocks.swift', 'ImportTests.swift'], [], None),
              (['PersistenceRevalidation.swift'], provider, '31 persistence revalidation assertions; 4 failed'),
              (['LoadAccessTests.swift'], provider, '6 access-boundary assertions; 1 failed')]
    if baseline:
        groups = groups[2:3]
    elif previous:
        groups = groups[3:]
    preexec, env = None, dict(os.environ)
    if os.geteuid() == 0:
        temp.chmod(0o755)
        home = temp / 'home'; home.mkdir(); home.chmod(0o777)
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'))
        preexec = drop_privileges
    for index, (tests, platform, expected) in enumerate(groups):
        executable = temp / f'checks-{index}'
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                        *ui, *platform, *([] if baseline else [str(temp / 'ServerSettings.swift')]),
                        str(temp / 'AppSettings.swift'), str(temp / 'SettingsStore.swift'),
                        *[str(Path(__file__).with_name(p)) for p in tests],
                        '-o', str(executable)], check=True, timeout=120)
        result = subprocess.run([str(executable)], text=True, capture_output=True, timeout=45,
                                env=env, preexec_fn=preexec)
        print(result.stdout, end='', flush=True)
        print(result.stderr, end='', file=sys.stderr, flush=True)
        if baseline or previous:
            expected = '15 import/migration assertions; 13 failed' if baseline else expected
            if result.returncode != 1 or expected not in result.stdout:
                raise RuntimeError('Negative control did not reproduce expected defects: ' + str(expected))
            print('NEGATIVE CONTROL CONFIRMED:', expected)
        else:
            result.check_returncode()
