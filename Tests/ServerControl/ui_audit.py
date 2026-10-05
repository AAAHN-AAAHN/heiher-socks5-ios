#!/usr/bin/env python3
"""Actual server-control UI on an isolated Simulator product, never an IPA.

Reuses the repository's disposable test-target construction pattern. The runtime,
project, native pin and prepare/Stop patch are unchanged; native/SDK success at the
same HEAD is required. A Simulator result is not SideStore or LiveContainer proof.
"""
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/server-control-ui-audit'
WORK = ROOT / '.build/server-control-ui-audit'
CORE = ROOT / '.build/core'


def run(args, log, cwd=ROOT, timeout=180):
    with (OUT / log).open('w') as stream:
        subprocess.run([str(a) for a in args], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=60, cwd=ROOT)


def add_test_target(app):
    project = app / 'Socks5.xcodeproj'
    path = project / 'project.pbxproj'
    value = json.loads(output('plutil', '-convert', 'json', '-o', '-', path))
    objects = value['objects']
    root = objects[value['rootObject']]
    targets = [key for key in root['targets'] if objects[key]['productType'] == 'com.apple.product-type.application']
    if len(targets) != 1:
        raise RuntimeError('Expected exactly one production app target')
    target = targets[0]
    def add(name, fields):
        key = hashlib.sha1(('server-control-ui-audit/' + name).encode()).hexdigest()[:24].upper()
        if key in objects:
            raise RuntimeError('Generated test object collides with an existing Xcode object')
        objects[key] = fields
        return key
    source = add('source', dict(isa='PBXFileReference', lastKnownFileType='sourcecode.swift', path='ServerControlUITests.swift', sourceTree='<group>'))
    file = add('build-file', dict(isa='PBXBuildFile', fileRef=source))
    sources = add('sources', dict(isa='PBXSourcesBuildPhase', buildActionMask='2147483647', files=[file], runOnlyForDeploymentPostprocessing='0'))
    frameworks = add('frameworks', dict(isa='PBXFrameworksBuildPhase', buildActionMask='2147483647', files=[], runOnlyForDeploymentPostprocessing='0'))
    product = add('product', dict(isa='PBXFileReference', explicitFileType='wrapper.cfbundle', includeInIndex='0', path='ServerControlUITests.xctest', sourceTree='BUILT_PRODUCTS_DIR'))
    proxy = add('proxy', dict(isa='PBXContainerItemProxy', containerPortal=value['rootObject'], proxyType='1', remoteGlobalIDString=target, remoteInfo='Socks5'))
    dependency = add('dependency', dict(isa='PBXTargetDependency', target=target, targetProxy=proxy))
    settings = dict(PRODUCT_BUNDLE_IDENTIFIER='hev.Socks5.ServerControlUITests', PRODUCT_NAME='$(TARGET_NAME)',
                    SWIFT_VERSION='5.0', SWIFT_TREAT_WARNINGS_AS_ERRORS='YES', GENERATE_INFOPLIST_FILE='YES',
                    IPHONEOS_DEPLOYMENT_TARGET='17.2', TARGETED_DEVICE_FAMILY='1', TEST_TARGET_NAME='Socks5',
                    SDKROOT='iphonesimulator', SUPPORTED_PLATFORMS='iphonesimulator', CODE_SIGNING_ALLOWED='NO',
                    CLANG_ENABLE_MODULES='YES', SWIFT_OPTIMIZATION_LEVEL='-Onone',
                    LD_RUNPATH_SEARCH_PATHS=['$(inherited)', '@executable_path/Frameworks', '@loader_path/Frameworks'])
    config = add('debug', dict(isa='XCBuildConfiguration', buildSettings=settings, name='Debug'))
    configs = add('configs', dict(isa='XCConfigurationList', buildConfigurations=[config], defaultConfigurationIsVisible='0', defaultConfigurationName='Debug'))
    test = add('test-target', dict(isa='PBXNativeTarget', buildConfigurationList=configs, buildPhases=[sources, frameworks],
               buildRules=[], dependencies=[dependency], name='ServerControlUITests', productName='ServerControlUITests',
               productReference=product, productType='com.apple.product-type.bundle.ui-testing'))
    root['targets'].append(test)
    root.setdefault('attributes', {}).setdefault('TargetAttributes', {})[test] = dict(CreatedOnToolsVersion='27.0', TestTargetID=target)
    objects[root['mainGroup']]['children'].append(source)
    objects[root['productRefGroup']]['children'].append(product)
    path.write_bytes(plistlib.dumps(value, sort_keys=False))
    shutil.copyfile(ROOT / 'Tests/ServerControl/ServerControlUITests.swift', app / 'ServerControlUITests.swift')
    scheme = project / 'xcshareddata/xcschemes/ServerControlUIAudit.xcscheme'
    scheme.parent.mkdir(parents=True, exist_ok=True)
    ref = lambda key, name, product: f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{key}" BuildableName="{product}" BlueprintName="{name}" ReferencedContainer="container:Socks5.xcodeproj"/>'
    app_ref = ref(target, 'Socks5', 'Socks5.app')
    test_ref = ref(test, 'ServerControlUITests', 'ServerControlUITests.xctest')
    scheme.write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2700" version="1.3">
<BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries>
<BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="NO" buildForArchiving="NO" buildForAnalyzing="YES">{app_ref}</BuildActionEntry>
<BuildActionEntry buildForTesting="YES" buildForRunning="NO" buildForProfiling="NO" buildForArchiving="NO" buildForAnalyzing="YES">{test_ref}</BuildActionEntry>
</BuildActionEntries></BuildAction>
<TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES">
<Testables><TestableReference skipped="NO">{test_ref}</TestableReference></Testables><MacroExpansion>{app_ref}</MacroExpansion>
</TestAction></Scheme>
''')
    shutil.copyfile(path, OUT / 'generated-test-project.pbxproj')


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
    if config['features'] != ['server']:
        raise RuntimeError('Independent server-control composition required')
    native = ROOT / 'artifacts/server-control'
    head = output('git', 'rev-parse', 'HEAD').strip()
    if not (native / 'SUCCESS.txt').is_file() or not (native / 'sdk-success.txt').is_file():
        raise RuntimeError('Same-source native and SDK success required')
    if (native / 'compiled-headers/source-commit.txt').read_text().strip() != head:
        raise RuntimeError('Stale native headers')
    run(['git', 'diff', '--exit-code',
         'b67733e7e13ae61401425e13a274f4fc7459bdb2', 'HEAD', '--',
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
        identifier = output('xcrun', 'simctl', 'create', 'Server Control UI Audit', device['identifier'], runtime['identifier']).strip()
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
        product = WORK / 'DerivedData/Build/Products/Debug-iphonesimulator/Socks5.app/Socks5'
        (OUT / 'simulator-app-sha256.txt').write_text(hashlib.sha256(product.read_bytes()).hexdigest() + '\n')
        for path, digest in snapshot.items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Audit modified a tracked source: ' + path)
    except Exception as exc:
        failure = exc
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
    (OUT / 'SUCCESS.txt').write_text('PASS: actual Simulator settings, invalid Start, Start/Stop, native listeners and portrait/landscape control reachability. No IPA, SideStore or LiveContainer test.\n')


if __name__ == '__main__':
    main()
