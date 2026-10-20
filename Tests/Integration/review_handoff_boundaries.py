#!/usr/bin/env python3
"""Portable handoff fault injection using a real temporary Git checkout.

These are provenance/archive fixtures, not an Apple build, IPA or UI execution.
Every rejected input must leave the destination and pass receipt uncreated.
"""
from contextlib import ExitStack
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Build'))
import review_handoff as handoff


class HandoffBoundaries(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='review-handoff-fixture-')))
        self.product = self.root / '.build/integrated-product-source'
        self.out = self.root / 'artifacts/integrated'
        self.archive = self.root / 'artifacts/integrated-input/review-input.tar.gz'
        self.output = self.root / '.build/github-output'
        self.stack.enter_context(mock.patch.multiple(handoff, ROOT=self.root, PRODUCT=self.product,
                                                     OUT=self.out, ARCHIVE=self.archive))
        self.stack.enter_context(mock.patch.multiple(handoff.source, ROOT=self.root, PRODUCT=self.product, OUT=self.out))
        self.git('init', '-q')
        self.put(self.root / '.gitignore', b'.build/\nartifacts/\n')
        self.put(self.root / 'Socks5/App.swift', b'// fixture source, not a product\n')
        self.put(self.root / 'Tools/check.sh', b'#!/bin/sh\nexit 0\n', 0o755)
        self.put(self.root / 'HevSocks5Server.xcframework/baseline.a', b'original baseline\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Handoff Fixture', '-c', 'user.email=handoff-fixture@example.invalid',
                 'commit', '-qm', 'Input fixture')
        self.commit = self.git('rev-parse', 'HEAD')
        self.tree = self.git('rev-parse', 'HEAD^{tree}')
        for name in self.git('ls-files').splitlines():
            if not name.startswith('HevSocks5Server.xcframework/'):
                self.put(self.product / name, (self.root / name).read_bytes(), (self.root / name).stat().st_mode & 0o777)
        self.put(self.product / 'HevSocks5Server.xcframework/ios-arm64/library.a', b'generated fixture library\n')
        self.put(self.product / 'HevSocks5Server.xcframework/ios-arm64/tool', b'fixture executable\n', 0o750)
        self.out.mkdir(parents=True)
        for name in handoff.PHASES:
            self.put(self.out / name, b'fixture-only phase evidence\n', 0o640)
        self.put(self.out / 'SUCCESS.txt', b'PASS fixture build\n')
        self.put(self.out / 'sdk-success.txt', b'PASS fixture SDK\n')
        self.put(self.out / 'Socks5-integrated-unsigned.ipa', b'not an actual IPA; archive fixture\n')
        self.put(self.out / 'package-review.json', json.dumps({
            'commit': self.commit, 'sha256': hashlib.sha256((self.out / 'Socks5-integrated-unsigned.ipa').read_bytes()).hexdigest()
        }).encode())
        self.stack.enter_context(mock.patch.dict(os.environ, {
            'GITHUB_REPOSITORY': 'fixture/project', 'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_JOB': 'verify-macos', 'RUNNER_OS': 'macOS', 'GITHUB_SHA': self.commit,
            'GITHUB_OUTPUT': str(self.output), 'REVIEW_INPUT_ARTIFACT_ID': '67890',
            'REVIEW_INPUT_ARTIFACT_DIGEST': 'd' * 64, 'REVIEW_PRODUCER_ATTEMPT': '1',
        }))
        handoff.source.record_product()
        handoff.pack()
        self.original_hash = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        os.environ['REVIEW_INPUT_SHA256'] = self.original_hash
        with tarfile.open(self.archive, 'r:gz') as archive:
            self.entries = [(copy.copy(item), archive.extractfile(item).read()) for item in archive.getmembers()]
        self.manifest = json.loads(next(raw for item, raw in self.entries if item.name == 'MANIFEST.json'))
        self.expected = {item.name: (raw, item.mode) for item, raw in self.entries if item.name != 'MANIFEST.json'}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT, text=True).strip()

    def put(self, path, raw, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)

    def consumer(self, attempt='1'):
        shutil.rmtree(self.product)
        for name in handoff.PHASES:
            (self.out / name).unlink()
        os.environ.update(GITHUB_JOB='review-macos', GITHUB_RUN_ATTEMPT=attempt)

    def rewrite(self, change):
        manifest = copy.deepcopy(self.manifest)
        entries = [(copy.copy(item), raw) for item, raw in self.entries if item.name != 'MANIFEST.json']
        change(manifest, entries)
        raw_manifest = json.dumps(manifest).encode()
        header = tarfile.TarInfo('MANIFEST.json')
        header.mode, header.size = 0o644, len(raw_manifest)
        path = self.root / '.build/altered-input.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for item, raw in [(header, raw_manifest), *entries]:
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))
        os.environ['REVIEW_INPUT_SHA256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def reject(self, message, path=None):
        with self.assertRaisesRegex(RuntimeError, message):
            handoff.restore(path or self.archive)
        self.assertFalse(self.product.exists())
        self.assertFalse((self.out / 'review-handoff-consumer.json').exists())
        self.assertEqual(self.git('diff', '--exit-code', 'HEAD', '--'), '')
        self.assertEqual(self.git('diff', '--cached', '--exit-code', 'HEAD', '--'), '')

    def check_roundtrip(self, attempt):
        self.consumer(attempt)
        handoff.restore(self.archive)
        for name, (raw, mode) in self.expected.items():
            path = self.product / name[len('product/'):] if name.startswith('product/') else self.out / name[len('phases/'):]
            self.assertEqual(path.read_bytes(), raw, name)
            self.assertEqual(path.stat().st_mode & 0o777, mode, name)
        receipt = json.loads((self.out / 'review-handoff-consumer.json').read_text())
        self.assertEqual(receipt['consumer']['attempt'], attempt)
        self.assertEqual(receipt['manifest']['producer']['attempt'], '1')
        self.assertEqual(receipt['input_artifact_id'], '67890')
        self.assertEqual(receipt['archive_sha256'], self.original_hash)
        self.assertEqual(receipt['manifest']['source'], {'commit': self.commit, 'tree': self.tree})
        self.assertIn('does not establish Simulator or UI success', receipt['scope'])
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_exact_bytes_and_permissions_roundtrip(self):
        self.check_roundtrip('1')

    def test_consumer_rerun_keeps_original_producer_attempt(self):
        self.check_roundtrip('2')

    def test_archive_digest_mismatch_before_restore(self):
        self.consumer()
        os.environ['REVIEW_INPUT_SHA256'] = '0' * 64
        self.reject('archive digest mismatch')

    def test_wrong_run_repository_job_or_attempt_rejected(self):
        self.consumer('2')
        for field, value in [('repository', 'another/repo'), ('run_id', '999'), ('job', 'unrelated-job'), ('attempt', '2')]:
            with self.subTest(field=field):
                path = self.rewrite(lambda manifest, entries: manifest['producer'].update({field: value}))
                self.reject('Wrong repository, run, producer job or producer attempt', path)

    def test_future_producer_and_missing_output_rejected(self):
        self.consumer()
        os.environ['REVIEW_PRODUCER_ATTEMPT'] = '2'
        self.reject('Producer attempt is from the future')
        os.environ['REVIEW_PRODUCER_ATTEMPT'] = '1'
        for variable in ['REVIEW_INPUT_ARTIFACT_ID', 'REVIEW_INPUT_ARTIFACT_DIGEST', 'REVIEW_INPUT_SHA256']:
            with self.subTest(variable=variable), mock.patch.dict(os.environ, {variable: ''}):
                self.reject('Missing or invalid')

    def test_wrong_source_commit_and_tree_rejected(self):
        self.consumer()
        for field in ['commit', 'tree']:
            with self.subTest(field=field):
                path = self.rewrite(lambda manifest, entries: manifest['source'].update({field: 'f' * 40}))
                self.reject('Transferred source commit/tree differs', path)

    def change_file(self, manifest, entries, name, raw=None, mode=None, update_manifest=True):
        position = next(i for i, (item, _) in enumerate(entries) if item.name == name)
        item, old = entries[position]
        raw = old if raw is None else raw
        item.mode = item.mode if mode is None else mode
        entries[position] = item, raw
        if update_manifest:
            manifest['files'][name] = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'mode': item.mode}

    def test_source_bytes_and_execute_bit_rejected_despite_consistent_manifest(self):
        self.consumer()
        for raw, mode in [(b'changed source\n', None), (None, 0o644)]:
            with self.subTest(raw=raw, mode=mode):
                path = self.rewrite(lambda manifest, entries: self.change_file(
                    manifest, entries, 'product/Tools/check.sh', raw=raw, mode=mode))
                self.reject('Transferred product source bytes/mode differ', path)

    def test_framework_bytes_and_execute_bit_rejected_despite_consistent_manifest(self):
        self.consumer()
        for raw, mode in [(b'wrong native library\n', None), (None, 0o644)]:
            with self.subTest(raw=raw, mode=mode):
                path = self.rewrite(lambda manifest, entries: self.change_file(
                    manifest, entries, 'product/HevSocks5Server.xcframework/ios-arm64/tool', raw=raw, mode=mode))
                self.reject('Framework bytes/modes differ from archived build', path)

    def test_unreviewed_ipa_rejected_despite_consistent_manifest(self):
        self.consumer()
        path = self.rewrite(lambda manifest, entries: self.change_file(
            manifest, entries, 'phases/Socks5-integrated-unsigned.ipa', raw=b'another IPA\n'))
        self.reject('Transferred IPA differs', path)

    def test_empty_success_and_absent_phase_rejected(self):
        self.consumer()
        path = self.rewrite(lambda manifest, entries: self.change_file(manifest, entries, 'phases/sdk-success.txt', raw=b''))
        self.reject('Missing successful build/SDK markers', path)
        def remove(manifest, entries):
            name = 'phases/package-review.json'
            manifest['files'].pop(name)
            entries[:] = [(item, raw) for item, raw in entries if item.name != name]
        self.reject('Incomplete or extra build/SDK phase evidence', self.rewrite(remove))

    def test_inconsistent_member_bytes_or_mode_rejected(self):
        self.consumer()
        for raw, mode in [(b'changed\n', None), (None, 0o700)]:
            with self.subTest(raw=raw, mode=mode):
                path = self.rewrite(lambda manifest, entries: self.change_file(
                    manifest, entries, 'product/Tools/check.sh', raw=raw, mode=mode, update_manifest=False))
                self.reject('Archive/manifest bytes or mode differ', path)

    def test_archive_path_link_duplicate_and_special_mode_rejected(self):
        self.consumer()
        for kind, message in [('traversal', 'Unsafe archive path'), ('absolute', 'Unsafe archive path'),
                              ('symlink', 'non-regular file'), ('hardlink', 'non-regular file'),
                              ('duplicate', 'Duplicate or case-colliding'), ('setuid', 'Unsafe archive file mode')]:
            with self.subTest(kind=kind):
                def change(manifest, entries):
                    item, raw = copy.copy(entries[0][0]), entries[0][1]
                    if kind == 'traversal': item.name = '../escaped'
                    if kind == 'absolute': item.name = '/tmp/escaped-handoff'
                    if kind == 'symlink': item.type, item.linkname = tarfile.SYMTYPE, '../escaped'
                    if kind == 'hardlink': item.type, item.linkname = tarfile.LNKTYPE, '../escaped'
                    if kind == 'setuid': item.mode |= 0o4000
                    if kind == 'duplicate': entries.append((item, raw))
                    else: entries[0] = item, raw
                self.reject(message, self.rewrite(change))

    def test_unlisted_and_omitted_product_source_rejected(self):
        self.consumer()
        def omit(manifest, entries):
            name = 'product/Socks5/App.swift'
            manifest['files'].pop(name)
            entries[:] = [(item, raw) for item, raw in entries if item.name != name]
        self.reject('complete source tree', self.rewrite(omit))
        def extra(manifest, entries):
            item = tarfile.TarInfo('product/unrelated.txt')
            item.mode = 0o644
            entries.append((item, b'unreviewed file'))
        self.reject('Archive/manifest inventory differs', self.rewrite(extra))

    def test_preexisting_phase_not_overwritten(self):
        self.consumer()
        path = self.out / 'SUCCESS.txt'
        self.put(path, b'pre-existing unrelated marker\n')
        self.reject('Refusing to overwrite pre-existing phase evidence')
        self.assertEqual(path.read_bytes(), b'pre-existing unrelated marker\n')

    def test_linked_destination_not_followed(self):
        self.consumer()
        outside = self.root / '.build/unrelated-directory'
        outside.mkdir()
        self.product.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'Linked restore destination'):
            handoff.restore(self.archive)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.out / 'review-handoff-consumer.json').exists())

    def test_producer_without_completed_sdk_cannot_export(self):
        (self.out / 'sdk-success.txt').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Missing completed phase'):
            handoff.pack()
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(), self.original_hash)

    def test_linked_receipt_not_followed(self):
        self.consumer()
        outside = self.root / '.build/unrelated-receipt.json'
        (self.out / 'review-handoff-consumer.json').symlink_to(outside)
        self.reject('Review requires a fresh product workspace')
        self.assertFalse(outside.exists())


if __name__ == '__main__':
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    unittest.main(verbosity=2)
