#!/usr/bin/env python3
"""Validate the fixed app-icon resource and feature boundary; no app runtime code."""
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[2]
BASE = '75335d201cb1e541bb153e9899badbc11ccf1973'
INPUT = 'f88e8c8946b095c4d5551d413dee3b4a60943714'
CATALOG = 'Socks5/Assets.xcassets/AppIcon.appiconset'
IMAGE_HASH = '4a2f2a9384e8b6db351a9284232db56e719377e60f17123e4a6992cee1799cc2'
MANIFEST = {'images': [{'filename': 'AppIcon.png', 'idiom': 'universal',
                        'platform': 'ios', 'size': '1024x1024'}],
            'info': {'author': 'xcode', 'version': 1}}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def png(data):
    """Fully decode this noninterlaced indexed resource; not a general PNG library.

    Apple ImageIO independently decodes the real source and compiled images in CI.
    Restrict to the approved four-chunk, opaque palette format instead of accepting
    partially checked alternative formats. Never repair or recompress the input.
    """
    require(data[:8] == b'\x89PNG\r\n\x1a\n', 'PNG signature')
    chunks = []
    pos = 8
    while pos < len(data):
        require(pos + 12 <= len(data), 'Truncated PNG chunk')
        length, kind = struct.unpack_from('>I4s', data, pos)
        end = pos + 12 + length
        require(end <= len(data), 'Chunk exceeds file')
        payload = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from('>I', data, pos + 8 + length)[0]
        require(zlib.crc32(kind + payload) == crc, 'PNG chunk CRC')
        chunks.append((kind, payload))
        pos = end
    require([c[0] for c in chunks] == [b'IHDR', b'PLTE', b'IDAT', b'IEND'],
            'Expected opaque single-image PNG chunks, no transparency/animation/trailing data')
    require(len(chunks[0][1]) == 13 and not chunks[-1][1], 'Header/end length')
    header = struct.unpack('>IIBBBBB', chunks[0][1])
    require(header == (1024, 1024, 2, 3, 0, 0, 0), 'Approved size/bit depth/colour format')
    palette = chunks[1][1]
    require(len(palette) == 12, 'Four RGB palette entries required')
    stride = 256
    expected = (stride + 1) * 1024
    decoder = zlib.decompressobj()
    raw = decoder.decompress(chunks[2][1], expected + 1)
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
            and len(raw) == expected, 'Complete bounded IDAT decompression')
    previous = bytes(stride)
    rgb = bytearray()
    counts = [0] * 4
    for y in range(1024):
        offset = y * (stride + 1)
        method = raw[offset]
        require(method <= 4, 'PNG filter')
        row = bytearray(raw[offset + 1:offset + 1 + stride])
        for x in range(stride):
            a, b, c = (row[x - 1] if x else 0), previous[x], (previous[x - 1] if x else 0)
            if method == 1:
                predictor = a
            elif method == 2:
                predictor = b
            elif method == 3:
                predictor = (a + b) // 2
            elif method == 4:
                p = a + b - c
                distances = (abs(p - a), abs(p - b), abs(p - c))
                predictor = (a, b, c)[distances.index(min(distances))]
            else:
                predictor = 0
            row[x] = (row[x] + predictor) & 255
        for packed in row:
            for shift in (6, 4, 2, 0):
                index = (packed >> shift) & 3
                counts[index] += 1
                rgb += palette[index * 3:index * 3 + 3]
        previous = row
    return {'size': [1024, 1024], 'bitDepth': 2, 'colourType': 3,
            'bytes': len(data), 'palette': list(palette), 'pixelCounts': counts,
            'rgbSHA256': hashlib.sha256(rgb).hexdigest(), 'alpha': 'none',
            'sourceSHA256': hashlib.sha256(data).hexdigest()}


def catalog(folder):
    require(json.loads((folder / 'Contents.json').read_bytes()) == MANIFEST,
            'Exact single-size iOS manifest and filename')
    require({p.name for p in folder.iterdir()} == {'Contents.json', 'AppIcon.png'},
            'No hidden/unused/alternate icon files')
    result = png((folder / 'AppIcon.png').read_bytes())
    require(result['sourceSHA256'] == IMAGE_HASH, 'Approved artwork bytes changed')
    return result


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def main():
    result = catalog(ROOT / CATALOG)
    git('merge-base', '--is-ancestor', BASE, 'HEAD')
    git('merge-base', '--is-ancestor', INPUT, 'HEAD')
    paths = git('ls-files').decode().splitlines()
    originals = git('ls-tree', '-r', '--name-only', INPUT).decode().splitlines()
    allowed = {'.github/workflows/verify-build.yml', 'README.md', 'docs/features/app-icon.md'}
    shared = {'Build/build.sh', 'Build/check.py', 'docs/main-baseline.md'}
    inherited = {'Tests/baseline_audit.py', 'docs/top-level-principles.md',
                 'docs/history/main-before-project-audit-20260926.md'}
    for path in shared | inherited:
        require((ROOT / path).read_bytes() == git('show', BASE + ':' + path),
                'Current main source: ' + path)
    old_config = json.loads(git('show', INPUT + ':Build/features.json'))
    require(json.loads((ROOT / 'Build/features.json').read_bytes()) ==
            dict(old_config, base_commit=BASE), 'Only the exact main reference changes')
    preserved = []
    require(set(originals) <= set(paths), 'Original file removed')
    for path in originals:
        if path not in allowed | shared | {'Build/features.json'}:
            require((ROOT / path).read_bytes() == git('show', INPUT + ':' + path), path)
            preserved.append(path)
    history = 'docs/history/app-icon-before-final-audit-20260926.md'
    require((ROOT / history).read_bytes() == git('show',
            '1beaefa4e068a3b4e9473bab478b27526b88defd:README.md'), 'Original audit history')
    require(all(p.startswith('Tests/AppIcon/') or p == history or p in inherited
                for p in set(paths) - set(originals)),
            'Unexpected feature addition')
    baseline_config = json.loads(git('show', BASE + ':Build/features.json'))
    config = json.loads((ROOT / 'Build/features.json').read_bytes())
    require(config['features'] == ['icon'] and not config['patches'], 'Icon-only composition')
    for key in ('sources', 'upstream_app'):
        require(config[key] == baseline_config[key], 'Native/app source pin changed')
    for path in ('Socks5/Socks5App.swift', 'Socks5/ContentView.swift'):
        require((ROOT / path).read_bytes() == git('show', BASE + ':' + path), 'Runtime source changed')
    info = plistlib.loads((ROOT / 'Socks5/Info.plist').read_bytes())
    require(set(info) == {'UIApplicationSceneManifest', 'NSLocalNetworkUsageDescription'}, 'Extra plist feature')
    require(info['UIApplicationSceneManifest']['UIApplicationSupportsMultipleScenes'] is False,
            'Preserve existing single-scene declaration')
    require((ROOT / 'README.md').read_bytes() == (ROOT / 'docs/features/app-icon.md').read_bytes(), 'README mirror')
    result.update(testedCommit=git('rev-parse', 'HEAD').decode().strip(),
                  inputCommit=INPUT, baseline=BASE, unchangedInputFiles=preserved,
                  scope='Source and complete PNG decoding. Not compilation, installation or OS rendering.')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
