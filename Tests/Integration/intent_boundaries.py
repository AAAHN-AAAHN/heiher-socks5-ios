#!/usr/bin/env python3
"""Execute exact AppRoot routing and actual storage/audio coordination boundaries.

Only SwiftUI view construction is omitted from the host; routing method bodies
are copied verbatim and hashed. Platform facades record root effects. A second
build uses actual SettingsStore and audio-service sources with controlled disk
and endpoint adapters. This is neither an AVFAudio execution nor a Simulator UI
result. Mutants must compile and fail at their intended behavioral assertion.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/integrated/intent-boundaries'
PREVIOUS = 'ed6b920cee4f3e5f0469807e521f19bf6f92f92e'
ADDED_BACKGROUND = ('LoopAudioService.swift', 'PlaybackProgressMonitor.swift', 'RecoveryExecutionLease.swift',
                    'PeriodicPingService.swift', 'PeriodicPingModel.swift')
EXPECTED_SOURCES = {
    'Socks5/AppRoot.swift', 'Socks5/Socks5App.swift', 'Socks5/ContentView.swift',
    'Socks5/Server/ServerController.swift', 'Socks5/Server/ServerSettings.swift',
    'Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift',
    'Socks5/Settings/SettingsView.swift', 'Socks5/Statistics/TrafficStatistics.swift',
    'Socks5/Statistics/TrafficStatisticsView.swift',
    'Socks5/BackgroundKeepAlive/BackgroundKeepAlive.swift',
    'Socks5/BackgroundKeepAlive/BackgroundKeepAliveView.swift',
    *('Socks5/BackgroundKeepAlive/' + name for name in ADDED_BACKGROUND),
}
ROUTING = ('direct', 'repeated', 'echo', 'off-on', 'loading', 'failed-stop', 'origin',
           'location-reentry', 'audio-reentry', 'direct-reentry', 'start-reentry', 'readiness-reentry',
           'direct-unrelated', 'direct-newer-unrelated', 'direct-identical-reentry',
           'start-unrelated', 'stop-unrelated', 'stop-newer-unrelated', 'start-identical-reentry',
           'terminal-on', 'terminal-start', 'terminal-off', 'location-loading', 'location-failed-off',
           'location-unrelated', 'location-newer-unrelated', 'terminal-location')
LIVE = ('blocked-load', 'blocked-save', 'stale-import', 'invalid-import',
        'unrelated-reentry', 'same-field-reentry', 'whole-field-reentry', 'import-intent', 'location-reentry')


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def root_contract(code):
    for name, kind in (('settings', 'SettingsStore'), ('server', 'ServerController'),
                       ('keepAlive', 'BackgroundKeepAlive'), ('ping', 'PeriodicPingModel')):
        require(code.count('@StateObject private var ' + name + ' = ' + kind + '()') == 1,
                'Root owner lifetime: ' + name)
    require(re.findall(r'\.tag\(AppSettings.Tab\.(\w+)\)', code) == [
        'statistics', 'server', 'background', 'settings'], 'Four-tab composition changed')
    require(code.count('.modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))') == 1,
            'Root event lifetime changed')
    require('audioEnabled: audioEnabled)' in code and 'set: { enabled in self.applyAudioIntent(enabled) })' in code,
            'Audio toggle bypasses direct intent')
    require('locationEnabled: locationEnabled,' in code and 'set: { enabled in self.applyLocationIntent(enabled) })' in code,
            'Location toggle bypasses immediate Off')
    require('.onChange(of: settings.change, initial: true)' in code,
            'Missing initial change observation')
    require('.onChange(of: settings.loadState)' in code, 'Missing load readiness observation')
    require('.onChange(of: settings.value' not in code, 'Value-only restoration returned')
    require('start: startServer, stop: stopServer' in code, 'Server controls bypass intent routing')
    require('TrafficStatisticsView(isVisible: settings.value.selectedTab == .statistics)' in code,
            'Statistics visibility ownership changed')


def project_contract(project, original):
    sources = re.findall(r'[A-F0-9]{24} /\* Sources \*/ = \{(.*?)\n\s*\};', project, re.S)
    group = re.findall(r'[A-F0-9]{24} /\* BackgroundKeepAlive \*/ = \{(.*?)\n\s*\};', project, re.S)
    require(len(sources) == len(group) == 1, 'Ambiguous app source phase or background group')
    for name in ADDED_BACKGROUND:
        escaped = re.escape(name)
        build = re.findall(r'([A-F0-9]{24}) /\* ' + escaped + r' in Sources \*/ = '
                           r'\{isa = PBXBuildFile; fileRef = ([A-F0-9]{24}) /\* ' + escaped + r' \*/; \};', project)
        refs = re.findall(r'([A-F0-9]{24}) /\* ' + escaped + r' \*/ = '
                          r'\{isa = PBXFileReference; lastKnownFileType = sourcecode.swift; '
                          r'path = "' + escaped + r'"; sourceTree = "<group>"; \};', project)
        require(len(build) == len(refs) == 1 and build[0][1] == refs[0], 'Invalid app file reference: ' + name)
        require(sources[0].count(build[0][0] + ' /* ' + name + ' in Sources */,') == 1,
                'Missing app target source: ' + name)
        require(group[0].count(refs[0] + ' /* ' + name + ' */,') == 1,
                'Missing background group source: ' + name)
    # All twelve existing target inputs and every build setting retain their
    # original bytes. The only allowed project delta is these five source links.
    kept = [line for line in project.splitlines(keepends=True)
            if not any('/* ' + name + ' */' in line or '/* ' + name + ' in Sources */' in line
                       for name in ADDED_BACKGROUND)]
    require(''.join(kept) == original, 'Project changed beyond the five Background target registrations')


def source_contract():
    paths = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'Socks5').rglob('*.swift')}
    require(paths == EXPECTED_SOURCES, 'Production Swift inventory is not the exact 12-to-17 composition')
    code = (ROOT / 'Socks5/AppRoot.swift').read_text()
    root_contract(code)
    original = subprocess.check_output(['git', '-C', str(ROOT), 'show',
        PREVIOUS + ':Socks5.xcodeproj/project.pbxproj'], text=True)
    project = (ROOT / 'Socks5.xcodeproj/project.pbxproj').read_text()
    project_contract(project, original)
    # These are source guard controls; unlike runtime mutants they do not claim
    # an execution failure. Each damages the exact link the guard must protect.
    for label, changed in (
        ('direct-binding', code.replace('audioEnabled: audioEnabled)',
                                       'audioEnabled: settings.binding(\\.background.silentAudio))', 1)),
        ('location-binding', code.replace('locationEnabled: locationEnabled,',
                                         'locationEnabled: settings.binding(\\.background.continuousLocation),', 1)),
        ('load-observer', code.replace('.onChange(of: settings.loadState)', '.onChange(of: settings.value)', 1)),
        ('duplicate-owner', code.replace('@StateObject private var keepAlive', '@State private var keepAlive', 1)),
    ):
        try:
            root_contract(changed)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Source negative control accepted: ' + label)
    source_link = re.search(r'^\s*[A-F0-9]{24} /\* LoopAudioService.swift in Sources \*/,\n', project, re.M)
    require(source_link is not None, 'Missing target link control input')
    try:
        project_contract(project[:source_link.start()] + project[source_link.end():], original)
    except RuntimeError:
        pass
    else:
        raise RuntimeError('Removed app target input accepted')
    return {'swift_sources': len(paths), 'source_rejection_controls': 5}


def routing_methods():
    code = (ROOT / 'Socks5/AppRoot.swift').read_text()
    start, end = '    private var audioEnabled: Binding<Bool> {', '    var body: some View {'
    require(code.count(start) == code.count(end) == 1, 'AppRoot routing extraction boundary changed')
    return code[code.index(start):code.index(end)]


def host(methods):
    return '''@MainActor private final class RootIntentHost {
    let settings: SettingsStore
    let server = ServerController()
    let keepAlive = BackgroundKeepAlive()
    var appliedSettingsChange: SettingsStore.Change?
    init(settings: SettingsStore) { self.settings = settings }
''' + methods + '}\n'


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    if sys.argv[1:] not in ([], ['--source-only'], ['--routing-only']):
        raise SystemExit('Usage: intent_boundaries.py [--source-only|--routing-only]')
    mode = sys.argv[1:] or []
    source_result = {} if mode == ['--routing-only'] else source_contract()
    if mode == ['--source-only']:
        print(json.dumps({'result': 'PASS', **source_result}, indent=2))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'result.json').unlink(missing_ok=True)
    methods = routing_methods()
    fixture = (ROOT / 'Tests/Integration/IntentBoundaryTests.swift').read_text()
    require(fixture.count('// INSERT_ROOT_INTENT_HOST') == 1, 'Fixture insertion boundary changed')
    entries = []
    with tempfile.TemporaryDirectory(prefix='release-intent-') as folder:
        temporary = Path(folder)

        def compile_host(label, body, production=()):
            source = temporary / (label + '.swift')
            source.write_text(fixture.replace('// INSERT_ROOT_INTENT_HOST', host(body)))
            binary = temporary / label
            args = ['swiftc', '-parse-as-library', '-swift-version', '5',
                    '-strict-concurrency=complete', '-warnings-as-errors']
            if production:
                args += ['-D', 'LIVE_SETTINGS']
            args += [str(source), *map(str, production), '-o', str(binary)]
            with (OUT / (label + '-compile.log')).open('w') as stream:
                subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            return binary

        def execute(binary, label, case, rejection=None):
            result = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=30)
            output = result.stdout + result.stderr
            (OUT / (label + '-' + case + '.log')).write_text(output)
            if rejection is None:
                require(result.returncode == 0 and 'PASS:' in output, 'Routing/live failure: ' + label + '/' + case)
            else:
                require(result.returncode != 0 and 'ROOT_INTENT_' + rejection in output,
                        'Compiled mutant missed its intended failure: ' + label)
            entries.append({'label': label, 'case': case, 'returncode': result.returncode,
                            'expected_rejection': rejection, 'result': 'PASS'})

        current = compile_host('routing-current', methods)
        for case in ROUTING:
            execute(current, 'routing-current', case)
        mutations = [
            ('missing-direct', '        keepAlive.setAudio(enabled)\n', '', 'direct', 'DIRECT_ORDER'),
            ('no-ready-gate', '        guard settings.loadState == .ready else { return }\n', '', 'loading', 'LOADING_APPLIED'),
            ('revision-only', 'guard appliedSettingsChange != change else',
             'guard appliedSettingsChange?.revision != change.revision else', 'origin', 'ORIGIN_IGNORED'),
            ('explicit-echo', '        keepAlive.syncAudio(value.background.silentAudio)\n',
             '        keepAlive.setAudio(value.background.silentAudio)\n', 'echo', 'ECHO_EXPLICIT'),
            ('stale-location', '        guard settings.loadState == .ready, settings.change == change else { return }\n',
             '', 'location-reentry', 'STALE_AUDIO_AFTER_LOCATION'),
            ('stale-direct', '        guard settings.audioChange == previous else { return }\n',
             '        _ = previous\n', 'direct-reentry', 'STALE_DIRECT_MEMORY'),
            ('global-audio-stamp', 'settings.audioChange', 'settings.change',
             'direct-unrelated', 'UNRELATED_DROPPED_OFF'),
            ('global-server-stamp', 'settings.serverRunningChange', 'settings.change',
             'stop-unrelated', 'UNRELATED_DROPPED_STOP'),
            ('global-location-stamp', 'settings.locationChange', 'settings.change',
             'location-unrelated', 'LOCATION_UNRELATED_DROPPED_OFF'),
            ('no-location-off', '            keepAlive.setLocation(false)\n', '',
             'location-failed-off', 'LOCATION_FAILED_OFF_GATED'),
            ('terminal-on', '        guard !enabled || settings.acceptsNewIntent else {\n'
             '            settings.set(\\.background.silentAudio, enabled, origin: .user)\n'
             '            return\n        }\n', '', 'terminal-on', 'TERMINAL_AUDIO_ON'),
        ]
        for label, before, after, case, rejection in mutations:
            require(before in methods, 'Mutation boundary missing: ' + label)
            changed = methods.replace(before, after) if label.startswith('global-') else methods.replace(before, after, 1)
            if label == 'no-ready-gate':
                changed = changed.replace('guard settings.loadState == .ready, settings.change == change else',
                                          'guard settings.change == change else')
            binary = compile_host(label, changed)
            execute(binary, label, case, rejection)
        production_hashes = {}
        if mode != ['--routing-only']:
            production = []
            for name in ('Socks5/Server/ServerSettings.swift', 'Socks5/Settings/AppSettings.swift',
                         'Socks5/Settings/SettingsStore.swift',
                         *('Socks5/BackgroundKeepAlive/' + name for name in ADDED_BACKGROUND)):
                raw = (ROOT / name).read_bytes()
                production_hashes[name] = hashlib.sha256(raw).hexdigest()
                # Framework imports are the only production-source substitutions.
                text = raw.decode().replace('import HevSocks5Server\n', '').replace('import SwiftUI\n', 'import Foundation\n')
                copied = temporary / Path(name).name
                copied.write_text(text)
                production.append(copied)
            live = compile_host('live-production', methods, production)
            for case in LIVE:
                execute(live, 'live-production', case)
    value = {'result': 'PASS', **source_result,
             'root_sha256': hashlib.sha256((ROOT / 'Socks5/AppRoot.swift').read_bytes()).hexdigest(),
             'routing_methods_sha256': hashlib.sha256(methods.encode()).hexdigest(),
             'fixture_sha256': hashlib.sha256(fixture.encode()).hexdigest(),
             'production_sources': production_hashes, 'cases': entries,
             'scope': 'Exact routing methods; controlled disk and audio endpoint. No AVFAudio, native listener, Simulator or physical-device result.'}
    (OUT / 'result.json').write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
