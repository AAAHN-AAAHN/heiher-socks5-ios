#!/usr/bin/env python3
"""Verify server control without persistent settings, using the production bodies."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as name:
    temp = Path(name)
    sources = []
    for path in ['ServerSettings.swift', 'ServerController.swift']:
        code = (ROOT / 'Socks5/Server' / path).read_text().replace('import HevSocks5Server\n', '')
        if sys.platform != 'darwin':
            code = code.replace('import SwiftUI\n', 'import Foundation\n')
        output = temp / path
        output.write_text(code)
        sources.append(str(output))
    mocks = []
    if sys.platform != 'darwin':
        (temp / 'UI.swift').write_text('import Foundation\nprotocol ObservableObject {}\n@propertyWrapper struct Published<T> { var wrappedValue: T }\n')
        mocks.append(str(temp / 'UI.swift'))
    executable = temp / 'server-tests'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', *mocks, *sources,
                    str(Path(__file__).with_name('ServerMocks.swift')),
                    str(Path(__file__).with_name('ServerTests.swift')), '-o', str(executable)], check=True, timeout=120)
    subprocess.run([str(executable)], check=True, timeout=45)
    # Compare extraction against the exact last audited model, not a rewritten oracle.
    original = subprocess.check_output(['git', '-C', str(ROOT), 'show',
        '16689f780f3e0e0c9344397273528697f197c9e5:Socks5/Settings/AppSettings.swift'], text=True)
    original = original.replace('AppSettings', 'OriginalAppSettings').replace('ServerSettings', 'OriginalServerSettings').replace('SettingsError', 'OriginalSettingsError')
    (temp / 'Original.swift').write_text(original)
    parity = temp / 'parity'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                    str(ROOT / 'Socks5/Server/ServerSettings.swift'), str(temp / 'Original.swift'),
                    str(Path(__file__).with_name('ConfigurationParity.swift')), '-o', str(parity)], check=True, timeout=120)
    subprocess.run([str(parity)], check=True, timeout=30)
