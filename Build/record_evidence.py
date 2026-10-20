#!/usr/bin/env python3
"""Record immutable Git source identity separately from generated native artifacts."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
name = json.loads((ROOT / 'Build/features.json').read_bytes())['name']
out = ROOT / 'artifacts' / name
out.mkdir(parents=True, exist_ok=True)
def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])
commit = git('rev-parse', 'HEAD').decode().strip()
tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
paths = git('ls-tree', '-r', '--name-only', 'HEAD').decode().splitlines()
manifest = {p: hashlib.sha256(git('show', 'HEAD:' + p)).hexdigest() for p in paths}
(out / 'source-sha256.json').write_text(json.dumps(manifest, indent=2) + '\n')
(out / 'source-identity.json').write_text(json.dumps({'commit': commit, 'tree': tree,
    'scope': 'Git source snapshot; generated native framework/archive is recorded separately'}, indent=2) + '\n')
subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip', 'HEAD', '-o', str(out / 'verified-source.zip')], check=True)
subprocess.run(['git', '-C', str(ROOT), 'bundle', 'create', str(out / 'history.bundle'), 'HEAD'], check=True)
print('Recorded', len(paths), 'source files and reachable Git history for', commit)
