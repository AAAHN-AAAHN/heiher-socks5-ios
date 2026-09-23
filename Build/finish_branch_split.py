#!/usr/bin/env python3
"""Delete only the superseded settings ref, after successful release validation.

Run by the one explicitly authorized cleanup job, with an exact lease. The old
settings history remains an ancestor of the replacement and release commits.
"""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OLD = '16689f780f3e0e0c9344397273528697f197c9e5'

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()

def refs():
    return {line.split()[1].removeprefix('refs/heads/'): line.split()[0]
            for line in git('ls-remote', '--heads', 'origin').splitlines()}

manifest = json.loads((ROOT / 'docs/feature-membership.json').read_bytes())
expected = dict(manifest['branches'])
expected['main'] = manifest['base_commit']
expected['release/integrated'] = os.environ['GITHUB_SHA']
assert len(expected) == 8
before = refs()
for branch, commit in expected.items():
    assert before.get(branch) == commit, 'Concurrent branch change: ' + branch
assert set(before) in (set(expected), set(expected) | {'feature/settings'}), 'Unexpected branch set; do not delete anything'
subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', OLD, expected['feature/settings-persistence']], check=True)
if 'feature/settings' in before:
    assert before['feature/settings'] == OLD, 'Old branch changed; refusing deletion'
    subprocess.run(['git', '-C', str(ROOT), 'push',
                    '--force-with-lease=refs/heads/feature/settings:' + OLD,
                    'origin', ':refs/heads/feature/settings'], check=True)
after = refs()
assert after == expected, 'Remote final refs differ from validated eight-branch plan'
out = ROOT / 'artifacts/branch-layout'
out.mkdir(parents=True, exist_ok=True)
(out / 'final-branches.json').write_text(json.dumps(after, indent=2, sort_keys=True) + '\n')
(out / 'RESULT.txt').write_text('PASS: exactly eight refs; only old feature/settings removed with exact lease; history retained.\n')
print('PASS: final eight branches and unchanged feature heads verified')
