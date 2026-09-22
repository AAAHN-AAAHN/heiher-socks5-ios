#!/usr/bin/env python3
"""One-time, owner-authorized baseline update. Publish only after all checks pass."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

APP = '180012e8b9dbaa2002a68ebd2c75bccebcfb789c'
SERVER = 'b3585289622561caf4b8789b436cc8820ecd6be0'
HISTORICAL = '83d350d28d6a31e7730cfa74b49f58d2af642397'
RELEASE = '563d3d197d3e64de5bacb07da4f66e0ab9c3ba34'
BRANCHES = {
    'main': HISTORICAL,
    'feature/udp-compat': '51eed67071d4be701277e371e7db1a65203a7bb2',
    'feature/traffic-statistics': '7dae9e89f13242dad429786f431cbe45ba71975c',
    'feature/background': '31d09c8edf796f83882610ce90775a2deafca0aa',
    'feature/settings': 'b3590d3887584281002b2d2c033280d127ad7685',
    'feature/app-icon': '12e3eba0fb0d25ef4af03b435af269e85e581209',
    'release/integrated': RELEASE,
}
TEMP_BRANCH = 'maintenance/latest-baseline-20260922'
REPO = Path(__file__).resolve().parents[1]


def git(*args, data=None, env=None):
    return subprocess.check_output(['git', '-C', str(REPO), *args], input=data, env=env)


def snapshot(ref):
    result = {}
    for entry in git('ls-tree', '-rz', ref).split(b'\0'):
        if entry:
            header, name = entry.split(b'\t', 1)
            mode, kind, sha = header.decode().split()
            assert kind == 'blob', (ref, name, kind)
            result[name.decode()] = (mode, git('cat-file', 'blob', sha))
    return result


def put(files, name, data):
    files[name] = ('100644', data.encode() if isinstance(data, str) else data)


def text(files, name):
    return files[name][1].decode()


def dump(value):
    return json.dumps(value, indent=2, sort_keys=True) + '\n'


def commit(files, parents, message):
    env = dict(os.environ, GIT_AUTHOR_NAME='github-actions[bot]',
               GIT_COMMITTER_NAME='github-actions[bot]',
               GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com',
               GIT_COMMITTER_EMAIL='41898282+github-actions[bot]@users.noreply.github.com')
    with tempfile.TemporaryDirectory() as directory:
        env['GIT_INDEX_FILE'] = directory + '/index'
        git('read-tree', '--empty', env=env)
        entries = []
        for name, (mode, data) in sorted(files.items()):
            sha = git('hash-object', '-w', '--stdin', data=data).decode().strip()
            entries.append(f'{mode} blob {sha}\t{name}\0'.encode())
        git('update-index', '-z', '--index-info', data=b''.join(entries), env=env)
        tree = git('write-tree', env=env).decode().strip()
    args = ['commit-tree', tree]
    for parent in parents:
        args += ['-p', parent]
    return git(*args, data=(message + '\n').encode(), env=env).decode().strip()


def upstream_is_current():
    for repo, expected in [('socks5-ios', APP), ('hev-socks5-server', SERVER)]:
        actual = git('ls-remote', f'https://github.com/heiher/{repo}.git', 'refs/heads/main').decode().split()[0]
        assert actual == expected, f'Upstream changed during update: {repo}: {actual}'


BASELINE_DOC = f'''# Shared latest-upstream combination

## Definition

Main combines the latest verified `heiher/socks5-ios` app source with a fresh,
**unpatched** build of the latest verified `heiher/hev-socks5-server` main branch.
It is not a byte-identical mirror of the iOS repository, not its old prebuilt core,
and not the historical fork snapshot. Latest means the upstream main tips verified
for this update, not a floating dependency fetched differently on every build.

- iOS source: `{APP}`
- Server source: `{SERVER}`
- Verified date: 2026-09-22
- Submodules: the exact revisions referenced by that server, in `Build/upstream.json`.

Main's `Socks5/`, `Socks5.xcodeproj/` and LICENSE are byte-for-byte upstream.
The bundled XCFramework is rebuilt from clean server sources using upstream's
`build-apple.sh`. Its complete tracked file inventory, SHA-256 hashes and build
provenance are in `Build/baseline-framework.json`. The root README and build/audit
infrastructure describe this combination; the upstream README is preserved at
`docs/upstream/README.md`. There are no UDP, statistics, lifecycle or app-feature
patches on main. Consequently known unpatched upstream limitations are not hidden.
Use `release/integrated` for the feature-complete app.

## Inheritance

Every existing feature branch incorporates the new main as an ancestor, preserves
its own runtime feature code, and carries the identical baseline XCFramework,
`Build/upstream.json`, provenance inventory and shared build/check scripts. Its
`Build/features.json` identifies the actual main commit in `base_commit` and lists
only its feature patches. Traffic statistics additionally depends on UDP
compatibility; integration includes every feature tip. Old branch history is
preserved by merge ancestry and archive tags, not discarded by a forced rebase.

During feature builds the clean base engine is checked out at the shared pinned
revision, declared patches are applied, and a patched framework replaces the base
framework in the disposable build workspace. The committed baseline framework is
never represented as having those patches. Run `bash Build/build.sh` before building
feature code with Xcode; statistics needs its rebuilt public C API.

`Build/check.py` checks pin equality, the committed baseline framework inventory,
feature-to-main ancestry and shared file identity. Checks read baseline bytes from
Git, so a locally rebuilt feature framework is not mistaken for the committed one.
Future branches should start from current main and keep these shared files intact.
Updating the baseline is explicit: resolve upstream tips, rebuild the unpatched
framework, update the shared lock, merge main into descendants and revalidate.
There is no unattended update that could silently change a known working build.

## Verification and scope

The baseline and five focused branches are checked on Linux and macOS; the
integrated app is checked after those jobs succeed. macOS produces real ARM64 iOS
archives. Unpatched baseline tests include actual TCP relay and source identity;
its known Darwin UDP limitations are not mislabeled as fixed. Features run their
applicable UDP, statistics, background, settings and lifecycle regression tests.
No application Swift source or existing C patch changes in this baseline update.
Host tests and archives are not new iPhone call, VPN, battery or throughput tests.

Prior branch tips are saved under `archive/before-latest-baseline-20260922/`.
Publication verifies expected old SHAs and advances all seven branches atomically
only after successful checks. Candidate tags and the maintenance branch are then
removed; the maintenance commit is archived for reproducibility. A failed check
leaves the prior active branches untouched. Artifact logs record tested commit IDs.
'''


def common_files(old, upstream, framework, provenance):
    config = json.loads(text(old, 'Build/features.json'))
    lock = {'schema_version': 1, 'verified_date': '2026-09-22', 'upstream_app': APP,
            'sources': config['sources']}
    assert lock['sources']['.'] == SERVER
    files = {}
    for name in ['Build/build.sh', 'Build/check.py', 'Tests/tcp_smoke.py', '.gitignore']:
        files[name] = old[name]
    put(files, '.github/workflows/verify-build.yml', (REPO / '.github/workflows/verify-build.yml').read_bytes())
    put(files, 'Build/upstream.json', dump(lock))
    inventory = {str(p.relative_to(framework)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(framework.rglob('*')) if p.is_file()}
    assert 'ios-arm64/libhev-socks5-server.a' in inventory
    for p in framework.rglob('*'):
        if p.is_file():
            put(files, 'HevSocks5Server.xcframework/' + str(p.relative_to(framework)), p.read_bytes())
    put(files, 'Build/baseline-framework.json', dump({'upstream_app': APP, 'sources': lock['sources'],
                                                    'files': inventory, 'build': provenance}))
    build = text(files, 'Build/build.sh')
    build = build.replace('mkdir -p "$OUT"', 'mkdir -p "$OUT"\npython3 Build/check.py baseline > "$OUT/baseline-audit.log"\nSERVER_REF=$(python3 -c \'import json; print(json.load(open("Build/upstream.json"))["sources"]["."])\')', 1)
    build = build.replace('checkout --detach ' + SERVER, 'checkout --detach "$SERVER_REF"')
    put(files, 'Build/build.sh', build)
    check = text(files, 'Build/check.py')
    helper = '''

def baseline():
    lock = json.loads((ROOT / 'Build/upstream.json').read_text())
    manifest = json.loads((ROOT / 'Build/baseline-framework.json').read_text())
    assert CONFIG['sources'] == lock['sources'] == manifest['sources']
    assert CONFIG['upstream_app'] == lock['upstream_app'] == manifest['upstream_app']
    prefix = 'HevSocks5Server.xcframework/'
    names = git(ROOT, 'ls-tree', '-r', '--name-only', 'HEAD', prefix).decode().splitlines()
    actual = {name[len(prefix):]: hashlib.sha256(git(ROOT, 'show', 'HEAD:' + name)).hexdigest() for name in names}
    assert actual == manifest['files'], 'Committed framework differs from shared baseline'
    if CONFIG['name'] == 'baseline':
        assert not CONFIG['features'] and not CONFIG['patches']
        for path in ('Socks5', 'Socks5.xcodeproj', 'LICENSE'):
            assert git(ROOT, 'rev-parse', 'HEAD:' + path) == git(ROOT, 'rev-parse', lock['upstream_app'] + ':' + path)
    else:
        base = CONFIG['base_commit']
        git(ROOT, 'merge-base', '--is-ancestor', base, 'HEAD')
        for path in ('Build/upstream.json', 'Build/baseline-framework.json', 'Build/build.sh',
                     'Build/check.py', 'docs/main-baseline.md', 'HevSocks5Server.xcframework'):
            assert git(ROOT, 'rev-parse', 'HEAD:' + path) == git(ROOT, 'rev-parse', base + ':' + path), path
    print('PASS: shared source pins, baseline framework, app identity and main ancestry')
'''
    check = check.replace('\ndef patches():', helper + '\n\ndef patches():', 1)
    check = check.replace("    assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False\n    assert info.get('NSLocalNetworkUsageDescription')",
                          "    if CONFIG['name'] != 'baseline':\n        assert info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False\n        assert info.get('NSLocalNetworkUsageDescription')")
    check = check.replace("    if command == 'apply':", "    if command == 'baseline':\n        baseline()\n    elif command == 'apply':")
    put(files, 'Build/check.py', check)
    put(files, 'docs/main-baseline.md', BASELINE_DOC)
    put(files, 'docs/upstream/README.md', upstream['README.md'][1])
    return files


def update_docs(files):
    replacements = {
        '`main` is the unmodified upstream\nfork baseline, not the release branch.': '`main` is the latest verified app + unpatched server combination,\nnot a byte-identical upstream mirror or the release branch.',
        f'Exact original `{HISTORICAL}`': 'Latest verified app + unpatched server combination',
        'Pristine main': 'Combined main',
        'pristine main': 'combined main',
        'to pristine upstream': 'to the combined main baseline',
        'pristine upstream remains on `main`': 'the shared app + engine baseline remains on `main`',
        f'Its parent is the pristine fork baseline,\n`{HISTORICAL}`.': 'Its shared base is the latest app + engine combination on main,\nidentified by `base_commit` in `Build/features.json`.',
        'Its original contents also remain unchanged on main.': 'Main documents the combined baseline separately.',
        'The original framework is replaced only in the disposable build\nworkspace; it is not misrepresented as a patched library in the source repository.':
            'The committed framework is the fresh unpatched main baseline. Feature builds\nreplace it only in the disposable build workspace; it is not a prepatched library.',
        'Main is restored only after every required check succeeds, with':
            'The earlier historical-main cleanup completed; later main updates use',
    }
    old_intro = f'''Main is the exact pre-customization fork baseline `{HISTORICAL}`.
Its original README and tracked binary framework are retained unchanged. This is
not a rolling mirror of today's upstream main. Feature branches rebuild from pinned'''
    for name in list(files):
        if not name.endswith('.md') or name.startswith(('docs/upstream/', 'docs/branches/')):
            continue
        data = text(files, name)
        data = data.replace(old_intro, 'Main combines latest verified iOS source and a freshly built unpatched engine.\nSee [the shared baseline specification](main-baseline.md). Feature branches inherit\nidentical pins and framework objects from main. They rebuild from pinned')
        for before, after in replacements.items():
            data = data.replace(before, after)
        put(files, name, data)


def make_candidates(framework, provenance):
    upstream, historical, old = snapshot(APP), snapshot(HISTORICAL), snapshot(RELEASE)
    # Only upstream's bundled core changed; do not silently overwrite future app changes.
    for path, value in historical.items():
        if not path.startswith('HevSocks5Server.xcframework/'):
            assert upstream.get(path) == value, 'New upstream app edits require review: ' + path
    common = common_files(old, upstream, framework, provenance)
    main = dict(upstream)
    for name in list(main):
        if name.startswith('HevSocks5Server.xcframework/'):
            del main[name]
    main.update(common)
    config = json.loads(text(old, 'Build/features.json'))
    config.update(name='baseline', features=[], patches=[], upstream_app=APP)
    put(main, 'Build/features.json', dump(config))
    put(main, 'README.md', BASELINE_DOC.replace('`docs/main-baseline.md`', '`docs/main-baseline.md`'))
    put(main, 'docs/build-and-validation.md', old['docs/build-and-validation.md'][1])
    update_docs(main)
    new = {'main': commit(main, [APP], 'Define main as latest upstream app plus freshly rebuilt unpatched Hev server')}
    compositions = {'main': main}
    for branch, previous in BRANCHES.items():
        if branch == 'main':
            continue
        feature = snapshot(previous)
        files = dict(main)
        # Replay the feature's exact source delta, then inherit shared baseline files.
        for name in historical.keys() - feature.keys():
            files.pop(name, None)
        for name, value in feature.items():
            if historical.get(name) != value and not name.startswith('HevSocks5Server.xcframework/'):
                files[name] = value
        files.update(common)
        config = json.loads(text(feature, 'Build/features.json'))
        config.update(upstream_app=APP, base_commit=new['main'])
        put(files, 'Build/features.json', dump(config))
        update_docs(files)
        if branch != 'release/integrated':
            readme = text(files, 'README.md').replace('](docs/build-and-validation.md)',
                f'](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/{branch}/docs/build-and-validation.md)')
            put(files, 'README.md', readme)
            parents = [new['feature/udp-compat'] if branch.endswith('traffic-statistics') else new['main'], previous]
        else:
            members = json.loads(text(feature, 'docs/feature-membership.json'))
            members['base_commit'] = new['main']
            members['branches'] = {name: sha for name, sha in new.items() if name.startswith('feature/')}
            for name, contents in compositions.items():
                if name.startswith('feature/'):
                    put(files, 'docs/branches/' + name.replace('/', '-') + '.md', contents['README.md'][1])
            members['files'] = {name: hashlib.sha256(files[name][1]).hexdigest() for name in members['files']}
            put(files, 'docs/feature-membership.json', dump(members))
            parents = [new[name] for name in ('feature/traffic-statistics', 'feature/background', 'feature/settings', 'feature/app-icon')] + [previous]
        # No application runtime or patch changes are permitted by this update.
        for name, value in feature.items():
            if name.startswith(('Socks5/', 'Patches/', 'Tests/')) or name == 'Socks5.xcodeproj/project.pbxproj':
                assert files.get(name) == value, 'Unexpected feature change: ' + name
        new[branch] = commit(files, parents, 'Inherit shared latest-upstream main; preserve feature implementation and history')
        compositions[branch] = files
    for branch, sha in new.items():
        git('merge-base', '--is-ancestor', BRANCHES[branch], sha)
        if branch != 'main':
            git('merge-base', '--is-ancestor', new['main'], sha)
    return new, compositions


def prepare(framework, provenance_file):
    upstream_is_current()
    expected = {**BRANCHES, TEMP_BRANCH: os.environ['GITHUB_SHA']}
    refs = {line.split()[1].removeprefix('refs/heads/'): line.split()[0]
            for line in git('ls-remote', '--heads', 'origin').decode().splitlines()}
    assert refs == expected, 'Repository changed; do not overwrite concurrent work'
    core = framework.parent
    sources = json.loads(git('show', RELEASE + ':Build/features.json'))['sources']
    for relative, sha in sources.items():
        actual = subprocess.check_output(['git', '-C', str(core / relative), 'rev-parse', 'HEAD']).decode().strip()
        assert actual == sha
        subprocess.run(['git', '-C', str(core / relative), 'diff', '--exit-code', 'HEAD'], check=True)
    new, compositions = make_candidates(framework, json.loads(provenance_file.read_text()))
    out = REPO / 'artifacts/baseline-update'
    out.mkdir(parents=True, exist_ok=True)
    prefix = 'refs/tags/staging/latest-baseline-' + os.environ['GITHUB_RUN_ID'] + '/'
    candidate_tags = {name: prefix + name for name in new}
    archives = {name: 'refs/tags/archive/before-latest-baseline-20260922/' + name + '-' + sha[:12]
                for name, sha in expected.items()}
    existing_tags = {line.split()[1]: line.split()[0] for line in git('ls-remote', '--tags', 'origin').decode().splitlines()}
    pushes = []
    for branch, tag in archives.items():
        if tag in existing_tags:
            assert existing_tags[tag] == expected[branch]
        else:
            pushes.append(expected[branch] + ':' + tag)
    for branch, tag in candidate_tags.items():
        assert tag not in existing_tags
        pushes.append(new[branch] + ':' + tag)
    git('push', '--atomic', 'origin', *pushes)
    state = {'old': expected, 'new': new, 'archives': archives, 'candidates': candidate_tags,
             'upstream_app': APP, 'upstream_server': SERVER}
    (out / 'state.json').write_text(dump(state))
    git('fetch', 'origin', '--tags')
    git('bundle', 'create', str(out / 'history.bundle'), '--all')
    (out / 'PRESERVATION.txt').write_text('All prior feature Swift, resources, patches and test files are byte-identical.\nAll new branches inherit combined main, shared pins and unpatched framework.\n')
    matrix = {'include': [{'ref': sha, 'name': name} for name, sha in new.items() if name != 'release/integrated']}
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('matrix=' + json.dumps(matrix) + '\n')
        stream.write('integrated=' + new['release/integrated'] + '\n')
    print(dump(new))


def publish(state_path):
    upstream_is_current()
    state = json.loads(state_path.read_text())
    refs = {line.split()[1]: line.split()[0] for line in git('ls-remote', 'origin').decode().splitlines()}
    for branch, sha in state['old'].items():
        assert refs.get('refs/heads/' + branch) == sha, 'Concurrent branch update: ' + branch
        assert refs.get(state['archives'][branch]) == sha, 'Missing archive'
    args = ['push', '--atomic']
    args += ['--force-with-lease=refs/heads/' + name + ':' + sha for name, sha in state['old'].items()]
    args += ['origin']
    for branch, sha in state['new'].items():
        assert refs.get(state['candidates'][branch]) == sha
        git('merge-base', '--is-ancestor', state['old'][branch], sha)
        args.append(sha + ':refs/heads/' + branch)
    args += [':refs/heads/' + TEMP_BRANCH] + [':' + ref for ref in state['candidates'].values()]
    git(*args)
    current = {line.split()[1].removeprefix('refs/heads/'): line.split()[0]
               for line in git('ls-remote', '--heads', 'origin').decode().splitlines()}
    assert current == state['new']
    (state_path.parent / 'COMPLETED.json').write_text(dump({'branches': current, 'result': 'All seven branch builds verified and published atomically'}))
    print(dump(current))


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        prepare(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
    elif sys.argv[1] == 'publish':
        publish(Path(sys.argv[2]).resolve())
    else:
        raise SystemExit('Expected prepare or publish')
