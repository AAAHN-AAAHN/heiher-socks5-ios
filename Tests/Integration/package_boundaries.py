#!/usr/bin/env python3
"""Execute the old ZIP comparison and current whole-payload comparison.

Small byte fixtures reproduce a dropped/changed resource or extra payload passing
an executable-and-plist-only check. They are never used as built iPhone products.
"""
import ast
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Build'))
from release_source import check_ipa_files



def symbol_contract():
    # Archived release linkers may strip unused compatibility entry points.
    # Exercise the actual verifier bodies, retaining the exact stale check as
    # a negative control. These strings are fixtures, not an Apple build claim.
    old = subprocess.check_output(['git', '-C', str(ROOT), 'show',
        'cbe4ebef8deebeda48e1feb2d529677543a0c394:Build/verify_release.py'])
    current = (ROOT / 'Build/verify_release.py').read_bytes()
    required = ['hev_socks5_server_endpoint_try_stats',
                'hev_socks5_server_endpoint_try_rows', 'hev_socks5_server_prepare']
    for label, source in [('stale', old), ('current', current)]:
        blocks = [node for node in ast.parse(source).body
                  if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple)
                  and all(isinstance(item, ast.Constant) and isinstance(item.value, str)
                          and item.value.startswith('hev_socks5_server_') for item in node.iter.elts)]
        assert len(blocks) == 2
        check = compile(ast.Module(body=blocks, type_ignores=[]), '<actual-package-symbol-check>', 'exec')
        for case in ['current-only', *required, 'obsolete-payload']:
            names = [name for name in required if name != case]
            if case == 'obsolete-payload': names.append('hev_socks5_server_stats')
            symbols = '\n'.join('0000000100000000 T _' + name for name in names)
            accepted = True
            try: exec(check, {'re': re, 'symbols': symbols})
            except AssertionError: accepted = False
            assert accepted == (label == 'current' and case == 'current-only'), (label, case)
            print('PASS: archive symbols', label, case, 'accepted=', accepted)


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    old = subprocess.check_output(['git', '-C', str(ROOT), 'show',
                                  '5a708728636d1ae5579ed11787696701eba37cb8'])
    blocks = [node for node in ast.parse(old).body if isinstance(node, ast.With)]
    if len(blocks) != 1:
        raise RuntimeError('Exact previous package checker changed')
    comparison = compile(ast.Module(body=blocks, type_ignores=[]), '<exact-old-zip-comparison>', 'exec')
    symbol_contract()
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
                for name, data in packaged.items():
                    entry = zipfile.ZipInfo('Payload/Socks5.app/' + name)
                    entry.create_system = 3
                    entry.external_attr = ((app / name).stat().st_mode if name in files else 0o100644) << 16
                    archive.writestr(entry, data)
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
