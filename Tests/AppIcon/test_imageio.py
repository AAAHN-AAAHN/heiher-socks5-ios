#!/usr/bin/env python3
"""Run the real Apple decoder against valid and mismatched compiled-icon fixtures.

The exact prior decoder is a negative control, not a replacement for new execution.
Synthetic fixture images never enter the app catalog or production target.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

from check_icon import ROOT, CATALOG, require

PRIOR = '639de66aa2265f3beffc1d0b433981d2e8073cb2'


def png(width, height=None, transparent=False):
    height = width if height is None else height
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    pixel = b'\x20\x60\x80\x00' if transparent else b'\x20\x60\x80'
    raw = (b'\x00' + pixel * width) * height
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8,
            6 if transparent else 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def main(decoder):
    require(__debug__, 'Run without Python optimization')
    require(sys.platform == 'darwin', 'Actual Apple ImageIO execution required')
    old_source = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                         PRIOR + ':Tests/AppIcon/DecodeImages.swift'])
    cases = [
        ('source', 'AppIcon.png', (ROOT / CATALOG / 'AppIcon.png').read_bytes(), True, True),
        ('phone-2x', 'AppIcon60x60@2x.png', png(120), True, True),
        ('phone-3x', 'AppIcon60x60@3x~iphone.png', png(180), True, True),
        ('pad-2x', 'AppIcon76x76@2x~ipad.png', png(152), True, True),
        ('pad-fractional', 'AppIcon83.5x83.5@2x~ipad.png', png(167), True, True),
        ('unscaled', 'AppIcon60x60.png', png(60), True, True),
        ('empty-input', None, b'', True, False),
        ('wrong-source-size', 'AppIcon.png', png(1), True, False),
        ('tiny-fallback', 'AppIcon60x60@2x.png', png(1), True, False),
        ('wrong-scale-size', 'AppIcon60x60@2x.png', png(60), True, False),
        ('unknown-name', 'AppIconWrong.png', png(120), True, False),
        ('invalid-scale', 'AppIcon60x60@4x.png', png(120), True, False),
        ('mismatched-point-size', 'AppIcon60x61@2x.png', png(120), True, False),
        ('wrong-suffix-order', 'AppIcon60x60~ipad@2x.png', png(120), True, False),
        ('non-square', 'AppIcon60x60@2x.png', png(120, 119), False, False),
        ('transparent', 'AppIcon60x60@2x.png', png(120, transparent=True), False, False),
        ('non-PNG', 'AppIcon1x1.png', bytes.fromhex(
            '47494638396101000100800000000000ffffff2c00000000010001000002024401003b'), True, False),
    ]
    rows = []
    with tempfile.TemporaryDirectory(prefix='icon-imageio-') as temporary:
        root = Path(temporary)
        source = root / 'Prior.swift'; source.write_bytes(old_source)
        old = root / 'prior-decoder'
        build = subprocess.run(['xcrun', 'swiftc', '-parse-as-library', '-swift-version', '5',
                                '-warnings-as-errors', str(source), '-o', str(old)],
                               capture_output=True, text=True, timeout=120)
        require(build.returncode == 0, build.stdout + build.stderr)
        for label, name, data, old_accepts, accepts in cases:
            folder = root / label; folder.mkdir()
            args = []
            if name:
                path = folder / name; path.write_bytes(data); args = [str(path)]
            for version, executable, expected in [('old', old, old_accepts), ('current', decoder, accepts)]:
                result = subprocess.run([str(executable), *args], capture_output=True, text=True, timeout=30)
                rows.append({'case': label, 'version': version, 'expected_accept': expected,
                             'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
                require((result.returncode == 0) == expected,
                        json.dumps(rows, indent=2) + '\nUnexpected ImageIO verdict')
                if expected and args:
                    decoded = json.loads(result.stdout)
                    require(len(decoded) == 1 and decoded[0]['allPixelsOpaque'] is True
                            and decoded[0]['fileSHA256'] == hashlib.sha256(data).hexdigest(),
                            'Decoded result does not identify the actual fixture')
    print(json.dumps({'cases': len(cases), 'executions': len(rows), 'prior_commit': PRIOR,
                      'prior_decoder_sha256': hashlib.sha256(old_source).hexdigest(),
                      'scope': 'Real Apple decoder, synthetic fixtures, not physical installation',
                      'results': rows}, indent=2))


if __name__ == '__main__':
    require(len(sys.argv) == 2, 'Pass the current compiled ImageIO decoder')
    main(Path(sys.argv[1]).resolve())
