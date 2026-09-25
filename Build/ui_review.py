#!/usr/bin/env python3
"""Actual integrated UI test using the immutable feature's test-target builder.

Only a temporary source copy receives an XCTest target. The product uses the same
rebuilt XCFramework as the ARM64 archive. This does not emulate either installer.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/integrated/ui'
WORK = ROOT / '.build/integrated-ui'


def run(args, log, timeout=180, cwd=ROOT):
    with (OUT / log).open('w') as stream:
        subprocess.run([str(a) for a in args], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=60).strip()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    if not __debug__ or sys.platform != 'darwin' or WORK.exists():
        raise SystemExit('Use assertions, the Apple toolchain and a clean UI workspace')
    app = WORK / 'application'; app.mkdir(parents=True)
    run(['git', 'archive', '--format=zip', 'HEAD', '-o', OUT / 'source.zip'], 'source-archive.log')
    with zipfile.ZipFile(OUT / 'source.zip') as source:
        source.extractall(app)
    shutil.rmtree(app / 'HevSocks5Server.xcframework')
    shutil.copytree(ROOT / 'HevSocks5Server.xcframework', app / 'HevSocks5Server.xcframework')
    spec = importlib.util.spec_from_file_location('feature_ui_builder', ROOT / 'Tests/Statistics/ui_audit.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    builder.OUT = OUT
    builder.add_test_target(app)
    # The target remains in the temporary project, never the committed app target.
    shutil.copyfile(ROOT / 'Tests/Integration/IntegrationUITests.swift', app / 'StatisticsUITests.swift')
    runtimes = json.loads(output('xcrun', 'simctl', 'list', 'runtimes', '-j'))['runtimes']
    runtime = next(r for r in runtimes if r.get('isAvailable') and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
    types = json.loads(output('xcrun', 'simctl', 'list', 'devicetypes', '-j'))['devicetypes']
    device = next(d for d in types if d['name'] == 'iPhone 16')
    identifier = output('xcrun', 'simctl', 'create', 'Integrated UI Review', device['identifier'], runtime['identifier'])
    (OUT / 'environment.json').write_text(json.dumps({'runtime': runtime, 'device': device, 'udid': identifier}, indent=2))
    failure = None; cleanup = []
    try:
        run(['xcrun', 'simctl', 'boot', identifier], 'boot.log')
        run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], 'ready.log', timeout=120)
        # Keep test failures, runtime warnings and explicit attachments; avoid the
        # optional bulk system-diagnostic collection that stalled after runner exit.
        run(['xcodebuild', 'test', '-project', app / 'Socks5.xcodeproj', '-scheme', 'StatisticsUIAudit',
             '-destination', 'platform=iOS Simulator,id=' + identifier, '-parallel-testing-enabled', 'NO',
             '-derivedDataPath', WORK / 'DerivedData', '-resultBundlePath', OUT / 'UI.xcresult',
             '-collect-test-diagnostics', 'never',
             'CODE_SIGNING_ALLOWED=NO', 'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES',
             'MARKETING_VERSION=1.1.0', 'CURRENT_PROJECT_VERSION=7'], 'ui-test.log', timeout=900)
        run(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', OUT / 'UI.xcresult'], 'test-summary.json')
        run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', OUT / 'UI.xcresult',
             '--output-path', OUT / 'attachments'], 'attachments.log')
        container = Path(output('xcrun', 'simctl', 'get_app_container', identifier, 'hev.Socks5', 'data'))
        settings = json.loads((container / 'Library/Application Support/Socks5/settings.json').read_bytes())
        assert settings['serverRunning'] is False
        assert settings['background'] == {'continuousLocation': False, 'silentAudio': False}
        (OUT / 'final-settings.json').write_text(json.dumps(settings, indent=2))
        run(['git', 'diff', '--exit-code', 'HEAD', '--', 'Socks5', 'Socks5.xcodeproj', 'Patches', 'Build', 'Tests'], 'source-preservation.log')
    except Exception as exc:
        failure = exc
    finally:
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
    (OUT / 'SUCCESS.txt').write_text('PASS: actual integrated Server/Statistics/Background/Settings UI, durable intent and native greeting. Simulator only, not SideStore or LiveContainer.\n')


if __name__ == '__main__':
    main()
