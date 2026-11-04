#!/usr/bin/env python3
"""Bind two exact checkouts and import the source objects without changing GITHUB_SHA.

Only the historical importer's one workflow-head comparison is adapted: the
control checkout must match the real GITHUB_SHA, and the separate source-input
checkout must match its pinned015543 identity. Every other importer byte remains.
"""
import argparse
import ast
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ORIGINAL_BINDING = (
    "    require(helper == os.environ.get('GITHUB_SHA'), 'Checkout must be the exact helper commit')\n"
)
ADAPTED_BINDING = (
    "    require(helper == SOURCE_INPUT_COMMIT, 'Source-input checkout must be the exact pinned helper commit')\n"
)


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def adapt_importer(original):
    require(original.count(ORIGINAL_BINDING) == 1, 'Original importer context anchor differs')
    adapted = original.replace(ORIGINAL_BINDING, ADAPTED_BINDING, 1)
    require(adapted.replace(ADAPTED_BINDING, ORIGINAL_BINDING, 1) == original,
            'Importer adapter changed additional original bytes')
    old_tree, new_tree = ast.parse(original), ast.parse(adapted)
    old_functions = {n.name: ast.dump(n, include_attributes=False) for n in old_tree.body if isinstance(n, ast.FunctionDef)}
    new_functions = {n.name: ast.dump(n, include_attributes=False) for n in new_tree.body if isinstance(n, ast.FunctionDef)}
    require(set(old_functions) == set(new_functions), 'Importer function set changed')
    require([n for n in old_functions if old_functions[n] != new_functions[n]] == ['main'],
            'Importer adapter changed another function')
    return adapted


