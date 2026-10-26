#!/usr/bin/env python3
"""Lock upstream roots separately from explicitly selected dependencies."""
import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ('core', 'server', 'tunnel')


def require(value, message):
    if not value:
        raise ValueError(message)


def sources(lock, name):
    component = lock['components'][name]
    result = {'.': component['commit'], **component['gitlinks']}
    for path, owner in component['overrides'].items():
        result[path] = lock['components'][owner]['commit']
    return result


def validate(lock):
    require(lock['schema_version'] == 2, 'Unsupported upstream lock schema')
    require(set(lock['components']) == set(COMPONENTS), 'Native component inventory differs')
    for name, component in lock['components'].items():
        require(set(component) == {'repository', 'commit', 'gitlinks', 'overrides'},
                'Unexpected component fields: ' + name)
        require(component['repository'] == f'https://github.com/heiher/hev-socks5-{name}.git',
                'Unexpected upstream repository: ' + name)
        for sha in (component['commit'], *component['gitlinks'].values()):
            require(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha),
                    'Native input is not an immutable commit: ' + name)
        for path in component['gitlinks']:
            require(isinstance(path, str) and path not in ('', '.') and
                    str(PurePosixPath(path)) == path and not PurePosixPath(path).is_absolute() and
                    '..' not in PurePosixPath(path).parts and '\\' not in path,
                    'Unsafe native dependency path: ' + name)
        require(component['overrides'] in ({}, {'src/core': 'core'}) and
                set(component['overrides']) <= set(component['gitlinks']),
                'Undeclared native dependency override: ' + name)
    require(not lock['components']['core']['gitlinks'] and
            not lock['components']['core']['overrides'], 'Core unexpectedly has dependencies')
    require(sources(lock, 'server') == lock['sources'], 'Effective server source pins differ')
    for name in ('server', 'tunnel'):
        require(sources(lock, name).get('src/core') == lock['components']['core']['commit'],
                'Consumer does not select the locked core: ' + name)
    return lock


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def gitlinks(repo, ref):
    result = {}
    for record in git(repo, 'ls-tree', '-rz', ref).split(b'\0'):
        if record:
            meta, path = record.split(b'\t', 1)
            mode, kind, sha = meta.decode().split()
            if mode == '160000':
                require(kind == 'commit', 'Invalid native gitlink')
                result[path.decode()] = sha
    return result


def verify(lock, name, destination):
    component = lock['components'][name]
    for path, sha in sources(lock, name).items():
        repo = destination / path
        require(not repo.is_symlink(), 'Linked native input: ' + str(repo))
        require(git(repo, 'rev-parse', 'HEAD').decode().strip() == sha,
                'Effective native HEAD differs: ' + str(repo))
        require(git(repo, 'cat-file', '-t', sha).strip() == b'commit',
                'Native input is not a commit: ' + str(repo))
        if path != '.':
            require(not gitlinks(repo, sha), 'Unrecorded nested dependency: ' + str(repo))
    require(gitlinks(destination, component['commit']) == component['gitlinks'],
            'Recorded upstream gitlinks differ: ' + name)


def checkout(lock, name, destination):
    require(not destination.is_symlink(), 'Linked native checkout')
    if not (destination / '.git').exists():
        component = lock['components'][name]
        subprocess.run(['git', 'clone', '--no-checkout', component['repository'], str(destination)],
                       check=True, stdout=subprocess.DEVNULL)
        git(destination, 'checkout', '--detach', component['commit'])
        git(destination, 'submodule', 'update', '--init', '--recursive')
        for path, owner in component['overrides'].items():
            sha = lock['components'][owner]['commit']
            repo = destination / path
            git(repo, 'fetch', 'origin', sha)
            git(repo, 'checkout', '--detach', sha)
    # Existing worktrees are validated, never reset over local or stale inputs.
    verify(lock, name, destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('checkout', 'verify', 'sources'))
    parser.add_argument('component', choices=COMPONENTS)
    parser.add_argument('destination', nargs='?', type=Path)
    args = parser.parse_args()
    lock = validate(json.loads((ROOT / 'Build/upstream.json').read_text()))
    if args.operation != 'sources':
        require(args.destination is not None, 'Native checkout path is required')
        (checkout if args.operation == 'checkout' else verify)(lock, args.component, args.destination)
    print(json.dumps({'component': args.component,
                      'upstream': lock['components'][args.component],
                      'sources': sources(lock, args.component)}, indent=2))
