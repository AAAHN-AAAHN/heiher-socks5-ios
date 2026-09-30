#!/usr/bin/env python3
"""Document-only rejection fixtures; application changes exist only in disposable worktrees."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / 'Build/check_documentation.py'
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'):
    ENV.pop(key, None)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], stderr=subprocess.PIPE, env=ENV)


def change(root, case):
    manifest = root / 'docs/documentation.json'
    value = json.loads(manifest.read_bytes())
    readme = root / 'README.md'
    mirror = root / value['readme_mirror']
    parent_doc = root / ('docs/upstream/README.md' if value['branch'] == 'main' else 'docs/main-baseline.md')
    source = sorted((root / 'Socks5').rglob('*.swift'))[0]
    if case == 'valid':
        return
    if case == 'parent-content':
        parent_doc.write_bytes(parent_doc.read_bytes() + b'\nUnexpected text.\n')
    elif case == 'parent-missing':
        parent_doc.unlink()
    elif case == 'parent-link':
        parent_doc.unlink()
        parent_doc.symlink_to(root / 'LICENSE')
    elif case == 'mirror':
        readme.write_bytes(readme.read_bytes() + b'\nDifferent mirror.\n')
    elif case in ('structure', 'date', 'history', 'link', 'anchor'):
        text = readme.read_text()
        if case == 'structure':
            text = text.replace('## Purpose and scope', '## Missing required structure', 1)
        elif case == 'date':
            text += '\nSnapshot 2026-01-01.\n'
        elif case == 'history':
            text += '\n### Update history\nNot a functional contract.\n'
        elif case == 'link':
            text += '\n[Broken reference](missing-document.md)\n'
        else:
            text += '\n[Broken section](#missing-required-anchor)\n'
        readme.write_text(text)
        mirror.write_text(text)
    elif case == 'parent-mode':
        parent_doc.chmod(0o755)
    elif case in ('code-index', 'validator-index', 'parent-index'):
        target = source if case == 'code-index' else root / 'Build/check.py' if case == 'validator-index' else parent_doc
        data = target.read_bytes()
        target.write_bytes(data + b'\nStaged-only change.\n')
        subprocess.run(['git', '-C', str(root), 'add', '--', str(target)], check=True, env=ENV)
        target.write_bytes(data)
    elif case == 'license':
        target = root / 'LICENSE'
        target.write_bytes(target.read_bytes() + b'\nUnauthorized change.\n')
    elif case in ('test-input', 'workflow', 'source-pin'):
        name = {'test-input': 'Tests/baseline_audit.py', 'source-pin': 'Build/upstream.json',
                'workflow': '.github/workflows/verify-build.yml'}[case]
        target = root / name
        target.write_bytes(target.read_bytes() + b'\nUnauthorized change.\n')
    elif case in ('empty-section', 'title-count', 'crlf', 'trailing', 'fence',
                  'escaping-link', 'repository-link', 'invalid-link-scheme'):
        text = readme.read_text()
        if case == 'empty-section':
            start, end = text.index('## Purpose and scope'), text.index('## Functional behavior')
            text = text[:start] + '## Purpose and scope\n\n' + text[end:]
        elif case == 'title-count':
            text += '\n# Duplicate root title\n'
        elif case == 'crlf':
            text = text.replace('\n', '\r\n')
        elif case == 'trailing':
            text += '\nTrailing whitespace. \n'
        elif case == 'fence':
            text += '\n```text\nUnclosed code fence.\n'
        elif case == 'escaping-link':
            text += '\n[Escape](../../outside.md)\n'
        elif case == 'repository-link':
            text += '\n[Missing](https://github.com/AAAHN-AAAHN/heiher-socks5-ios/blob/main/docs/absent.md)\n'
        else:
            text += '\n[Unsafe](javascript:bad)\n'
        readme.write_bytes(text.encode())
        mirror.write_bytes(text.encode())
    elif case == 'owned-inventory':
        value['owned_documents'].append(value['owned_documents'][0])
        manifest.write_text(json.dumps(value))
    elif case == 'code-content':
        source.write_bytes(source.read_bytes() + b'\n// Forbidden frozen-source edit.\n')
    elif case == 'code-mode':
        source.chmod(source.stat().st_mode ^ 0o111)
    elif case == 'code-added':
        (root / 'Socks5/UnexpectedFrozenInput.swift').write_text('// Unexpected input.\n')
    elif case == 'code-missing':
        source.unlink()
    elif case == 'validator':
        path = root / 'Build/check.py'
        path.write_bytes(path.read_bytes() + b'\n# Unapproved validator change.\n')
    elif case == 'frozen-reference':
        value['frozen_source'] = '0' * 40
        manifest.write_text(json.dumps(value))
    elif case == 'parent-set':
        value['parents'] = {}
        manifest.write_text(json.dumps(value))
    elif case == 'extra-document':
        (root / 'docs/unexpected.md').write_bytes(readme.read_bytes())
    elif case == 'principles':
        path = root / 'docs/top-level-principles.md'
        path.write_bytes(path.read_bytes() + b'\nChanged principles.\n')
    elif case == 'upstream':
        path = root / 'docs/upstream/README.md'
        path.write_bytes(path.read_bytes() + b'\nChanged source README.\n')
    else:
        raise ValueError(case)


def main():
    if not __debug__:
        raise SystemExit('Assertions must be enabled')
    cases = ['valid', 'parent-content', 'parent-missing', 'parent-link', 'mirror',
             'structure', 'date', 'history', 'link', 'anchor', 'code-content',
             'code-mode', 'code-added', 'code-missing', 'validator',
             'frozen-reference', 'parent-set', 'extra-document', 'principles', 'upstream',
             'parent-mode', 'code-index', 'validator-index', 'parent-index', 'license',
             'test-input', 'workflow', 'source-pin', 'empty-section', 'title-count', 'crlf',
             'trailing', 'fence', 'escaping-link', 'repository-link', 'invalid-link-scheme',
             'owned-inventory']
    rows = []
    with tempfile.TemporaryDirectory(prefix='documentation-contract-') as directory:
        for number, case in enumerate(cases):
            root = Path(directory) / str(number)
            git('worktree', 'add', '--quiet', '--detach', str(root), 'HEAD')
            try:
                change(root, case)
                result = subprocess.run([sys.executable, str(CHECKER), '--root', str(root)],
                                        env=ENV, capture_output=True, text=True, timeout=90)
                expected = case == 'valid'
                if (result.returncode == 0) != expected:
                    raise RuntimeError((case, result.returncode, result.stdout, result.stderr))
                if not expected and not any(message in result.stderr for message in (
                        'RuntimeError:', 'FileNotFoundError:')):
                    raise RuntimeError(('Unexpected rejection mechanism', case, result.stderr))
                rows.append({'case': case, 'accepted': result.returncode == 0, 'expected': expected})
            finally:
                git('worktree', 'remove', '--force', str(root))
    print(json.dumps({'result': 'PASS', 'cases': rows,
                      'scope': 'Documentation structure/inheritance and frozen-input rejection; no app runtime execution'}, indent=2))


if __name__ == '__main__':
    main()
