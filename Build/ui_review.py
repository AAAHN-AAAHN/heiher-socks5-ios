#!/usr/bin/env python3
"""Actual integrated UI test using the immutable feature's test-target builder.

Only a temporary source copy receives an XCTest target. The product uses the same
rebuilt XCFramework as the ARM64 archive. This does not emulate either installer.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import socketserver
import subprocess
import sys
import threading
import zipfile
import hashlib
import xml.etree.ElementTree as ET
from release_source import PRODUCT, check_product, check_source

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/integrated/ui'
WORK = ROOT / '.build/integrated-ui'


def echo_module():
    source = ROOT / 'Tests/Background/check_udp_echo_native.py'
    spec = importlib.util.spec_from_file_location('native_udp_echo_fixture', source)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def echo_command(echo, command):
    if command not in ('reply', 'drop', 'snapshot'):
        raise ValueError('Unknown fixture command')
    if command != 'snapshot':
        # Preserve the bound UDP7 sockets: a reply-mode transition must not
        # create a port-unreachable error in the otherwise healthy relay.
        with echo.lock:
            echo.replies = command == 'reply'
            echo.received = {4: [], 6: []}
    return {'replies': echo.replies, 'packets': echo.snapshot()}


class UDPEchoFixture:
    """Host responder/control only; the app receives no test hooks or privileges."""
    def __init__(self):
        self.module = echo_module()
        self.echo = self.helper = None
        try:
            self.echo = self.module.Echo(True, elevate=False)
        except PermissionError:
            # This small responder has a mode command; the product and test
            # runner retain their ordinary identity, as in the native audit.
            self.helper = subprocess.Popen(
                ['sudo', '-n', sys.executable, str(Path(__file__).resolve()), '--udp-echo-helper'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
            try:
                assert self.module.response(self.helper)['ready']
            except Exception:
                self.finish_echo()
                raise
        self.events = []
        self.errors = []
        self.epoch = 0
        owner = self

        class Control(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(5)
                try:
                    command = self.rfile.readline(32).decode('ascii').rstrip('\n')
                    if command not in ('reply', 'drop', 'snapshot'):
                        raise ValueError('Unknown fixture command')
                    if command != 'snapshot':
                        owner.record('before-' + command)
                        owner.epoch += 1
                    result = owner.record(command, command)
                except Exception as error:
                    owner.errors.append(repr(error))
                    result = {'error': repr(error)}
                self.wfile.write(json.dumps(result).encode() + b'\n')

        try:
            self.control = socketserver.TCPServer(('127.0.0.1', 0), Control)
        except Exception:
            self.finish_echo()
            raise
        self.thread = threading.Thread(target=self.control.serve_forever,
                                       kwargs={'poll_interval': .1})
        self.thread.start()

    def record(self, name, command='snapshot'):
        observed = (self.module.command(self.helper, command) if self.helper is not None else
                    echo_command(self.echo, command))
        packets = {int(family): values for family, values in observed['packets'].items()}
        result = {'epoch': self.epoch, 'replies': observed['replies'],
                  'counts': {str(family): len(values) for family, values in packets.items()},
                  'ports': {str(family): sorted({value[2] for value in values})
                            for family, values in packets.items()},
                  'valid': all(value[0] == '00' and value[1] == ('127.0.0.1' if family == 4 else '::1')
                               and 0 < value[2] <= 65535
                               for family, values in packets.items() for value in values)}
        event = {'command': name, **result}
        if name != 'snapshot':
            event['packets'] = packets
        self.events.append(event)
        return result

    def finish_echo(self):
        if self.helper is not None:
            self.module.finish_process(self.helper)
        elif self.echo is not None:
            self.echo.finish()

    def configure_test_runner(self, app):
        scheme = app / 'Socks5.xcodeproj/xcshareddata/xcschemes/StatisticsUIAudit.xcscheme'
        tree = ET.parse(scheme)
        action = tree.getroot().find('TestAction')
        assert action is not None and action.find('EnvironmentVariables') is None
        action.set('shouldUseLaunchSchemeArgsEnv', 'NO')
        variables = ET.SubElement(action, 'EnvironmentVariables')
        ET.SubElement(variables, 'EnvironmentVariable', key='UDP_ECHO_FIXTURE_PORT',
                      value=str(self.control.server_address[1]), isEnabled='YES')
        tree.write(scheme, encoding='utf-8', xml_declaration=True)

    def close(self):
        self.control.shutdown()
        self.control.server_close()
        self.thread.join(3)
        assert not self.thread.is_alive(), 'Fixture control did not stop'
        try:
            self.record('final')
        finally:
            try:
                self.finish_echo()
            finally:
                (OUT / 'udp-echo-fixture.json').write_text(json.dumps(
                    {'events': self.events, 'errors': self.errors}, indent=2) + '\n')
        assert not self.errors, self.errors


def run(args, log, timeout=180, cwd=ROOT):
    with (OUT / log).open('w') as stream:
        subprocess.run([str(a) for a in args], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True, cwd=ROOT, timeout=60).strip()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for marker in ('SUCCESS.txt', 'advisory-check.txt', 'app-sha256.txt', 'final-settings.json',
                   'udp-echo-fixture.json'):
        (OUT / marker).unlink(missing_ok=True)
    if not __debug__ or sys.platform != 'darwin' or WORK.exists():
        raise SystemExit('Use assertions, the Apple toolchain and a clean UI workspace')
    check_product()
    app = WORK / 'application'; app.mkdir(parents=True)
    run(['git', 'archive', '--format=zip', 'HEAD', '-o', OUT / 'source.zip'], 'source-archive.log')
    with zipfile.ZipFile(OUT / 'source.zip') as source:
        source.extractall(app)
    shutil.rmtree(app / 'HevSocks5Server.xcframework')
    shutil.copytree(PRODUCT / 'HevSocks5Server.xcframework', app / 'HevSocks5Server.xcframework')
    spec = importlib.util.spec_from_file_location('feature_ui_builder', ROOT / 'Tests/Statistics/ui_audit.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    builder.OUT = OUT
    builder.add_test_target(app)
    # The target remains in the temporary project, never the committed app target.
    (app / 'StatisticsUITests.swift').write_bytes(
        (ROOT / 'Tests/Integration/IntegrationUITests.swift').read_bytes() + b'\n' +
        (ROOT / 'Tests/Background/AsyncAudioUITests.swift').read_bytes() + b'\n' +
        (ROOT / 'Tests/Statistics/StatisticsUITests.swift').read_bytes())
    runtimes = json.loads(output('xcrun', 'simctl', 'list', 'runtimes', '-j'))['runtimes']
    runtime = next(r for r in runtimes if r.get('isAvailable') and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
    types = json.loads(output('xcrun', 'simctl', 'list', 'devicetypes', '-j'))['devicetypes']
    device = next(d for d in types if d['name'] == 'iPhone 16')
    identifier = output('xcrun', 'simctl', 'create', 'Integrated UI Review', device['identifier'], runtime['identifier'])
    (OUT / 'environment.json').write_text(json.dumps({'runtime': runtime, 'device': device, 'udid': identifier}, indent=2))
    failure = None; cleanup = []; fixture = None
    try:
        run(['xcrun', 'simctl', 'boot', identifier], 'boot.log')
        run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], 'ready.log', timeout=120)
        fixture = UDPEchoFixture()
        fixture.configure_test_runner(app)
        # Keep test failures, runtime warnings and explicit attachments; avoid the
        # optional bulk system-diagnostic collection that stalled after runner exit.
        test_failure = None
        try:
            run(['xcodebuild', 'test', '-project', app / 'Socks5.xcodeproj', '-scheme', 'StatisticsUIAudit',
                 '-destination', 'platform=iOS Simulator,id=' + identifier, '-parallel-testing-enabled', 'NO',
                 '-derivedDataPath', WORK / 'DerivedData', '-resultBundlePath', OUT / 'UI.xcresult',
                 '-collect-test-diagnostics', 'never',
                 'CODE_SIGNING_ALLOWED=NO', 'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES',
                 'MARKETING_VERSION=3.0.0', 'CURRENT_PROJECT_VERSION=1'], 'ui-test.log', timeout=900)
        except Exception as exc:
            test_failure = exc
        diagnostic_failure = None
        for command, log in [
            (['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', OUT / 'UI.xcresult'],
             'test-summary.json'),
            (['xcrun', 'xcresulttool', 'get', 'object', '--legacy', '--format', 'json', '--path', OUT / 'UI.xcresult'],
             'xcresult.json'),
            (['xcrun', 'xcresulttool', 'export', 'attachments', '--path', OUT / 'UI.xcresult',
              '--output-path', OUT / 'attachments'], 'attachments.log'),
        ]:
            try:
                run(command, log)
            except Exception as exc:
                if diagnostic_failure is None:
                    diagnostic_failure = exc
        if test_failure is not None:
            raise test_failure
        if diagnostic_failure is not None:
            raise diagnostic_failure
        console = (OUT / 'ui-test.log').read_text()
        result_text = (OUT / 'xcresult.json').read_text()
        for text in (console, result_text):
            if 'This method can lead to UI unresponsiveness' in text:
                raise RuntimeError('Main-thread synchronous audio advisory remains')
        summary = json.loads((OUT / 'test-summary.json').read_text())
        if summary.get('failedTests', 0) or summary.get('skippedTests', 0) or summary.get('passedTests') != 4:
            raise RuntimeError('Incomplete integrated XCTest result')
        (OUT / 'advisory-check.txt').write_text('PASS: targeted synchronous main-thread audio advisory absent from console and xcresult.\n')
        binary = WORK / 'DerivedData/Build/Products/Debug-iphonesimulator/Socks5.app/Socks5'
        (OUT / 'app-sha256.txt').write_text(hashlib.sha256(binary.read_bytes()).hexdigest() + '\n')
        container = Path(output('xcrun', 'simctl', 'get_app_container', identifier, 'hev.Socks5', 'data'))
        settings = json.loads((container / 'Library/Application Support/Socks5/settings.json').read_bytes())
        assert settings['serverRunning'] is False
        assert settings['background'] == {
            'continuousLocation': False, 'silentAudio': False,
            'periodicUDPEcho': {'enabled': False, 'destinations': '127.0.0.1,::1', 'period': '00200'}}
        (OUT / 'final-settings.json').write_text(json.dumps(settings, indent=2))
        check_product()
        run(['git', 'diff', '--exit-code', 'HEAD', '--'], 'source-preservation.log')
        run(['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 'source-index.log')
    except Exception as exc:
        failure = exc
    finally:
        if fixture is not None:
            try:
                fixture.close()
            except Exception as exc:
                cleanup.append('UDP Echo fixture: ' + str(exc))
        for action in ('shutdown', 'delete'):
            try:
                run(['xcrun', 'simctl', action, identifier], 'cleanup-' + action + '.log', timeout=30)
            except Exception as exc:
                cleanup.append(str(exc))
    (OUT / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
    if failure:
        raise failure
    if cleanup:
        raise RuntimeError('UI cleanup failed: ' + repr(cleanup))
    (OUT / 'SUCCESS.txt').write_text('PASS: actual integrated Server/Statistics/Background/Settings UI, durable intent, native greeting and periodic UDP7 echo/no-reply with Stop/restart/Off. Simulator only, not SideStore or LiveContainer.\n')


if __name__ == '__main__':
    if sys.argv[1:] == ['--udp-echo-helper']:
        echo = echo_module().Echo(True, elevate=False)
        try:
            print(json.dumps({'ready': True}), flush=True)
            for line in sys.stdin:
                print(json.dumps(echo_command(echo, line.rstrip('\n'))), flush=True)
        finally:
            echo.finish()
    else:
        main()
