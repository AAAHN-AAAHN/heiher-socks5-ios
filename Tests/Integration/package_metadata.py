#!/usr/bin/env python3
"""Exact prior/current IPA metadata boundaries; fixtures are not built products."""
import ast
import copy
import hashlib
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Build'))
from release_source import check_ipa_files

PRIOR = 'cebf999eb5ae461393a4be531d357e9a86d7d5d4'
CASES = ('clean', 'no-directories', 'reordered', 'nested', 'empty-source',
         'missing-source', 'source-file-link', 'source-directory-link', 'source-root-link',
         'source-fifo', 'executable-no-execute', 'resource-executable', 'file-setuid',
         'file-link', 'file-fifo', 'file-directory', 'file-no-type', 'dos-creator',
         'directory-link', 'directory-file', 'directory-no-execute', 'directory-data',
         'foreign-directory', 'traversal-directory', 'absolute-directory', 'dot-directory',
         'duplicate-directory', 'duplicate-file', 'changed-bytes', 'missing-file', 'extra-file')
OLD_REJECTS = {'duplicate-directory', 'duplicate-file', 'changed-bytes', 'missing-file', 'extra-file'}
VALID = {'clean', 'no-directories', 'reordered', 'nested'}


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    raw = subprocess.check_output(['git', '-C', str(ROOT), 'show', PRIOR])
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == PRIOR
    function = next(n for n in ast.parse(raw).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'check_ipa_files')
    namespace = {'zipfile': zipfile}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<exact-prior-checker>', 'exec'), namespace)
    checks = 0
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix='ipa-metadata-') as tmp:
            root = Path(tmp); app = root / 'Socks5.app'; app.mkdir(); app.chmod(0o755)
            for name, content, mode in [('Socks5', b'executable fixture', 0o755),
                                        ('Info.plist', b'plist fixture', 0o644),
                                        ('Silence.wav', b'wave fixture', 0o644)]:
                path = app / name; path.write_bytes(content); path.chmod(mode)
            if case == 'nested':
                (app / 'nested').mkdir(); (app / 'nested/empty').mkdir()
                (app / 'nested/data').write_bytes(b'data')
            entries = []
            prefix = 'Payload/Socks5.app/'
            for path in [app, *sorted(app.rglob('*'))]:
                name = prefix if path == app else prefix + path.relative_to(app).as_posix()
                info = zipfile.ZipInfo.from_file(path, name)
                entries.append((info, b'' if path.is_dir() else path.read_bytes()))
            info = zipfile.ZipInfo('Payload/'); info.create_system = 3
            info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
            entries.insert(0, (info, b''))
            if case == 'no-directories': entries = [e for e in entries if not e[0].is_dir()]
            if case == 'reordered': entries.reverse()
            if case in ('empty-source', 'missing-source'):
                for path in app.iterdir(): path.unlink()
                entries = []
                if case == 'missing-source': app.rmdir()
            if case == 'source-file-link':
                target = root / 'wave'; target.write_bytes((app / 'Silence.wav').read_bytes())
                (app / 'Silence.wav').unlink(); (app / 'Silence.wav').symlink_to(target)
            if case == 'source-directory-link':
                target = root / 'directory'; target.mkdir(); (app / 'linked').symlink_to(target, target_is_directory=True)
            if case == 'source-root-link':
                alias = root / 'alias'; alias.symlink_to(app, target_is_directory=True); app = alias
            if case == 'source-fifo':
                import os
                os.mkfifo(app / 'fifo')
            modes = {'executable-no-execute': stat.S_IFREG | 0o644,
                     'resource-executable': stat.S_IFREG | 0o755,
                     'file-setuid': stat.S_IFREG | 0o4644,
                     'file-link': stat.S_IFLNK | 0o644, 'file-fifo': stat.S_IFIFO | 0o644,
                     'file-directory': stat.S_IFDIR | 0o644, 'file-no-type': 0o644}
            if case in modes:
                name = prefix + ('Socks5' if case == 'executable-no-execute' else 'Silence.wav')
                next(i for i, _ in entries if i.filename == name).external_attr = modes[case] << 16
            if case == 'dos-creator':
                next(i for i, _ in entries if i.filename == prefix + 'Socks5').create_system = 0
            if case in ('directory-link', 'directory-file', 'directory-no-execute'):
                info = next(i for i, _ in entries if i.filename == prefix)
                mode = {'directory-link': stat.S_IFLNK | 0o755, 'directory-file': stat.S_IFREG | 0o755,
                        'directory-no-execute': stat.S_IFDIR | 0o644}[case]
                info.external_attr = mode << 16 | 0x10
            if case == 'directory-data':
                entries = [(i, b'not empty' if i.filename == prefix else b) for i, b in entries]
            if case in ('foreign-directory', 'traversal-directory', 'absolute-directory', 'dot-directory'):
                name = {'foreign-directory': 'foreign/', 'traversal-directory': '../escape/',
                        'absolute-directory': '/absolute/', 'dot-directory': 'Payload/./Socks5.app/'}[case]
                info = zipfile.ZipInfo(name); info.create_system = 3
                info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                entries.append((info, b''))
            if case.startswith('duplicate-'):
                entry = next(e for e in entries if e[0].is_dir() == (case == 'duplicate-directory'))
                entries.append((copy.copy(entry[0]), entry[1]))
            if case == 'changed-bytes':
                entries = [(i, b'changed' if i.filename.endswith('Silence.wav') else b) for i, b in entries]
            if case == 'missing-file': entries = [e for e in entries if not e[0].filename.endswith('Silence.wav')]
            if case == 'extra-file':
                info = zipfile.ZipInfo(prefix + 'extra'); info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16; entries.append((info, b'extra'))
            ipa = root / 'fixture.zip'
            with zipfile.ZipFile(ipa, 'w') as archive:
                for info, content in entries: archive.writestr(info, content)
            for label, check in [('prior', namespace['check_ipa_files']), ('current', check_ipa_files)]:
                accepted = True
                try: check(ipa, app)
                except RuntimeError: accepted = False
                expected = case not in OLD_REJECTS if label == 'prior' else case in VALID
                assert accepted == expected, (case, label, accepted)
                print('PASS:', label, case, 'accepted=', accepted)
                checks += 1
    print(f'PASS: {checks} exact-prior/current metadata cases; {len(CASES)} inputs; no app execution')


if __name__ == '__main__':
    main()
