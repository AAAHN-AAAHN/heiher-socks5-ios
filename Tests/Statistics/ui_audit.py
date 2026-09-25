#!/usr/bin/env python3
"""Actual statistics UI interaction on a temporary Simulator product; never an IPA.

The committed app/project and baseline XCFramework are not edited. A source copy
gets a test target and a Simulator-only library rebuilt from the six pinned patches.
XCTest drives actual scrolling, taps, tab switches and a native SOCKS greeting.
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
OUT = ROOT / 'artifacts/statistics-ui-audit'
WORK = ROOT / '.build/statistics-ui-audit'
CORE = ROOT / '.build/statistics-final-audit/core'


def run(args, log, cwd=ROOT, timeout=180):
    with (OUT / log).open('w') as stream:
        subprocess.run([str(a) for a in args], cwd=cwd, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=60)


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
        key = hashlib.sha1(('statistics-ui-audit/' + name).encode()).hexdigest()[:24].upper()
        if key in objects:
            raise RuntimeError('Generated test object collides with an existing Xcode object')
        objects[key] = fields
        return key
    source = add('source', dict(isa='PBXFileReference', lastKnownFileType='sourcecode.swift', path='StatisticsUITests.swift', sourceTree='<group>'))
    file = add('build-file', dict(isa='PBXBuildFile', fileRef=source))
    sources = add('sources', dict(isa='PBXSourcesBuildPhase', buildActionMask='2147483647', files=[file], runOnlyForDeploymentPostprocessing='0'))
    frameworks = add('frameworks', dict(isa='PBXFrameworksBuildPhase', buildActionMask='2147483647', files=[], runOnlyForDeploymentPostprocessing='0'))
    product = add('product', dict(isa='PBXFileReference', explicitFileType='wrapper.cfbundle', includeInIndex='0', path='StatisticsUITests.xctest', sourceTree='BUILT_PRODUCTS_DIR'))
    proxy = add('proxy', dict(isa='PBXContainerItemProxy', containerPortal=value['rootObject'], proxyType='1', remoteGlobalIDString=target, remoteInfo='Socks5'))
    dependency = add('dependency', dict(isa='PBXTargetDependency', target=target, targetProxy=proxy))
    settings = dict(PRODUCT_BUNDLE_IDENTIFIER='hev.Socks5.StatisticsUITests', PRODUCT_NAME='$(TARGET_NAME)',
                    SWIFT_VERSION='5.0', SWIFT_TREAT_WARNINGS_AS_ERRORS='YES', GENERATE_INFOPLIST_FILE='YES',
                    IPHONEOS_DEPLOYMENT_TARGET='17.2', TARGETED_DEVICE_FAMILY='1', TEST_TARGET_NAME='Socks5',
                    SDKROOT='iphonesimulator', SUPPORTED_PLATFORMS='iphonesimulator', CODE_SIGNING_ALLOWED='NO',
                    CLANG_ENABLE_MODULES='YES', SWIFT_OPTIMIZATION_LEVEL='-Onone',
                    LD_RUNPATH_SEARCH_PATHS=['$(inherited)', '@executable_path/Frameworks', '@loader_path/Frameworks'])
    config = add('debug', dict(isa='XCBuildConfiguration', buildSettings=settings, name='Debug'))
    configs = add('configs', dict(isa='XCConfigurationList', buildConfigurations=[config], defaultConfigurationIsVisible='0', defaultConfigurationName='Debug'))
    test = add('test-target', dict(isa='PBXNativeTarget', buildConfigurationList=configs, buildPhases=[sources, frameworks],
               buildRules=[], dependencies=[dependency], name='StatisticsUITests', productName='StatisticsUITests',
               productReference=product, productType='com.apple.product-type.bundle.ui-testing'))
    root['targets'].append(test)
    root.setdefault('attributes', {}).setdefault('TargetAttributes', {})[test] = dict(CreatedOnToolsVersion='27.0', TestTargetID=target)
    objects[root['mainGroup']]['children'].append(source)
    objects[root['productRefGroup']]['children'].append(product)
    path.write_bytes(plistlib.dumps(value, sort_keys=False))
    shutil.copyfile(ROOT / 'Tests/Statistics/StatisticsUITests.swift', app / 'StatisticsUITests.swift')
    scheme = project / 'xcshareddata/xcschemes/StatisticsUIAudit.xcscheme'
    scheme.parent.mkdir(parents=True, exist_ok=True)
    ref = lambda key, name, product: f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{key}" BuildableName="{product}" BlueprintName="{name}" ReferencedContainer="container:Socks5.xcodeproj"/>'
    app_ref = ref(target, 'Socks5', 'Socks5.app')
    test_ref = ref(test, 'StatisticsUITests', 'StatisticsUITests.xctest')
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
    (OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    if not __debug__ or sys.platform != 'darwin':
        raise SystemExit('Assertions and an actual Apple toolchain are required')
    if WORK.exists():
        raise SystemExit('Use a clean UI audit workspace')
    if not output('xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version').strip().startswith('27.'):
        raise SystemExit('An iOS 27 Simulator SDK is required')
    config = json.loads((ROOT / 'Build/features.json').read_bytes())
    if config['features'] != ['udp', 'statistics']:
        raise RuntimeError('Statistics-only composition required')
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
        identifier = output('xcrun', 'simctl', 'create', 'Statistics UI Audit', device['identifier'], runtime['identifier']).strip()
        (OUT / 'runtime.json').write_text(json.dumps(dict(runtime=runtime, deviceType=device, udid=identifier), indent=2))
        run(['xcrun', 'simctl', 'boot', identifier], 'simulator-boot.log')
        run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], 'simulator-ready.log', timeout=120)
        run(['xcodebuild', 'test', '-project', app / 'Socks5.xcodeproj', '-scheme', 'StatisticsUIAudit',
             '-destination', 'platform=iOS Simulator,id=' + identifier, '-parallel-testing-enabled', 'NO',
             '-derivedDataPath', WORK / 'DerivedData', '-resultBundlePath', OUT / 'UI.xcresult',
             'CODE_SIGNING_ALLOWED=NO', 'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES'], 'ui-test.log', timeout=900)
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
    (OUT / 'SUCCESS.txt').write_text('PASS: actual Simulator scrolling, Start/Stop native handshake and tab navigation in portrait/landscape. No IPA, SideStore or LiveContainer test.\n')


if __name__ == '__main__':
    main()
