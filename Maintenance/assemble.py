#!/usr/bin/env python3
"""Assemble reviewed feature commits from exact Git objects, preserving old history."""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import subprocess
import tempfile
from review import prepare

REPO = Path(__file__).resolve().parents[1]
HOME = Path(os.environ['RUNNER_TEMP']) / 'socks5-reorganization'
TEMPLATES = REPO / 'Maintenance/templates'
REVIEW = HOME / 'reviewed-Socks5'
BASE = '83d350d28d6a31e7730cfa74b49f58d2af642397'
OLD = 'b68dbb9ca7d4d028111666915eba951911857b1d'
SOURCES = {'.': 'b3585289622561caf4b8789b436cc8820ecd6be0',
           'src/core': '162dd996299fc2d2bff2dd63728f8a2cd71ed31a',
           'third-part/hev-task-system': '328f35d903221b51811b3d02b277d665dfbdc75f',
           'third-part/yaml': '162227cd7d2b6108bc8bc133273e11413222ddf4'}
DOCS = {'udp': 'udp-compatibility', 'statistics': 'traffic-statistics',
        'background': 'background', 'settings': 'settings-lifecycle', 'icon': 'app-icon'}
BRANCHES = {'udp': 'feature/udp-compat', 'statistics': 'feature/traffic-statistics',
            'background': 'feature/background', 'settings': 'feature/settings',
            'icon': 'feature/app-icon', 'integrated': 'release/integrated'}


def git(*args, data=None, env=None):
    return subprocess.check_output(['git', '-C', str(REPO), *args], input=data, env=env)


def old(path):
    return git('show', f'{OLD}:{path}')


def files_at(ref, prefix):
    return git('ls-tree', '-r', '--name-only', ref, prefix).decode().splitlines()


def project(files):
    text = git('show', f'{BASE}:Socks5.xcodeproj/project.pbxproj').decode()
    extra = [p for p in files if p.startswith('Socks5/') and p.endswith(('.swift', '.wav', '.plist'))
             and p not in ('Socks5/ContentView.swift', 'Socks5/Socks5App.swift')]
    build, refs, sources, resources = [], [], [], []
    groups = {}
    def uid(key):
        return 'F0' + hashlib.sha1(key.encode()).hexdigest()[:22].upper()
    for path in sorted(extra):
        name = Path(path).name
        ref = uid('ref/' + path)
        bld = uid('build/' + path)
        ext = Path(path).suffix
        kind = {'.swift': 'sourcecode.swift', '.wav': 'audio.wav', '.plist': 'text.plist.xml'}[ext]
        refs.append(f'\t\t{ref} /* {name} */ = {{isa = PBXFileReference; lastKnownFileType = {kind}; path = "{name}"; sourceTree = "<group>"; }};')
        directory = str(Path(path).parent.relative_to('Socks5'))
        groups.setdefault(directory, []).append(f'\t\t\t\t{ref} /* {name} */,')
        if ext == '.swift':
            phase = 'Sources'
            sources.append(f'\t\t\t\t{bld} /* {name} in Sources */,')
        elif ext == '.wav':
            phase = 'Resources'
            resources.append(f'\t\t\t\t{bld} /* {name} in Resources */,')
        else:
            continue
        build.append(f'\t\t{bld} /* {name} in {phase} */ = {{isa = PBXBuildFile; fileRef = {ref} /* {name} */; }};')
    text = text.replace('/* End PBXBuildFile section */', '\n'.join(build) + '\n/* End PBXBuildFile section */')
    text = text.replace('/* End PBXFileReference section */', '\n'.join(refs) + '\n/* End PBXFileReference section */')
    text = text.replace('\t\t\t\tD30F96602C18058B002DB6BF /* ContentView.swift in Sources */,', '\t\t\t\tD30F96602C18058B002DB6BF /* ContentView.swift in Sources */,\n' + '\n'.join(sources))
    text = text.replace('\t\t\t\tD30F96622C18058E002DB6BF /* Assets.xcassets in Resources */,', '\t\t\t\tD30F96622C18058E002DB6BF /* Assets.xcassets in Resources */,\n' + '\n'.join(resources))
    children = groups.pop('.', [])
    declarations = []
    for directory, members in groups.items():
        key = uid('group/' + directory)
        children.append(f'\t\t\t\t{key} /* {directory} */,')
        declarations.append(f'''\t\t{key} /* {directory} */ = {{
\t\t\tisa = PBXGroup;
\t\t\tchildren = (
''' + '\n'.join(members) + f'''
\t\t\t);
\t\t\tpath = "{directory}";
\t\t\tsourceTree = "<group>";
\t\t}};''')
    text = text.replace('\t\t\t\tD30F965D2C18058B002DB6BF /* Socks5App.swift */,', '\t\t\t\tD30F965D2C18058B002DB6BF /* Socks5App.swift */,\n' + '\n'.join(children))
    text = text.replace('/* End PBXGroup section */', '\n'.join(declarations) + '\n/* End PBXGroup section */')
    text = text.replace('INFOPLIST_KEY_UIApplicationSceneManifest_Generation = YES;', 'INFOPLIST_FILE = Socks5/Info.plist;\n\t\t\t\tINFOPLIST_KEY_UIApplicationSceneManifest_Generation = NO;')
    return text.encode()


