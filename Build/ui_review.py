#!/usr/bin/env python3
"""Actual integrated UI test using the immutable feature's test-target builder.

Only a temporary source copy receives an XCTest target. The product uses the same
rebuilt XCFramework as the ARM64 archive. This does not emulate either installer.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import zipfile
import hashlib
import xml.etree.ElementTree as ET
from release_source import PRODUCT, check_product, check_source
from simulator_diagnostics import capture_failure, observed_run, output_bytes, record_command, warning

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


def write_diagnostic(message):
    try:
        print(message, file=sys.stderr, flush=True)
    except Exception:
        pass  # Diagnostics must not replace the original failure.


class UDPEchoFixture:
    """Host responder/control only; the app receives no test hooks or privileges."""
    def __init__(self):
        self.module = echo_module()
        self.echo = self.helper = None
        self.helper_diagnostic = None
        try:
            self.echo = self.module.Echo(True, elevate=False)
        except PermissionError:
            # This small responder has a mode command; the product and test
            # runner retain their ordinary identity, as in the native audit.
            command = ['sudo', '-n', sys.executable, str(Path(__file__).resolve()), '--udp-echo-helper']
            self.helper_started = time.monotonic()
            self.helper_diagnostic = {'argv': command, 'started_unix': time.time(),
                                      'stderr': 'udp-echo-helper.log', 'stages': []}
            try:
                with (OUT / 'udp-echo-helper.log').open('wb') as log:
                    self.helper = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                   stderr=log, text=True, bufsize=1)
                self.record_helper('spawned')
                assert self.module.response(self.helper)['ready']
                self.record_helper('ready')
            except Exception as error:
                self.record_helper('startup-failed', error)
                self.cleanup_failed_start()
                raise
        self.events = []
        self.errors = []
        self.control_observations = []
        self.epoch = 0
        owner = self

        class Control(socketserver.StreamRequestHandler):
            def handle(self):
                self.request.settimeout(5)
                command = None
                try:
                    command = owner.observe_control('read', lambda: self.rfile.readline(32)).decode('ascii').rstrip('\n')
                    if command not in ('reply', 'drop', 'snapshot'):
                        raise ValueError('Unknown fixture command')
                    if command != 'snapshot':
                        owner.record('before-' + command)
                        owner.epoch += 1
                    result = owner.record(command, command)
                except Exception as error:
                    owner.errors.append(repr(error))
                    result = {'error': repr(error)}
                payload = json.dumps(result).encode() + b'\n'
                owner.observe_control('write', lambda: self.wfile.write(payload),
                                      command=command, requested_bytes=len(payload))

        try:
            self.control = socketserver.TCPServer(('127.0.0.1', 0), Control)
        except Exception:
            self.cleanup_failed_start()
            raise
        self.thread = threading.Thread(target=self.control.serve_forever,
                                       kwargs={'poll_interval': .1})
        self.thread.start()

    def record(self, name, command='snapshot'):
        observed = self.observe_control('ipc', lambda: (
            self.module.command(self.helper, command) if self.helper is not None else
            echo_command(self.echo, command)), event=name, command=command)
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

    def observe_control(self, stage, operation, **details):
        started = time.monotonic()
        record = {'stage': stage, 'started_unix': time.time(), **details}
        self.control_observations.append(record)
        value = None
        failure = None
        try:
            value = operation()
            return value
        except BaseException as error:
            failure = error
            raise
        finally:
            record.update(finished_unix=time.time(),
                          elapsed_seconds=time.monotonic() - started,
                          returned_bytes=len(value) if isinstance(value, bytes) else
                                         value if isinstance(value, int) else None,
                          failure=type(failure).__name__ if failure else None,
                          errno=getattr(failure, 'errno', None),
                          error=repr(failure) if failure else None)

    def save_control_observations(self):
        try:
            records = [dict(record) for record in self.control_observations]
            (OUT / 'udp-echo-control.jsonl').write_text(
                ''.join(json.dumps(record) + '\n' for record in records))
        except Exception as error:
            write_diagnostic('UDP Echo control diagnostic failed: ' + repr(error))

    def record_helper(self, stage, error=None):
        if self.helper_diagnostic is None:
            return
        try:
            self.helper_diagnostic['stages'].append({
                'stage': stage, 'elapsed_seconds': time.monotonic() - self.helper_started,
                'pid': self.helper.pid if self.helper is not None else None,
                'poll': self.helper.poll() if self.helper is not None else None,
                'error': repr(error) if error is not None else None})
            (OUT / 'udp-echo-helper.json').write_text(json.dumps(self.helper_diagnostic, indent=2) + '\n')
        except Exception as error:
            write_diagnostic('UDP Echo helper diagnostic failed: ' + repr(error))

    def cleanup_failed_start(self):
        try:
            self.finish_echo()
        except Exception as cleanup_error:
            # Preserve the startup exception; finish_echo records this secondary
            # failure without claiming a still-unconfirmed child has exited.
            write_diagnostic('UDP Echo fixture startup cleanup failed: ' + repr(cleanup_error))

    def finish_echo(self):
        if self.helper is not None:
            self.record_helper('cleanup-started')
            try:
                self.module.finish_process(self.helper)
            except Exception as error:
                self.record_helper('cleanup-failed', error)
                raise
            self.record_helper('cleanup-finished')
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
                self.save_control_observations()
                (OUT / 'udp-echo-fixture.json').write_text(json.dumps(
                    {'events': self.events, 'errors': self.errors}, indent=2) + '\n')
        assert not self.errors, self.errors


def run(args, log, timeout=180, cwd=ROOT, timing=False):
    command = list(map(str, args))
    started_unix, started = time.time(), time.monotonic()
    failure = None
    try:
        with (OUT / log).open('w') as stream:
            observed_run(command, out=OUT, cwd=cwd, stdout=stream,
                         stderr=subprocess.STDOUT, check=True, timeout=timeout)
    except Exception as exc:
        failure = exc
        raise
    finally:
        if timing or command[:2] == ['xcrun', 'simctl']:
            record = {'command': command, 'log': log, 'timeout_seconds': timeout,
                      'started_unix': started_unix, 'finished_unix': time.time(),
                      'elapsed_seconds': time.monotonic() - started,
                      'failure': type(failure).__name__ if failure else None,
                      'returncode': getattr(failure, 'returncode', None) if failure else 0}
            try:
                with (OUT / 'ui-command-timings.jsonl').open('a') as stream:
                    stream.write(json.dumps(record) + '\n')
            except Exception as timing_failure:
                if failure is None:
                    raise
                write_diagnostic('UI command timing could not be saved: ' + repr(timing_failure))


def output(*args, log=None):
    command = list(map(str, args))
    started, started_unix = time.monotonic(), time.time()
    failure = None
    try:
        value = observed_run(command, out=OUT, stdout=subprocess.PIPE,
                             text=True, cwd=ROOT, timeout=60, check=True).stdout
        if log:
            (OUT / log).write_bytes(output_bytes(value))
        return value.strip()
    except Exception as error:
        failure = error
        if log and isinstance(error, subprocess.TimeoutExpired):
            try:
                (OUT / log).write_bytes(output_bytes(error.stdout) + output_bytes(error.stderr))
            except Exception as log_error:
                warning('Failed to retain UI control output: ' + repr(log_error))
        raise
    finally:
        record_command(OUT, 'ui-control-command-timings.jsonl', command, 60,
                       started, started_unix, failure,
                       getattr(failure, 'returncode', None) if failure else 0)


def ui_test_source():
    """Prepare independent case entry in the temporary XCTest target only."""
    entries = (
        ('Tests/Integration/IntegrationUITests.swift',
         ('testServerControlsAndTabNavigation',
          'testPeriodicUDPEchoThroughRunningServerAndPersistence')),
        ('Tests/Background/AsyncAudioUITests.swift', ()),
        ('Tests/Statistics/StatisticsUITests.swift',
         ('testServerControlsAndTabNavigation',)),
    )
    hook = b'        try IntegratedUITestFixture.prepare()\n'
    parts = []
    for path, methods in entries:
        original = (ROOT / path).read_bytes()
        if b'IntegratedUITestFixture' in original:
            raise RuntimeError('Entry preparation already present: ' + path)
        updated = original
        for method in methods:
            header = ('    @MainActor func ' + method + '() throws {\n').encode()
            if updated.count(header) != 1:
                raise RuntimeError('Expected a unique original UI case: ' + path + ':' + method)
            updated = updated.replace(header, header + hook, 1)
        if updated.replace(hook, b'') != original:
            raise RuntimeError('An original UI test body changed: ' + path)
        parts.append(updated)
    generated = b'\n'.join(parts)
    if generated.count(hook) != 3:
        raise RuntimeError('Expected exactly three case-entry preparations')
    return generated + rb'''
// Entry-only preparation for the generated temporary XCTest source.
// This prepares each selected case. It never repairs state after that case.
@MainActor
private enum IntegratedUITestFixture {
    static func prepare() throws {
        let app = XCUIApplication()
        defer {
            app.terminate()
            XCUIDevice.shared.orientation = .portrait
        }
        XCUIDevice.shared.orientation = .portrait
        app.launch()

        // Observe the loaded settings before deciding whether an intent is Off.
        // The app may restore saved On/Start while loading its ordinary file.
        try saved(app)
        try selectTab("Background", in: app)
        @MainActor func toggle() -> XCUIElement {
            let row = app.switches["background.udpEcho.enabled"]
            let backing = row.switches.firstMatch
            return backing.exists ? backing : row
        }
        try reveal(toggle(), in: app)
        try require(waitUntil {
            toggle().value as? String == "0" || toggle().value as? String == "1"
        }, "The actual UDP Echo switch must report an ordinary On/Off value")
        if toggle().value as? String == "1" { toggle().tap() }
        try require(waitUntil { toggle().value as? String == "0" },
                    "The case's initial UDP Echo intent must be Off")
        let state = app.staticTexts["background.udpEcho.state"]
        try reveal(state, in: app)
        try require(waitUntil(timeout: 10) { state.label == "Off" },
                    "The actual UDP Echo service must settle to Off")

        try selectTab("Server", in: app)
        let start = app.buttons["Start"]
        let stop = app.buttons["Stop"]
        try reveal(start, in: app)
        try reveal(stop, in: app)
        try require(waitUntil { start.isEnabled || stop.isEnabled },
                    "The real Server controls must leave their transition state")
        if stop.isEnabled { stop.tap() }
        try require(waitUntil { start.isEnabled && !stop.isEnabled },
                    "The case's initial server intent must be Stop")
        try saved(app)
        // Defer terminates this preparation process before the unchanged case
        // launches its own process. No probe adds traffic to its zero baseline.
    }

    private static func selectTab(_ name: String, in app: XCUIApplication) throws {
        let tab = app.tabBars.buttons[name]
        try require(tab.waitForExistence(timeout: 10), "The \(name) tab must exist")
        try require(waitUntil { tab.isHittable }, "The \(name) tab must be reachable")
        tab.tap()
    }

    private static func saved(_ app: XCUIApplication) throws {
        try selectTab("Settings", in: app)
        let export = app.buttons["Export JSON"]
        try require(export.waitForExistence(timeout: 5), "The real Settings page must load")
        try reveal(export, in: app)
        // These are the original periodic case's actual persistence indicators.
        // There is no invented Saved label and no private file/preference access.
        try require(waitUntil {
            export.isHittable && export.isEnabled &&
                !app.staticTexts["Loading saved settings..."].exists &&
                !app.staticTexts["Saving changes..."].exists &&
                !app.buttons["Retry Save"].exists
        }, "Accepted initial settings must be durable before process recreation")
    }

    private static func reveal(_ element: XCUIElement, in app: XCUIApplication) throws {
        if element.exists && element.isHittable { return }
        let collection = app.collectionViews.firstMatch
        let scroll = app.scrollViews.firstMatch
        try require(waitUntil { collection.exists || scroll.exists },
                    "The actual page must expose a scrollable container")
        let form = collection.exists ? collection : scroll
        for attempt in 0..<12 {
            if element.exists && element.isHittable { return }
            let target = element.exists ? element.frame : .null
            let viewport = visibleViewport(of: form, in: app)
            let moveDown: Bool
            if element.exists && usable(target) && usable(viewport) {
                if target.minY < viewport.minY {
                    moveDown = true
                } else if target.maxY > viewport.maxY {
                    moveDown = false
                } else {
                    moveDown = target.midY < viewport.midY
                }
            } else {
                // Invalid/absent frames use exactly this bounded fallback:
                // attempts 0...5 down, attempts 6...11 up, at most 12 swipes.
                moveDown = attempt < 6
            }
            if moveDown { form.swipeDown() } else { form.swipeUp() }
        }
        try require(element.exists && element.isHittable,
                    "Use the actual control reachable within twelve swipes")
    }

    private static func visibleViewport(of form: XCUIElement,
                                        in app: XCUIApplication) -> CGRect {
        guard form.exists, app.exists else { return .null }
        let formFrame = form.frame
        let appFrame = app.frame
        guard usable(formFrame), usable(appFrame) else { return .null }
        var viewport = formFrame.intersection(appFrame)
        guard usable(viewport) else { return .null }
        let tabBar = app.tabBars.firstMatch
        if tabBar.exists {
            let tabFrame = tabBar.frame
            if usable(tabFrame), viewport.intersects(tabFrame) {
                viewport = CGRect(x: viewport.minX, y: viewport.minY,
                                  width: viewport.width,
                                  height: max(0, min(viewport.maxY, tabFrame.minY) - viewport.minY))
            }
        }
        return usable(viewport) ? viewport : .null
    }

    private static func usable(_ frame: CGRect) -> Bool {
        !frame.isNull && !frame.isInfinite && !frame.isEmpty &&
            frame.origin.x.isFinite && frame.origin.y.isFinite &&
            frame.size.width.isFinite && frame.size.height.isFinite
    }

    private static func waitUntil(timeout: TimeInterval = 5,
                                  _ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if condition() { return true }
            Thread.sleep(forTimeInterval: 0.05)
        } while Date() < deadline
        return false
    }

    private static func require(_ condition: Bool, _ message: String) throws {
        guard condition else {
            // A setup failure is an uncaught test error, never a skip or success.
            throw NSError(domain: "IntegratedUITestFixture", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: message])
        }
    }
}
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for marker in ('SUCCESS.txt', 'advisory-check.txt', 'app-sha256.txt', 'final-settings.json',
                   'udp-echo-fixture.json', 'udp-echo-helper.json', 'udp-echo-helper.log',
                   'udp-echo-control.jsonl',
                   'ui-command-timings.jsonl', 'ui-control-command-timings.jsonl',
                   'process-observations.jsonl'):
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
    (app / 'StatisticsUITests.swift').write_bytes(ui_test_source())
    failure = None; cleanup = []; fixture = None; identifier = None
    phase = 'fixture-start'
    try:
        # Start the bound UDP7 responder before CoreSimulator and retain it for
        # the entire UI run. Echo/drop changes reuse these same sockets.
        fixture = UDPEchoFixture()
        fixture.configure_test_runner(app)
        phase = 'selection'
        runtimes = json.loads(output('xcrun', 'simctl', 'list', 'runtimes', '-j', log='runtimes.json'))['runtimes']
        runtime = next(r for r in runtimes if r.get('isAvailable') and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
        types = json.loads(output('xcrun', 'simctl', 'list', 'devicetypes', '-j', log='device-types.json'))['devicetypes']
        device = next(d for d in types if d['name'] == 'iPhone 16')
        phase = 'create'
        identifier = output('xcrun', 'simctl', 'create', 'Integrated UI Review', device['identifier'], runtime['identifier'], log='created-device.txt')
        phase = 'environment'
        (OUT / 'environment.json').write_text(json.dumps({'runtime': runtime, 'device': device, 'udid': identifier}, indent=2))
        phase = 'boot'
        run(['xcrun', 'simctl', 'boot', identifier], 'boot.log')
        phase = 'bootstatus'
        run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], 'ready.log', timeout=360)
        phase = 'ui-tests'
        # Keep test failures, runtime warnings and explicit attachments; avoid the
        # optional bulk system-diagnostic collection that stalled after runner exit.
        test_failure = None
        try:
            arguments = ['-project', app / 'Socks5.xcodeproj', '-scheme', 'StatisticsUIAudit',
                         '-destination', 'platform=iOS Simulator,id=' + identifier,
                         '-parallel-testing-enabled', 'NO', '-derivedDataPath', WORK / 'DerivedData',
                         'CODE_SIGNING_ALLOWED=NO', 'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES',
                         'MARKETING_VERSION=3.0.0', 'CURRENT_PROJECT_VERSION=1']
            # Compile the identical test target before measuring UI execution.
            # Cold SDK/module compilation must not consume the four tests' budget.
            run(['xcodebuild', 'build-for-testing', *arguments], 'ui-build.log', timeout=900, timing=True)
            run(['xcodebuild', 'test-without-building', *arguments,
                 '-resultBundlePath', OUT / 'UI.xcresult', '-collect-test-diagnostics', 'never'],
                'ui-test.log', timeout=1800, timing=True)
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
        for text in ((OUT / 'ui-build.log').read_text(), console, result_text):
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
        capture_failure(OUT, phase, identifier, exc)
    finally:
        if fixture is not None:
            fixture.save_control_observations()
            try:
                fixture.close()
            except Exception as exc:
                cleanup.append('UDP Echo fixture: ' + str(exc))
                capture_failure(OUT, 'cleanup-udp-fixture', identifier, exc)
        if identifier is not None:
            for action in ('shutdown', 'delete'):
                try:
                    run(['xcrun', 'simctl', action, identifier], 'cleanup-' + action + '.log', timeout=120)
                except Exception as exc:
                    cleanup.append(str(exc))
                    capture_failure(OUT, 'cleanup-' + action, identifier, exc)
    (OUT / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
    if failure:
        raise failure
    if cleanup:
        raise RuntimeError('UI cleanup failed: ' + repr(cleanup))
    (OUT / 'SUCCESS.txt').write_text('PASS: actual integrated Server/Statistics/Background/Settings UI, durable intent, native greeting and periodic UDP7 echo/no-reply with Stop/restart/Off. Simulator only, not SideStore or LiveContainer.\n')


if __name__ == '__main__':
    if sys.argv[1:] == ['--udp-echo-helper']:
        def phase(name):
            write_diagnostic(json.dumps({'udp_echo_helper_phase': name, 'pid': os.getpid(),
                                         'parent_pid': os.getppid(), 'uid': os.geteuid(),
                                         'time_ns': time.monotonic_ns()}))
        phase('entry')
        module = echo_module()
        phase('module-loaded')
        echo = module.Echo(True, elevate=False)
        try:
            phase('udp7-ready')
            print(json.dumps({'ready': True}), flush=True)
            for line in sys.stdin:
                print(json.dumps(echo_command(echo, line.rstrip('\n'))), flush=True)
        finally:
            phase('stopping')
            echo.finish()
            phase('stopped')
    else:
        main()
