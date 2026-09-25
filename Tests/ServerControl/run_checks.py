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
    for test in ('ServerTests', 'RevalidationTests'):
        executable = temp / test
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', *mocks, *sources,
                        str(Path(__file__).with_name('ServerMocks.swift')),
                        str(Path(__file__).with_name(test + '.swift')), '-o', str(executable)], check=True, timeout=120)
        subprocess.run([str(executable)], check=True, timeout=45)
    # The old equality must fail the same byte-sensitive postconditions.
    old = temp / 'OldServerSettings.swift'
    old.write_bytes(subprocess.check_output(['git', '-C', str(ROOT), 'show',
        '68599f96331f3f45e3fa271db02e6ede0fc35d73:Socks5/Server/ServerSettings.swift']))
    negative = temp / 'old-equality'
    subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', *mocks,
                    str(old), sources[1], str(Path(__file__).with_name('ServerMocks.swift')),
                    str(Path(__file__).with_name('RevalidationTests.swift')), '-o', str(negative)], check=True, timeout=120)
    result = subprocess.run([str(negative), '--unicode-only'], text=True, capture_output=True, timeout=45)
    print(result.stdout, end='', flush=True)
    if result.returncode != 1 or '22 server revalidation assertions; 22 failed' not in result.stdout:
        raise RuntimeError('Original equality negative control failed to reproduce: ' + result.stderr)
    print('PASS: original model fails 22 specified byte-sensitive postconditions; current model passes')
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
