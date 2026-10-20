#!/usr/bin/env python3
"""Transfer one verified macOS product to a fresh Simulator/UI job.

The archive is an input handoff, never UI success. The original product/source
check and all Simulator/UI scripts remain unchanged. No archive path is passed
to extractall; only validated regular files are written into fresh destinations.
"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import release_source as source

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/integrated'
PRODUCT = ROOT / '.build/integrated-product-source'
ARCHIVE = ROOT / 'artifacts/integrated-input/review-input.tar.gz'
PHASES = ('SUCCESS.txt', 'sdk-success.txt', 'built-framework.json', 'package-review.json',
          'Socks5-integrated-unsigned.ipa', 'packaged-Info.plist', 'environment.txt', 'toolchain.txt')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def number(value):
    require(bool(re.fullmatch(r'[1-9][0-9]*', value)), 'Missing or invalid run/attempt/artifact ID')
    return value


def digest(value):
    require(bool(re.fullmatch(r'[0-9a-f]{64}', value)), 'Missing or invalid expected digest')
    return value


def context(job):
    require(os.environ['GITHUB_JOB'] == job, 'Unexpected producer/consumer job')
    require(os.environ['RUNNER_OS'] == 'macOS', 'macOS product/review job required')
    return {'repository': os.environ['GITHUB_REPOSITORY'], 'run_id': number(os.environ['GITHUB_RUN_ID']),
            'attempt': number(os.environ['GITHUB_RUN_ATTEMPT']), 'job': job}


def identity():
    commit = source.check_source()
    require(commit == os.environ['GITHUB_SHA'], 'Checkout is not this workflow source')
    return {'commit': commit, 'tree': source.git('rev-parse', 'HEAD^{tree}')}


def safe_name(name):
    path = PurePosixPath(name)
    require(bool(name) and not path.is_absolute() and path.as_posix() == name
            and '..' not in path.parts and '\\' not in name
            and not any(ord(c) < 32 or ord(c) == 127 for c in name), 'Unsafe archive path')
    return name


def read_file(path):
    require(stat.S_ISREG(path.lstat().st_mode), 'Expected regular input file: ' + str(path))
    mode = stat.S_IMODE(path.stat().st_mode)
    require(mode & ~0o777 == 0 and mode & 0o400, 'Unexpected input permissions')
    return path.read_bytes(), mode


def files_below(folder):
    result = {}
    for path in sorted(folder.rglob('*')):
        require(not path.is_symlink(), 'Linked product input')
        if path.is_dir():
            continue
        result[path.relative_to(folder).as_posix()] = read_file(path)
    return result


def check_payloads(manifest, payloads, expected_source):
    require(manifest['source'] == expected_source, 'Transferred source commit/tree differs')
    product = {name[len('product/'):]: item for name, item in payloads.items() if name.startswith('product/')}
    phases = {name[len('phases/'):]: item for name, item in payloads.items() if name.startswith('phases/')}
    require(set(phases) == set(PHASES), 'Incomplete or extra build/SDK phase evidence')
    require(len(product) + len(phases) == len(payloads), 'Unexpected transfer namespace')
    require(all(phases[name][0] for name in ('SUCCESS.txt', 'sdk-success.txt')), 'Missing successful build/SDK markers')
    built = json.loads(phases['built-framework.json'][0])
    require(built['commit'] == expected_source['commit'] and built['tree'] == expected_source['tree'],
            'Framework belongs to another source')
    framework = {name[len('HevSocks5Server.xcframework/'):]:
                 {'sha256': sha256(raw), 'mode': '100755' if mode & 0o111 else '100644'}
                 for name, (raw, mode) in product.items() if name.startswith('HevSocks5Server.xcframework/')}
    require(bool(framework) and framework == built['framework'], 'Framework bytes/modes differ from archived build')
    tracked = source.git('ls-tree', '-r', '--name-only', 'HEAD').splitlines()
    tracked = {name for name in tracked if not name.startswith('HevSocks5Server.xcframework/')}
    require(set(product) == tracked | {'HevSocks5Server.xcframework/' + name for name in framework},
            'Transferred product file inventory differs from the complete source tree')
    for name in tracked:
        actual, mode = product[name]
        expected, expected_mode = read_file(ROOT / name)
        require(actual == expected and bool(mode & 0o111) == bool(expected_mode & 0o111),
                'Transferred product source bytes/mode differ: ' + name)
    package = json.loads(phases['package-review.json'][0])
    require(package['commit'] == expected_source['commit']
            and package['sha256'] == sha256(phases['Socks5-integrated-unsigned.ipa'][0]),
            'Transferred IPA differs from the successful package review')


def write_archive(path, manifest, payloads):
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), 'Refusing to replace a previous handoff')
    entries = {'MANIFEST.json': ((json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode(), 0o644), **payloads}
    with tarfile.open(path, 'x:gz', format=tarfile.PAX_FORMAT) as archive:
        for name, (raw, mode) in sorted(entries.items()):
            item = tarfile.TarInfo(safe_name(name))
            item.size, item.mode, item.mtime = len(raw), mode, 0
            archive.addfile(item, io.BytesIO(raw))


def pack():
    producer, expected_source = context('verify-macos'), identity()
    source.check_product()
    payloads = {'product/' + name: item for name, item in files_below(PRODUCT).items()}
    payloads.update({'phases/' + name: read_file(OUT / name) for name in PHASES})
    manifest = {'schema': 1, 'producer': producer, 'source': expected_source,
                'files': {name: {'size': len(raw), 'sha256': sha256(raw), 'mode': mode}
                          for name, (raw, mode) in sorted(payloads.items())}}
    check_payloads(manifest, payloads, expected_source)
    write_archive(ARCHIVE, manifest, payloads)
    archive_hash = sha256(ARCHIVE.read_bytes())
    source.check_product()
    receipt = {'status': 'VERIFIED_BUILD_INPUT_EXPORTED', 'manifest': manifest, 'archive_sha256': archive_hash,
               'artifact_name': 'Integrated-review-input-' + producer['run_id'] + '-' + producer['attempt'],
               'scope': 'Successful native/build/SDK/package input; Simulator and UI are separate gates.'}
    (OUT / 'review-handoff-producer.json').write_text(json.dumps(receipt, indent=2) + '\n')
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
        stream.write('archive-sha256=' + archive_hash + '\nproducer-attempt=' + producer['attempt'] + '\n')
    print('Preserved exact product and phase input:', archive_hash)


def read_archive(path, expected_hash):
    raw, _ = read_file(path)
    require(sha256(raw) == digest(expected_hash), 'Handoff archive digest mismatch')
    payloads = {}
    folded = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for item in archive.getmembers():
            name = safe_name(item.name)
            require(item.isfile() and not item.issparse(), 'Archive contains a non-regular file')
            require(name.casefold() not in folded, 'Duplicate or case-colliding archive path')
            folded.add(name.casefold())
            require(item.mode & ~0o777 == 0 and item.mode & 0o400, 'Unsafe archive file mode')
            payloads[name] = (archive.extractfile(item).read(), item.mode)
    require('MANIFEST.json' in payloads, 'Missing transfer manifest')
    manifest = json.loads(payloads.pop('MANIFEST.json')[0])
    require(manifest['schema'] == 1 and type(manifest['schema']) is int, 'Unknown handoff schema')
    require(set(payloads) == set(manifest['files']), 'Archive/manifest inventory differs')
    for name, (raw, mode) in payloads.items():
        require(manifest['files'][name] == {'size': len(raw), 'sha256': sha256(raw), 'mode': mode},
                'Archive/manifest bytes or mode differ: ' + name)
    return manifest, payloads


def unlinked_parent(path):
    require(path.is_relative_to(ROOT), 'Restore destination is outside this checkout')
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'Linked restore destination')
        if parent == ROOT:
            break


def consumer_request():
    consumer, expected_source = context('review-macos'), identity()
    artifact_id = number(os.environ['REVIEW_INPUT_ARTIFACT_ID'])
    artifact_digest = digest(os.environ['REVIEW_INPUT_ARTIFACT_DIGEST'])
    digest(os.environ['REVIEW_INPUT_SHA256'])
    producer_attempt = number(os.environ['REVIEW_PRODUCER_ATTEMPT'])
    require(int(producer_attempt) <= int(consumer['attempt']), 'Producer attempt is from the future')
    return consumer, expected_source, artifact_id, artifact_digest, producer_attempt


def restore(path):
    consumer, expected_source, artifact_id, artifact_digest, producer_attempt = consumer_request()
    manifest, payloads = read_archive(path, os.environ['REVIEW_INPUT_SHA256'])
    require(manifest['producer'] == {**consumer, 'attempt': producer_attempt, 'job': 'verify-macos'},
            'Wrong repository, run, producer job or producer attempt')
    check_payloads(manifest, payloads, expected_source)
    receipt_path = OUT / 'review-handoff-consumer.json'
    unlinked_parent(PRODUCT)
    unlinked_parent(OUT)
    require(not PRODUCT.exists() and not receipt_path.exists() and not receipt_path.is_symlink(),
            'Review requires a fresh product workspace')
    require(all(not (OUT / name).exists() and not (OUT / name).is_symlink() for name in PHASES),
            'Refusing to overwrite pre-existing phase evidence')
    PRODUCT.parent.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='integrated-handoff-', dir=PRODUCT.parent) as temporary:
        staging = Path(temporary)
        for name, (raw, mode) in payloads.items():
            destination = staging / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(raw)
            destination.chmod(mode)
        # All content checks finish before either final destination is populated.
        shutil.move(str(staging / 'product'), PRODUCT)
        for name in PHASES:
            shutil.move(str(staging / 'phases' / name), OUT / name)
    for name, (raw, mode) in payloads.items():
        destination = PRODUCT / name[len('product/'):] if name.startswith('product/') else OUT / name[len('phases/'):]
        require(read_file(destination) == (raw, mode), 'Restored bytes/mode mismatch')
    source.check_product()
    receipt = {'status': 'VERIFIED_BUILD_INPUT_RESTORED', 'manifest': manifest, 'consumer': consumer,
               'input_artifact_id': artifact_id, 'input_artifact_digest': artifact_digest,
               'archive_sha256': os.environ['REVIEW_INPUT_SHA256'],
               'scope': 'Exact producer input restored; this receipt does not establish Simulator or UI success.'}
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print('Restored exact producer input from artifact', artifact_id, 'producer attempt', producer_attempt,
          'consumer attempt', consumer['attempt'])


if __name__ == '__main__':
    require(__debug__, 'Assertions must be enabled')
    if sys.argv[1:] == ['pack']:
        pack()
    elif sys.argv[1:] == ['check-request']:
        consumer_request()
        print('Producer artifact ID, digests, source and attempt are valid for this review request')
    elif len(sys.argv) == 3 and sys.argv[1] == 'restore':
        restore(Path(sys.argv[2]))
    else:
        raise SystemExit('Usage: review_handoff.py pack | check-request | restore ARCHIVE')
