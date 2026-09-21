#!/usr/bin/env python3
"""Finalize names only after every feature and integrated verification succeeds."""
from pathlib import Path
import json
import subprocess

BASE = '83d350d28d6a31e7730cfa74b49f58d2af642397'
DATA = Path('reorganization-state')


def git(*args):
    return subprocess.check_output(['git', *args])


def main():
    before = json.loads((DATA / 'old-branches.json').read_text())
    after = json.loads((DATA / 'new-branches.json').read_text())
    archives = json.loads((DATA / 'archives.json').read_text())
    refs = {line.split()[1]: line.split()[0] for line in git('ls-remote', 'origin').decode().splitlines()}
    for branch, sha in after.items():
        assert refs.get('refs/heads/' + branch) == sha, 'Feature changed during verification: ' + branch
    for branch, item in archives.items():
        assert refs.get(item['tag']) == item['sha'], 'Missing original archive: ' + branch
        assert refs.get('refs/heads/' + branch) == item['sha'], 'Original branch changed: ' + branch
    args = ['push', '--atomic']
    obsolete = [name for name in archives if name != 'main' and name not in after]
    for branch in ['main', *obsolete]:
        args.append('--force-with-lease=refs/heads/' + branch + ':' + before[branch])
    args += ['origin', BASE + ':refs/heads/main']
    args += [':refs/heads/' + branch for branch in obsolete]
    git(*args)
    final = {line.split()[1].removeprefix('refs/heads/'): line.split()[0]
             for line in git('ls-remote', '--heads', 'origin').decode().splitlines()}
    expected = dict(after, main=BASE)
    assert final == expected, (final, expected)
    (DATA / 'final-branches.json').write_text(json.dumps(final, indent=2) + '\n')
    git('fetch', '--prune', 'origin')
    git('bundle', 'create', str((DATA / 'history-final.bundle').resolve()), '--all')
    (DATA / 'COMPLETED.txt').write_text('All five feature builds and the integrated build passed.\nPristine main and exactly six development/release branches verified.\nOld branch tips remain under verified archive tags.\n')
    print(json.dumps(final, indent=2))


if __name__ == '__main__':
    main()
