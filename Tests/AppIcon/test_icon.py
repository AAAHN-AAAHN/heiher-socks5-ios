#!/usr/bin/env python3
"""Mutation tests for resource validation, including the actual old weak checks."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import zlib

import check_icon as audit


def chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


class IconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (audit.ROOT / audit.CATALOG / 'AppIcon.png').read_bytes()
        cls.ihdr = cls.data[16:29]
        cls.palette = cls.data[41:53]

    def test_complete_source(self):
        result = audit.png(self.data)
        self.assertEqual(result['sourceSHA256'], audit.IMAGE_HASH)
        self.assertEqual(sum(result['pixelCounts']), 1024 * 1024)
        self.assertEqual(len([n for n in result['pixelCounts'] if n]), 4)

    def test_every_single_bit_corruption(self):
        damaged = bytearray(self.data)
        for index in range(len(damaged)):
            for bit in range(8):
                damaged[index] ^= 1 << bit
                with self.assertRaises((ValueError, zlib.error)):
                    audit.png(damaged)
                damaged[index] ^= 1 << bit
        self.assertEqual(damaged, self.data)
        print(f"PASS: all {len(damaged) * 8} one-bit mutations rejected; original bytes restored")

    def test_truncation(self):
        for length in (0, 8, 29, 53, len(self.data) - 1):
            with self.subTest(length=length), self.assertRaises(ValueError):
                audit.png(self.data[:length])

    def test_crc(self):
        damaged = bytearray(self.data); damaged[100] ^= 1
        with self.assertRaises(ValueError): audit.png(damaged)

    def test_wrong_dimensions(self):
        wrong = struct.pack('>II', 1023, 1024) + self.ihdr[8:]
        with self.assertRaises(ValueError): audit.png(self.data[:8] + chunk(b'IHDR', wrong) + self.data[33:])

    def test_transparency(self):
        with self.assertRaises(ValueError):
            audit.png(self.data[:57] + chunk(b'tRNS', b'\x00') + self.data[57:])

    def test_alpha_format(self):
        header = struct.pack('>IIBBBBB', 1024, 1024, 8, 6, 0, 0, 0)
        with self.assertRaises(ValueError): audit.png(self.data[:8] + chunk(b'IHDR', header) + self.data[33:])

    def test_valid_crc_invalid_compression(self):
        damaged = self.data[:57] + chunk(b'IDAT', b'not-zlib') + chunk(b'IEND', b'')
        with self.assertRaises((ValueError, zlib.error)): audit.png(damaged)

    def test_excess_decoded_data(self):
        stream = zlib.compress(bytes(1024 * 257 + 1))
        with self.assertRaises(ValueError): audit.png(self.data[:57] + chunk(b'IDAT', stream) + chunk(b'IEND', b''))

    def test_trailing_data(self):
        with self.assertRaises(ValueError): audit.png(self.data + b'junk')

    def test_bad_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); (folder / 'AppIcon.png').write_bytes(self.data)
            for change in ({'filename': 'Missing.png'}, {'platform': 'macos'}, {'idiom': 'iphone'}, {'size': '512x512'}):
                value = json.loads(json.dumps(audit.MANIFEST)); value['images'][0].update(change)
                (folder / 'Contents.json').write_text(json.dumps(value))
                with self.subTest(change=change), self.assertRaises(ValueError): audit.catalog(folder)

    def test_artwork_and_extra_file_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'Contents.json').write_text(json.dumps(audit.MANIFEST))
            altered = bytearray(self.palette); altered[0] ^= 1
            (folder / 'AppIcon.png').write_bytes(self.data[:33] + chunk(b'PLTE', altered) + self.data[57:])
            with self.assertRaisesRegex(ValueError, 'artwork'): audit.catalog(folder)
            (folder / 'AppIcon.png').write_bytes(self.data); (folder / 'Unused.png').write_bytes(self.data)
            with self.assertRaisesRegex(ValueError, 'unused'): audit.catalog(folder)

    def test_actual_old_composition_checks_accept_invalid_resources(self):
        spec = importlib.util.spec_from_file_location('original_checks', audit.ROOT / 'Build/check.py')
        old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(audit.ROOT / 'Socks5', root / 'Socks5')
            shutil.copytree(audit.ROOT / 'Socks5.xcodeproj', root / 'Socks5.xcodeproj')
            old.ROOT = root
            image = root / audit.CATALOG / 'AppIcon.png'
            image.write_bytes(self.data[:29])
            with contextlib.redirect_stdout(io.StringIO()): old.composition()
            with self.assertRaises(ValueError): audit.catalog(root / audit.CATALOG)
            image.write_bytes(self.data)
            bad = json.loads(json.dumps(audit.MANIFEST)); bad['images'][0]['filename'] = 'Missing.png'
            (root / audit.CATALOG / 'Contents.json').write_text(json.dumps(bad))
            with contextlib.redirect_stdout(io.StringIO()): old.composition()
            with self.assertRaises(ValueError): audit.catalog(root / audit.CATALOG)
        print('NEGATIVE CONTROL: unchanged original composition() accepted truncated PNG and missing referenced filename.')


if __name__ == '__main__': unittest.main(verbosity=2)
