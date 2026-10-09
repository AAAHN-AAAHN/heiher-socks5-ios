#!/usr/bin/env python3
"""Actual statistics UI interaction on a temporary Simulator product; never an IPA.

The committed app/project and baseline XCFramework are not edited. A source copy
gets a test target and a Simulator-only library rebuilt from the declared patches.
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


def verify_presentation():
    """Keep the frozen table/sample behavior with the approved visibility cadence."""
    ui_base = 'cfcda5795b833b3ba8768fa4453f6f92606d3be1'
    changed = set(output('git', 'diff', '--name-only', ui_base, 'HEAD', '--',
                         'Socks5', 'Socks5.xcodeproj').splitlines())
    assert changed <= {'Socks5/Statistics/TrafficStatisticsView.swift',
                       'Socks5/Statistics/TrafficStatistics.swift'}, changed
    view = (ROOT / 'Socks5/Statistics/TrafficStatisticsView.swift').read_text()
    old_view = output('git', 'show', ui_base + ':Socks5/Statistics/TrafficStatisticsView.swift')
    model = (ROOT / 'Socks5/Statistics/TrafficStatistics.swift').read_text()
    old_model = output('git', 'show', ui_base + ':Socks5/Statistics/TrafficStatistics.swift')

    def endpoint_names(text):
        return text.replace('ClientTrafficStatistics', 'EndpointTrafficStatistics')\
            .replace('HevSocks5ClientStats', 'HevSocks5EndpointStats')\
            .replace('hev_socks5_server_client_stats', 'hev_socks5_server_endpoint_rows')\
            .replace('hev_socks5_server_stats', 'hev_socks5_server_endpoint_stats')

    def without_comments(text):
        return '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('//'))

    # Preserve the model and sampling behavior while decoding only new labels.
    approved_model = endpoint_names(without_comments(old_model))
    signature = 'address: String, received: UInt64'
    entry = 'Entry(id: id, address: address)'
    assert approved_model.count(signature) == 1 and approved_model.count(entry) == 1
    approved_model = approved_model.replace(signature, 'address: @autoclosure () -> String, received: UInt64')\
        .replace(entry, 'Entry(id: id, address: address())')
    assert without_comments(model) == approved_model
    renderer = '    /// One shared'
    sampler = '    private func sample()'
    assert view.split(renderer, 1)[1].split(sampler, 1)[0] == \
        old_view.split(renderer, 1)[1].split(sampler, 1)[0]
    approved_sample = endpoint_names(without_comments(old_view.split(sampler, 1)[1]))
    address_start = '            let address = withUnsafePointer(to: &row.address) {'
    address_end = ('            }\n'
                   '            sampledClients.sample(id: row.id, address: address, received: row.received,\n'
                   '                                 sent: row.sent, at: time)')
    assert approved_sample.count(address_start) == 1 and approved_sample.count(address_end) == 1
    approved_sample = approved_sample.replace(address_start,
        '            sampledClients.sample(id: row.id, address: withUnsafePointer(to: &row.address) {')\
        .replace(address_end, '            }, received: row.received, sent: row.sent, at: time)')
    assert without_comments(view.split(sampler, 1)[1]) == approved_sample
    old_task = endpoint_names(old_view.split('        .task(id:', 1)[1].split(renderer, 1)[0])
    guard = 'guard isVisible && scenePhase == .active else { return }'
    sleep = 'Task.sleep(for: .seconds(1))'
    assert old_task.count(guard) == 1 and old_task.count(sleep) == 1
    approved_task = old_task.replace(guard,
        'guard isVisible && scenePhase == .active && !Task.isCancelled else { return }')\
        .replace('                do { try await ' + sleep + ' }',
                 '                let now = Date().timeIntervalSinceReferenceDate\n'
                 '                let delay = ((now * 2).rounded(.down) + 1) / 2 - now\n'
                 '                do { try await Task.sleep(for: .seconds(delay)) }')
    assert view.split('        .task(id:', 1)[1].split(renderer, 1)[0] == approved_task

    # Move the unchanged Form inside the visible/active gate. Hidden body
    # evaluations cannot sort cached rows or format the tables.
    prefix = '                Section {\n                    Text("Spd.'
    old_prefix = endpoint_names(old_view.split(prefix, 1)[0])\
        .replace('No client payload recorded yet.', 'No peer socket I/O recorded yet.')\
        .replace('New clients will be included in the next sample.',
                 'Some peer rows are awaiting an update.')
    old_opening = ('    var body: some View {\n        let clientRows = clients.rows\n'
                   '        NavigationStack {\n')
    assert old_prefix.count(old_opening) == 1
    leading, form = old_prefix.split(old_opening, 1)
    approved_prefix = leading + ('    var body: some View {\n        NavigationStack {\n'
        '            if isVisible && scenePhase == .active {\n'
        '                let clientRows = clients.rows\n') + ''.join(
            '    ' + line for line in form.splitlines(keepends=True))
    assert view.split('    ' + prefix.replace('\n', '\n    '), 1)[0] == approved_prefix
    assert ('                .navigationTitle("Statistics")\n            }\n        }\n'
            '        .task(id: isVisible && scenePhase == .active)') in view
    assert 'DisclosureGroup' not in view
    assert view.count('summary(statistics, id: "total")') == 1
    assert view.count('summary(client.traffic, id: "client-\\(client.id)")') == 1
    assert view.count('        clients = sampledClients\n') == 1
    assert 'tableCell("In + Out"' in view and 'tableCell("Total"' not in view
    assert '.font(.body.weight(.bold))' in view and '.font(.callout)' in view
    assert 'Grid(alignment:' in view and '.foregroundStyle(.black)' in view
    assert '.fontWeight(bold ? .bold : .regular)' in view and 'Color(white: 0.82)' in view
    assert view.count('.minimumScaleFactor(0.5)') == 1
    assert '.minimumScaleFactor(0.7)' not in view
    assert '["KB", "MB", "GB", "TB", "PB"]' in model
    assert '["Kbps", "Mbps", "Gbps", "Tbps", "Pbps"]' in model
    assert 'In is bytes the OS accepted toward that IP' in view
    assert 'Out is bytes this server consumed from that IP' in view
    assert 'Total sums peer endpoints' in view
    assert 'over the actual sampling interval, in bits per second' in view


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
    verify_presentation()
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
        run(['xcrun', 'xcresulttool', 'export', 'attachments', '--path', OUT / 'UI.xcresult',
             '--output-path', OUT / 'screenshots'], 'screenshots-export.log')
        run(['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', OUT / 'UI.xcresult',
             '--compact'], 'test-summary.json')
        summary = json.loads((OUT / 'test-summary.json').read_text())
        assert summary['result'] == 'Passed', summary
        for key, expected in {'totalTestCount': 1, 'passedTests': 1,
                              'failedTests': 0, 'skippedTests': 0, 'expectedFailures': 0}.items():
            assert type(summary[key]) is int and summary[key] == expected, (key, summary)
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
    (OUT / 'SUCCESS.txt').write_text('PASS: actual Simulator scrolling, Start/Stop native handshake and tab navigation in portrait/landscape. No IPA, SideStore or LiveContainer test.\n')


if __name__ == '__main__':
    main()
