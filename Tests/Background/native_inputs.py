#!/usr/bin/env python3
"""Record and verify the prepared native inputs consumed by Background audits."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULE = b'module HevSocks5Server { header "hev-main.h" export * }\n'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def snapshot(folder):
    require(folder.is_dir() and not folder.is_symlink(), 'Missing or linked native framework')
    result = {}
    for path in sorted(folder.rglob('*')):
        require(not path.is_symlink(), 'Linked native framework input: ' + str(path))
        if path.is_dir():
            continue
        require(path.is_file(), 'Non-file native framework input: ' + str(path))
        result[path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    require(bool(result), 'Empty native framework')
    return result


def locations():
    name = json.loads((ROOT / 'Build/features.json').read_bytes())['name']
    require(name == 'background', 'This receipt belongs to the standalone Background composition')
    return ROOT / 'artifacts' / name, ROOT / '.build/core/HevSocks5Server.xcframework'


def head():
    return subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()


def record(core, commit):
    output, framework = locations()
    require(core == ROOT / '.build/core' and commit == head(), 'Native record source identity changed')
    files = snapshot(framework)
    raw = (core / 'src/hev-main.h').read_bytes()
    for name in files:
        if name.endswith('/Headers/hev-main.h'):
            require((framework / name).read_bytes() == raw, 'Built framework contains a stale header')
    require('ios-arm64/Headers/hev-main.h' in files and
            'ios-arm64_x86_64-simulator/Headers/hev-main.h' in files, 'Missing iOS framework headers')
    headers = output / 'compiled-headers'
    require(not headers.is_symlink(), 'Linked prepared headers directory')
    headers.mkdir(parents=True, exist_ok=True)
    (headers / 'hev-main.h').write_bytes(raw)
    (headers / 'module.modulemap').write_bytes(MODULE)
    (headers / 'source-commit.txt').write_text(commit + '\n')
    (headers / 'SHA256SUMS.txt').write_text(''.join(
        hashlib.sha256((headers / name).read_bytes()).hexdigest() + '  ' + name + '\n'
        for name in ('hev-main.h', 'module.modulemap')))
    (output / 'built-framework.json').write_text(json.dumps(
        {'source_commit': commit, 'files': files}, indent=2) + '\n')


def verify():
    output, framework = locations()
    commit = head()
    require((output / 'SUCCESS.txt').is_file(), 'Prepared native build has not completed successfully')
    require((output / 'tested-commit.txt').read_text().strip() == commit, 'Native build is from another commit')
    headers = output / 'compiled-headers'
    require(headers.is_dir() and not headers.is_symlink(), 'Missing or linked prepared headers directory')
    for name in ('hev-main.h', 'module.modulemap', 'source-commit.txt', 'SHA256SUMS.txt'):
        require((headers / name).is_file() and not (headers / name).is_symlink(),
                'Missing or linked prepared header input: ' + name)
    require((headers / 'source-commit.txt').read_text().strip() == commit, 'Prepared headers are from another commit')
    expected = ''.join(hashlib.sha256((headers / name).read_bytes()).hexdigest() + '  ' + name + '\n'
                       for name in ('hev-main.h', 'module.modulemap'))
    require((headers / 'SHA256SUMS.txt').read_text() == expected, 'Prepared header/module checksum mismatch')
    require((headers / 'module.modulemap').read_bytes() == MODULE, 'Unexpected prepared module map')
    receipt = json.loads((output / 'built-framework.json').read_bytes())
    require(set(receipt) == {'source_commit', 'files'} and receipt['source_commit'] == commit,
            'Native framework receipt has the wrong source identity')
    require(receipt['files'] == snapshot(framework), 'Prepared framework files differ from the built receipt')
    raw = (headers / 'hev-main.h').read_bytes()
    for name in receipt['files']:
        if name.endswith('/Headers/hev-main.h'):
            require((framework / name).read_bytes() == raw, 'SDK and framework headers disagree')
    return framework


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    if len(sys.argv) == 4 and sys.argv[1] == 'record':
        record(Path(sys.argv[2]), sys.argv[3])
    elif sys.argv[1:] == ['verify']:
        verify()
    elif len(sys.argv) == 3 and sys.argv[1] == 'copy':
        framework = verify()
        destination = Path(sys.argv[2])
        require(destination.parent.is_dir() and not destination.is_symlink(), 'Invalid temporary framework destination')
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(framework, destination)
        require(snapshot(destination) == snapshot(framework), 'Native framework copy changed')
    else:
        raise SystemExit('Usage: native_inputs.py record CORE COMMIT | verify | copy DESTINATION')
    print('PASS: prepared native input identity and exact file hashes')


if __name__ == '__main__':
    main()
