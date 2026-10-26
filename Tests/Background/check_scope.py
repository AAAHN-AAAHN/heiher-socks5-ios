#!/usr/bin/env python3
"""Audit the Background delta while preserving its complete native parent.

This checks source/configuration contracts, not an installed app or OS permission.
Run against a complete Git checkout; source archives do not prove ancestry.
"""
import ast
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / 'Build/features.json').read_bytes())
BASE = CONFIG['base_commit']
assert BASE == '0181c7a3a0e19dc45eaad8b4f9767efb8d094abe'
PARENT = json.loads((ROOT / 'docs/documentation.json').read_bytes())['parents']['feature/icmp-relay']


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def data(path):
    return (ROOT / path).read_bytes()


def text(path):
    return data(path).decode('utf-8')


def original(path):
    return git('show', PARENT + ':' + path)


def fields(project, name):
    return re.findall(r'^\s*' + re.escape(name) + r' = (.*);$', project, re.M)


def main():
    import runpy
    documents = runpy.run_path(str(ROOT / 'Build/check_documentation.py'))
    documents['check'](ROOT)
    git('merge-base', '--is-ancestor', BASE, 'HEAD')
    git('merge-base', '--is-ancestor', PARENT, 'HEAD')
    base_paths = documents['code_paths'](ROOT, git('ls-tree', '-r', '--name-only', PARENT).decode().splitlines())
    current_paths = documents['code_paths'](ROOT, git('ls-files').decode().splitlines())
    allowed = {'.github/workflows/verify-build.yml', 'Build/check.py',
               'Build/features.json', 'README.md', 'Socks5/Socks5App.swift', 'Socks5/ContentView.swift',
               'Socks5.xcodeproj/project.pbxproj'}
    additions = {'Socks5/AppRoot.swift', 'Socks5/Info.plist',
                 'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift',
                 'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift',
                 'Socks5/BackgroundKeepAlive/LoopAudioService.swift',
                 'Socks5/BackgroundKeepAlive/PlaybackProgressMonitor.swift',
                 'Socks5/BackgroundKeepAlive/RecoveryExecutionLease.swift',
                 'Socks5/BackgroundKeepAlive/PeriodicPingService.swift',
                 'Socks5/BackgroundKeepAlive/PeriodicPingModel.swift',
                 'Socks5/BackgroundKeepAlive/Silence.wav', 'docs/features/background.md'}
    assert set(base_paths) <= set(current_paths), 'An inherited native-parent file was removed'
    for path in set(current_paths) - set(base_paths):
        assert path in additions or path.startswith('Tests/Background/'), path
    preserved = []
    for path in base_paths:
        if path not in allowed:
            assert data(path) == original(path), 'Inherited native-parent implementation changed: ' + path
            assert git('ls-files', '--stage', path).split()[0] == git('ls-tree', PARENT, path).split()[0], path
            preserved.append(path)
    assert data('Socks5/Socks5App.swift') == original('Socks5/Socks5App.swift').replace(
        b'ContentView()', b'AppRoot()', 1), 'Unexpected app entry-point change'
    # Only snapshot UI inputs before the worker and return completion to MainActor.
    # Keep the baseline layout, YAML, native invocation and Stop behavior exact.
    baseline_view = original('Socks5/ContentView.swift')
    assert baseline_view.count(b'DispatchQueue.global().async {') == 1
    assert baseline_view.count(b'                        isRunning = false\n') == 1
    expected_view = baseline_view.replace(
        b'DispatchQueue.global().async {',
        b'DispatchQueue.global().async { [workersText, listenPortText, listenAddrText,\n'
        b'                        udpListenPortText, udpListenAddrText, listenIpv6OnlyToggle,\n'
        b'                        bindIpv4AddrText, bindIpv6AddrText, bindIfaceText, authUserText, authPassText] in', 1)
    expected_view = expected_view.replace(
        b'                        isRunning = false\n',
        b'                        DispatchQueue.main.async { isRunning = false }\n', 1)
    assert data('Socks5/ContentView.swift') == expected_view, 'Unexpected standalone UI actor-boundary change'
    baseline_config = json.loads(original('Build/features.json'))
    assert CONFIG['name'] == 'background'
    assert CONFIG['features'] == baseline_config['features'] + ['background']
    assert CONFIG['patches'] == baseline_config['patches']
    for key in ('base_commit', 'sources', 'upstream_app'):
        assert CONFIG[key] == baseline_config[key]
    # Feature validation may evolve; native patch/format/reverse/package logic may not.
    old_checks = ast.parse(original('Build/check.py'))
    new_checks = ast.parse(data('Build/check.py'))
    old_functions = {n.name: n for n in old_checks.body if isinstance(n, ast.FunctionDef)}
    new_functions = {n.name: n for n in new_checks.body if isinstance(n, ast.FunctionDef)}
    for name, function in old_functions.items():
        if name not in {'baseline', 'composition'}:
            assert ast.dump(function) == ast.dump(new_functions[name]), name
    project = text('Socks5.xcodeproj/project.pbxproj')
    old_project = original('Socks5.xcodeproj/project.pbxproj').decode()
    for key in ('IPHONEOS_DEPLOYMENT_TARGET', 'PRODUCT_BUNDLE_IDENTIFIER',
                'SWIFT_VERSION', 'TARGETED_DEVICE_FAMILY', 'CODE_SIGN_STYLE'):
        assert fields(project, key) == fields(old_project, key), key
    assert fields(project, 'INFOPLIST_FILE') == ['Socks5/Info.plist'] * 2
    assert fields(project, 'INFOPLIST_KEY_UIApplicationSceneManifest_Generation') == ['NO'] * 2
    assert not fields(project, 'CODE_SIGN_ENTITLEMENTS')
    info = plistlib.loads(data('Socks5/Info.plist'))
    assert set(info['UIBackgroundModes']) == {'audio', 'location'}
    assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False
    for key in ('NSLocationWhenInUseUsageDescription',
                'NSLocationAlwaysAndWhenInUseUsageDescription', 'NSLocalNetworkUsageDescription'):
        assert isinstance(info[key], str) and info[key].strip(), key
    assert not any(key.startswith('BGTask') for key in info)
    assert not list((ROOT / 'Socks5').rglob('*.entitlements'))
    root = text('Socks5/AppRoot.swift')
    assert re.findall(r'@AppStorage\("([^"]+)"\)', root) == [
        'background.continuousLocation', 'background.silentAudio']
    assert root.count('@StateObject private var keepAlive = BackgroundKeepAlive()') == 1
    assert root.count('.modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))') == 1
    assert 'ScrollView { ContentView() }' in root
    for name in ('location', 'audio'):
        assert '.onChange(of: ' + name + 'Enabled, initial: true)' in root
    assert 'locationEnabled: $locationEnabled' in root
    assert 'keepAlive.setLocation(value)' in root
    assert 'keepAlive.syncAudio(value)' in root
    binding = root[root.index('audioEnabled: Binding('):root.index('.tabItem { Label("Background"')]
    assert binding.index('keepAlive.setAudio(value)') < binding.index('audioEnabled = keepAlive.audioEnabled')
    assert 'audioEnabled = value' not in binding
    controller = text('Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift')
    assert all(token not in controller for token in ('UserDefaults', 'AppStorage', 'HevSocks5Server',
                                                    'BGTaskScheduler', 'MPRemoteCommandCenter'))
    assert all(token not in controller for token in ('Timer(', 'AVAudioPlayer', 'AVAudioSession.sharedInstance'))
    assert 'deinit { audio.unregister(audioOwner) }' in controller
    assert 'audio.setEnabled(enabled, owner: audioOwner)' in controller
    service = text('Socks5/BackgroundKeepAlive/LoopAudioService.swift')
    assert service.count('DispatchSource.makeTimerSource(') == 1
    assert service.count('DispatchSource.makeTimerSource(flags: recovery ? .strict : [], queue: control)') == 1
    assert 'var interval = 0.5' in service and 'var warning = 2.0' in service and 'var stalled = 10.0' in service
    assert 'var speculativeRecoveryCertified = false' in service
    assert 'precondition(outstanding == 1)' in service
    assert 'guard work == nil else { return }' in service
    assert 'if next.stop != current.stop { releaseBarrier = true }' in service
    assert 'executionClaim.start(mayIssue: { [weak self] in self?.mayRequestClaim(job.ticket) == true })' in service
    assert 'return !exhausted && ticket.on && ticket.stop == input.stop\n' in service
    assert 'return !exhausted && ticket.on && ticket.stop == input.stop && ticket.epoch == input.epoch' in service
    assert 'retryAt = returnedAt + policy.interval' in service
    assert 'timerOperation == work?.id, armed <= deadline' in service
    assert 'enum Step: String, Sendable {' in service
    assert 'defer { context.step(step, true) }' in service
    assert 'guard !inbox.queued else { return false }' in service
    assert 'queue: nil)' in service and 'self?.notify(normalize(note))' in service
    assert not re.search(r'\.sync\(', service)
    assert 'if records.count == 64 { records.removeFirst() }' in service
    # One real, audio-specific queue boundary; the public handle and platform
    # lock are checked, while the AV adapter cannot cross queues as Sendable.
    swift_modules = list((ROOT / 'Socks5/BackgroundKeepAlive').glob('*.swift'))
    unchecked = [p.name for p in swift_modules if '@unchecked Sendable' in p.read_text()]
    assert set(unchecked) == {'LoopAudioService.swift', 'PeriodicPingService.swift'}, unchecked
    assert service.count('@unchecked Sendable') == 1
    assert 'final class LoopAudioService: Sendable {' in service
    assert 'private final class LoopAudioQueueOwner: @unchecked Sendable {' in service
    assert 'private nonisolated final class AudioEndpoint: NSObject, LoopAudioEndpoint {' in service
    assert 'private nonisolated final class DelegateProxy: NSObject, AVAudioPlayerDelegate, Sendable {' in service
    assert 'guard ioDelegateGeneration == receipt.generation else' in service
    assert 'guard receipt.generation == generation, player != nil else' in service
    assert 'guard !ioDeliveryQueued else { return false }' in service
    receipt = service[service.index('    func receiveSession(_ receipt: LoopAudioService.SessionReceipt) {'):]
    assert receipt.index('activationCompletion = nil') < receipt.index('completion?(')
    lease = text('Socks5/BackgroundKeepAlive/RecoveryExecutionLease.swift')
    assert 'private final class LeaseStorage<Value: Sendable>: Sendable {' in lease
    assert 'OSAllocatedUnfairLock(initialState: value)' in lease and 'Mutex(value)' in lease
    assert 'withValue<Result: Sendable>(_ body: @Sendable (inout Value) -> Result)' in lease
    assert 'uncheckedState' not in lease and 'withLockUnchecked' not in lease
    assert 'private final class ApplicationHolder: Sendable' in lease
    assert '@MainActor private func finish(_ request: Request)' in lease
    assert 'return mayIssue()' in lease
    monitor = text('Socks5/BackgroundKeepAlive/PlaybackProgressMonitor.swift')
    assert 'let positionQuantum: Double?' in monitor
    assert 'a.positionQuantum != nil, s.positionQuantum != nil' in monitor
    # The unchanged adapter has no device-qualified property-precision bound.
    assert 'positionQuantum:' not in service
    # Actual target references, build-file membership, group membership and SDK
    # compiler input must all include each new module, not merely name a file.
    phase = project[project.index('/* Begin PBXSourcesBuildPhase section */'):project.index('/* End PBXSourcesBuildPhase section */')]
    sdk = text('Tests/Background/check_audio_sdk.sh')
    for name in ('LoopAudioService.swift', 'PlaybackProgressMonitor.swift', 'RecoveryExecutionLease.swift',
                 'PeriodicPingService.swift', 'PeriodicPingModel.swift'):
        build = re.search(r'([A-F0-9]{24}) /\* ' + re.escape(name) + r' in Sources \*/ = \{isa = PBXBuildFile; fileRef = ([A-F0-9]{24})', project)
        assert build and build[1] + ' /* ' + name + ' in Sources */' in phase, name
        assert '/* ' + name + ' */ = {isa = PBXFileReference;' in project, name
        assert 'Socks5/BackgroundKeepAlive/' + name in sdk, name
    assert '-strict-concurrency=complete' in sdk and '-warnings-as-errors' in sdk
    view = text('Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift')
    assert view.index('Text("Audio")') < view.index('Text("Location")')
    assert view.index('Section("Location state")') < view.index('Text("Periodic ping")')
    assert root.count('@StateObject private var ping = PeriodicPingModel(fileURL: PeriodicPingModel.standaloneURL)') == 1
    assert 'keepAlive: keepAlive, ping: ping,' in root
    ping = text('Socks5/BackgroundKeepAlive/PeriodicPingService.swift')
    assert ping.count('DispatchSource.makeTimerSource(') == 1
    for function in ('generation', 'client_new', 'ping', 'cancel', 'client_free'):
        assert 'hev_socks5_server_icmp_' + function + '(' in ping, function
    assert all(token not in ping for token in ('socket(', 'sendto(', 'recv(', 'PingPacket',
                                               'ServerController', 'isRunning', 'hev_meter_', 'Statistics'))
    assert 'Waiting for native ICMP server' in ping and 'Waiting for native ICMP capacity' in ping
    assert 'private let audioEvents' not in view
    assert 'service.observeAudioNotifications(BackgroundKeepAlive.audioNotifications,' in service
    assert data('README.md') == data('docs/features/background.md')
    assert hashlib.sha256(data('Socks5/BackgroundKeepAlive/Silence.wav')).hexdigest() == (
        '26131825c935435301fb05d3549d815bc93b1e717d6228d890ee9578dd00025e')
    print(json.dumps({
        'base_main': BASE, 'native_parent': PARENT, 'tested_commit': git('rev-parse', 'HEAD').decode().strip(),
        'native_parent_files_preserved': preserved,
        'inherited_modified_paths_reviewed': sorted(allowed),
        'background_additions': sorted(set(current_paths) - set(base_paths)),
        'result': 'PASS: complete native-parent boundary, source pins, native client, entry/root/settings, project, plist, assets and README',
        'scope': 'Source contracts only; no IPA, installed signing, LiveContainer runtime, or device permissions.'
    }, indent=2))


if __name__ == '__main__':
    main()
