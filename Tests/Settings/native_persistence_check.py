#!/usr/bin/env python3
"""Exercise actual persistence -> controller -> Hev, without an app/IPA or UI taps."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('server_native', ROOT / 'Tests/ServerControl/native_controller_check.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def compile_host(core, folder, output):
    include = folder / 'include'; include.mkdir()
    shutil.copyfile(core / 'src/hev-main.h', include / 'hev-main.h')
    (include / 'module.modulemap').write_text('module HevSocks5Server { header "hev-main.h" export * }\n')
    paths = ['Socks5/Server/ServerSettings.swift', 'Socks5/Server/ServerController.swift',
             'Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift']
    sources = [str(Path(__file__).with_name('NativePersistenceHost.swift'))]
    for path in paths:
        text = (ROOT / path).read_text()
        if sys.platform != 'darwin':
            text = text.replace('import SwiftUI\n', 'import Foundation\n', 1)
        dest = folder / Path(path).name; dest.write_text(text); sources.append(str(dest))
    if sys.platform != 'darwin':
        ui = folder / 'Platform.swift'
        ui.write_text('''import Foundation
protocol ObservableObject {}
@propertyWrapper struct Published<T> { var wrappedValue: T }
struct Binding<T> {
    let get: () -> T; let set: (T) -> Void
    init(get: @escaping () -> T, set: @escaping (T) -> Void) { self.get = get; self.set = set }
    var wrappedValue: T { get { get() } nonmutating set { set(newValue) } }
}
class NSFileCoordinator {
    init(filePresenter: Any?) {}
    func coordinate(readingItemAt url: URL, options: [Int], error: UnsafeMutablePointer<NSError?>?, byAccessor: (URL) -> Void) { byAccessor(url) }
}
extension URL {
    func startAccessingSecurityScopedResource() -> Bool { true }
    func stopAccessingSecurityScopedResource() {}
}
''')
        sources.append(str(ui))
    libraries = [core / 'bin/libhev-socks5-server.a', core / 'third-part/yaml/bin/libyaml.a',
                 core / 'third-part/hev-task-system/bin/libhev-task-system.a']
    executable = folder / 'persistence-host'
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(['swiftc', '-swift-version', '5', '-warnings-as-errors', '-I', str(include),
                        *sources, *map(str, libraries), '-Xlinker', '-lpthread', '-o', str(executable)],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
    return executable


def main():
    core, output = map(lambda p: Path(p).resolve(), sys.argv[1:3])
    output.mkdir(parents=True, exist_ok=True)
    records = []
    def record(workers, case):
        records.append(dict(workers=workers, case=case, passed=True))
        (output / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        executable = compile_host(core, folder, output)
        previous_env = os.environ.get('PERSISTENCE_TEST_FILE')
        try:
            for workers in (1, 4):
                case_dir = folder / str(workers); case_dir.mkdir()
                file = case_dir / 'settings.json'
                os.environ['PERSISTENCE_TEST_FILE'] = str(file)
                with socket.socket() as s:
                    s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
                options = dict(workers=str(workers), listenAddress='127.0.0.1', listenPort=str(port),
                    udpListenAddress='127.0.0.1', udpListenPort='0', bindIPv4Address='0.0.0.0',
                    bindIPv6Address='::', bindInterface='', authUsername='user', authPassword='\u00e9', listenIPv6Only=False)
                document = dict(version=1, server=options, serverRunning=True,
                    background=dict(continuousLocation=False, silentAudio=False), selectedTab='background')
                external = case_dir / 'external.json'; external.write_text(json.dumps(document))
                with (output / f'workers{workers}.log').open('wb') as log:
                    host = native.Host(executable, log)
                    try:
                        response = host.request('import-file', path=str(external))
                        assert not response['operationError']
                        native.wait_auth(port, 'user', '\u00e9')
                        assert json.loads(file.read_text()) == document
                        record(workers, 'coordinated-import-starts-real-server')
                        host.request('set-password', password='e\u0301')
                        native.wait_auth(port, 'user', 'e\u0301')
                        assert not native.authenticate(port, 'user', '\u00e9')
                        assert json.loads(file.read_text())['server']['authPassword'].encode() == b'e\xcc\x81'
                        record(workers, 'binding-byte-change-saves-and-reconfigures')
                    finally:
                        host.close()
                    # This is a new native process, not just a new store object.
                    host = native.Host(executable, log)
                    try:
                        native.wait_auth(port, 'user', 'e\u0301')
                        assert host.request('state')['savedRunning']
                        record(workers, 'new-process-restores-durable-start-and-bytes')
                        options.update(authUsername='\u1100\u1161', authPassword='p' * 255)
                        document['selectedTab'] = 'statistics'
                        host.request('import-data', payload=json.dumps(document))
                        native.wait_auth(port, options['authUsername'], options['authPassword'])
                        assert not native.authenticate(port, '\uac00', options['authPassword'])
                        record(workers, 'whole-import-korean-bytes-and-255-byte-secret')
                        prior = file.read_bytes()
                        result = host.request('import-data', payload='{"version":99}')
                        assert result['operationError'] and file.read_bytes() == prior
                        native.wait_auth(port, options['authUsername'], options['authPassword'])
                        record(workers, 'invalid-import-preserves-disk-and-live-auth')
                        parked = case_dir / 'parked.json'; file.rename(parked); file.mkdir()
                        native.stop(host, options, port)
                        assert host.request('state')['storageError']
                        assert json.loads(parked.read_text())['serverRunning']
                        record(workers, 'failed-save-does-not-prevent-real-stop')
                        file.rmdir(); parked.rename(file)
                        native.stop(host, options, port)
                        assert not host.request('state')['storageError']
                        assert not json.loads(file.read_text())['serverRunning']
                        record(workers, 'same-stop-retries-durable-save')
                    finally:
                        host.close()
                    host = native.Host(executable, log)
                    try:
                        state = host.request('state')
                        assert not state['running'] and not state['savedRunning']
                        native.stop(host, options, port)
                        record(workers, 'new-process-respects-persisted-stop')
                    finally:
                        host.close()
        finally:
            if previous_env is None: os.environ.pop('PERSISTENCE_TEST_FILE', None)
            else: os.environ['PERSISTENCE_TEST_FILE'] = previous_env
    assert len(records) == 16
    print('PASS: 16 actual-file/controller/Hev records; test command adapter, not iPhone UI or installer execution.')


if __name__ == '__main__':
    main()
