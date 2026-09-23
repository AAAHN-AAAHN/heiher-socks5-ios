#!/usr/bin/env python3
"""Exercise the actual server controller without loading any persistence module."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    sources = []
    for name in ('ServerSettings.swift', 'ServerController.swift'):
        code = (ROOT / 'Socks5/Server' / name).read_text().replace('import HevSocks5Server\n', '')
        if sys.platform != 'darwin':
            code = code.replace('import SwiftUI\n', 'import Foundation\n')
        path = folder / name
        path.write_text(code)
        sources.append(str(path))
    if sys.platform != 'darwin':
        mocks = folder / 'UIMocks.swift'
        mocks.write_text('protocol ObservableObject {}\n@propertyWrapper struct Published<T> { var wrappedValue: T }\n')
        sources.append(str(mocks))
    executable = folder / 'server-tests'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', *sources,
                    str(Path(__file__).with_name('ServerMocks.swift')),
                    str(Path(__file__).with_name('ServerTests.swift')), '-o', str(executable)],
                   check=True, timeout=120)
    subprocess.run([str(executable)], check=True, timeout=45)
print('PASS: server runtime is testable without AppSettings, SettingsStore or JSON persistence.')
