#!/usr/bin/env python3
"""Record immutable Git source identity separately from generated native artifacts."""
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys

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
source = out / 'source.zip'
if not source.is_file():
    source = out / 'verified-source.zip'
    subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=zip', commit, '-o', str(source)], check=True)
subprocess.run([sys.executable, str(ROOT / 'Build/check.py'), 'archive', str(source), commit], check=True)
if source.name != 'verified-source.zip':
    shutil.copyfile(source, out / 'verified-source.zip')
print('Recorded', len(paths), 'source files for', commit)
