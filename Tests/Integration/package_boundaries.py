#!/usr/bin/env python3
"""Execute the old ZIP comparison and current whole-payload comparison.

Small byte fixtures reproduce a dropped/changed resource or extra payload passing
an executable-and-plist-only check. They are never used as built iPhone products.
"""
import ast
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Build'))
from release_source import check_ipa_files


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    old = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                  '5a708728636d1ae5579ed11787696701eba37cb8'])
    blocks = [node for node in ast.parse(old).body if isinstance(node, ast.With)]
    if len(blocks) != 1:
        raise RuntimeError('Exact previous package checker changed')
    comparison = compile(ast.Module(body=blocks, type_ignores=[]), '<exact-old-zip-comparison>', 'exec')
    count = 0
    for case in ('clean', 'changed-resource', 'missing-resource', 'extra-resource',
                 'changed-binary', 'changed-plist'):
        with tempfile.TemporaryDirectory(prefix='release-package-') as folder:
            root = Path(folder);app = root / 'Socks5.app';app.mkdir()
            info = {'CFBundleIdentifier': 'fixture.only'}
            files = {'Socks5': b'binary fixture', 'Info.plist': plistlib.dumps(info), 'Silence.wav': b'wave fixture'}
            for name, data in files.items(): (app / name).write_bytes(data)
            packaged = dict(files)
            if case == 'changed-resource': packaged['Silence.wav'] = b'changed'
            elif case == 'missing-resource': del packaged['Silence.wav']
            elif case == 'extra-resource': packaged['unexpected.txt'] = b'extra'
            elif case == 'changed-binary': packaged['Socks5'] = b'changed'
            elif case == 'changed-plist': packaged['Info.plist'] = plistlib.dumps({'CFBundleIdentifier': 'other'})
            ipa = root / 'fixture.zip'
            with zipfile.ZipFile(ipa, 'w') as archive:
                for name, data in packaged.items(): archive.writestr('Payload/Socks5.app/' + name, data)
            for label in ('old', 'current'):
                accepted = True
                try:
                    if label == 'old':
                        exec(comparison, {'zipfile': zipfile, 'plistlib': plistlib, 'ipa': ipa,
                                          'binary': files['Socks5'], 'info': info})
                    else:
                        check_ipa_files(ipa, app)
                except (RuntimeError, AssertionError, KeyError): accepted = False
                expected = case == 'clean' or (label == 'old' and case in
                           ('changed-resource', 'missing-resource', 'extra-resource'))
                if accepted != expected: raise RuntimeError((label, case, accepted))
                print('PASS:', label, case, 'accepted=', accepted)
                count += 1
    print(f'PASS: {count} exact-old/current IPA payload boundary cases; no archive build in these fixtures.')


if __name__ == '__main__':
    main()
