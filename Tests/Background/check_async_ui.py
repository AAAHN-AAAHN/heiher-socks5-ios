#!/usr/bin/env python3
"""Diagnose the remaining advisory in a temporary iOS27 Simulator source copy.

The tracked app and project are unchanged. Temporary call-boundary markers retain
real call order and results; their runtime is diagnostic evidence, not the final
uninstrumented product verification. No host or installer modification is made.
"""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/audio-async-ui'
WORK = ROOT / '.build/audio-async-ui'


def output(*args):
    return subprocess.check_output(list(map(str, args)), text=True, timeout=60)


def run(args, log, timeout=180):
    with (OUT / log).open('w') as stream:
        subprocess.run(list(map(str, args)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


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
        key = hashlib.sha1(('background-async-ui/' + name).encode()).hexdigest()[:24].upper()
        if key in objects:
            raise RuntimeError('Generated test object collides with an existing Xcode object')
        objects[key] = fields
        return key
    source = add('source', dict(isa='PBXFileReference', lastKnownFileType='sourcecode.swift', path='AsyncAudioUITests.swift', sourceTree='<group>'))
    file = add('build-file', dict(isa='PBXBuildFile', fileRef=source))
    sources = add('sources', dict(isa='PBXSourcesBuildPhase', buildActionMask='2147483647', files=[file], runOnlyForDeploymentPostprocessing='0'))
    frameworks = add('frameworks', dict(isa='PBXFrameworksBuildPhase', buildActionMask='2147483647', files=[], runOnlyForDeploymentPostprocessing='0'))
    product = add('product', dict(isa='PBXFileReference', explicitFileType='wrapper.cfbundle', includeInIndex='0', path='AsyncAudioUITests.xctest', sourceTree='BUILT_PRODUCTS_DIR'))
    proxy = add('proxy', dict(isa='PBXContainerItemProxy', containerPortal=value['rootObject'], proxyType='1', remoteGlobalIDString=target, remoteInfo='Socks5'))
    dependency = add('dependency', dict(isa='PBXTargetDependency', target=target, targetProxy=proxy))
    settings = dict(PRODUCT_BUNDLE_IDENTIFIER='hev.Socks5.AsyncAudioUITests', PRODUCT_NAME='$(TARGET_NAME)',
                    SWIFT_VERSION='5.0', SWIFT_TREAT_WARNINGS_AS_ERRORS='YES', GENERATE_INFOPLIST_FILE='YES',
                    IPHONEOS_DEPLOYMENT_TARGET='17.2', TARGETED_DEVICE_FAMILY='1', TEST_TARGET_NAME='Socks5',
                    SDKROOT='iphonesimulator', SUPPORTED_PLATFORMS='iphonesimulator', CODE_SIGNING_ALLOWED='NO',
                    CLANG_ENABLE_MODULES='YES', SWIFT_OPTIMIZATION_LEVEL='-Onone',
                    LD_RUNPATH_SEARCH_PATHS=['$(inherited)', '@executable_path/Frameworks', '@loader_path/Frameworks'])
    config = add('debug', dict(isa='XCBuildConfiguration', buildSettings=settings, name='Debug'))
    configs = add('configs', dict(isa='XCConfigurationList', buildConfigurations=[config], defaultConfigurationIsVisible='0', defaultConfigurationName='Debug'))
    test = add('test-target', dict(isa='PBXNativeTarget', buildConfigurationList=configs, buildPhases=[sources, frameworks],
               buildRules=[], dependencies=[dependency], name='AsyncAudioUITests', productName='AsyncAudioUITests',
               productReference=product, productType='com.apple.product-type.bundle.ui-testing'))
    root['targets'].append(test)
    root.setdefault('attributes', {}).setdefault('TargetAttributes', {})[test] = dict(CreatedOnToolsVersion='27.0', TestTargetID=target)
    objects[root['mainGroup']]['children'].append(source)
    objects[root['productRefGroup']]['children'].append(product)
    path.write_bytes(plistlib.dumps(value, sort_keys=False))
    shutil.copyfile(ROOT / 'Tests/Background/AsyncAudioUITests.swift', app / 'AsyncAudioUITests.swift')
    scheme = project / 'xcshareddata/xcschemes/AsyncAudioAudit.xcscheme'
    scheme.parent.mkdir(parents=True, exist_ok=True)
    ref = lambda key, name, product: f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{key}" BuildableName="{product}" BlueprintName="{name}" ReferencedContainer="container:Socks5.xcodeproj"/>'
    app_ref = ref(target, 'Socks5', 'Socks5.app')
    test_ref = ref(test, 'AsyncAudioUITests', 'AsyncAudioUITests.xctest')
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


def instrument_audio_boundary(app):
    # Diagnostic-only copy: preserve the real calls and ordering, bracket each
    # suspected synchronous boundary. No probe is written to the tracked source.
    path = app / 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift'
    source = path.read_text()
    calls = {
        'let session = AVAudioSession.sharedInstance()': 'shared-session',
        'try session.setCategory(.playback, mode: .default, options: [.mixWithOthers])': 'category',
        'try? session.setPrefersNoInterruptionsFromSystemAlerts(true)': 'alert-preference',
        'player = try AVAudioPlayer(contentsOf: url)': 'player-init',
    }
    for call, label in calls.items():
        if call not in source:
            raise RuntimeError('Missing diagnostic boundary: ' + call)
        source = source.replace(call, f'NSLog("BG_AUDIO_TRACE before {label}"); {call}; NSLog("BG_AUDIO_TRACE after {label}")')
    source = source.replace('session.activate(options: [], completionHandler: completion)',
        'NSLog("BG_AUDIO_TRACE before async-activate"); session.activate(options: [], completionHandler: completion); NSLog("BG_AUDIO_TRACE after async-activate-request")')
    source = source.replace('session.deactivate(options: [.notifyOthersOnDeactivation], completionHandler: completion)',
        'NSLog("BG_AUDIO_TRACE before async-deactivate"); session.deactivate(options: [.notifyOthersOnDeactivation], completionHandler: completion); NSLog("BG_AUDIO_TRACE after async-deactivate-request")')
    source = source.replace('guard let current = player, current.play(),',
        'guard let current = player, tracePlay(current),')
    source = source.replace('previous?.stop()',
        'NSLog("BG_AUDIO_TRACE before stop"); previous?.stop(); NSLog("BG_AUDIO_TRACE after stop")')
    helper = '\n    private func tracePlay(_ player: AVAudioPlayer) -> Bool {\n        NSLog("BG_AUDIO_TRACE before player-play")\n        defer { NSLog("BG_AUDIO_TRACE after player-play") }\n        return player.play()\n    }\n'
    source = source[:source.rfind('}')] + helper + source[source.rfind('}'):]
    path.write_text(source)
    (OUT / 'diagnostic-controller.swift').write_text(source)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'SUCCESS.txt').unlink(missing_ok=True)
    if not __debug__ or WORK.exists():
        raise SystemExit('Assertions and a clean workspace are required')
    if not output('xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version').startswith('27.'):
        raise SystemExit('Actual iOS27 Simulator SDK required')
    paths = output('git', 'ls-files').splitlines()
    snapshot = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    (OUT / 'source-sha256.json').write_text(json.dumps(snapshot, indent=2) + '\n')
    (OUT / 'tested-commit.txt').write_text(output('git', 'rev-parse', 'HEAD'))
    run(['git', 'archive', '--format=zip', 'HEAD', '-o', OUT / 'source.zip'], 'source-archive.log')
    run(['xcodebuild', '-version'], 'toolchain.txt')
    app = WORK / 'application'
    app.mkdir(parents=True)
    with zipfile.ZipFile(OUT / 'source.zip') as source:
        source.extractall(app)
    add_test_target(app)
    instrument_audio_boundary(app)
    runtimes = json.loads(output('xcrun', 'simctl', 'list', 'runtimes', '-j'))['runtimes']
    runtime = next(r for r in runtimes if r.get('isAvailable') and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27-'))
    device = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'
    identifier = output('xcrun', 'simctl', 'create', 'Background Async Audio', device, runtime['identifier']).strip()
    (OUT / 'runtime.json').write_text(json.dumps(dict(runtime=runtime, device=device, udid=identifier), indent=2))
    failure = None
    cleanup = []
    trace = None
    trace_stream = (OUT / 'audio-boundary-trace.log').open('w')
    try:
        run(['xcrun', 'simctl', 'boot', identifier], 'boot.log')
        run(['xcrun', 'simctl', 'bootstatus', identifier, '-b'], 'ready.log', timeout=120)
        trace = subprocess.Popen(['xcrun', 'simctl', 'spawn', identifier, 'log', 'stream',
                                  '--style', 'compact', '--level', 'debug', '--predicate',
                                  'process == "Socks5" AND (eventMessage CONTAINS "BG_AUDIO_TRACE" OR eventMessage CONTAINS "UI unresponsiveness")'],
                                 stdout=trace_stream, stderr=subprocess.STDOUT)
        run(['xcodebuild', 'test', '-project', app / 'Socks5.xcodeproj', '-scheme', 'AsyncAudioAudit',
             '-destination', 'platform=iOS Simulator,id=' + identifier, '-parallel-testing-enabled', 'NO',
             '-derivedDataPath', WORK / 'DerivedData', '-resultBundlePath', OUT / 'UI.xcresult',
             '-collect-test-diagnostics', 'never', 'CODE_SIGNING_ALLOWED=NO',
             'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES'], 'ui-test.log', timeout=900)
        run(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', OUT / 'UI.xcresult'], 'test-summary.json')
        run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', OUT / 'UI.xcresult',
             '--output-path', OUT / 'attachments'], 'attachments.log')
        run(['xcrun', 'xcresulttool', 'get', 'object', '--legacy', '--format', 'json',
             '--path', OUT / 'UI.xcresult'], 'result-object.json')
        summary = json.loads((OUT / 'test-summary.json').read_text())
        if summary.get('failedTests', 0) != 0 or summary.get('passedTests', 0) < 1:
            raise RuntimeError('Actual XCTest result is not a completed pass')
        # Inspect runtime issues as well as the console; do not disable their reporting.
        for name in ('ui-test.log', 'result-object.json'):
            text = (OUT / name).read_text()
            if 'This method can lead to UI unresponsiveness' in text:
                raise RuntimeError('The observed synchronous audio advisory remains: ' + name)
        (OUT / 'advisory-check.txt').write_text('PASS: no matching main-thread audio advisory in completed XCTest runtime results or console. Not a whole-device hang guarantee.\n')
        product = WORK / 'DerivedData/Build/Products/Debug-iphonesimulator/Socks5.app/Socks5'
        (OUT / 'app-sha256.txt').write_text(hashlib.sha256(product.read_bytes()).hexdigest() + '\n')
        for p, digest in snapshot.items():
            if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest:
                raise RuntimeError('Tracked source modified: ' + p)
    except Exception as exc:
        failure = exc
    finally:
        if trace is not None:
            trace.terminate()
            try:
                trace.wait(timeout=10)
            except subprocess.TimeoutExpired:
                trace.kill()
                trace.wait(timeout=10)
                cleanup.append('Diagnostic log stream required forced termination')
        trace_stream.close()
        for action in ('shutdown', 'delete'):
            try:
                run(['xcrun', 'simctl', action, identifier], 'cleanup-' + action + '.log', timeout=30)
            except Exception as exc:
                cleanup.append(str(exc))
    (OUT / 'cleanup.json').write_text(json.dumps(cleanup))
    if failure:
        raise failure
    if cleanup:
        raise RuntimeError('Simulator cleanup failed: ' + repr(cleanup))
    (OUT / 'SUCCESS.txt').write_text('PASS: actual iOS27 Simulator audio On/Off, playback, saved intent and advisory check. No physical SideStore, LiveContainer, background survival or IPA.\n')


if __name__ == '__main__':
    main()
