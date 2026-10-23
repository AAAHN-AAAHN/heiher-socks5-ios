#!/usr/bin/env python3
"""Run the exact shared baseline controls for a dedicated no-IPA workflow."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    base = json.loads((ROOT / 'Build/features.json').read_bytes())['base_commit']
    env = dict(os.environ)
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GITHUB_OUTPUT'):
        env.pop(key, None)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(ROOT), *args], env=env)
    git('merge-base', '--is-ancestor', base, 'HEAD')
    for path in ('Build/build.sh', 'Build/check.py', 'Tests/baseline_audit.py',
                 'Tests/tcp_smoke.py'):
        if (ROOT / path).read_bytes() != git('show', base + ':' + path):
            raise RuntimeError('Inherited baseline implementation differs: ' + path)
    with tempfile.TemporaryDirectory(prefix='shared-baseline-') as temporary:
        worktree = Path(temporary) / 'source'
        git('worktree', 'add', '--detach', str(worktree), base)
        try:
            subprocess.run([sys.executable, 'Tests/baseline_audit.py'], cwd=worktree,
                           env=env, check=True, timeout=180)
        finally:
            git('worktree', 'remove', '--force', str(worktree))
    print('PASS: exact inherited baseline inputs and owner workflow:', base)


if __name__ == '__main__':
    main()
