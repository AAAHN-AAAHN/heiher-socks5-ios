#!/usr/bin/env python3
"""Check candidate import against a disposable local Git remote, never GitHub."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def git(cwd, *args):
    return subprocess.check_output(['git', '-C', str(cwd), *args],
                                   stderr=subprocess.STDOUT, text=True).strip()


def main():
    source, report = map(lambda s: Path(s).resolve(), sys.argv[1:])
    spec = importlib.util.spec_from_file_location('resume_runner', Path(__file__).with_name('resume_runner.py'))
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    base = '618b3d2b413937aaad7373ee2af9e693ec81b84a'
    candidate = '3c2901f57a2bdfc76aaf248dedd9d0cdd64f3157'
    with tempfile.TemporaryDirectory(prefix='resume-protocol-') as directory:
        root = Path(directory)
        remote, work = root / 'remote.git', root / 'work'
        subprocess.run(['git', 'clone', '--mirror', '--no-hardlinks', str(source), str(remote)],
                       check=True, capture_output=True)
        git(remote, 'update-ref', 'refs/heads/feature/background', base)
        git(remote, 'update-ref', 'refs/heads/work/loop-background-candidate-20261017', candidate)
        subprocess.run(['git', 'clone', '--no-checkout', str(remote), str(work)], check=True, capture_output=True)
        git(work, 'checkout', '--detach', candidate)
        child = git(work, 'commit-tree', git(work, 'rev-parse', 'HEAD^{tree}'),
                    '-p', 'HEAD', '-m', 'Local-only exact bundle protocol fixture')
        ref = 'refs/heads/resume/background-20261018'
        git(work, 'update-ref', ref, child)
        (work / 'Diagnostics').mkdir(exist_ok=True)
        bundle = work / 'Diagnostics/resume.bundle'
        git(work, 'bundle', 'create', str(bundle), ref, '^' + candidate)
        data = {
            'schema': 1, 'repository': 'AAAHN-AAAHN/heiher-socks5-ios',
            'bundle': {'path': 'Diagnostics/resume.bundle',
                       'sha256': hashlib.sha256(bundle.read_bytes()).hexdigest()},
            'candidates': [{'profile': 'background', 'product_branch': 'feature/background',
                            'baseline': base, 'candidate_branch': 'work/loop-background-candidate-20261017',
                            'head': child, 'bundle_ref': ref, 'expected_candidate': candidate}],
        }
        path = work / 'Diagnostics/resume-manifest.json'
        path.write_text(json.dumps(data))
        runner.ROOT, runner.OUT = work, work / 'artifacts/resume'
        runner.OUT.mkdir(parents=True)
        os.environ['GITHUB_REPOSITORY'] = data['repository']
        os.environ['GITHUB_OUTPUT'] = str(work / 'outputs')
        # Refuse to exercise even a read unless origin is this temporary local repository.
        assert runner.git('remote', 'get-url', 'origin') == str(remote)
        runner.import_candidates(runner.manifest())
        assert git(remote, 'rev-parse', 'refs/heads/feature/background') == base
        assert git(remote, 'rev-parse', 'refs/heads/work/loop-background-candidate-20261017') == child
        runner.import_candidates(runner.manifest())
        bad = json.loads(json.dumps(data))
        bad['bundle']['sha256'] = '0' * 64
        try:
            runner.import_candidates(bad)
        except AssertionError as error:
            assert str(error) == 'Bundle digest differs'
        else:
            raise AssertionError('Bad bundle accepted')
        bad = json.loads(json.dumps(data))
        bad['candidates'][0]['candidate_branch'] = 'feature/background'
        path.write_text(json.dumps(bad))
        try:
            runner.manifest()
        except AssertionError:
            pass
        else:
            raise AssertionError('Product ref accepted by review importer')
        result = {
            'result': 'PASS', 'scope': 'Local Git protocol fixture only; no GitHub mutation or product tests',
            'checks': ['exact bundle identity retained', 'review ref fast-forward', 'product branch unchanged',
                       'idempotent rerun', 'bad digest refused', 'product ref refused'],
        }
        report.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))


if __name__ == '__main__':
    assert __debug__
    main()
