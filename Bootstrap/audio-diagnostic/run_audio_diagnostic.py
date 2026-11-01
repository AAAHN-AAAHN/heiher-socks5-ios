#!/usr/bin/env python3
"""One diagnostic build, then a fixed full/UI-Audio/UI-Audio execution plan.

Historical product input and instrumented temporary app copies are explicitly
diagnostic. Original XCTest source bytes, predicates and 5/10 second waits stay
unchanged. Every planned execution is retained; this never reports candidate CI.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import zipfile

TEST_FILES = ('Tests/Integration/IntegrationUITests.swift',
              'Tests/Background/AsyncAudioUITests.swift',
              'Tests/Statistics/StatisticsUITests.swift')
CASES = (
    'StatisticsUITests.AsyncAudioUITests testAsyncSessionPlaybackAndOff',
    'StatisticsUITests.IntegrationUITests testPeriodicUDPEchoThroughRunningServerAndPersistence',
    'StatisticsUITests.IntegrationUITests testServerControlsAndTabNavigation',
    'StatisticsUITests.StatisticsUITests testServerControlsAndTabNavigation')
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'
DEVICE_TYPE = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def file_record(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': sha256(raw), 'mode': stat.S_IMODE(path.stat().st_mode)}


def stop_group(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            process.wait(timeout=10)
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


class Commands:
    def __init__(self, output, cwd):
        self.output, self.cwd = output, cwd

    def run(self, args, log, timeout, must_succeed=False):
        log = Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        command = [str(value) for value in args]
        start, monotonic = utc(), time.monotonic()
        timed_out, error, code = False, None, None
        with log.open('xb') as stream:
            try:
                process = subprocess.Popen(command, cwd=self.cwd, stdout=stream,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    stop_group(process)
                    code = process.returncode
            except Exception as exc:
                error = repr(exc)
        receipt = {'argv': command, 'cwd': str(self.cwd), 'started_utc': start,
                   'finished_utc': utc(), 'elapsed_seconds': time.monotonic() - monotonic,
                   'timeout_seconds': timeout, 'timed_out': timed_out,
                   'returncode': code, 'error': error,
                   'log': str(log.relative_to(self.output)), **file_record(log)}
        receipt['command_succeeded'] = code == 0 and not timed_out and error is None
        with (self.output / 'commands.jsonl').open('a') as stream:
            stream.write(json.dumps(receipt) + '\n')
        if must_succeed:
            require(receipt['command_succeeded'], 'Command failed; retained at ' + str(log))
        return receipt


def fresh_source_copy(root, app, source_zip):
    subprocess.run(['git', '-C', str(root), 'archive', '--format=zip', 'HEAD', '-o', str(source_zip)], check=True)
    app.mkdir(parents=True)
    with zipfile.ZipFile(source_zip) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            require(not path.is_absolute() and '..' not in path.parts and
                    '\\' not in info.filename and path.as_posix() == info.filename.rstrip('/'),
                    'Unsafe exact-source archive path')
            destination = app.joinpath(*path.parts)
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            mode = info.external_attr >> 16
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG), 'Linked/non-regular source archive entry')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(archive.read(info))
            destination.chmod(0o755 if mode & 0o111 else 0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--input-evidence', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--patcher', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__ and sys.platform == 'darwin', 'Requires assertions and an actual Apple runner')
    root = args.root.resolve(strict=True)
    out, work = args.output.resolve(), args.work.resolve()
    require(not out.exists() and not work.exists(), 'Refusing to overwrite another diagnostic execution')
    out.mkdir(parents=True)
    work.mkdir(parents=True)
    pins = json.loads(args.pins.read_bytes())
    input_receipt = json.loads((args.input_evidence / 'diagnostic-input-receipt.json').read_bytes())
    require(input_receipt['status'] == 'HISTORICAL_PRODUCER_INPUT_VERIFIED_FOR_DIAGNOSTIC_ONLY',
            'Missing separately verified historical-input receipt')
    require(input_receipt['diagnostic']['run_id'] == int(os.environ['GITHUB_RUN_ID']) and
            input_receipt['diagnostic']['run_attempt'] == int(os.environ['GITHUB_RUN_ATTEMPT']) and
            input_receipt['diagnostic']['helper']['commit'] == os.environ['GITHUB_SHA'],
            'Input receipt belongs to a different diagnostic execution')
    commands = Commands(out, root)
    sys.path.insert(0, str(root / 'Build'))
    release = load_module('release_source', root / 'Build/release_source.py')
    sys.modules['release_source'] = release
    release.check_product()
    require(release.check_source() == pins['source']['commit'], 'Changed original source')
    original_tests = {name: (root / name).read_bytes() for name in TEST_FILES}
    for name, expected in pins['ui_source_sha256'].items():
        require(sha256((root / name).read_bytes()) == expected, 'Changed original source: ' + name)
    plan = [{'number': 1, 'label': 'full-original-four', 'cases': list(CASES)},
            {'number': 2, 'label': 'audio-original-two', 'cases': [CASES[0]]},
            {'number': 3, 'label': 'audio-original-three', 'cases': [CASES[0]]}]
    result = {'status': 'DIAGNOSTIC_RUNNING', 'candidate_execution': False,
              'canonical_execution': False, 'selected_product': False,
              'scope': 'Instrumented temporary app, historical native product, original assertions; never candidate/full-gate evidence.',
              'diagnostic_context': input_receipt['diagnostic'], 'historical_origin': input_receipt['origin'],
              'plan': plan, 'test_timeout_seconds_each': 900, 'build_for_testing_count': 0,
              'retry_until_success': False, 'iterations': [], 'errors': []}
    save(out / 'planned-execution.json', result)
    fixture = None
    try:
        commands.run(['xcodebuild', '-version'], out / 'xcode-version.txt', 30, True)
        commands.run(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], out / 'simulator-sdk.txt', 30, True)
        commands.run(['sw_vers'], out / 'macos-version.txt', 30, True)
        commands.run(['xcrun', 'swiftc', '--version'], out / 'swift-version.txt', 30, True)
        commands.run(['xcrun', 'simctl', 'list', 'runtimes', '-j'], out / 'runtimes.json', 60, True)
        commands.run(['xcrun', 'simctl', 'list', 'devicetypes', '-j'], out / 'device-types.json', 60, True)
        require((out / 'xcode-version.txt').read_text().splitlines()[0] == 'Xcode 27.1',
                'Diagnostic toolchain changed; retain environment without substituting another profile')
        require((out / 'simulator-sdk.txt').read_text().strip() == '27.1', 'Expected the observed Simulator SDK 27.1')
        runtimes = json.loads((out / 'runtimes.json').read_bytes())['runtimes']
        require(any(item['identifier'] == RUNTIME and item.get('isAvailable') for item in runtimes),
                'The observed iOS 27.0 Simulator runtime is unavailable')
        app = work / 'application'
        fresh_source_copy(root, app, out / 'original-source.zip')
        shutil.rmtree(app / 'HevSocks5Server.xcframework')
        shutil.copytree(release.PRODUCT / 'HevSocks5Server.xcframework', app / 'HevSocks5Server.xcframework')
        require(release.inventory(app / 'HevSocks5Server.xcframework') ==
                release.inventory(release.PRODUCT / 'HevSocks5Server.xcframework'),
                'Temporary framework differs from the original producer bytes/modes')
        builder = load_module('diagnostic_original_test_target_builder', root / 'Tests/Statistics/ui_audit.py')
        builder.OUT = out
        builder.add_test_target(app)
        combined = b'\n'.join(original_tests[name] for name in TEST_FILES)
        (app / 'StatisticsUITests.swift').write_bytes(combined)
        require(combined == original_tests[TEST_FILES[0]] + b'\n' +
                original_tests[TEST_FILES[1]] + b'\n' + original_tests[TEST_FILES[2]],
                'Original combined XCTest bytes changed')
        save(out / 'original-test-source-identities.json', {
            'files': {name: {'bytes': len(raw), 'sha256': sha256(raw)} for name, raw in original_tests.items()},
            'combined_file': file_record(app / 'StatisticsUITests.swift'),
            'test_predicates_and_assertions_changed': False,
            'original_audio_waits_seconds': [5, 10]})
        commands.run([sys.executable, args.patcher, '--application', app,
                      '--receipt', out / 'instrumentation-patch-receipt.json'],
                     out / 'instrumentation-patcher.log', 30, True)
        require((app / 'StatisticsUITests.swift').read_bytes() == combined,
                'Instrumentation touched original XCTest source')
        for name, raw in original_tests.items():
            require((app / name).read_bytes() == raw and (root / name).read_bytes() == raw,
                    'Instrumentation changed an original testcase file')
        ui = load_module('diagnostic_original_ui_fixture', root / 'Build/ui_review.py')
        ui.OUT = out / 'udp-fixture'
        ui.OUT.mkdir()
        fixture = ui.UDPEchoFixture()
        fixture.configure_test_runner(app)
        # The original fixture is present for the full first execution; its same
        # bound responder remains alive until all predeclared diagnostics finish.
        copied = out / 'ephemeral-app-source'
        copied.mkdir()
        for name in ('Socks5/AppRoot.swift', 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift',
                     'Socks5/Settings/SettingsStore.swift', 'StatisticsUITests.swift',
                     'Socks5.xcodeproj/project.pbxproj',
                     'Socks5.xcodeproj/xcshareddata/xcschemes/StatisticsUIAudit.xcscheme'):
            source = app / name
            if source.is_file():
                destination = copied / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        derived = work / 'DerivedData'
        build = commands.run(['xcodebuild', 'build-for-testing', '-project', app / 'Socks5.xcodeproj',
                              '-scheme', 'StatisticsUIAudit', '-destination', 'generic/platform=iOS Simulator',
                              '-derivedDataPath', derived, '-resultBundlePath', out / 'build.xcresult',
                              'CODE_SIGNING_ALLOWED=NO', 'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES',
                              'MARKETING_VERSION=3.0.0', 'CURRENT_PROJECT_VERSION=1'],
                             out / 'build-for-testing.log', 900)
        result['build_for_testing_count'] = 1
        result['build'] = build
        require(build['command_succeeded'], 'Diagnostic build-for-testing failed')
        xctestruns = list((derived / 'Build/Products').glob('*.xctestrun'))
        require(len(xctestruns) == 1, 'Expected exactly one actual build-for-testing xctestrun')
        xctestrun = xctestruns[0]
        shutil.copyfile(xctestrun, out / xctestrun.name)
        build_inventory = {}
        for path in sorted((derived / 'Build/Products').rglob('*')):
            if path.is_symlink():
                build_inventory[str(path.relative_to(derived))] = {'symlink_target': os.readlink(path)}
            elif path.is_file():
                build_inventory[str(path.relative_to(derived))] = file_record(path)
        save(out / 'diagnostic-built-product-inventory.json', build_inventory)
        for planned in plan:
            current = {**planned, 'status': 'NOT_STARTED', 'errors': []}
            result['iterations'].append(current)
            iteration = out / ('iteration-' + str(planned['number']))
            iteration.mkdir()
            device = None
            trace_process, trace_stream = None, None
            try:
                commands.run(['xcrun', 'simctl', 'create', 'Audio diagnosis ' + str(planned['number']),
                              DEVICE_TYPE, RUNTIME], iteration / 'created-device.txt', 60, True)
                device = (iteration / 'created-device.txt').read_text().strip()
                require(re.fullmatch(r'[0-9A-F-]{36}', device), 'Invalid actual Simulator UUID')
                current['device_udid'] = device
                current['fresh_device_and_app_container'] = True
                commands.run(['xcrun', 'simctl', 'boot', device], iteration / 'boot.log', 60, True)
                commands.run(['xcrun', 'simctl', 'bootstatus', device, '-b'], iteration / 'ready.log', 120, True)
                trace_stream = (iteration / 'audio-intent-live.log').open('xb')
                trace_process = subprocess.Popen(
                    ['xcrun', 'simctl', 'spawn', device, 'log', 'stream', '--style', 'compact',
                     '--level', 'debug', '--predicate', 'eventMessage CONTAINS "AUDIO_INTENT_TRACE"'],
                    stdout=trace_stream, stderr=subprocess.STDOUT, start_new_session=True)
                command = ['xcodebuild', 'test-without-building', '-xctestrun', xctestrun,
                           '-destination', 'platform=iOS Simulator,id=' + device,
                           '-parallel-testing-enabled', 'NO', '-resultBundlePath', iteration / 'Test.xcresult',
                           '-collect-test-diagnostics', 'never']
                if planned['number'] != 1:
                    command.append('-only-testing:StatisticsUITests/AsyncAudioUITests/testAsyncSessionPlaybackAndOff')
                execution = commands.run(command, iteration / 'xcode-test.log', 900)
                current['execution'] = execution
                summary_command = commands.run(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary',
                                                '--path', iteration / 'Test.xcresult'],
                                               iteration / 'test-summary.json', 60)
                object_command = commands.run(['xcrun', 'xcresulttool', 'get', 'object', '--legacy', '--format', 'json',
                                               '--path', iteration / 'Test.xcresult'], iteration / 'xcresult.json', 60)
                attachments_command = commands.run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', iteration / 'Test.xcresult',
                                                    '--output-path', iteration / 'attachments'], iteration / 'attachments.log', 60)
                current['raw_result_exports'] = {'object': object_command, 'attachments': attachments_command}
                if not object_command['command_succeeded'] or not attachments_command['command_succeeded']:
                    current['errors'].append('Raw xcresult object or attachment export failed; error output retained')
                console = (iteration / 'xcode-test.log').read_text(errors='replace')
                cases = [{'test': case, 'result': outcome, 'duration_seconds': float(seconds)}
                         for case, outcome, seconds in re.findall(
                             r"Test Case '-\[([^\]]+)\]' (passed|failed) \(([0-9.]+) seconds\)\.", console)]
                current['actual_completed_console_cases'] = cases
                current['summary_command'] = summary_command
                if summary_command['command_succeeded']:
                    current['actual_xcresult_summary'] = json.loads((iteration / 'test-summary.json').read_bytes())
                summary = current.get('actual_xcresult_summary', {})
                exact_cases = (len(cases) == len(planned['cases']) and
                               {case['test'] for case in cases} == set(planned['cases']) and
                               all(case['result'] == 'passed' for case in cases))
                passed = (execution['command_succeeded'] and exact_cases and
                          summary.get('passedTests') == len(planned['cases']) and
                          summary.get('failedTests', 0) == 0 and summary.get('skippedTests', 0) == 0)
                current['status'] = 'DIAGNOSTIC_PLANNED_CASES_PASSED' if passed else 'DIAGNOSTIC_FAILED'
                current['expected_case_count'] = len(planned['cases'])
                current['exact_original_case_count_and_identities_passed'] = bool(passed)
            except Exception as exc:
                current['status'] = 'DIAGNOSTIC_FAILED'
                current['errors'].append(repr(exc))
            finally:
                if device:
                    trace_history = commands.run(
                        ['xcrun', 'simctl', 'spawn', device, 'log', 'show', '--style', 'compact',
                         '--last', '30m', '--predicate', 'eventMessage CONTAINS "AUDIO_INTENT_TRACE"'],
                        iteration / 'audio-intent-history.log', 30)
                    current['trace_history_command'] = trace_history
                    commands.run(['xcrun', 'simctl', 'get_app_container', device, 'hev.Socks5', 'data'],
                                 iteration / 'app-data-container.txt', 30)
                    try:
                        container = Path((iteration / 'app-data-container.txt').read_text().strip())
                        settings = container / 'Library/Application Support/Socks5/settings.json'
                        if settings.is_file() and not settings.is_symlink():
                            shutil.copyfile(settings, iteration / 'actual-final-settings.json')
                    except Exception as exc:
                        current['errors'].append('settings capture: ' + repr(exc))
                if trace_process is not None:
                    current['trace_process_exit_before_stop'] = trace_process.poll()
                    stop_group(trace_process)
                if trace_stream is not None:
                    trace_stream.close()
                trace_files = [iteration / name for name in ('audio-intent-live.log', 'audio-intent-history.log')]
                current['audio_intent_trace_files'] = {
                    path.name: file_record(path) for path in trace_files if path.is_file()}
                current['audio_intent_trace_event_counts_by_file'] = {}
                for path in trace_files:
                    if path.is_file():
                        events = re.findall(r'AUDIO_INTENT_TRACE seq=[0-9]+ uptime=[0-9]+\.[0-9]+ event=([^\s]+)',
                                            path.read_text(errors='replace'))
                        current['audio_intent_trace_event_counts_by_file'][path.name] = {
                            event: events.count(event) for event in sorted(set(events))}
                current['audio_intent_trace_observed'] = any(
                    counts for counts in current['audio_intent_trace_event_counts_by_file'].values())
                if current['status'] == 'DIAGNOSTIC_PLANNED_CASES_PASSED' and not current['audio_intent_trace_observed']:
                    current['errors'].append('Tests completed but no instrumented Audio intent trace was captured')
                    current['status'] = 'DIAGNOSTIC_FAILED'
                if device:
                    for action in ('shutdown', 'delete'):
                        cleanup = commands.run(['xcrun', 'simctl', action, device], iteration / ('cleanup-' + action + '.log'), 30)
                        if not cleanup['command_succeeded']:
                            current['errors'].append('Simulator ' + action + ' failed')
                            current['status'] = 'DIAGNOSTIC_FAILED'
                save(iteration / 'diagnostic-outcome.json', current)
                # A failing iteration is preserved and does not replace or cancel
                # the other two predeclared executions. This is not pass-seeking.
    except Exception as exc:
        result['errors'].append(repr(exc))
    finally:
        if fixture is not None:
            try:
                fixture.close()
            except Exception as exc:
                result['errors'].append('UDP fixture cleanup: ' + repr(exc))
        try:
            release.check_product()
            require(release.check_source() == pins['source']['commit'], 'Original checkout changed')
            for name, raw in original_tests.items():
                require((root / name).read_bytes() == raw, 'Original testcase changed')
            if (work / 'application/StatisticsUITests.swift').exists():
                require((work / 'application/StatisticsUITests.swift').read_bytes() ==
                        b'\n'.join(original_tests[name] for name in TEST_FILES),
                        'Temporary combined original XCTest source changed during execution')
            result['original_source_and_historical_product_preserved_after_diagnostic'] = True
        except Exception as exc:
            result['errors'].append('Source/product preservation: ' + repr(exc))
            result['original_source_and_historical_product_preserved_after_diagnostic'] = False
        complete = (not result['errors'] and len(result['iterations']) == 3 and
                    all(row['status'] == 'DIAGNOSTIC_PLANNED_CASES_PASSED' and not row['errors']
                        for row in result['iterations']))
        result['status'] = 'DIAGNOSTIC_PLAN_PASSED_NOT_CANDIDATE' if complete else 'DIAGNOSTIC_PLAN_FAILED_NOT_CANDIDATE'
        result['finished_utc'] = utc()
        save(out / 'diagnostic-result.json', result)
    print(json.dumps({'status': result['status'], 'iterations_recorded': len(result['iterations']),
                      'candidate_execution': False, 'selected_product': False}))
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
