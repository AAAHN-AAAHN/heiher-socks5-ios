#!/usr/bin/env python3
"""Test actual JSON/storage code; no app archive or IPA. Host access tests are unprivileged."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled')

root = Path(__file__).resolve().parents[2]
mode = sys.argv[1] if len(sys.argv) == 2 else ''
if len(sys.argv) > 2 or mode not in ('', '--baseline-import', '--previous-store'):
    raise SystemExit('Only --baseline-import or --previous-store is supported.')
baseline = mode == '--baseline-import'
previous = mode == '--previous-store'
reference = '9c2e76afcde7a20ff1bbdcf2a1f7e9092e1a98fd'
previous_ref = '633c04905ed7ca4acd7272fb040c8d1c66cb38e3'
# These tests describe the synchronous API of both historical controls. Keep
# their exact source with those old stores instead of weakening their assertions
# to accommodate the current asynchronous API.
historical_tests = 'a22bc4579a82e46b9e20389182bc1e63e6deedbf'


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
        ref = reference if baseline else (previous_ref if previous and path.endswith('SettingsStore.swift') else
              'c1722e48f99e140b98cc436979b8ffc49ca0fa63' if previous and path.endswith('AppSettings.swift') else None)
        raw = (subprocess.check_output(['git', '-C', str(root), 'show', ref + ':' + path])
               if ref else (root / path).read_bytes())
        print('SOURCE', path, hashlib.sha256(raw).hexdigest(), flush=True)
        code = raw.decode().replace('import HevSocks5Server\n', '')
        if sys.platform != 'darwin':
            code = code.replace('import SwiftUI\n', 'import Foundation\n')
        (temp / Path(path).name).write_text(code)
    ui, provider = [], []
    if sys.platform != 'darwin':
        (temp / 'UIMocks.swift').write_bytes(Path(__file__).with_name('HostUI.swift').read_bytes())
        (temp / 'ProviderMocks.swift').write_bytes(Path(__file__).with_name('HostProvider.swift').read_bytes())
        ui = [str(temp / 'UIMocks.swift')]
        provider = [str(temp / 'ProviderMocks.swift')]
    groups = [(['SettingsTests.swift'], provider, None),
              (['ValidationTests.swift'], provider, None),
              (['CoordinationMocks.swift', 'ImportTests.swift'], [], None),
              (['PersistenceRevalidation.swift'], provider, '33 persistence revalidation assertions; 4 failed'),
              (['LoadAccessTests.swift'], provider, '6 access-boundary assertions; 1 failed')]
    if not baseline and not previous:
        groups.append((['FinalPersistenceTests.swift'], provider, None))
        groups.append((['PeriodicPingPersistenceTests.swift'], provider, None))
        groups.append((['FinalCoordination.swift'], [], None))
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
        store = temp / 'SettingsStore.swift'
        if tests == ['FinalCoordination.swift']:
            # Redirect only the two OS-scope calls to counted test boundaries.
            # The store's coordination, cancellation, revision and write body is exact.
            body = store.read_text()
            for original_name, test_name in [('startAccessingSecurityScopedResource', 'testScopeStart'),
                                             ('stopAccessingSecurityScopedResource', 'testScopeStop')]:
                assert body.count(original_name + '()') == 1
                body = body.replace(original_name + '()', test_name + '()')
            store = temp / 'SettingsStore-scope-boundary.swift'
            store.write_text(body)
        test_sources = []
        for test in tests:
            raw = (subprocess.check_output(['git', '-C', str(root), 'show',
                       historical_tests + ':Tests/Settings/' + test])
                   if baseline or previous else Path(__file__).with_name(test).read_bytes())
            destination = temp / test
            destination.write_bytes(raw)
            print('TEST_SOURCE', test, hashlib.sha256(raw).hexdigest(), flush=True)
            test_sources.append(str(destination))
        support = [] if baseline or previous else [str(Path(__file__).with_name('StorageTestSupport.swift'))]
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors',
                        *ui, *platform, *([] if baseline else [str(temp / 'ServerSettings.swift')]),
                        str(temp / 'AppSettings.swift'), str(store),
                        *support, *test_sources,
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

if not baseline and not previous:
    composition = json.loads((root / 'Build/features.json').read_bytes())['name']
    subprocess.run([sys.executable, str(Path(__file__).with_name('async_storage_check.py'))], check=True)
    subprocess.run([sys.executable, str(Path(__file__).with_name('rollback_storage_check.py'))], check=True)
    subprocess.run([sys.executable, str(Path(__file__).with_name('check_file_feedback.py')),
                    '--source', str(root), '--out', str(root / 'artifacts' / composition / 'settings-file-feedback')], check=True)
