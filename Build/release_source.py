#!/usr/bin/env python3
"""Bind release-only generated inputs to a clean tracked revision.

These checks are provenance boundaries, not protection against an adversary able
to rewrite both artifacts and attestations. They never alter production source.
"""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/integrated'
PRODUCT = ROOT / '.build/integrated-product-source'


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def check_source():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    git('diff', '--exit-code', 'HEAD', '--')
    git('diff', '--cached', '--exit-code', 'HEAD', '--')
    return git('rev-parse', 'HEAD')


def inventory(folder):
    files = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Unexpected generated symlink: ' + str(path))
        if path.is_file():
            files[path.relative_to(folder).as_posix()] = {
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'mode': '100755' if path.stat().st_mode & 0o111 else '100644'}
    if not files:
        raise RuntimeError('Missing generated input: ' + str(folder))
    return files


def record_product():
    commit = check_source()
    value = {'commit': commit, 'tree': git('rev-parse', 'HEAD^{tree}'),
             'framework': inventory(PRODUCT / 'HevSocks5Server.xcframework')}
    (OUT / 'built-framework.json').write_text(json.dumps(value, indent=2) + '\n')


def check_product():
    commit = check_source()
    for name in ('SUCCESS.txt', 'sdk-success.txt'):
        if not (OUT / name).is_file() or not (OUT / name).read_bytes():
            raise RuntimeError('Missing completed phase: ' + name)
    value = json.loads((OUT / 'built-framework.json').read_bytes())
    if value['commit'] != commit or value['tree'] != git('rev-parse', 'HEAD^{tree}'):
        raise RuntimeError('Generated framework belongs to a different source revision')
    if inventory(PRODUCT / 'HevSocks5Server.xcframework') != value['framework']:
        raise RuntimeError('Generated framework changed after the archive build')
    for name in git('ls-tree', '-r', '--name-only', 'HEAD').splitlines():
        if name.startswith('HevSocks5Server.xcframework/'):
            continue
        source, copied = ROOT / name, PRODUCT / name
        if copied.is_symlink() or copied.read_bytes() != source.read_bytes():
            raise RuntimeError('Product source differs: ' + name)
        if bool(copied.stat().st_mode & 0o111) != bool(source.stat().st_mode & 0o111):
            raise RuntimeError('Product source mode differs: ' + name)
    return value


def check_ipa_files(ipa, app):
    if app.is_symlink() or not app.is_dir():
        raise RuntimeError('Missing or linked archive app: ' + str(app))
    prefix = 'Payload/Socks5.app/'
    expected = {}
    directories = {'Payload/': None, prefix: stat.S_IMODE(app.stat().st_mode)}
    for path in app.rglob('*'):
        name = prefix + path.relative_to(app).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            directories[name + '/'] = stat.S_IMODE(mode)
        elif stat.S_ISREG(mode):
            expected[name] = path
        else:
            raise RuntimeError('Unexpected archive file type: ' + name)
    if not expected:
        raise RuntimeError('Empty archive app')
    with zipfile.ZipFile(ipa) as archive:
        if archive.testzip() is not None or len(archive.namelist()) != len(set(archive.namelist())):
            raise RuntimeError('Corrupt IPA or duplicate ZIP entries')
        for entry in archive.infolist():
            # This pipeline creates Unix ZIPs. Bytes alone do not preserve an
            # executable's permissions or distinguish a regular file from a link.
            mode = entry.external_attr >> 16
            if entry.create_system != 3:
                raise RuntimeError('Missing Unix IPA metadata: ' + entry.filename)
            if entry.is_dir():
                if (entry.filename not in directories or not stat.S_ISDIR(mode)
                        or entry.file_size != 0 or mode & 0o500 != 0o500
                        or (directories[entry.filename] is not None
                            and stat.S_IMODE(mode) != directories[entry.filename])):
                    raise RuntimeError('Unexpected IPA directory: ' + entry.filename)
            elif not stat.S_ISREG(mode):
                raise RuntimeError('Unexpected IPA file type: ' + entry.filename)
        actual = {i.filename for i in archive.infolist() if not i.is_dir()}
        if actual != set(expected):
            raise RuntimeError('IPA file inventory differs from the verified archive')
        for name, path in expected.items():
            if stat.S_IMODE(archive.getinfo(name).external_attr >> 16) != stat.S_IMODE(path.stat().st_mode):
                raise RuntimeError('IPA permissions differ: ' + name)
            if archive.read(name) != path.read_bytes():
                raise RuntimeError('IPA resource differs: ' + name)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('record', 'check', 'source'):
        raise SystemExit('Usage: release_source.py record|check|source')
    {'record': record_product, 'check': check_product, 'source': check_source}[sys.argv[1]]()