def root_view(features):
    settings = 'settings' in features
    stats = 'statistics' in features
    bg = 'background' in features
    lines = ['import SwiftUI', '', '@MainActor', 'struct AppRoot: View {']
    if settings:
        lines += ['    @StateObject private var settings = SettingsStore()', '    @StateObject private var server = ServerController()']
    else:
        lines += ['    @State private var selectedTab = "server"']
    if bg:
        lines += ['    @StateObject private var keepAlive = BackgroundKeepAlive()']
        if not settings:
            lines += ['    @AppStorage("background.continuousLocation") private var locationEnabled = false', '    @AppStorage("background.silentAudio") private var audioEnabled = false']
    if settings and not stats:
        lines += ['', '    private var selectedTab: Binding<AppSettings.Tab> {',
                  '        Binding(get: { settings.value.selectedTab == .settings ? .settings : .server },',
                  '                set: { settings.set(\\.selectedTab, $0) })', '    }']
    selection = 'settings.binding(\\.selectedTab)' if settings and stats else ('selectedTab' if settings else '$selectedTab')
    lines += ['', '    var body: some View {', f'        TabView(selection: {selection}) {{']
    if stats:
        vis = 'settings.value.selectedTab == .statistics' if settings else 'selectedTab == "statistics"'
        tag = 'AppSettings.Tab.statistics' if settings else '"statistics"'
        lines += [f'            TrafficStatisticsView(isVisible: {vis})', '                .tabItem { Label("Statistics", systemImage: "chart.bar") }', f'                .tag({tag})']
    tag = 'AppSettings.Tab.server' if settings else '"server"'
    lines += ['            ScrollView { ContentView() }', '                .tabItem { Label("Server", systemImage: "network") }', f'                .tag({tag})']
    if bg:
        lb = 'settings.binding(\\.background.continuousLocation)' if settings else '$locationEnabled'
        ab = 'settings.binding(\\.background.silentAudio)' if settings else '$audioEnabled'
        tag = 'AppSettings.Tab.background' if settings else '"background"'
        lines += ['            BackgroundKeepAliveView(keepAlive: keepAlive,', f'                                    locationEnabled: {lb},', f'                                    audioEnabled: {ab})', '                .tabItem { Label("Background", systemImage: "switch.2") }', f'                .tag({tag})']
    if settings:
        lines += ['            SettingsView(settings: settings)', '                .tabItem { Label("Settings", systemImage: "square.and.arrow.up") }', '                .tag(AppSettings.Tab.settings)']
    lines += ['        }']
    if settings:
        lines += ['        .environmentObject(settings)', '        .environmentObject(server)', '        .onChange(of: settings.value, initial: true) { _, value in']
        if bg:
            lines += ['            if keepAlive.locationEnabled != value.background.continuousLocation {', '                keepAlive.setLocation(value.background.continuousLocation)', '            }', '            if keepAlive.audioEnabled != value.background.silentAudio {', '                keepAlive.setAudio(value.background.silentAudio)', '            }']
        lines += ['            server.apply(value)', '        }']
    elif bg:
        lines += ['        .onChange(of: locationEnabled, initial: true) { _, value in keepAlive.setLocation(value) }', '        .onChange(of: audioEnabled, initial: true) { _, value in keepAlive.setAudio(value) }']
    if bg:
        lines += ['        .modifier(BackgroundKeepAliveEvents(keepAlive: keepAlive))']
    lines += ['    }', '}', '']
    return '\n'.join(lines).encode()


