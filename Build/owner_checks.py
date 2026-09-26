#!/usr/bin/env python3
"""Run exact owners' source/driver controls without falsifying release scope.

Combined runtime tests are run separately against the integrated engine/controller.
Detached temporary worktrees retain genuine Git objects for old-code controls and
are removed even on failure. No feature branch or application file is changed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/integrated/owner-controls'
CHECKS = {
    'feature/udp-compat': ['Tests/udp_audit_driver_regression.py'],
    'feature/traffic-statistics': ['Tests/Statistics/input_probe.py'],
    'feature/server-control': ['Tests/ServerControl/input_integrity_check.py'],
    'feature/settings-persistence': ['Tests/ServerControl/input_integrity_check.py'],
    'feature/background': ['Tests/Background/check_scope.py',
                           'Tests/Background/check_audit_integrity.py',
                           'Tests/Background/audit_driver_check.py'],
    'feature/app-icon': ['Tests/AppIcon/test_icon.py',
                         'Tests/AppIcon/test_audit_boundaries.py',
                         'Tests/AppIcon/audit_driver_check.py'],
}


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    refs = json.loads((ROOT / 'docs/feature-membership.json').read_bytes())['branches']
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
        env.pop(key, None)
    for branch, scripts in CHECKS.items():
        with tempfile.TemporaryDirectory(prefix='release-owner-') as folder:
            path = Path(folder) / 'source'
            subprocess.run(['git', '-C', str(ROOT), 'worktree', 'add', '--detach', str(path), refs[branch]],
                           check=True, env=env, timeout=60)
            failure = None
            try:
                for script in scripts:
                    log = OUT / (branch.split('/')[-1] + '-' + Path(script).stem + '.log')
                    with log.open('w') as stream:
                        subprocess.run([sys.executable, str(path / script)], cwd=path, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
            except Exception as error:
                failure = error
            finally:
                cleanup = subprocess.run(['git', '-C', str(ROOT), 'worktree', 'remove', '--force', str(path)],
                                         env=env, capture_output=True, text=True, timeout=60)
                (OUT / (branch.split('/')[-1] + '-cleanup.log')).write_text(cleanup.stdout + cleanup.stderr)
            if failure:
                raise failure
            cleanup.check_returncode()
            print('PASS: exact pinned owner driver/source controls:', branch, refs[branch], flush=True)


if __name__ == '__main__':
    main()