def save_new(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--source-input', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, 'Assertions must remain enabled')
    control = args.control.resolve(strict=True)
    source_input = args.source_input.resolve(strict=True)
    root, out = args.root.resolve(), args.output.resolve()
    require(control != source_input and not control.is_relative_to(source_input)
            and not source_input.is_relative_to(control), 'Control and source-input checkouts must be disjoint')
    require(not root.exists() and not out.exists(), 'Refusing to replace a worktree or diagnostic evidence')
    require(not root.is_relative_to(control) and not root.is_relative_to(source_input),
            'Candidate worktree must be separate from the two checkouts')
    out.mkdir(parents=True)
    report = {'schema': 1, 'scope': 'Explicit input identity adapter; not candidate or runtime acceptance',
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'result': 'INPUT_PREPARATION_FAILED', 'original_importer_main_unmodified': False,
              'one_identity_comparison_adapted': True, 'all_other_importer_bytes_preserved': False,
              'GITHUB_identity_overrides': 0, 'source_worktree_created': False,
              'candidate_credit': False, 'remote_mutations': 0, 'secondary_recording_errors': []}
    failure = None
    saved_traceback = None
    original_env_identity = {k: os.environ.get(k) for k in
                             ('GITHUB_SHA', 'GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB')}
    try:
        pins = json.loads(args.pins.read_bytes())
        require(os.environ.get('GITHUB_REPOSITORY') == pins['repository'], 'Wrong actual diagnostic repository')
        require(os.environ.get('GITHUB_JOB') == 'diagnose_statistics_only', 'Unexpected diagnostic job')
        require(re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', '')), 'Invalid actual control SHA')
        require(int(os.environ['GITHUB_RUN_ID']) != pins['origin_run_id'], 'A new diagnostic cannot impersonate its origin run')
        validator = control / 'Bootstrap/runtime_handoff.py'
        require(sha(validator.read_bytes()) == pins['validator_sha256']['Bootstrap/runtime_handoff.py'],
                'Original runtime identity/payload helper differs')
        rh = load_module('current_input_original_runtime_handoff', validator)
        control_identity = rh.identity(control)
        require(control_identity['commit'] == os.environ['GITHUB_SHA'], 'Control checkout differs from real GITHUB_SHA')
        input_identity = rh.identity(source_input)
        require(input_identity == pins['source_input_helper'], 'Source-input checkout is not exact015543')
        file_proofs = {}
        for name, expected in pins['source_input_files'].items():
            actual = record(source_input / name)
            require({k: actual[k] for k in ('bytes', 'sha256')} == expected, 'Source-input file differs: ' + name)
            file_proofs[name] = actual
        original_path = source_input / 'Bootstrap/import_candidates.py'
        original = original_path.read_text()
        require(original.encode() == original_path.read_bytes(), 'Original importer text normalization changed bytes')
        adapted = adapt_importer(original)
        (out / 'original-import_candidates.py').write_bytes(original_path.read_bytes())
        (out / 'bound-source-input-importer.py').write_text(adapted)
        diff = ''.join(difflib.unified_diff(original.splitlines(keepends=True), adapted.splitlines(keepends=True),
                                           fromfile='original015543/import_candidates.py',
                                           tofile='source-input-identity-adapter/import_candidates.py'))
        (out / 'source-input-identity-only.diff').write_text(diff)
        report.update(actual_control=control_identity, source_input=input_identity, source_input_files=file_proofs,
                      actual_diagnostic_identity=original_env_identity,
                      importer_adapter_diff=record(out / 'source-input-identity-only.diff'),
                      all_other_importer_bytes_preserved=True)
        save_new(out / 'identity-binding-before-import.json', report)
        raw_result = source_input / 'artifacts/candidate-prepare/result.json'
        require(not raw_result.exists(), 'Fresh source-input checkout already contains importer output')
        refs_before = rh.git(source_input, 'for-each-ref', '--format=%(refname) %(objectname)')
        control_refs_before = rh.git(control, 'for-each-ref', '--format=%(refname) %(objectname)')
        namespace = {'__name__': 'current_bound_source_input_importer', '__file__': str(original_path),
                     'SOURCE_INPUT_COMMIT': pins['source_input_helper']['commit']}
        exec(compile(adapted, str(out / 'bound-source-input-importer.py'), 'exec'), namespace)
        argv = sys.argv
        try:
            sys.argv = [str(original_path), '--candidate', 'statistics', '--sha', pins['source']['commit']]
            namespace['main']()
        finally:
            sys.argv = argv
        require({k: os.environ.get(k) for k in original_env_identity} == original_env_identity,
                'A diagnostic GitHub identity was changed')
        require(rh.git(source_input, 'for-each-ref', '--format=%(refname) %(objectname)') == refs_before,
                'Source-input importer changed refs')
        require(rh.identity(source_input) == input_identity and rh.identity(control) == control_identity,
                'Original source-input/control bytes or identity changed')
        (out / 'actual-source-input-importer-result.json').write_bytes(raw_result.read_bytes())
        report['input_importer_result'] = record(out / 'actual-source-input-importer-result.json')
        command = ['git', '-C', str(source_input), 'worktree', 'add', '--detach', str(root), pins['source']['commit']]
        report['worktree_create_command'] = command
        with (out / 'worktree-create.log').open('xb') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
        report['source_worktree_created'] = True
        actual_source = rh.identity(root)
        require(actual_source == pins['source'], 'Detached source worktree differs from actual5bb Statistics commit/tree')
        require(rh.git(source_input, 'for-each-ref', '--format=%(refname) %(objectname)') == refs_before,
                'Detached worktree creation changed input refs')
        require(rh.git(control, 'for-each-ref', '--format=%(refname) %(objectname)') == control_refs_before,
                'Control refs changed during input preparation')
        require(rh.identity(source_input) == input_identity and rh.identity(control) == control_identity,
                'Control/source-input source bytes changed during worktree creation')
        report.update(result='DIAGNOSTIC_SOURCE_INPUT_PREPARED_NOT_CANDIDATE', actual_source=actual_source,
                      source_worktree=str(root), refs_unchanged=True)
    except BaseException as error:
        failure, saved_traceback = error, error.__traceback__
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            require({k: os.environ.get(k) for k in original_env_identity} == original_env_identity,
                    'A diagnostic GitHub identity was changed')
        except BaseException as error:
            if failure is None:
                failure, saved_traceback = error, error.__traceback__
                report['failure'] = {'type': type(error).__name__, 'message': str(error)}
                report['result'] = 'INPUT_PREPARATION_FAILED'
            else:
                report['secondary_recording_errors'].append({'stage': 'identity-final-check', 'type': type(error).__name__, 'message': str(error)})
        try:
            save_new(out / 'current-input-preparation.json', report)
        except BaseException as error:
            if failure is None:
                failure, saved_traceback = error, error.__traceback__
            try:
                sys.stderr.write('Could not save diagnostic input result: ' + type(error).__name__ + '\n')
            except BaseException:
                pass
    if failure is not None:
        raise failure.with_traceback(saved_traceback)
    print('DIAGNOSTIC_SOURCE_INPUT_PREPARED_NOT_CANDIDATE source=' + report['actual_source']['commit'])


if __name__ == '__main__':
    main()
