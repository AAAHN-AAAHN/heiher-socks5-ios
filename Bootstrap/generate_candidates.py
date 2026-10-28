#!/usr/bin/env python3
"""Build exact local CI inputs from frozen heads and a verified remote snapshot."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from import_candidates import FORBIDDEN, NAMES, REPOSITORY, full_sha, require

HELPER = Path(__file__).resolve().parents[1]
BASE = HELPER.parent
ORDER = ('udp', 'statistics', 'background', 'server', 'settings', 'icon', 'integrated')
OLD_BRANCHES = {'main', 'feature/udp-compat', 'feature/traffic-statistics',
                'feature/background', 'feature/server-control', 'feature/settings-persistence',
                'feature/app-icon', 'feature/icmp-relay', 'release/integrated'}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *map(str, args)],
                                   stderr=subprocess.STDOUT, text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=BASE / 'repository.git')
    parser.add_argument('--heads', type=Path, default=BASE / 'evidence/candidate-heads.json')
    parser.add_argument('--old-heads', type=Path, default=BASE / 'evidence/remote-before.json')
    parser.add_argument('--remote-heads', type=Path, default=BASE / 'evidence/helper-remote-heads.json')
    parser.add_argument('--output', type=Path, default=HELPER)
    parser.add_argument('--candidates', nargs='+', choices=ORDER)
    parser.add_argument('--macos-only', nargs='+', choices=ORDER, default=[],
                        help='Run only the macOS row for these selected candidates')
    options = parser.parse_args()
    repo = options.repository.resolve()
    heads = json.loads(options.heads.read_bytes())
    require(set(heads) <= NAMES and set(ORDER[:-1]) <= set(heads) and 'main' in heads,
            'Frozen heads must contain Main and all six feature candidates')
    for name, sha in heads.items():
        require(full_sha(sha) and git(repo, 'cat-file', '-t', sha) == 'commit', 'Invalid frozen head: ' + name)
        require(git(repo, 'rev-parse', 'refs/heads/candidate/' + name) == sha, 'Local candidate ref moved: ' + name)
        for excluded in FORBIDDEN:
            result = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', excluded, sha])
            require(result.returncode == 1, 'Forbidden ancestry or missing ancestry evidence: ' + name)
    selected = options.candidates or [name for name in ORDER if name in heads]
    require(len(selected) == len(set(selected)) and all(name in heads for name in selected),
            'Requested candidate is missing or duplicated')
    selected = [name for name in ORDER if name in selected]
    require(len(options.macos_only) == len(set(options.macos_only)) and
            set(options.macos_only) <= set(selected), 'macOS-only names must be unique selected candidates')
    support = [name for name in ORDER if name in heads and name not in selected]

    snapshot = json.loads(options.remote_heads.read_bytes())
    require(snapshot['repository'] == REPOSITORY, 'Unexpected remote snapshot repository')
    remote = {row['ref']: row['sha'] for row in snapshot['refs'] if row['type'] == 'commit'}
    old = json.loads(options.old_heads.read_bytes())
    require({row['name'] for row in old} == OLD_BRANCHES, 'Unexpected old operating branch set')
    exclusions = []
    for row in old:
        ref, sha = 'refs/heads/' + row['name'], row['commit']['sha']
        require(full_sha(sha) and remote.get(ref) == sha, 'Remote operating branch moved: ' + ref)
        exclusions.append(dict(ref=ref, sha=sha))
    main_ref = 'refs/heads/work/udp-echo-main-20261028'
    require(remote.get(main_ref) == heads['main'], 'Verified Main prerequisite is unavailable remotely')
    exclusions.append(dict(ref=main_ref, sha=heads['main']))
    excluded_shas = list(dict.fromkeys(row['sha'] for row in exclusions))
    require(not set(heads[name] for name in selected) & set(excluded_shas), 'Selected candidate was excluded')

    refs = {f'refs/heads/candidate/{name}': heads[name] for name in selected}
    refs.update({f'refs/heads/support/{name}': heads[name] for name in support})
    with tempfile.TemporaryDirectory(prefix='udp-candidate-generation-') as temporary:
        temporary = Path(temporary)
        packed = temporary / 'packing.git'
        subprocess.run(['git', 'clone', '--quiet', '--bare', '--shared', str(repo), str(packed)], check=True)
        for ref, sha in refs.items():
            git(packed, 'update-ref', ref, sha)
        bundle = temporary / 'candidates.bundle'
        git(packed, '-c', 'pack.threads=1', 'bundle', 'create', '--version=2', bundle,
            *refs, *('^' + sha for sha in excluded_shas))
        actual = {row.split(' ', 1)[1]: row.split(' ', 1)[0]
                  for row in git(packed, 'bundle', 'list-heads', bundle).splitlines()}
        require(actual == refs, 'Generated bundle heads differ from frozen identities')
        prerequisites = []
        with bundle.open('rb') as stream:
            for line in stream:
                if line == b'\n':
                    break
                if line.startswith(b'-'):
                    prerequisites.append(line[1:41].decode('ascii'))
        require(all(full_sha(sha) for sha in prerequisites), 'Invalid bundle prerequisite')

        manifest = dict(
            sha256=digest(bundle),
            candidates=[dict(name=name, sha=heads[name], ref=f'refs/heads/work/udp-echo-{name}-20261028')
                        for name in selected],
            support=[dict(name=name, sha=heads[name]) for name in support],
            matrix=[dict(name=name, sha=heads[name], os=host,
                         runtime=host == 'xcode-27' and name != 'udp')
                    for name in selected for host in
                    (('xcode-27',) if name in options.macos_only else ('ubuntu-24.04', 'xcode-27'))])
        # This repository receives only the verified remote histories. Thus a
        # successful import proves that no unavailable local commit is required.
        available = temporary / 'available'
        available.mkdir()
        git(available, 'init', '--quiet')
        git(available, 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head', repo, *excluded_shas)
        git(available, 'bundle', 'verify', bundle)
        bootstrap = available / 'Bootstrap'
        bootstrap.mkdir()
        shutil.copyfile(HELPER / 'Bootstrap/import_candidates.py', bootstrap / 'import_candidates.py')
        shutil.copyfile(bundle, bootstrap / 'candidates.bundle')
        (bootstrap / 'candidates.json').write_text(json.dumps(manifest, indent=2) + '\n')
        git(available, 'add', 'Bootstrap')
        git(available, '-c', 'user.name=Candidate preparation fixture', '-c', 'user.email=fixture@localhost',
            'commit', '--quiet', '-m', 'Verify local read-only candidate preparation')
        environment = dict(os.environ, GITHUB_REPOSITORY=REPOSITORY,
                           GITHUB_SHA=git(available, 'rev-parse', 'HEAD'),
                           GITHUB_OUTPUT=str(temporary / 'matrix-output.txt'))
        verified = subprocess.run(['python3', str(bootstrap / 'import_candidates.py')], cwd=available,
                                  env=environment, text=True, capture_output=True)
        require(verified.returncode == 0, 'Actual read-only importer rejected generated inputs:\n' + verified.stderr)
        emitted = json.loads((temporary / 'matrix-output.txt').read_text().split('=', 1)[1])
        require(emitted == {'include': manifest['matrix']}, 'Emitted matrix differs from requested coverage')

        output = options.output.resolve()
        (output / 'Bootstrap').mkdir(parents=True, exist_ok=True)
        (output / '.github/workflows').mkdir(parents=True, exist_ok=True)
        for name in ('Bootstrap/import_candidates.py', 'Bootstrap/generate_candidates.py',
                     '.github/workflows/udp-echo-candidate.yml'):
            if output != HELPER:
                shutil.copyfile(HELPER / name, output / name)
        target = output / 'Bootstrap/candidates.bundle'
        shutil.copyfile(bundle, target)
        (output / 'Bootstrap/candidates.json').write_text(json.dumps(manifest, indent=2) + '\n')
        for path in (output / 'Bootstrap').glob('candidates.bundle.part-*'):
            path.unlink()
        encoded = base64.b64encode(target.read_bytes()).decode('ascii')
        for index, start in enumerate(range(0, len(encoded), 32_000)):
            (output / f'Bootstrap/candidates.bundle.part-{index:02d}').write_text(encoded[start:start + 32_000])
        receipt = dict(result='PASS', selected=selected, support=support, heads=heads,
                       macos_only=options.macos_only,
                       bundle_sha256=manifest['sha256'], bundle_bytes=target.stat().st_size,
                       prerequisites=prerequisites, verified_remote_exclusions=exclusions,
                       remote_snapshot_time=snapshot['fetched_at'], remote_snapshot_sha256=digest(options.remote_heads),
                       frozen_heads_sha256=digest(options.heads), matrix=manifest['matrix'],
                       remote_mutations=False, actual_importer_verified=True,
                       bundle_upload_path=str(target),
                       scope='Local bundle and read-only preparation verified; CI runtime results are not implied.')
        (output / 'Bootstrap/generation-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.output:
            print(error.output)
        raise
