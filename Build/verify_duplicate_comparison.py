#!/usr/bin/env python3
"""Reproduce the duplicate comparison and prove reconciliation kept product bytes.

The compared commits remain reachable merge ancestors. This is source evidence,
not an assertion that different UI adapters were exercised on a real iPhone.
"""
import hashlib
import json
from pathlib import Path
import subprocess

if not __debug__:
    raise SystemExit('Assertions must be enabled.')
ROOT = Path(__file__).resolve().parents[1]
CONTROL = '68599f96331f3f45e3fa271db02e6ede0fc35d73'
PERSISTENCE = '633c04905ed7ca4acd7272fb040c8d1c66cb38e3'
RUNTIME = '0ab3c33a667cd7fabf6b0683d98c619d2bff169c'
CONFIG = '506156e6a83dcc4d40ce675136d269c1b02fd49d'
RELEASE = '6ad54bdca195f8ff97db6ac40d3374888c52e314'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def blob(ref, path):
    return git('show', ref + ':' + path)


def inventory(ref):
    result = {}
    for entry in git('ls-tree', '-rz', ref).split(b'\0'):
        if entry:
            metadata, path = entry.split(b'\t', 1)
            result[path.decode()] = metadata.decode()
    return result


def main():
    comparisons = []
    for a, b in ((CONTROL, RUNTIME), (PERSISTENCE, CONFIG)):
        left, right = inventory(a), inventory(b)
        same = sorted(p for p in set(left) & set(right) if left[p] == right[p])
        different = sorted((set(left) | set(right)) - set(same))
        comparisons.append(dict(left=a, right=b, identical=same, changed=different))
    for path in ('Socks5/Settings/AppSettings.swift', 'Socks5/Settings/SettingsStore.swift',
                 'Socks5/Settings/SettingsView.swift', 'Patches/hev-server-startup-stop.patch'):
        assert blob(PERSISTENCE, path) == blob(CONFIG, path), path
    canonical = blob(CONTROL, 'Socks5/Server/ServerController.swift')
    alternate = blob(RUNTIME, 'Socks5/Server/ServerController.swift')
    assert alternate == canonical.replace(b'apply(_ settings:', b'apply(_ configuration:').replace(
        b'desired = running ? settings : nil', b'desired = running ? configuration : nil')
    canonical = blob(CONTROL, 'Socks5/Server/ServerSettings.swift')
    assert blob(RUNTIME, 'Socks5/Server/ServerSettings.swift') == canonical.replace(
        b'/// Validated server options; Codable supports callers without owning any storage.\n', b'')
    before, after = inventory(RELEASE), inventory('HEAD')
    protected = sorted(p for p in set(before) | set(after) if p.startswith(
        ('Socks5/', 'Socks5.xcodeproj/', 'Patches/', 'HevSocks5Server.xcframework/')))
    for path in protected:
        assert before.get(path) == after.get(path), 'Unexpected product change: ' + path
        assert (ROOT / path).read_bytes() == blob(RELEASE, path), path
    for ref in (CONTROL, PERSISTENCE, RUNTIME, CONFIG):
        git('merge-base', '--is-ancestor', ref, 'HEAD')
    print(json.dumps(dict(result='PASS', comparisons=comparisons,
        product_reference=RELEASE, unchanged_product_files=len(protected),
        unchanged_product_sha256={p: hashlib.sha256(blob(RELEASE, p)).hexdigest() for p in protected},
        scope='Exact source comparison and history preservation. No production code adopted or rewritten.'), indent=2))


if __name__ == '__main__':
    main()
