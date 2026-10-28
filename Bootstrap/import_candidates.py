"""Verify candidate objects for local CI; never update repository refs or publish."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'AAAHN-AAAHN/heiher-socks5-ios'
NAMES = {'main', 'udp', 'statistics', 'background', 'server', 'settings', 'icon', 'integrated'}
FORBIDDEN = ('e5980901a6c0b7a8b12ddc37461e22405f7dbe0e',
             '0a62910f5e444edbf176fe3ccd52363e5b8f869e')


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def full_sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate')
    parser.add_argument('--sha')
    options = parser.parse_args()
    require((options.candidate is None) == (options.sha is None),
            '--candidate and --sha must be supplied together')
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Unexpected repository')
    helper = git('rev-parse', 'HEAD')
    require(helper == os.environ.get('GITHUB_SHA'), 'Checkout must be the exact helper commit')
    git('diff', '--exit-code', 'HEAD', '--')
    git('diff', '--cached', '--exit-code', 'HEAD', '--')

    manifest = json.loads((ROOT / 'Bootstrap/candidates.json').read_bytes())
    entries = manifest['candidates']
    require(isinstance(entries, list) and entries, 'Candidate list is empty or invalid')
    candidates = {}
    for entry in entries:
        name, sha = entry['name'], entry['sha']
        require(name in NAMES and name not in candidates and full_sha(sha), 'Invalid candidate identity')
        require(entry['ref'] == f'refs/heads/work/udp-echo-{name}-20261028', 'Unexpected candidate label')
        require(not entry.get('previous') or full_sha(entry['previous']), 'Invalid prior identity')
        candidates[name] = sha
    if options.candidate is not None:
        require(candidates.get(options.candidate) == options.sha, 'Requested candidate differs from manifest')
    support = {}
    for entry in manifest.get('support', []):
        name, sha = entry['name'], entry['sha']
        require(name in NAMES and name not in candidates and name not in support and full_sha(sha),
                'Invalid supporting candidate identity')
        support[name] = sha

    matrix = []
    seen = set()
    for row in manifest['matrix']:
        name, sha, host = row['name'], row['sha'], row['os']
        runtime = row.get('runtime', False)
        require(set(row) <= {'name', 'sha', 'os', 'runtime'}, 'Unexpected matrix field')
        require(candidates.get(name) == sha and host in ('ubuntu-24.04', 'xcode-27'), 'Invalid matrix identity')
        require(type(runtime) is bool and (not runtime or (host == 'xcode-27' and name not in ('main', 'udp'))),
                'Runtime coverage requires a supported macOS candidate')
        require((name, host) not in seen, 'Duplicate matrix job')
        seen.add((name, host))
        matrix.append(dict(name=name, sha=sha, os=host, runtime=runtime))
    require({row['name'] for row in matrix} == set(candidates), 'Every candidate requires a verification job')

    bundle = ROOT / 'Bootstrap/candidates.bundle'
    require(hashlib.sha256(bundle.read_bytes()).hexdigest() == manifest['sha256'], 'Candidate bundle hash mismatch')
    heads = [line.split(' ', 1) for line in git('bundle', 'list-heads', str(bundle)).splitlines()]
    expected_heads = [[sha, 'refs/heads/candidate/' + name] for name, sha in candidates.items()]
    expected_heads += [[sha, 'refs/heads/support/' + name] for name, sha in support.items()]
    require(sorted(heads) == sorted(expected_heads),
            'Bundle heads differ from declared candidates')
    # Git verifies every prerequisite before importing any candidate objects.
    git('bundle', 'verify', str(bundle))
    refs = git('for-each-ref', '--format=%(refname) %(objectname)')
    git('bundle', 'unbundle', str(bundle))
    require(git('for-each-ref', '--format=%(refname) %(objectname)') == refs, 'Object import changed refs')
    for sha in list(candidates.values()) + list(support.values()):
        require(git('cat-file', '-t', sha) == 'commit', 'Candidate must be a commit')
        for excluded in FORBIDDEN:
            result = subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', excluded, sha])
            require(result.returncode == 1, 'Forbidden ancestry or missing ancestry evidence')

    result = dict(result='PASS', helper_commit=helper, refs_changed=False,
                  remote_mutations=False, candidates=entries, support=manifest.get('support', []),
                  bundle_sha256=manifest['sha256'], matrix=matrix)
    output = ROOT / 'artifacts/candidate-prepare'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('matrix=' + json.dumps({'include': matrix}, separators=(',', ':')) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