def assemble(name, features):
    result = {}
    def copy_review(directory):
        for p in (REVIEW / directory).rglob('*'):
            if p.is_file() and p.suffix not in ('.md', '.plist'):
                result['Socks5/' + str(p.relative_to(REVIEW))] = p.read_bytes()
    for p in (TEMPLATES / 'Build').glob('*'):
        result['Build/' + p.name] = p.read_bytes()
    result['.github/workflows/verify-build.yml'] = (REPO / '.github/workflows/verify-build.yml').read_bytes()
    result['.gitignore'] = b'.build/\nartifacts/\n.DS_Store\n__pycache__/\n*.pyc\n'
    result['docs/upstream/README.md'] = git('show', f'{BASE}:README.md')
    result['docs/build-and-validation.md'] = (TEMPLATES / 'docs/build-and-validation.md').read_bytes()
    result['Tests/tcp_smoke.py'] = (TEMPLATES / 'Tests/tcp_smoke.py').read_bytes()
    plist = {'UIApplicationSceneManifest': {'UIApplicationSupportsMultipleScenes': False},
             'NSLocalNetworkUsageDescription': 'Allow devices on your hotspot or local network to connect to your SOCKS5 server.'}
    entries = []
    def patch(filename, repository):
        entries.append({'file': filename, 'repository': repository})
        result['Patches/' + filename] = (TEMPLATES / filename).read_bytes() if (TEMPLATES / filename).exists() else old('Patches/' + filename)
    if 'udp' in features:
        patch('hev-udp-port-zero.patch', '.')
        patch('hev-udp-sockaddr.patch', 'src/core')
        result['Tests/udp_sockaddr_regression.py'] = old('Tests/udp_sockaddr_regression.py')
    if 'statistics' in features:
        for file, repo in [('hev-stats-task-io.patch', 'third-part/hev-task-system'), ('hev-stats-core.patch', 'src/core'), ('hev-stats-server.patch', '.')]:
            patch(file, repo)
        copy_review('Statistics')
        for file in ['traffic_stats_host.c', 'traffic_stats_regression.py', 'traffic_statistics_model.swift']:
            result['Tests/' + file] = old('Tests/' + file)
    if 'background' in features:
        copy_review('BackgroundKeepAlive')
        for file in files_at(OLD, 'Tests/Background'):
            result[file] = old(file)
        plist = plistlib.loads((REVIEW / 'Info.plist').read_bytes())
    if 'settings' in features:
        copy_review('Settings')
        copy_review('Server')
        result['Socks5/ContentView.swift'] = (REVIEW / 'ContentView.swift').read_bytes()
        patch('hev-server-startup-stop.patch', '.')
        for p in (TEMPLATES / 'Tests/Settings').glob('*'):
            if p.name != 'check_integration.py':
                result['Tests/Settings/' + p.name] = p.read_bytes()
        for file in ['server_lifecycle_host.c', 'server_lifecycle_regression.py']:
            result['Tests/' + file] = (TEMPLATES / 'Tests' / file).read_bytes()
    if 'icon' in features:
        for file in files_at(OLD, 'Socks5/Assets.xcassets/AppIcon.appiconset'):
            result[file] = old(file)
    if set(features) & {'settings', 'background', 'statistics'}:
        result['Socks5/AppRoot.swift'] = root_view(features)
        result['Socks5/Socks5App.swift'] = git('show', f'{BASE}:Socks5/Socks5App.swift').replace(b'ContentView()', b'AppRoot()')
    result['Socks5/Info.plist'] = plistlib.dumps(plist, sort_keys=False)
    config = {'name': name, 'features': features, 'upstream_app': BASE, 'sources': SOURCES, 'patches': entries}
    result['Build/features.json'] = (json.dumps(config, indent=2) + '\n').encode()
    for feature in features:
        doc = 'docs/features/' + DOCS[feature] + '.md'
        result[doc] = (TEMPLATES / doc).read_bytes()
    result['Socks5.xcodeproj/project.pbxproj'] = project(result)
    if name != 'integrated':
        feature = next(k for k, v in BRANCHES.items() if v.split('/')[-1] == name)
        readme = ('# SOCKS5 for iOS: ' + name + '\n\n'
                  'This is the focused `' + BRANCHES[feature] + '` branch.\n'
                  'For the complete app use `release/integrated`; pristine upstream remains on `main`.\n\n'
                  'Build and verification: [instructions](docs/build-and-validation.md).\n'
                  'The following specification is also preserved verbatim at `docs/features/' + DOCS[feature] + '.md`.\n\n')
        result['README.md'] = readme.encode() + result['docs/features/' + DOCS[feature] + '.md']
    return result


