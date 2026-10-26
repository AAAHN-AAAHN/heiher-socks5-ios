#!/usr/bin/env python3
"""Exercise declared/effective dependency boundaries using real Git objects."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Build'))
import native_sources as native


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def commit(repo, message):
    git(repo, '-c', 'user.name=Native input fixture', '-c', 'user.email=audit@localhost',
        'commit', '-qm', message)
    return git(repo, 'rev-parse', 'HEAD').decode().strip()


def expect(label, operation, accepted):
    try:
        operation()
        result = True
    except (ValueError, KeyError, subprocess.CalledProcessError):
        result = False
    if result != accepted:
        raise RuntimeError((label, result, accepted))
    print('PASS native lock:', label, 'accepted=', result)


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    import os
    for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        os.environ.pop(name, None)
    locked = json.loads((ROOT / 'Build/upstream.json').read_text())
    expect('committed lock structure', lambda: native.validate(locked), True)
    cases = ('schema', 'missing-component', 'repository', 'floating-ref', 'escaping-path',
             'undeclared-override', 'effective-drift', 'consumer-core-drift')
    for case in cases:
        value = copy.deepcopy(locked)
        server = value['components']['server']
        if case == 'schema':
            value['schema_version'] = 1
        elif case == 'missing-component':
            del value['components']['tunnel']
        elif case == 'repository':
            server['repository'] = 'https://example.invalid/server.git'
        elif case == 'floating-ref':
            server['commit'] = 'main'
        elif case == 'escaping-path':
            server['gitlinks']['../outside'] = server['commit']
        elif case == 'undeclared-override':
            server['overrides']['third-part/hev-task-system'] = 'core'
        elif case == 'effective-drift':
            value['sources']['src/core'] = '0' * 40
        else:
            value['components']['tunnel']['gitlinks']['src/core'] = '0' * 40
        expect(case, lambda: native.validate(value), False)

    with tempfile.TemporaryDirectory(prefix='native-source-lock-') as directory:
        root = Path(directory)
        core = root / 'src/core'
        core.mkdir(parents=True)
        git(core, 'init', '-q')
        (core / 'probe.c').write_text('int original;\n')
        git(core, 'add', 'probe.c')
        declared = commit(core, 'Recorded dependency')
        (core / 'probe.c').write_text('int current;\n')
        git(core, 'add', 'probe.c')
        selected = commit(core, 'Selected dependency')
        git(root, 'init', '-q')
        (root / 'README').write_text('Upstream root fixture.\n')
        git(root, 'add', 'README')
        git(root, 'update-index', '--add', '--cacheinfo', '160000', declared, 'src/core')
        head = commit(root, 'Original upstream gitlink')
        value = copy.deepcopy(locked)
        value['components']['core'].update(commit=selected)
        for name in ('server', 'tunnel'):
            value['components'][name].update(commit=head, gitlinks={'src/core': declared},
                                              overrides={'src/core': 'core'})
        value['sources'] = native.sources(value, 'server')
        native.validate(value)
        expect('explicit override with preserved upstream gitlink',
               lambda: native.verify(value, 'server', root), True)
        original = git(root, 'rev-parse', 'HEAD:src/core').decode().strip()
        if original != declared:
            raise RuntimeError('Fixture did not preserve the upstream gitlink')
        changed = copy.deepcopy(value)
        changed['components']['server']['gitlinks']['src/core'] = selected
        expect('false declared gitlink', lambda: native.verify(changed, 'server', root), False)
        git(core, 'checkout', '--detach', declared)
        expect('unapplied effective dependency', lambda: native.verify(value, 'server', root), False)
        git(core, 'checkout', '--detach', selected)
        wrong_head = copy.deepcopy(value)
        wrong_head['components']['server']['commit'] = selected
        expect('wrong upstream root', lambda: native.verify(wrong_head, 'server', root), False)
        git(core, 'update-index', '--add', '--cacheinfo', '160000', declared, 'unexpected')
        nested = commit(core, 'Unrecorded nested dependency')
        value['components']['core']['commit'] = nested
        value['sources'] = native.sources(value, 'server')
        native.validate(value)
        expect('unrecorded nested dependency', lambda: native.verify(value, 'server', root), False)
    print('SUMMARY: immutable roots, declared gitlinks, explicit overrides and dependency closure checked')


if __name__ == '__main__':
    main()
