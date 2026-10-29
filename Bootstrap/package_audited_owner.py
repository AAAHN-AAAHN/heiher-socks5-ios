#!/usr/bin/env python3
"""Produce Apple products from an already completed exact-source UDP/Statistics audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile

HELPER = Path(__file__).resolve().parents[1]
REPOSITORY = 'AAAHN-AAAHN/heiher-socks5-ios'
AUDITS = {
    'udp': {
        'composition': 'udp-compat', 'directory': 'udp-final-audit',
        'success': 'Scoped UDP repair and dynamic-buffer audit passed. Read summary.json and buffer evidence for limits and observations. No IPA was built.\n',
        'sdk_logs': ('ios-arm64-syntax.log',),
    },
    'statistics': {
        'composition': 'traffic-statistics', 'directory': 'statistics-final-audit',
        'success': 'PASS: peer socket I/O native audit and applicable type checks.\nUDP contents preserved. No IPA or XCFramework build.\n',
        'sdk_logs': ('ios-c-syntax.log', 'ios-swift-typecheck.log', 'project.log'),
    },
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root, command, log=None, timeout=900, append=False):
    command = [str(item) for item in command]
    if log is None:
        return subprocess.check_output(command, cwd=root, stderr=subprocess.STDOUT,
                                       text=True, timeout=timeout)
    with log.open('a' if append else 'w') as stream:
        subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=timeout)


def check(root, *args, log=None):
    return run(root, [sys.executable, 'Build/check.py', *args], log)


def inventory(directory):
    require(directory.is_dir() and not directory.is_symlink(), 'Missing or linked input/output directory')
    result = {}
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'Linked input/output: ' + str(path))
        if path.is_dir():
            continue
        require(path.is_file(), 'Non-regular input/output: ' + str(path))
        result[str(path.relative_to(directory))] = {
            'bytes': path.stat().st_size, 'sha256': digest(path),
            'mode': stat.S_IMODE(path.stat().st_mode),
        }
    return result


def clean_source(root, sha):
    require(git(root, 'rev-parse', 'HEAD') == sha, 'Candidate HEAD differs from the frozen helper manifest')
    # Reject untracked/ignored input injection before running any candidate Python.
    others = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--others', '-z'])
    require(all(not name or name.startswith((b'artifacts/', b'.build/'))
                for name in others.split(b'\0')), 'Untracked application/build input')
    git(root, 'diff', '--exit-code', sha, '--')
    git(root, 'diff', '--cached', '--exit-code', sha, '--')
    # The owner checker compares raw files and modes, including assume-unchanged files.
    check(root, 'worktree', sha)


def audit_log(path, candidate, command=None):
    text = path.read_text()
    if candidate == 'statistics':
        return text
    prefix, separator, payload = text.partition('\n')
    require(separator and json.loads(prefix) == command, 'Unexpected UDP audit command prefix: ' + path.name)
    return payload


def preflight(candidate, root):
    require(__debug__, 'Assertions must be enabled')
    require(root.is_dir() and not root.is_symlink(), 'Candidate root must be a real directory')
    root = root.resolve()
    require(Path(git(root, 'rev-parse', '--show-toplevel')).resolve() == root,
            'Candidate root must be the worktree root')
    manifest_path = HELPER / 'Bootstrap/candidates.json'
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Unexpected repository')
        helper_sha = os.environ['GITHUB_SHA']
        require(git(HELPER, 'rev-parse', 'HEAD') == helper_sha, 'Helper checkout differs from workflow SHA')
        for name in ('Bootstrap/candidates.json', 'Bootstrap/package_audited_owner.py'):
            committed = subprocess.check_output(['git', '-C', str(HELPER), 'show', helper_sha + ':' + name])
            require((HELPER / name).read_bytes() == committed, 'Changed helper packaging input: ' + name)
    manifest = json.loads(manifest_path.read_bytes())
    matches = [entry for entry in manifest['candidates'] if entry.get('name') == candidate]
    require(len(matches) == 1, 'Owner must be an explicit frozen candidate')
    sha = matches[0]['sha']
    require(re.fullmatch('[0-9a-f]{40}', sha) is not None, 'Invalid candidate SHA')
    matrix = [row for row in manifest['matrix']
              if row.get('name') == candidate and row.get('os') == 'xcode-27']
    require(len(matrix) == 1 and matrix[0]['sha'] == sha, 'Missing exact macOS candidate declaration')
    clean_source(root, sha)
    definition = AUDITS[candidate]
    config = json.loads((root / 'Build/features.json').read_bytes())
    require(config['name'] == definition['composition'], 'Owner composition differs')
    require(set(config['features']) == ({'udp'} if candidate == 'udp' else {'udp', 'statistics'}),
            'Unexpected owner feature scope')
    audit = root / 'artifacts' / definition['directory']
    for path in (root / 'artifacts', root / '.build', audit):
        require(not path.is_symlink(), 'Linked audit/build path')
    for name in ('SUCCESS.txt', 'tested-commit.txt', 'source.zip', 'archive-identity.log',
                 'input-identity.log', 'input-worktree.log', 'input-index.log',
                 'final-identity.log', 'final-worktree.log', 'final-index.log', 'reverse.log',
                 *definition['sdk_logs']):
        require((audit / name).is_file() and not (audit / name).is_symlink(),
                'Missing completed Apple owner audit receipt: ' + name)
    require((audit / 'SUCCESS.txt').read_text() == definition['success'], 'Owner audit did not complete')
    require((audit / 'tested-commit.txt').read_text().strip() == sha, 'Owner audit tested a different SHA')
    python, original_root = '', root
    if candidate == 'udp':
        command = json.loads((audit / 'archive-identity.log').read_text().splitlines()[0])
        require(isinstance(command, list) and len(command) == 5 and all(isinstance(arg, str) for arg in command),
                'Malformed UDP archive command receipt')
        python, source = command[0], Path(command[3])
        require(Path(python).is_absolute() and re.fullmatch(r'python(?:3(?:\.\d+)?)?', Path(python).name),
                'Unexpected UDP audit interpreter')
        require(source.is_absolute() and '..' not in source.parts
                and source.parts[-3:] == ('artifacts', 'udp-final-audit', 'source.zip'),
                'Unexpected UDP audit source archive path')
        original_root = source.parents[2]
    archive_command = [python, 'Build/check.py', 'archive',
                       str(original_root / 'artifacts' / definition['directory'] / 'source.zip'), sha]
    require(audit_log(audit / 'archive-identity.log', candidate, archive_command)
            == 'PASS: source archive inventory, Git modes and raw bytes\n', 'Missing audit archive identity')
    for phase in ('input', 'final'):
        require(audit_log(audit / (phase + '-identity.log'), candidate,
                          [python, 'Build/check.py', 'worktree', sha])
                == 'PASS: fixed application HEAD, index, raw bytes and Git modes\n',
                'Missing audit source identity: ' + phase)
        require(audit_log(audit / (phase + '-worktree.log'), candidate,
                          ['git', 'diff', '--exit-code', 'HEAD', '--']) == ''
                and audit_log(audit / (phase + '-index.log'), candidate,
                              ['git', 'diff', '--cached', '--exit-code', 'HEAD', '--']) == '',
                'Owner audit source changes: ' + phase)
    require(audit_log(audit / 'reverse.log', candidate,
                      [python, 'Build/check.py', 'reverse',
                       str(original_root / '.build' / definition['directory'] / 'core')])
            == 'PASS: reverse patches restore exact upstream source\n', 'Missing exact native restoration receipt')
    with zipfile.ZipFile(audit / 'source.zip') as source:
        require(source.comment.decode('ascii') == sha, 'Owner audit source ZIP names a different commit')
    check(root, 'archive', audit / 'source.zip', sha)
    check(root, 'baseline')
    check(root, 'composition')
    return root, sha, config, audit, inventory(audit)


def uuid_map(text):
    rows = re.findall(r'UUID:\s+([0-9A-Fa-f-]{36})\s+\(([^)]+)\)', text)
    require(rows and len({arch for _, arch in rows}) == len(rows), 'Missing or duplicate Mach-O UUID')
    return {arch: value.upper() for value, arch in rows}


def unsigned_macho(path):
    data = path.read_bytes()
    endian = {b'\xcf\xfa\xed\xfe': '<', b'\xfe\xed\xfa\xcf': '>'}.get(data[:4])
    require(endian is not None and len(data) >= 32, 'Expected a thin 64-bit iOS application executable')
    count, size = struct.unpack_from(endian + 'II', data, 16)
    end, offset = 32 + size, 32
    require(end <= len(data), 'Truncated Mach-O load commands')
    for _ in range(count):
        require(offset + 8 <= end, 'Truncated Mach-O load command')
        command, length = struct.unpack_from(endian + 'II', data, offset)
        require(length >= 8 and offset + length <= end, 'Invalid Mach-O load command length')
        require(command != 0x1d, 'Application contains an LC_CODE_SIGNATURE')
        offset += length
    require(offset == end, 'Unexpected Mach-O command boundary')


def produce(candidate, root, sha, config, audit, audit_before):
    name = config['name']
    out, core = root / 'artifacts' / name, root / '.build/core'
    archive = root / '.build' / (name + '.xcarchive')
    package = root / '.build' / ('package-' + name)
    for path in (out, core, archive, package):
        require(not path.is_symlink(), 'Linked product path')
    require(not core.exists() and not archive.exists() and not package.exists(),
            'Product generation requires fresh .build/core, archive and package directories')
    if out.exists():
        inventory(out)  # Do not follow linked stale outputs.
    out.mkdir(parents=True, exist_ok=True)
    (root / '.build').mkdir(exist_ok=True)
    for filename in ('SUCCESS.txt', 'audited-product.json', 'SHA256SUMS.txt', 'source.zip',
                     'history.bundle', 'tested-commit.txt', 'features.json', 'build-info.txt',
                     'Socks5-' + name + '-source.zip', 'Socks5-' + name + '-unsigned.ipa', 'Socks5-dSYMs.zip'):
        (out / filename).unlink(missing_ok=True)
    receipt = {
        'result': 'FAIL', 'owner': candidate, 'composition': name, 'source_commit': sha,
        'source_tree': git(root, 'rev-parse', sha + '^{tree}'),
        'helper_commit': git(HELPER, 'rev-parse', 'HEAD'),
        'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'audit_directory': str(audit.relative_to(root)), 'audit_input_files': audit_before,
        'native_source_pins': config['sources'],
        'patches': [dict(item, sha256=digest(root / 'Patches' / item['file'])) for item in config['patches']],
        'scope': 'Apple product generation after the completed exact-source owner audit; no replacement or weakening of owner audit gates.',
    }
    product = None
    applied = False
    try:
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
                stream.write('composition=' + name + '\nartifact_path=artifacts/' + name + '\n')
        shutil.copyfile(audit / 'source.zip', out / 'source.zip')
        shutil.copyfile(audit / 'tested-commit.txt', out / 'tested-commit.txt')
        shutil.copyfile(root / 'Build/features.json', out / 'features.json')
        check(root, 'archive', out / 'source.zip', sha, log=out / 'archive-audit.log')
        run(root, ['git', 'bundle', 'create', out / 'history.bundle', 'HEAD'], out / 'history-bundle.log')
        run(root, ['git', 'clone', '--no-checkout', 'https://github.com/heiher/hev-socks5-server.git', core], out / 'clone.log')
        run(core, ['git', 'checkout', '--detach', config['sources']['.']], out / 'checkout.log')
        run(core, ['git', 'submodule', 'update', '--init', '--recursive'], out / 'submodules.log')
        check(root, 'checkout', core, log=out / 'source-checkout.log')
        check(root, 'apply', core, log=out / 'source-apply.log')
        applied = True
        formatter = shutil.which('clang-format-18') or shutil.which('clang-format')
        require(formatter and 'version 18.' in run(root, [formatter, '--version']), 'clang-format 18 is required')
        check(root, 'format', core, formatter, log=out / 'source-format.log')
        check(root, 'composition', log=out / 'composition.log')
        (out / 'build-info.txt').write_text(sha + '\n' + git(core, 'rev-parse', 'HEAD') + '\n'
                                          + git(core, 'submodule', 'status', '--recursive') + '\n')
        environment = run(root, ['xcodebuild', '-version'])
        sdk = run(root, ['xcrun', '--sdk', 'iphoneos', '--show-sdk-version']).strip()
        require(sdk.startswith('27.'), 'The audited Apple SDK must remain iOS 27')
        environment += '\niphoneos SDK: ' + sdk + '\n' + run(root, ['xcrun', 'swiftc', '--version'])
        (out / 'environment.txt').write_text(environment)
        # These are the Apple generation/archive commands from the owner's unchanged Build/build.sh.
        run(root, ['make', '-C', core, 'clean'], out / 'native-clean.log')
        run(core, ['./build-apple.sh'], out / 'core-apple.log', timeout=1800)
        framework = core / 'HevSocks5Server.xcframework'
        framework_files = inventory(framework)
        require(framework_files, 'Generated XCFramework is empty')
        product = Path(tempfile.mkdtemp(prefix=name + '-product-source.', dir=root / '.build'))
        run(root, ['unzip', '-q', out / 'source.zip', '-d', product], out / 'product-source.log')
        shutil.rmtree(product / 'HevSocks5Server.xcframework')
        shutil.copytree(framework, product / 'HevSocks5Server.xcframework')
        run(root, ['xcodebuild', 'archive', '-project', product / 'Socks5.xcodeproj', '-scheme', 'Socks5',
                   '-configuration', 'Release', '-sdk', 'iphoneos', '-destination', 'generic/platform=iOS',
                   '-archivePath', archive, "CODE_SIGN_IDENTITY=", 'CODE_SIGNING_REQUIRED=NO',
                   'CODE_SIGNING_ALLOWED=NO', 'MARKETING_VERSION=3.0.0', 'CURRENT_PROJECT_VERSION=1'],
            out / 'app-build.log', timeout=1800)
        app = archive / 'Products/Applications/Socks5.app'
        executable = app / 'Socks5'
        dwarf = archive / 'dSYMs/Socks5.app.dSYM/Contents/Resources/DWARF/Socks5'
        run(root, ['xcrun', 'lipo', executable, '-verify_arch', 'arm64'], out / 'arm64.log')
        check(root, 'package', app, log=out / 'package.log')
        unsigned_macho(executable)
        require(not (app / '_CodeSignature').exists(), 'Unexpected application signature directory')
        app_uuids = run(root, ['xcrun', 'dwarfdump', '--uuid', executable])
        dwarf_uuids = run(root, ['xcrun', 'dwarfdump', '--uuid', dwarf])
        (out / 'app-uuids.txt').write_text(app_uuids)
        (out / 'dsym-uuids.txt').write_text(dwarf_uuids)
        uuids = uuid_map(app_uuids)
        require('arm64' in uuids and uuids == uuid_map(dwarf_uuids), 'Application/dSYM UUID mismatch')
        (package / 'Payload').mkdir(parents=True)
        run(root, ['ditto', app, package / 'Payload/Socks5.app'], out / 'package-copy.log')
        ipa = out / ('Socks5-' + name + '-unsigned.ipa')
        dsym = out / 'Socks5-dSYMs.zip'
        run(package, ['zip', '-qr', ipa, 'Payload'], out / 'ipa-zip.log')
        run(root, ['unzip', '-t', ipa], out / 'package.log', append=True)
        run(root, ['ditto', '-c', '-k', '--keepParent', archive / 'dSYMs', dsym], out / 'dsym-zip.log')
        source = out / ('Socks5-' + name + '-source.zip')
        shutil.copyfile(out / 'source.zip', source)
        shutil.rmtree(product)
        product = None
        check(root, 'reverse', core, log=out / 'source-reverse.log')
        applied = False
        clean_source(root, sha)
        require(inventory(audit) == audit_before, 'Original owner audit outputs changed during packaging')
        require(inventory(framework) == framework_files, 'Generated framework bytes changed')
        products = {path.name: {'bytes': path.stat().st_size, 'sha256': digest(path)}
                    for path in (ipa, dsym, source, out / 'source.zip', out / 'history.bundle')}
        (out / 'SHA256SUMS.txt').write_text(''.join(value['sha256'] + '  ' + filename + '\n'
                                                 for filename, value in sorted(products.items())))
        receipt.update(result='PASS', apple_execution='completed', products=products,
                       app_dsym_uuids=uuids, unsigned=True, source_unchanged=True, audit_outputs_unchanged=True,
                       framework_directory=str(framework.relative_to(root)), framework_files=framework_files,
                       source_zip_scope='Exact Git source archive; its baseline framework is not the generated XCFramework recorded separately.')
        (out / 'SUCCESS.txt').write_text('PASS: exact audited ' + candidate + ' Apple products generated; original owner audit outputs preserved.\n')
    except Exception as error:
        receipt['error'] = str(error)
        raise
    finally:
        if product is not None:
            shutil.rmtree(product)
        if applied:
            try:
                check(root, 'reverse', core, log=out / 'failure-native-restore.log')
            except Exception as error:
                receipt['native_restore_error'] = str(error)
        (out / 'audited-product.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'result': receipt['result'], 'owner': candidate, 'source_commit': sha,
                      'receipt': str((out / 'audited-product.json').relative_to(root))}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True, choices=tuple(AUDITS))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true', help='Validate completed audit inputs without creating products')
    options = parser.parse_args()
    values = preflight(options.candidate, options.root)
    if options.check_only:
        print(json.dumps({'result': 'PASS', 'scope': 'Read-only audited input validation',
                          'candidate': options.candidate, 'source_commit': values[1],
                          'apple_execution': 'not_run; actual Apple generation still requires macOS CI'}))
        return
    require(sys.platform == 'darwin', 'Apple product generation requires macOS CI; --check-only performs input checks only')
    produce(options.candidate, *values)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.output:
            print(error.output, file=sys.stderr)
        raise