def commit(files, parents, message):
    env = os.environ.copy()
    env.update(GIT_AUTHOR_NAME='ChatGPT', GIT_AUTHOR_EMAIL='noreply@openai.com',
               GIT_COMMITTER_NAME='ChatGPT', GIT_COMMITTER_EMAIL='noreply@openai.com')
    with tempfile.TemporaryDirectory() as temp:
        env['GIT_INDEX_FILE'] = temp + '/index'
        git('read-tree', BASE, env=env)
        for name, data in sorted(files.items()):
            blob = git('hash-object', '-w', '--stdin', data=data).decode().strip()
            git('update-index', '--add', '--cacheinfo', '100644,' + blob + ',' + name, env=env)
        tree = git('write-tree', env=env).decode().strip()
    args = ['commit-tree', tree]
    for parent in parents:
        args += ['-p', parent]
    return git(*args, data=(message + '\n').encode(), env=env).decode().strip()


def main():
    HOME.mkdir(parents=True, exist_ok=True)
    output = REPO / 'artifacts/reorganization'
    output.mkdir(parents=True, exist_ok=True)
    raw = git('ls-remote', '--heads', 'origin').decode()
    before = {line.split()[1].removeprefix('refs/heads/'): line.split()[0] for line in raw.splitlines()}
    (output / 'old-branches.json').write_text(json.dumps(before, indent=2) + '\n')
    git('bundle', 'create', str(output / 'history-before.bundle'), '--all')
    prepare(REPO, TEMPLATES, HOME)
    heads, contents = {}, {}
    for feature in ['udp', 'statistics', 'background', 'settings', 'icon']:
        branch = BRANCHES[feature]
        features = ['udp', 'statistics'] if feature == 'statistics' else [feature]
        data = assemble(branch.split('/')[-1], features)
        parents = [heads['udp']] if feature == 'statistics' else [BASE]
        sha = commit(data, parents, f'Implement and document isolated {feature} feature with reproducible checks')
        heads[feature], contents[feature] = sha, data
    final = assemble('integrated', ['udp', 'statistics', 'background', 'settings', 'icon'])
    final['README.md'] = (TEMPLATES / 'docs/integrated-readme.md').read_bytes().replace(b'](features/', b'](docs/features/').replace(b'](build-and-validation.md)', b'](docs/build-and-validation.md)')
    final['docs/README.md'] = (TEMPLATES / 'docs/integrated-readme.md').read_bytes()
    final['docs/history-before-reorganization.txt'] = raw.encode()
    members = {'branches': {BRANCHES[k]: v for k, v in heads.items()}, 'files': {}}
    for feature, files in contents.items():
        readme = 'docs/branches/' + BRANCHES[feature].replace('/', '-') + '.md'
        final[readme] = files['README.md']
        members['files'][readme] = hashlib.sha256(final[readme]).hexdigest()
        for name, data in files.items():
            if name.startswith(('Patches/', 'Socks5/Statistics/', 'Socks5/BackgroundKeepAlive/', 'Socks5/Settings/', 'Socks5/Server/', 'Socks5/Assets.xcassets/AppIcon', 'docs/features/')):
                assert final[name] == data, name
                members['files'][name] = hashlib.sha256(data).hexdigest()
    final['docs/feature-membership.json'] = (json.dumps(members, indent=2, sort_keys=True) + '\n').encode()
    heads['integrated'] = commit(final, [heads[k] for k in ['statistics', 'background', 'settings', 'icon']],
                                 'Integrate all reviewed features and preserve complete feature specifications')
    manifest = {BRANCHES[k]: v for k, v in heads.items()}
    (output / 'new-branches.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # Archive old tips before any branch name is changed. Never overwrite an archive.
    archives = {}
    tags = git('ls-remote', '--tags', 'origin').decode().splitlines()
    tag_values = {line.split()[1]: line.split()[0] for line in tags}
    for branch, sha in before.items():
        if branch in manifest:
            continue
        ref = 'refs/tags/archive/2026-09-22/' + branch
        if ref in tag_values and tag_values[ref] != sha:
            ref += '-' + sha[:12]
        if ref not in tag_values:
            git('push', 'origin', sha + ':' + ref)
        archives[branch] = {'sha': sha, 'tag': ref}
    (output / 'archives.json').write_text(json.dumps(archives, indent=2) + '\n')
    # Safe even on a retry: a concurrent update fails the explicit lease.
    args = ['push', '--atomic']
    for branch in manifest:
        args.append('--force-with-lease=refs/heads/' + branch + ':' + before.get(branch, ''))
    args.append('origin')
    args += [sha + ':refs/heads/' + branch for branch, sha in manifest.items()]
    git(*args)
    git('bundle', 'create', str(output / 'history-after-prepare.bundle'), '--all')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('matrix=' + json.dumps({'include': [{'ref': heads[k], 'feature': k} for k in ['udp', 'statistics', 'background', 'settings', 'icon']]}) + '\n')
        stream.write('integrated=' + heads['integrated'] + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
