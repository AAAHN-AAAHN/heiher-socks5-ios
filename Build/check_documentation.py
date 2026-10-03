#!/usr/bin/env python3
"""Validate current-parent documents without relaxing frozen functional inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'docs/documentation.json'
SUPPORT = {'Build/check_documentation.py', 'Tests/documentation_contract.py'}
CONTROLS = {'Build/check.py', 'Build/check_ownership.py',
            'Tests/AppIcon/check_icon.py', 'Tests/Background/check_scope.py',
            'Tests/Statistics/audit.py'}
FROZEN = {
    'main': '75335d201cb1e541bb153e9899badbc11ccf1973',
    'feature/app-icon': 'a17e33b283025377601aef1bcfd32dfa6b79a426',
    'feature/background': '25c4b2f9bc82b8079212dd5bbcff06034b67959c',
    'feature/server-control': '368aa4cf89436651414a8885a2a171f5cff9abd5',
    'feature/settings-persistence': 'a52f2599c4bdb895bc4e8d04ba84f03f45b2a5c7',
    'feature/traffic-statistics': 'dc6feaadb9061eb320bbce5d66c56a7c814c93d3',
    'feature/udp-compat': '84d47e88de993a8f4b4cc084f9240f29565c78ed',
    'release/integrated': 'b9dcac6da65fb7eed7ba5aad19d5208f45d5abcc',
}
PARENTS = {name: ['main'] for name in FROZEN if name != 'main'}
PARENTS.update({'main': ['upstream'],
                'feature/traffic-statistics': ['feature/udp-compat'],
                'feature/settings-persistence': ['feature/server-control'],
                'release/integrated': [name for name in FROZEN if name.startswith('feature/')]})
HEADINGS = ['Purpose and scope', 'Functional behavior', 'Implementation and ownership',
            'Design rationale and resource cost', 'Verification contract',
            'Operation and limitations', 'Related documents']
REPOSITORY = 'https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/'


def require(value, message):
    if not value:
        raise RuntimeError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def tree(root, ref):
    result = {}
    for record in git(root, 'ls-tree', '-rz', ref).split(b'\0'):
        if record:
            meta, name = record.split(b'\t', 1)
            mode, kind, sha = meta.decode().split()
            result[name.decode()] = (mode, kind, sha)
    return result


def index_tree(root):
    result = {}
    for record in git(root, 'ls-files', '--stage', '-z').split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, sha, stage = meta.decode().split()
        require(stage == '0' and name.decode() not in result, 'Unmerged index input')
        result[name.decode()] = (mode, 'blob', sha)
    return result


def show(root, ref, path):
    return git(root, 'show', ref + ':' + path)


def document(path):
    return path.endswith(('.md', '.rst', '.txt')) and (path == 'README.md' or path.startswith('docs/'))


def configuration(root):
    path = Path(root) / MANIFEST
    require(path.is_file() and not path.is_symlink(), 'Missing regular documentation contract')
    value = json.loads(path.read_bytes())
    require(value['branch'] in FROZEN, 'Unknown documentation branch')
    require(value['frozen_source'] == FROZEN[value['branch']], 'Frozen source identity changed')
    require(set(value['validation_files']) <= CONTROLS | SUPPORT, 'Unexpected documentation-code exception')
    require(SUPPORT <= set(value['validation_files']), 'Missing documentation validation support')
    return value


def documentation_input(root, path):
    value = configuration(root)
    return document(path) or path in value['validation_files'] or path in (MANIFEST, 'docs/feature-membership.json')


def code_paths(root, paths):
    value = configuration(root)
    excluded = set(value['validation_files']) | {MANIFEST, 'docs/feature-membership.json'}
    return [p for p in paths if not document(p) and p not in excluded]


def stamp(path):
    if path.is_symlink():
        import os
        data, mode = os.readlink(path).encode(), '120000'
    else:
        require(path.is_file(), 'Missing regular frozen input: ' + str(path))
        data = path.read_bytes()
        mode = '100755' if path.stat().st_mode & 0o111 else '100644'
    digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    return mode, 'blob', digest


def check_membership(root, baseline, value):
    path = 'docs/feature-membership.json'
    if path not in baseline:
        require(not (root / path).exists(), 'Unexpected functional membership file')
        return
    original = json.loads(show(root, value['frozen_source'], path))
    current = json.loads((root / path).read_bytes())
    require(set(current) == set(original), 'Membership structure changed')
    for key in set(original) - {'sources', 'files'}:
        require(current[key] == original[key], 'Functional membership changed: ' + key)
    expected_files = {p: h for p, h in original.get('files', {}).items() if not document(p)}
    require(current.get('files', {}) == expected_files, 'Functional file hashes changed')
    expected_sources = {p: e for p, e in original.get('sources', {}).items() if not document(p)}
    require(set(current.get('sources', {})) == set(expected_sources), 'Functional ownership inventory changed')
    for path, entry in expected_sources.items():
        updated = current['sources'][path]
        if path not in value['validation_files']:
            require(updated == entry, 'Functional source reference changed: ' + path)
        else:
            require(updated.get('path', path) == entry.get('path', path), 'Validation source path changed: ' + path)
            git(root, 'merge-base', '--is-ancestor', entry['commit'], updated['commit'])
            git(root, 'merge-base', '--is-ancestor', updated['commit'], 'HEAD')
            data = show(root, updated['commit'], updated.get('path', path))
            require(data == (root / path).read_bytes(), 'Validation owner differs: ' + path)
            require(hashlib.sha256(data).hexdigest() == updated['sha256'], 'Validation owner hash differs: ' + path)


def parent_target(branch, path):
    if branch == 'upstream':
        return 'docs/upstream/' + path
    if path == 'README.md':
        return 'docs/branches/' + branch.replace('/', '-') + '.md'
    return path


def anchors(text):
    result, counts = set(), {}
    for heading in re.findall(r'^#{1,6} +(.+?) *#*$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug + ('-' + str(count) if count else ''))
    return result


def check_links(root, path, text, refs):
    clean = re.sub(r'^```.*?^```[^\n]*$', '', text, flags=re.M | re.S)
    for target in re.findall(r'!?\[[^\]]*\]\(([^\s)]+)\)', clean):
        target = unquote(target)
        parts = urlsplit(target)
        ref = None
        if target.startswith(REPOSITORY):
            tail = parts.path.split('/blob/', 1)[1]
            branch = next((b for b in sorted(refs, key=len, reverse=True) if tail.startswith(b + '/')), None)
            require(branch is not None, 'Unpinned repository link: ' + target)
            ref, name = refs[branch], tail[len(branch) + 1:]
        elif parts.scheme:
            require(parts.scheme in ('https', 'http', 'mailto') and bool(parts.netloc or parts.scheme == 'mailto'),
                    'Invalid external link: ' + target)
            continue
        else:
            require(not parts.netloc and not parts.path.startswith('/'), 'Invalid local link: ' + target)
            name = posixpath.normpath(posixpath.join(posixpath.dirname(path), parts.path)) if parts.path else path
        require(name not in ('', '.', '..') and not name.startswith('../') and '\\' not in name,
                'Escaping documentation link: ' + target)
        if ref is None:
            destination = root / name
            require(destination.is_file() and not destination.is_symlink(), 'Broken document link: ' + target)
            data = destination.read_bytes()
        else:
            try:
                data = show(root, ref, name)
            except subprocess.CalledProcessError as error:
                raise RuntimeError('Broken repository document link: ' + target) from error
        if parts.fragment:
            require(parts.fragment in anchors(data.decode()), 'Missing documentation anchor: ' + target)


def check(root=ROOT, live=False):
    root = Path(root).resolve()
    value = configuration(root)
    branch = value['branch']
    baseline = tree(root, value['frozen_source'])
    staged = index_tree(root)
    git(root, 'merge-base', '--is-ancestor', value['frozen_source'], 'HEAD')
    names = set(git(root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')) - {''}
    special = set(value['validation_files']) | {MANIFEST, 'docs/feature-membership.json'}
    for name in (set(baseline) | names) - special:
        if document(name):
            continue
        require(name in baseline and name in names, 'Frozen input added or removed: ' + name)
        require(stamp(root / name) == baseline[name], 'Frozen input changed: ' + name)
        require(staged.get(name) == baseline[name], 'Frozen index changed: ' + name)
    for name, expected in value['validation_files'].items():
        require(name in names and stamp(root / name) == ('100644', 'blob', expected),
                'Documentation validator differs from approval: ' + name)
        require(staged.get(name) == ('100644', 'blob', expected),
                'Documentation validator index differs: ' + name)
    check_membership(root, baseline, value)
    parents = value['parents']
    require(set(parents) == set(PARENTS[branch]), 'Documentation parent set differs')
    inherited, inherited_entries = {}, {}
    refs = {branch: 'HEAD'}
    seen = set()

    def collect(parent, ref):
        if (parent, ref) in seen:
            return
        seen.add((parent, ref))
        require(parent not in refs or refs[parent] == ref, 'Inconsistent document parent: ' + parent)
        refs[parent] = ref
        if parent != 'upstream':
            data = json.loads(show(root, ref, MANIFEST))
            require(data['branch'] == parent, 'Parent contract identity differs')
            for grandparent, ancestor in data['parents'].items():
                collect(grandparent, ancestor)

    for parent, ref in parents.items():
        git(root, 'merge-base', '--is-ancestor', ref, 'HEAD')
        collect(parent, ref)
        for source, entry in tree(root, ref).items():
            if not document(source):
                continue
            target = parent_target(parent, source)
            data = show(root, ref, source)
            require(target not in inherited or inherited[target] == data, 'Conflicting inherited document: ' + target)
            inherited[target] = data
            require(target not in inherited_entries or inherited_entries[target] == entry,
                    'Conflicting inherited mode: ' + target)
            inherited_entries[target] = entry
    owned = set(value['owned_documents'])
    require(len(owned) == len(value['owned_documents']) and all(document(p) for p in owned),
            'Invalid owned document inventory')
    require(not owned & set(inherited), 'Owned document masks a parent copy')
    actual_docs = {p for p in names if document(p)}
    require(actual_docs == owned | set(inherited), 'Documentation inventory differs')
    for name, data in inherited.items():
        require(not (root / name).is_symlink() and (root / name).read_bytes() == data,
                'Inherited documentation changed: ' + name)
        require(stamp(root / name) == inherited_entries[name] and staged.get(name) == inherited_entries[name],
                'Inherited documentation mode or index changed: ' + name)
    mirror = value['readme_mirror']
    require(mirror in owned and (root / 'README.md').read_bytes() == (root / mirror).read_bytes(), 'README mirror differs')
    require((root / 'docs/top-level-principles.md').read_bytes() ==
            show(root, FROZEN['main'], 'docs/top-level-principles.md'), 'Governing principles changed')
    upstream = json.loads((root / 'Build/upstream.json').read_bytes())['upstream_app']
    require((root / 'docs/upstream/README.md').read_bytes() == show(root, upstream, 'README.md'), 'Upstream README changed')
    require((root / 'LICENSE').read_bytes() == show(root, upstream, 'LICENSE'), 'Upstream license changed')
    for name in actual_docs:
        data = (root / name).read_bytes()
        require(not (root / name).is_symlink(), 'Linked document: ' + name)
        if name.startswith('docs/upstream/') or name == 'docs/top-level-principles.md':
            continue
        text = data.decode('utf-8')
        require(text.startswith('# ') and text.endswith('\n') and '\r' not in text, 'Document format: ' + name)
        require(len(re.findall(r'^# ', text, re.M)) == 1, 'Document title count: ' + name)
        require(all(part.strip() for part in re.split(r'^## .+$', text, flags=re.M)),
                'Empty document section: ' + name)
        require(stamp(root / name)[0] == '100644', 'Explanatory document mode: ' + name)
        require(not any(line.rstrip() != line for line in text.splitlines()), 'Document trailing whitespace: ' + name)
        require(re.findall(r'^## (.+)$', text, re.M) == HEADINGS, 'Document section structure: ' + name)
        require(len(re.findall(r'^```', text, re.M)) % 2 == 0, 'Unclosed document code fence: ' + name)
        require(not re.search(r'\b20\d{2}[-/]\d{2}[-/]\d{2}\b|\b20\d{6}\b', name + '\n' + text),
                'Dated narrative document: ' + name)
        require(not re.search(r'(?im)^#{1,6} .*\b(changelog|history|release notes|legacy|updates)\b', text),
                'Narrative-history section: ' + name)
        check_links(root, name, text, refs)
    if live:
        for parent, ref in refs.items():
            if parent in ('upstream', branch):
                continue
            current = git(root, 'ls-remote', '--exit-code', 'origin', 'refs/heads/' + parent).decode().split()[0]
            require(current == ref, 'Current remote document parent differs: ' + parent)
    result = {'branch': branch, 'documents': len(actual_docs), 'inherited_documents': len(inherited),
              'frozen_inputs': len([p for p in baseline if not document(p) and p not in special]),
              'approved_documentation_files': sorted(value['validation_files']), 'result': 'PASS'}
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--live-parents', action='store_true')
    args = parser.parse_args()
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    check(args.root, args.live_parents)
