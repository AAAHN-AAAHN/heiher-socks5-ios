#!/usr/bin/env python3
"""Actual persistent settings UI on an isolated Simulator product, never an IPA.

Reuses the repository's disposable test-target construction pattern. The runtime,
project, native pin and prepare/Stop patch are unchanged; native/SDK success at the
same HEAD is required. A Simulator result is not SideStore or LiveContainer proof.
"""
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/settings-persistence-ui-audit'
WORK = ROOT / '.build/settings-persistence-ui-audit'
CORE = ROOT / '.build/core'


def run(args, log, cwd=ROOT, timeout=180):
    with (OUT / log).open('w') as stream:
        subprocess.run([str(a) for a in args], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=60, cwd=ROOT)


def add_test_target(app):
    # Reuse the exact server owner's temporary target builder, never its test body.
    import importlib.util
    spec = importlib.util.spec_from_file_location('server_ui', ROOT / 'Tests/ServerControl/ui_audit.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.OUT = OUT
    builder.add_test_target(app)
    original = app / 'ServerControlUITests.swift'
    original.unlink()
    shutil.copyfile(ROOT / 'Tests/Settings/SettingsPersistenceUITests.swift', app / 'SettingsPersistenceUITests.swift')
    project = app / 'Socks5.xcodeproj/project.pbxproj'
    scheme = app / 'Socks5.xcodeproj/xcshareddata/xcschemes/ServerControlUIAudit.xcscheme'
    for path in (project, scheme):
        path.write_text(path.read_text().replace('ServerControlUITests', 'SettingsPersistenceUITests'))
    shutil.copyfile(project, OUT / 'generated-test-project.pbxproj')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ('SUCCESS.txt', 'simulator-app-sha256.txt', 'simulator-library-sha256.txt'):
        (OUT / name).unlink(missing_ok=True)
    if not __debug__ or sys.platform != 'darwin':
        raise SystemExit('Assertions and an actual Apple toolchain are required')
    if WORK.exists():
        raise SystemExit('Use a clean UI audit workspace')
    run(['git', 'diff', '--exit-code', 'HEAD', '--'], 'input-worktree.log')
    run(['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 'input-index.log')
    if not output('xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version').strip().startswith('27.'):
        raise SystemExit('An iOS 27 Simulator SDK is required')
    config = json.loads((ROOT / 'Build/features.json').read_bytes())
    if config['features'] != ['server', 'settings']:
        raise RuntimeError('Settings plus server-control composition required')
    native = ROOT / 'artifacts/settings-persistence'
    head = output('git', 'rev-parse', 'HEAD').strip()
    if not (native / 'SUCCESS.txt').is_file() or not (native / 'sdk-success.txt').is_file():
        raise RuntimeError('Same-source native and SDK success required')
    if (native / 'compiled-headers/source-commit.txt').read_text().strip() != head:
        raise RuntimeError('Stale native headers')
    run(['git', 'diff', '--exit-code',
         '9b40f1bc3885b74b6016cf4e6eb2e6689ee18664', 'HEAD', '--',
         'Socks5', 'Socks5.xcodeproj', 'Patches', 'Build/features.json', 'Build/upstream.json',
         'HevSocks5Server.xcframework'], 'preserved-production.log')
    snapshot = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                for p in output('git', 'ls-files').splitlines()}
    (OUT / 'source-sha256.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    (OUT / 'tested-commit.txt').write_text(output('git', 'rev-parse', 'HEAD'))
    run(['git', 'archive', '--format=zip', 'HEAD', '-o', OUT / 'source.zip'], 'source-archive.log')
    app = WORK / 'application'
    app.mkdir(parents=True)
    with zipfile.ZipFile(OUT / 'source.zip') as archive:
        archive.extractall(app)
    identifier = None
    applied = False
    failure = None
    cleanup = []
    try:
        run([sys.executable, 'Build/check.py', 'apply', CORE], 'native-apply.log')
        applied = True
        run(['tar', '--exclude=./.git', '--exclude=*/.git', '--exclude=./bin',
             '--exclude=*/bin', '--exclude=./build', '--exclude=*/build',
             '-czf', OUT / 'native-patched-source.tar.gz', '.'], 'native-archive.log', CORE)
        run(['make', 'clean'], 'native-clean.log', CORE)
        arch = platform.machine()
        if arch not in ('arm64', 'x86_64'):
            raise RuntimeError('Unsupported Simulator architecture: ' + arch)
        compiler = 'xcrun --sdk iphonesimulator clang'
        flags = f'-target {arch}-apple-ios17.2-simulator -isysroot ' + output('xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path').strip()
        run(['make', '-j3', 'PP=' + compiler, 'CC=' + compiler, 'CFLAGS=' + flags, 'static'], 'native-simulator-build.log', CORE, 600)
        library = WORK / 'libhev-socks5-server.a'
        run(['xcrun', 'libtool', '-static', '-o', library, CORE / 'bin/libhev-socks5-server.a',
             CORE / 'third-part/yaml/bin/libyaml.a', CORE / 'third-part/hev-task-system/bin/libhev-task-system.a'], 'native-combine.log')
        headers = WORK / 'headers'; headers.mkdir()
        for name in ('hev-main.h', 'module.modulemap'):
            shutil.copyfile(CORE / ('src/' + name if name.endswith('.h') else name), headers / name)
        framework = app / 'HevSocks5Server.xcframework'
        shutil.rmtree(framework)
        run(['xcodebuild', '-create-xcframework', '-library', library, '-headers', headers, '-output', framework], 'simulator-framework.log')
        (OUT / 'simulator-library-sha256.txt').write_text(hashlib.sha256(library.read_bytes()).hexdigest() + '\n')
        add_test_target(app)
        runtimes = json.loads(output('xcrun', 'simctl', 'list', 'runtimes', '-j'))['runtimes']
        runtime = next(r for r in runtimes if r.get('isAvailable') and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27-'))
        devices = json.loads(output('xcrun', 'simctl', 'list', 'devicetypes', '-j'))['devicetypes']
        device = next(d for d in devices if d['name'] == 'iPhone 16')
        identifier = output('xcrun', 'simctl', 'create', 'Settings Persistence UI Audit', device['identifier'], runtime['identifier']).strip()
        (OUT / 'runtime.json').write_text(json.dumps(dict(runtime=runtime, deviceType=device, udid=identifier), indent=2))
        run(['xcrun', 'simctl', 'boot', identifier], 'simulator-boot.log')
        run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], 'simulator-ready.log', timeout=120)
        run(['xcodebuild', 'test', '-project', app / 'Socks5.xcodeproj', '-scheme', 'ServerControlUIAudit',
             '-destination', 'platform=iOS Simulator,id=' + identifier, '-parallel-testing-enabled', 'NO',
             '-derivedDataPath', WORK / 'DerivedData', '-resultBundlePath', OUT / 'UI.xcresult',
             'CODE_SIGNING_ALLOWED=NO', 'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES'], 'ui-test.log', timeout=900)
        run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', OUT / 'UI.xcresult',
             '--output-path', OUT / 'screenshots'], 'screenshots-export.log')
        run(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', OUT / 'UI.xcresult',
             '--compact'], 'test-summary.json')
        summary = json.loads((OUT / 'test-summary.json').read_text())
        if summary.get('failedTests') != 0 or summary.get('passedTests') != 1 or summary.get('skippedTests') != 0:
            raise RuntimeError('Expected exactly one successful persistence UI test')
        container = Path(output('xcrun', 'simctl', 'get_app_container', identifier, 'hev.Socks5', 'data').strip())
        settings_file = container / 'Library/Application Support/Socks5/settings.json'
        data = settings_file.read_bytes()
        saved = json.loads(data)
        expected = dict(version=1, server=dict(workers='2', listenAddress='::', listenPort='1080',
            udpListenAddress='', udpListenPort='1080', bindIPv4Address='0.0.0.0', bindIPv6Address='::',
            bindInterface='', authUsername='', authPassword='', listenIPv6Only=False),
            serverRunning=False, background=dict(continuousLocation=False, silentAudio=False), selectedTab='settings')
        if saved != expected or len(data) > 65536:
            raise RuntimeError('Actual app settings.json does not match the UI persistence postcondition')
        (OUT / 'actual-settings.json').write_bytes(data)
        files = sorted(p.name for p in settings_file.parent.iterdir())
        if files != ['settings.json']:
            raise RuntimeError('Unexpected persistent or temporary files: ' + repr(files))
        (OUT / 'storage-result.json').write_text(json.dumps(dict(exactSnapshot=True, bytes=len(data), files=files,
            sha256=hashlib.sha256(data).hexdigest(), physicalProtectionTest=False), indent=2) + '\n')
        product = WORK / 'DerivedData/Build/Products/Debug-iphonesimulator/Socks5.app/Socks5'
        (OUT / 'simulator-app-sha256.txt').write_text(hashlib.sha256(product.read_bytes()).hexdigest() + '\n')
        for path, digest in snapshot.items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Audit modified a tracked source: ' + path)
    except Exception as exc:
        failure = exc
        # Preserve the actual file on a failed run without changing app state or
        # masking the original failure. No diagnostic code enters production.
        if identifier:
            try:
                container = Path(output('xcrun', 'simctl', 'get_app_container', identifier, 'hev.Socks5', 'data').strip())
                saved = container / 'Library/Application Support/Socks5/settings.json'
                (OUT / 'failed-settings.json').write_bytes(saved.read_bytes())
            except Exception as diagnostic:
                (OUT / 'failed-settings-read.txt').write_text(str(diagnostic) + '\n')
    finally:
        if identifier:
            for action in ('shutdown', 'delete'):
                try:
                    run(['xcrun', 'simctl', action, identifier], 'cleanup-' + action + '.log', timeout=30)
                except Exception as exc:
                    cleanup.append(str(exc))
        if applied:
            try:
                run([sys.executable, 'Build/check.py', 'reverse', CORE], 'native-reverse.log')
            except Exception as exc:
                cleanup.append(str(exc))
    (OUT / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
    if failure:
        raise failure
    if cleanup:
        raise RuntimeError('UI audit cleanup failed: ' + repr(cleanup))
    run(['git', 'diff', '--exit-code', 'HEAD', '--'], 'final-worktree.log')
    run(['git', 'diff', '--cached', '--exit-code', 'HEAD', '--'], 'final-index.log')
    (OUT / 'SUCCESS.txt').write_text('PASS: actual Simulator durable drafts, Start/Stop and tab restoration, native listeners, import/export sheet cancellation and exact on-disk JSON. No IPA, SideStore or LiveContainer test.\n')


if __name__ == '__main__':
    main()
