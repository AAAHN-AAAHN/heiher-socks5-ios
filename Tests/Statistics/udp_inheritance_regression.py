#!/usr/bin/env python3
"""Reject drift between the current UDP parent, its files and composed execution."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
    ENV.pop(key, None)


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    cases = ('valid', 'missing-fixture', 'changed-fixture', 'fixture-mode',
             'staged-fixture', 'stale-workflow', 'stale-parent', 'changed-driver',
             'missing-composed-execution')
    results = []
    with tempfile.TemporaryDirectory(prefix='udp-inheritance-') as directory:
        for index, case in enumerate(cases):
            root = Path(directory) / str(index)
            subprocess.run(['git', '-C', str(ROOT), 'worktree', 'add', '--quiet',
                            '--detach', str(root), 'HEAD'], check=True, env=ENV, timeout=60)
            try:
                values = runpy.run_path(str(root / 'Tests/Statistics/audit.py'))
                fixture = root / 'Tests/udp_stream_boundaries.c'
                if case == 'missing-fixture':
                    fixture.unlink()
                elif case == 'changed-fixture':
                    fixture.write_bytes(fixture.read_bytes() + b'\n/* Changed fixture. */\n')
                elif case == 'fixture-mode':
                    fixture.chmod(0o755)
                elif case == 'staged-fixture':
                    original = fixture.read_bytes()
                    fixture.write_bytes(original + b'\n/* Staged change. */\n')
                    subprocess.run(['git', '-C', str(root), 'add', str(fixture)],
                                   check=True, env=ENV, timeout=60)
                    fixture.write_bytes(original)
                elif case == 'stale-workflow':
                    path = root / '.github/workflows/verify-build.yml'
                    path.write_text(path.read_text().replace(values['UDP'], '0' * 40))
                elif case == 'stale-parent':
                    path = root / 'docs/documentation.json'
                    value = json.loads(path.read_bytes())
                    value['parents']['feature/udp-compat'] = '0' * 40
                    path.write_text(json.dumps(value))
                elif case == 'changed-driver':
                    path = root / 'Tests/udp_compat_audit.py'
                    path.write_bytes(path.read_bytes() + b'\n# Changed parent driver.\n')
                elif case == 'missing-composed-execution':
                    values['check_udp_inheritance'].__globals__['UDP_COMPOSED_SOURCES'] = ()
                try:
                    values['check_udp_inheritance']()
                    accepted = True
                except AssertionError:
                    accepted = False
                if accepted != (case == 'valid'):
                    raise RuntimeError(('Unexpected inheritance verdict', case, accepted))
                results.append({'case': case, 'accepted': accepted})
            finally:
                subprocess.run(['git', '-C', str(ROOT), 'worktree', 'remove', '--force', str(root)],
                               check=True, env=ENV, timeout=60)
    print(json.dumps({'result': 'PASS', 'cases': results,
                      'scope': 'Source inheritance and execution wiring; native behavior is tested separately'}, indent=2))


if __name__ == '__main__':
    main()
