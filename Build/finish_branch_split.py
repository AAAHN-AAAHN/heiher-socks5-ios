#!/usr/bin/env python3
"""Remove only the three reviewed obsolete refs after successful reconciliation.

All compared histories must already be ancestors of the release. Validate the
complete ref set, then use one atomic push with an exact lease for each deletion.
"""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OBSOLETE = {
    'feature/settings': '16689f780f3e0e0c9344397273528697f197c9e5',
    'feature/server-runtime': '0ab3c33a667cd7fabf6b0683d98c619d2bff169c',
    'feature/config-persistence': '506156e6a83dcc4d40ce675136d269c1b02fd49d'
}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def refs():
    return {line.split()[1].removeprefix('refs/heads/'): line.split()[0]
            for line in git('ls-remote', '--heads', 'origin').splitlines()}


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled.')
    manifest = json.loads((ROOT / 'docs/feature-membership.json').read_bytes())
    expected = dict(manifest['branches'])
    expected['main'] = manifest['base_commit']
    expected['release/integrated'] = os.environ['GITHUB_SHA']
    assert len(expected) == 8
    before = refs()
    out = ROOT / 'artifacts/branch-layout'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'before.json').write_text(json.dumps(before, indent=2, sort_keys=True) + '\n')
    for branch, commit in expected.items():
        assert before.get(branch) == commit, 'Concurrent branch change: ' + branch
    assert set(before) <= set(expected) | set(OBSOLETE), 'Unexpected branch; refusing cleanup'
    pending = {name: sha for name, sha in OBSOLETE.items() if name in before}
    for name, sha in pending.items():
        assert before[name] == sha, 'Reviewed branch changed: ' + name
        git('merge-base', '--is-ancestor', sha, expected['release/integrated'])
    if pending:
        subprocess.run(['git', '-C', str(ROOT), 'push', '--atomic',
                        *['--force-with-lease=refs/heads/' + name + ':' + sha for name, sha in pending.items()],
                        'origin', *[':refs/heads/' + name for name in pending]], check=True)
    after = refs()
    (out / 'after.json').write_text(json.dumps(after, indent=2, sort_keys=True) + '\n')
    assert after == expected, 'Remote refs changed; inspect before/after, do not infer completion'
    (out / 'RESULT.txt').write_text('PASS: exactly eight branches; reviewed obsolete refs removed atomically with leases; histories retained.\n')
    print('PASS: eight canonical branches; duplicate and old settings histories remain reachable')


if __name__ == '__main__':
    main()
