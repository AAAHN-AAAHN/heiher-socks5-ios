"""Apply the exact Release projection of the canonical ServerControl patch."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, 'Duplicate ServerControl contract key: ' + key)
        value[key] = item
    return value


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _state(repo, name):
    relative = PurePosixPath(name)
    _require(not relative.is_absolute() and '..' not in relative.parts and
             str(relative) == name and '\\' not in name,
             'Invalid ServerControl source path: ' + name)
    path = repo / name
    mode = path.lstat().st_mode
    _require(stat.S_ISREG(mode) and path.resolve() == path,
             'ServerControl source must be a regular file without symlink parents: ' + name)
    data = path.read_bytes()
    return {'mode': '100755' if mode & 0o111 else '100644',
            'sha256': _sha256(data),
            'blob_sha1': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def apply(repo, patch, reverse=False):
    """Validate the canonical input, project its context, apply, and validate output."""
    repo, patch = Path(repo).resolve(strict=True), Path(patch)
    contract = json.loads(Path(__file__).with_name('server-patch-context.json').read_bytes(),
                          object_pairs_hook=_unique)
    raw = patch.read_bytes()
    _require(patch.name == contract['patch'] and _sha256(raw) == contract['patch_sha256'],
             'Canonical ServerControl patch SHA256 or name differs')
    # UDP already owns the stronger atomic authentication load. Preserve the
    # canonical owner patch; omit only its exact superseded auth section.
    sections = re.split(rb'(?=^diff --git )', raw, flags=re.M)
    omitted = contract['superseded_sections']
    _require(len(set(omitted)) == len(omitted) and all(
        sum(_sha256(section) == digest for section in sections) == 1
        for digest in omitted), 'Superseded ServerControl section differs')
    projected = b''.join(section for section in sections
                         if _sha256(section) not in omitted)
    _require(_sha256(projected) == contract['projected_patch_sha256'],
             'Projected ServerControl patch SHA256 differs')
    indices = [line.decode() for line in re.findall(rb'^index [^\n]+$', raw, re.M)]
    _require(indices == contract['index_lines'] and
             re.findall(rb'^index [^\n]+$', projected, re.M) ==
             [line.encode() for line in indices], 'ServerControl index metadata differs')
    headers = re.findall(rb'^diff --git a/(\S+) b/(\S+)$', raw, re.M)
    _require(headers and all(left == right for left, right in headers) and
             {right.decode() for _, right in headers} == set(contract['files']),
             'ServerControl source inventory differs')
    before, after = ('after', 'before') if reverse else ('before', 'after')
    for name, states in contract['files'].items():
        _require(_state(repo, name) == states[before], 'ServerControl preimage differs: ' + name)
    command = ['git', 'apply', *(['-R'] if reverse else []), '--whitespace=error-all']
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    subprocess.run([*command, '--check', '-'], cwd=repo, env=env, input=projected, check=True)
    subprocess.run([*command, '-'], cwd=repo, env=env, input=projected, check=True)
    for name, states in contract['files'].items():
        _require(_state(repo, name) == states[after], 'ServerControl postimage differs: ' + name)
    print(f"ServerControl projection PASS {'reverse' if reverse else 'forward'} "
          f"canonical={contract['patch_sha256']} projected={contract['projected_patch_sha256']} "
          f"paths={len(contract['files'])}", flush=True)
