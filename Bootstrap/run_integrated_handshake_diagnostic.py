#!/usr/bin/env python3
"""One diagnostic call of original Integrated UI4 with temporary probe tracing.

The current diagnostic run and the old successful producer have distinct actual
identities. No GitHub identity is overwritten; no canonical consumer is forged.
This driver grants no runtime, release, D28 or full16 acceptance.
"""
import argparse
import datetime as dt
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'AAAHN-AAAHN/heiher-socks5-ios'
SOURCE = '7a8dbf7058b2677c3a4a8b7a4fe496bd97a96af6'
SOURCE_TREE = 'faee6667990a2f62bd8bc1a43e2af5e6c7cab80a'
DIAGNOSTIC_PARENT = 'd76294e376531c1b64be8620447745296d3de4e3'
PRODUCER_HELPER = '7875c96e11384908c2f8a0260b50de4d52f2c4cb'
PRODUCER_TREE = '83d45c7a40df765b8e5c4c59ff102707b31f1be4'
PRODUCER_PARENT = 'ca4f2c8fafb967a3f9cb064b73af7cb6affa1871'
PRODUCER_RUN, PRODUCER_ATTEMPT, PRODUCER_JOB = 41537968505, 1, 125594622722
ARTIFACT_ID, ARTIFACT_SIZE = 13188187488, 2204616
ARTIFACT_SHA = '12adafb8545e69b4564420215edd9dc990d749fbfa58bc78703469f3536e1a2d'
ARTIFACT_NAME = 'UDP-Echo-runtime-integrated-41537968505-1'
RECIPE_SHA = '74e8af3a339ae963c1ef551a7c8cb742b6e48835f3d7376b108650deabf045ee'
TRACE_CONTRACT_SHA = '45495c27dc87c7baec272e92ebed0b297e6f2970af90d2a9d3602252f7a2a5fc'
FORBIDDEN = ('e5980901a6c0b7a8b12ddc37461e22405f7dbe0e', '0a62910f5e444edbf176fe3ccd52363e5b8f869e')
PREREQUISITES = {
    '8bec30de328543f8f23b79a736385ed0e80aaa88', 'd1539f429b6a0e993adc9d50f816c3a29c3fac32',
    'e50f434be2610ef00713d39363963542db0020e2', 'd3f20d7e3905dcc300f0a5ebf155aa4cc2869774',
    'bf0789c68670078def846d7e3778e7f5cfe9e77f', '5d5327d4513b587e2a2e948fa20f588a04f1376f',
    'a55184fca134ce16b64335ac2f88b31b1161cd81', '953ee8d720cf32311d82dad1bcb1b566333c5d62'}
HEADS = {
    'statistics': '545d8690f30e82be990c536b3b2932d6d292c92f',
    'server': '59d5a05dfa8d94afd34d574b58e758b0efa681b9',
    'settings': 'e617a949c0fb0a0cbe1a80d47a4842f04feb6dda',
    'icon': 'b0a0e01b4414e4a6b3e89410b4bbfa8745e6c45d', 'integrated': SOURCE,
    'main': '0e030aedbd4127e9215b38bb23dd6e38c5872546',
    'udp': 'b05db817684d6b006353d5062fdba756d739faea',
    'background': 'e002fb55e95c35006683f8c8b182e99cd53b837c'}
HELPER_FILES = {
    'Bootstrap/candidates.json': 'ee1c3cd8b8b9a5bfe182d67a1ac3cc58a2b4e51fcfe399e1626f376a347bfb56',
    'Bootstrap/candidates.bundle': '55b142dcaddb6bddc9ab7563ad6cde3aa693ed327d5dfe6eeb63fbe8cbc44cfe',
    'Bootstrap/import_candidates.py': '1e647ab8a266a64097c5cc543f22d6a2c58010bfba8988b10fa4809589a6367e',
    'Bootstrap/ci_evidence.py': '827c8f69d562f60f416bfd9378b210beb9fa7aea28667716c54d4b449f5d3adc',
    'Bootstrap/runtime_handoff.py': '228dbcc1e3e28e682e1d956fd91a9100add223e613bb4aa09d47231e16499580'}
SOURCE_FILES = {
    'Build/ui_review.py': 'fdbe65201ac0b194299b8c8929530b316cdadfb641a1e252c2a1aadccb381f66',
    'Build/simulator_diagnostics.py': '98e6460e4c14524e034809b886aeee79fd58bb5a7c80359351ac7b0b293e86e2',
    'Build/release_source.py': 'c90aee96146fa2fa2ed0dd40bbf4cac9f1b4677506920a4dbb42c6316f80383b',
    'Build/review_handoff.py': '9f2122c1661e52495deea7f094fb3659574280e2f73bfe34064d3c839a2432bd',
    'Tests/Statistics/ui_audit.py': 'c94f9b0a87b45140a30252d8e535455fcb383c323c0301456bac9ad8d649a469',
    'Tests/Integration/IntegrationUITests.swift': '5654d9f5f107b4e1f65e3da7d8233ac9a002062979009f359e2c2e350e66727e',
    'Tests/Background/AsyncAudioUITests.swift': '14cfa19dbd0c8a167b3ea0f1d7412456a74449cbdd3843e8a15f46d03c34f260',
    'Tests/Statistics/StatisticsUITests.swift': 'e3865c71abf30ca76354cbe585c6ccb15f565bb28d3eb3ff0407da77e3cee574'}
SAFE_ENV = ('GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA',
            'GITHUB_REF', 'GITHUB_JOB', 'GITHUB_EVENT_NAME', 'RUNNER_OS', 'RUNNER_ARCH',
            'ImageOS', 'ImageVersion', 'DEVELOPER_DIR')
sys.dont_write_bytecode = True

def require(value, message):
    if not value:
        raise RuntimeError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')

def identity(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), 'Expected regular unlinked file: ' + str(path))
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': sha(raw), 'mode': stat.S_IMODE(info.st_mode)}

def child_environment():
    result = dict(os.environ)
    result.pop('GH_TOKEN', None)
    return result

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], env=child_environment(), timeout=60)

def git_text(root, *args):
    return git(root, *args).decode().strip()

def refs(root):
    return git(root, 'for-each-ref', '--format=%(refname) %(objectname)')

def snapshot(root):
    head, tree = git_text(root, 'rev-parse', 'HEAD'), git_text(root, 'rev-parse', 'HEAD^{tree}')
    git(root, 'diff', '--cached', '--no-ext-diff', '--no-textconv', '--exit-code', head, '--')
    files = {}
    for entry in git(root, 'ls-tree', '-rz', head).split(b'\0'):
        if not entry:
            continue
        meta, path_raw = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        name = os.fsdecode(path_raw)
        require(kind == 'blob' and mode in ('100644', '100755'), 'Unexpected tracked object')
        path = root / name
        require(path.resolve().is_relative_to(root.resolve()), 'Tracked path outside checkout')
        for parent in (path, *path.parents):
            require(not parent.is_symlink(), 'Linked tracked path')
            if parent == root:
                break
        record = identity(path)
        raw = path.read_bytes()
        require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == oid,
                'Tracked bytes differ: ' + name)
        require(bool(record['mode'] & 0o111) == (mode == '100755'), 'Tracked executable mode differs: ' + name)
        files[name] = dict(record, git_mode=mode, git_blob=oid)
    return {'commit': head, 'tree': tree, 'tracked_file_count': len(files), 'files': files}

def pinned_files(root, mapping):
    values = {name: identity(root / name) for name in mapping}
    require(all(values[n]['sha256'] == expected for n, expected in mapping.items()), 'Pinned validation code/input differs')
    return values

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def import_objects(producer, out):
    manifest = json.loads((producer / 'Bootstrap/candidates.json').read_bytes())
    candidates = {r['name']: r['sha'] for r in manifest['candidates']}
    support = {r['name']: r['sha'] for r in manifest['support']}
    require(len(candidates) == 5 and len(support) == 3 and {**candidates, **support} == HEADS,
            'Unexpected eight declared heads')
    require(all(r['ref'] == 'refs/heads/work/udp-echo-' + r['name'] + '-20261028' for r in manifest['candidates']),
            'Unexpected candidate labels')
    matrix = manifest['matrix']
    require(len(matrix) == 10 and len({(r['name'], r['os']) for r in matrix}) == 10, 'Unexpected matrix inventory')
    require(all(r['sha'] == candidates[r['name']] and r['os'] in ('ubuntu-24.04', 'xcode-27')
                and type(r['runtime']) is bool and r['runtime'] == (r['os'] == 'xcode-27') for r in matrix),
            'Unexpected exact matrix row')
    bundle = producer / 'Bootstrap/candidates.bundle'
    require(sha(bundle.read_bytes()) == manifest['sha256'] == HELPER_FILES['Bootstrap/candidates.bundle'], 'Bundle hash differs')
    header = bundle.read_bytes().split(b'\n\n', 1)[0].decode()
    require({line[1:41] for line in header.splitlines() if line.startswith('-')} == PREREQUISITES,
            'Original eight bundle prerequisites differ')
    listed = [line.split(' ', 1) for line in git_text(producer, 'bundle', 'list-heads', str(bundle)).splitlines()]
    expected = [[v, 'refs/heads/candidate/' + n] for n, v in candidates.items()]
    expected += [[v, 'refs/heads/support/' + n] for n, v in support.items()]
    require(sorted(listed) == sorted(expected), 'Bundle head inventory differs')
    before = refs(producer)
    verified = git(producer, 'bundle', 'verify', str(bundle))
    unbundled = git(producer, 'bundle', 'unbundle', str(bundle))
    require(refs(producer) == before, 'Object import changed refs')
    ancestry = []
    for name, commit in HEADS.items():
        require(git_text(producer, 'cat-file', '-t', commit) == 'commit', 'Expected candidate commit')
        for forbidden in FORBIDDEN:
            check = subprocess.run(['git', '-C', str(producer), 'merge-base', '--is-ancestor', forbidden, commit],
                                   env=child_environment(), capture_output=True, timeout=60)
            require(check.returncode == 1, 'Forbidden ancestry or missing original ancestry evidence')
            ancestry.append({'owner': name, 'commit': commit, 'forbidden': forbidden, 'exit_code': check.returncode})
    record = {'scope': 'Object import only, no original importer main/context invoked and no ref updates',
              'manifest_sha256': HELPER_FILES['Bootstrap/candidates.json'], 'bundle_sha256': manifest['sha256'],
              'heads': listed, 'prerequisites': sorted(PREREQUISITES), 'ancestry': ancestry,
              'refs_before': before.decode(), 'refs_after': refs(producer).decode(),
              'bundle_verify_stdout': verified.decode(), 'unbundle_stdout': unbundled.decode(),
              'original_importer_source_sha256': HELPER_FILES['Bootstrap/import_candidates.py']}
    write_json(out / 'object-import.json', record)
    return before

class CaptureResponse:
    """Transparent logging of the original api() response's bytes read by json.load."""
    def __init__(self, response, path, folder, sequence, requested):
        self.response, self.path, self.folder = response, path, folder
        self.sequence, self.requested, self.chunks = sequence, requested, []
        self.complete = False
    def __enter__(self):
        self.response.__enter__()
        return self
    def read(self, size=-1):
        raw = self.response.read(size)
        self.chunks.append(raw)
        if size == -1 or not raw:
            self.complete = True
        return raw
    def __exit__(self, *error):
        raw = b''.join(self.chunks)
        body = self.folder / f'{self.sequence:02d}-body.json'
        with body.open('xb') as stream:
            stream.write(raw)
        safe_headers = {k: self.response.headers.get(k) for k in ('Date', 'Content-Type', 'ETag', 'X-GitHub-Request-Id')}
        write_json(self.folder / f'{self.sequence:02d}-request.json', {
            'request': {'method': 'GET', 'url': 'https://api.github.com/repos/' + REPOSITORY + self.path},
            'requested_utc': self.requested, 'received_utc': utc(), 'HTTP_status': self.response.status,
            'safe_response_headers': safe_headers, 'body_path': body.name, 'body': identity(body),
            'complete_response_read': self.complete, 'credential_or_redirect_url_recorded': False})
        return self.response.__exit__(*error)

def actual_input(ci, producer, actual, out, counts):
    folder = out / 'actual-api'
    folder.mkdir()
    original_api = ci.api
    request_sequence = 0
    def capturing_api(path):
        nonlocal request_sequence
        request_sequence += 1
        requested = utc()
        response = original_api(path)
        return CaptureResponse(response, path, folder, request_sequence, requested)
    ci.api = capturing_api
    try:
        current = ci.api_json(f"/actions/runs/{actual['GITHUB_RUN_ID']}/attempts/{actual['GITHUB_RUN_ATTEMPT']}")
        require(current['id'] == int(actual['GITHUB_RUN_ID']) and current['run_attempt'] == int(actual['GITHUB_RUN_ATTEMPT'])
                and current['head_sha'] == actual['GITHUB_SHA'] and current['status'] == 'in_progress',
                'Current actual diagnostic run identity differs')
        require(current['repository']['full_name'] == REPOSITORY and current['event'] == actual['GITHUB_EVENT_NAME'],
                'Current actual diagnostic repository/event differs')
        old = ci.api_json(f'/actions/runs/{PRODUCER_RUN}/attempts/{PRODUCER_ATTEMPT}')
        require(old['id'] == PRODUCER_RUN and old['run_attempt'] == PRODUCER_ATTEMPT and old['head_sha'] == PRODUCER_HELPER
                and old['status'] == 'completed' and old['conclusion'] == 'failure', 'Original failed attempt identity differs')
        jobs = ci.pages(f'/actions/runs/{PRODUCER_RUN}/attempts/{PRODUCER_ATTEMPT}/jobs', 'jobs')
        require(len(jobs) == len({j['id'] for j in jobs}) == 26, 'Original completed job inventory differs')
        require(all(j['run_id'] == PRODUCER_RUN and j['run_attempt'] == PRODUCER_ATTEMPT and j['head_sha'] == PRODUCER_HELPER
                    and j['status'] == 'completed' for j in jobs), 'Old job generation/status differs')
        expected = f'build (integrated, {SOURCE}, xcode-27, true)'
        verified_job = ci.completed_job(jobs, expected, 'Execute the exact candidate owner gates')
        require(verified_job['id'] == PRODUCER_JOB, 'Original exact numeric successful producer differs')
        artifacts = ci.pages(f'/actions/runs/{PRODUCER_RUN}/artifacts', 'artifacts')
        selected = [a for a in artifacts if a['id'] == ARTIFACT_ID or a['name'] == ARTIFACT_NAME]
        require(len(selected) == 1, 'Original exact input artifact is absent or duplicated')
        metadata = selected[0]
        require(metadata['id'] == ARTIFACT_ID and metadata['name'] == ARTIFACT_NAME and metadata['expired'] is False,
                'Original input identity/expiry differs')
        require(metadata['size_in_bytes'] == ARTIFACT_SIZE and metadata['digest'] == 'sha256:' + ARTIFACT_SHA
                and metadata['workflow_run']['id'] == PRODUCER_RUN and metadata['workflow_run']['head_sha'] == PRODUCER_HELPER,
                'Original input immutable bytes/generation differs')
        metadata = dict(metadata, verified_producer_job=verified_job)
        require(counts['artifact_download_requests'] == 0, 'No download retry is permitted')
        counts['artifact_download_requests'] += 1
        storage_host = None
        try:
            response = original_api(f'/actions/artifacts/{ARTIFACT_ID}/zip')
        except urllib.error.HTTPError as error:
            require(error.code in (301, 302, 303, 307, 308), 'Original artifact API did not return a download')
            location = error.headers['Location']
            parts = urllib.parse.urlsplit(location)
            require(parts.scheme == 'https' and parts.hostname and parts.username is None and parts.password is None
                    and parts.port in (None, 443) and any(parts.hostname.endswith(suffix) for suffix in
                        ('.blob.core.windows.net', '.githubusercontent.com')), 'Unexpected storage download host')
            storage_host = parts.hostname
            try:
                # This independent signed storage request has no GitHub auth header.
                response = urllib.request.urlopen(location, timeout=60)
            except Exception as storage_error:
                raise RuntimeError('Original artifact storage request failed: ' + type(storage_error).__name__) from None
        archive = out / 'original-producer-runtime-input.zip'
        count, digest = 0, hashlib.sha256()
        with response, archive.open('xb') as stream:
            while block := response.read(1024 * 1024):
                count += len(block)
                require(count <= ARTIFACT_SIZE, 'Downloaded input exceeds immutable artifact size')
                stream.write(block)
                digest.update(block)
        require(count == ARTIFACT_SIZE and digest.hexdigest() == ARTIFACT_SHA, 'Original input ZIP digest/size differs')
        write_json(out / 'actual-producer-artifact.json', metadata)
        write_json(out / 'actual-api-binding.json', {
            'scope': 'Current actual diagnostic run separately bound to original completed producer inputs',
            'current_diagnostic_run': current, 'original_attempt': old, 'original_producer_job': verified_job,
            'original_producer_artifact': metadata, 'API_JSON_requests': request_sequence,
            'artifact_download_requests': counts['artifact_download_requests'], 'archive': identity(archive),
            'redirect_storage_host': storage_host, 'redirect_url_recorded': False,
            'GitHub_credential_sent_to_storage': False, 'same_run_consumer_claimed': False})
        return archive, metadata
    finally:
        ci.api = original_api

def load_recipe(path):
    require(identity(path)['sha256'] == RECIPE_SHA, 'Reviewed trace recipe bytes differ')
    recipe = json.loads(path.read_bytes())
    require(recipe['schema'] == 1 and recipe['source_commit'] == SOURCE
            and recipe['trace_contract_sha256'] == TRACE_CONTRACT_SHA and recipe['replace_count'] == 1,
            'Trace proposal identity differs')
    for kind in ('before', 'after'):
        require(sha(recipe[kind + '_fragment'].encode()) == recipe[kind + '_fragment_sha256'], 'Trace fragment digest differs')
    return recipe

def tree_files(root):
    result = {}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'Unexpected temporary application symlink')
        if p.is_file():
            result[p.relative_to(root).as_posix()] = identity(p)
    return result

def apply_trace(application, source, recipe, out):
    target = application / 'StatisticsUITests.swift'
    raw = target.read_bytes()
    originals = ('Tests/Integration/IntegrationUITests.swift', 'Tests/Background/AsyncAudioUITests.swift', 'Tests/Statistics/StatisticsUITests.swift')
    expected = b'\n'.join((source / n).read_bytes() for n in originals)
    require(raw == expected and sha(raw) == recipe['before_generated_sha256'], 'Original generated UI4 test source differs')
    before, after = recipe['before_fragment'].encode(), recipe['after_fragment'].encode()
    require(raw.count(before) == 1, 'Temporary exact handshake fragment is missing or duplicated')
    changed = raw.replace(before, after, 1)
    require(sha(changed) == recipe['after_generated_sha256'], 'Temporary traced UI4 source differs')
    original_tree = tree_files(application)
    raw_mode = target.stat().st_mode
    with (out / 'temporary-generated-tests.before.swift').open('xb') as stream:
        stream.write(raw)
    with target.open('wb') as stream:
        stream.write(changed)
    require(target.stat().st_mode == raw_mode and target.read_bytes() == changed, 'Temporary trace write changed mode/bytes')
    after_tree = tree_files(application)
    require(set(after_tree) == set(original_tree), 'Trace changed temporary application inventory')
    differences = [n for n in original_tree if original_tree[n] != after_tree[n]]
    require(differences == ['StatisticsUITests.swift'], 'Trace changed more than the temporary test file')
    with (out / 'temporary-generated-tests.after.swift').open('xb') as stream:
        stream.write(changed)
    diff = ''.join(difflib.unified_diff(raw.decode().splitlines(True), changed.decode().splitlines(True),
                                      fromfile='temporary-generated-tests.before.swift', tofile='temporary-generated-tests.after.swift'))
    with (out / 'temporary-generated-tests.diff').open('x') as stream:
        stream.write(diff)
    record = {'scope': 'Only diagnostic temporary test function tracing; no product/source change or test-isolation fix',
              'target': str(target), 'before_sha256': sha(raw), 'after_sha256': sha(changed), 'exact_replace_count': 1,
              'unchanged_original_test_cases': 4, 'changed_temporary_files': differences,
              'temporary_application_before': original_tree, 'temporary_application_after': after_tree,
              'recipe_sha256': RECIPE_SHA, 'trace_contract_sha256': TRACE_CONTRACT_SHA,
              'original_assertions_socket_parameters_and_timeouts_unchanged': True, 'gate_credit': 0}
    write_json(out / 'temporary-trace-receipt.json', record)
    return record

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--producer-helper', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    diagnostic = Path(__file__).resolve().parents[1]
    producer = options.producer_helper.resolve(strict=True)
    source, out = options.source.resolve(), options.output.resolve()
    temporary = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    require(source.is_relative_to(temporary) and out.is_relative_to(temporary) and source != out
            and source not in out.parents and out not in source.parents, 'Use separate fresh temporary source/output paths')
    require(not source.exists(), 'Diagnostic source worktree must be fresh')
    out.mkdir(parents=True, exist_ok=False)
    actual = {k: os.environ.get(k) for k in SAFE_ENV}
    result = {'schema': 1, 'scope': 'One unchanged original UI4 call with diagnostic temporary handshake trace only',
              'started_utc': utc(), 'actual_current_GitHub_environment': actual,
              'original_ui_called': 0, 'original_build_for_testing_calls': 0, 'original_test_without_building_calls': 0,
              'artifact_download_requests': 0, 'temporary_trace_applications': 0,
              'original_ui_exception': None, 'preparation_exception': None, 'readback_errors': [],
              'source_or_production_mutation_authorized': False, 'same_run_consumer_claimed': False,
              'runtime_accepted': False, 'canonical_accepted': False, 'D28_accepted': False, 'full16_accepted': False,
              'publication_accepted': False, 'gate_credit': 0}
    failure = failure_traceback = None
    source_before = producer_before = diagnostic_before = None
    producer_refs = diagnostic_refs = None
    helper = ui = release_source = None
    targets = payloads = None
    old_sys_path = list(sys.path)
    try:
        require(__debug__ and sys.flags.optimize == 0 and sys.platform == 'darwin' and actual['RUNNER_OS'] == 'macOS',
                'Requires assertions and the actual Apple runtime job')
        require(actual['GITHUB_REPOSITORY'] == REPOSITORY and actual['GITHUB_RUN_ATTEMPT'] == '1'
                and re.fullmatch(r'[1-9][0-9]*', actual['GITHUB_RUN_ID'] or '')
                and re.fullmatch(r'[0-9a-f]{40}', actual['GITHUB_SHA'] or ''), 'Unexpected actual GitHub environment')
        require(actual['GITHUB_JOB'] and actual['GITHUB_EVENT_NAME'], 'Missing actual diagnostic workflow identity')
        require(actual['DEVELOPER_DIR'] == '/Applications/Xcode_27.app/Contents/Developer', 'Unexpected selected Xcode path')
        require(os.environ.get('GH_TOKEN'), 'Authenticated artifact read requires the workflow token')
        diagnostic_before, producer_before = snapshot(diagnostic), snapshot(producer)
        require(diagnostic_before['commit'] == actual['GITHUB_SHA'] and git_text(diagnostic, 'rev-parse', 'HEAD^') == DIAGNOSTIC_PARENT,
                'Current diagnostic checkout/parent differs')
        require(producer_before['commit'] == PRODUCER_HELPER and producer_before['tree'] == PRODUCER_TREE
                and git_text(producer, 'rev-parse', 'HEAD^') == PRODUCER_PARENT, 'Original producer helper checkout differs')
        diagnostic_refs, producer_refs = refs(diagnostic), refs(producer)
        result['original_helper_validation_files'] = pinned_files(producer, HELPER_FILES)
        result['diagnostic_driver'] = identity(Path(__file__))
        recipe_path = Path(__file__).with_name('integrated_handshake_trace.json')
        recipe = load_recipe(recipe_path)
        result['trace_recipe'] = identity(recipe_path)
        require(import_objects(producer, out) == producer_refs, 'Unexpected refs before importing exact objects')
        require(git_text(producer, 'rev-parse', SOURCE + '^{tree}') == SOURCE_TREE, 'Exact source tree differs')
        git(producer, 'worktree', 'add', '--detach', str(source), SOURCE)
        source_before = snapshot(source)
        require(source_before['commit'] == SOURCE and source_before['tree'] == SOURCE_TREE
                and source_before['tracked_file_count'] == 313, 'Original source snapshot differs')
        write_json(out / 'source-before.json', source_before)
        result['original_owner_validation_files'] = pinned_files(source, SOURCE_FILES)
        ci = load_module(producer / 'Bootstrap/ci_evidence.py', 'exact_original_producer_ci_evidence')
        archive, metadata = actual_input(ci, producer, actual, out, result)
        # The old API input is fully verified now. No credential reaches any
        # original owner/UI/compiler/fixture import or child process below.
        os.environ.pop('GH_TOKEN', None)
        require('GH_TOKEN' not in os.environ, 'Workflow credential was not removed')
        result['credential_removed_before_owner_imports'] = True
        result['credential_removed_utc'] = utc()
        helper = load_module(producer / 'Bootstrap/runtime_handoff.py', 'exact_original_producer_runtime_handoff')
        source_identity = {'commit': SOURCE, 'tree': SOURCE_TREE}
        require(helper.identity(source) == source_identity, 'Original full raw source identity check failed')
        exported, tar_bytes = helper.read_artifact(archive, metadata)
        expected_old_producer = {'repository': REPOSITORY, 'run_id': str(PRODUCER_RUN), 'attempt': str(PRODUCER_ATTEMPT),
                                 'job': 'build', 'helper': {'commit': PRODUCER_HELPER, 'tree': PRODUCER_TREE}, 'runner_os': 'macOS'}
        pins = json.loads((source / 'Build/features.json').read_bytes())['sources']
        require(exported['schema'] == 1 and type(exported['schema']) is int and exported['status'] == 'VERIFIED_RUNTIME_INPUT_EXPORTED'
                and exported['producer'] == expected_old_producer and exported['source'] == source_identity
                and exported['candidate'] == 'integrated' and exported['native_pins'] == pins
                and exported['artifact_name'] == ARTIFACT_NAME, 'Original authenticated producer receipt differs')
        tar = out / 'original-producer-runtime-input.tar.gz'
        with tar.open('xb') as stream:
            stream.write(tar_bytes)
        manifest, payloads = helper.read_archive(tar, exported['archive_sha256'], 'integrated', source)
        require({k: v for k, v in manifest.items() if k != 'files'} ==
                {k: exported[k] for k in ('schema', 'candidate', 'source', 'native_pins', 'producer')}, 'Manifest/producer identity differs')
        helper.validate_payloads('integrated', source, source_identity, manifest, payloads)
        require(len(payloads) == 321, 'Original complete321 payload inventory differs')
        targets = helper.destinations('integrated', source, payloads)
        for name, destination in targets.items():
            raw, mode = payloads[name]
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(raw)
            destination.chmod(mode)
            require(helper.read_file(destination) == (raw, mode), 'Restored original payload bytes/mode differ')
        release_source = sys.modules['release_source']
        release_source.check_product()
        write_json(out / 'cross-run-diagnostic-input-receipt.json', {
            'scope': 'Actual cross-run diagnostic input only; not an original same-run runtime consumer receipt',
            'actual_current_consumer_environment': actual, 'original_actual_producer': expected_old_producer,
            'original_actual_API_producer_job': metadata['verified_producer_job'], 'original_actual_API_artifact': metadata,
            'original_ZIP': identity(archive), 'original_TAR': identity(tar), 'original_exported_receipt': exported,
            'original_manifest': manifest, 'payload_count': len(payloads), 'all_payloads_bytes_modes_read_back': True,
            'original_check_product_completed': True,
            'original_functions_used': ['identity', 'read_artifact', 'read_archive', 'validate_payloads', 'destinations', 'read_file', 'integrated.check_payloads', 'release_source.check_product'],
            'context_restore_and_check_producer_called': False, 'GITHUB_identity_override': False,
            'same_run_consumer_claimed': False, 'runtime_accepted': False, 'gate_credit': 0})
        sys.path.insert(0, str(source / 'Build'))
        ui = load_module(source / 'Build/ui_review.py', 'exact_original_integrated_ui_diagnostic_call')
        original_run = ui.run
        def traced_run(args, log, timeout=180, cwd=ui.ROOT, timing=False):
            command = list(map(str, args))
            if command[:2] == ['xcodebuild', 'build-for-testing']:
                require(result['original_build_for_testing_calls'] == 0 and result['temporary_trace_applications'] == 0,
                        'No repeated diagnostic build or trace application is allowed')
                require(timeout == 900, 'Original build timeout differs')
                result['original_build_for_testing_calls'] += 1
                apply_trace(ui.WORK / 'application', source, recipe, out)
                result['temporary_trace_applications'] += 1
            if command[:2] == ['xcodebuild', 'test-without-building']:
                require(result['original_test_without_building_calls'] == 0 and result['temporary_trace_applications'] == 1,
                        'No diagnostic test retry or untraced test call is allowed')
                require(timeout == 900 and not any(x.startswith(('-only-testing', '-skip-testing')) for x in command),
                        'Original full UI4 command/deadline differs')
                result['original_test_without_building_calls'] += 1
            return original_run(args, log, timeout=timeout, cwd=cwd, timing=timing)
        ui.run = traced_run
        require(result['original_ui_called'] == 0, 'No diagnostic UI retry is permitted')
        result['original_ui_called'] += 1
        try:
            # Original main retains its own original failure handling and cleanup.
            ui.main()
        except BaseException as error:
            result['original_ui_exception'] = traceback.format_exc()
            with (out / 'original-ui-exception.txt').open('x') as stream:
                stream.write(result['original_ui_exception'])
            failure, failure_traceback = error, error.__traceback__
        finally:
            ui.run = original_run
        result['original_ui_completed_without_exception'] = result['original_ui_exception'] is None
    except BaseException as error:
        result['preparation_exception'] = traceback.format_exc()
        if failure is None:
            failure, failure_traceback = error, error.__traceback__
    finally:
        os.environ.pop('GH_TOKEN', None)
        result['credential_present_at_finish'] = 'GH_TOKEN' in os.environ
        if source_before is not None:
            try:
                after = snapshot(source)
                write_json(out / 'source-after.json', after)
                require(after == source_before, 'Original313 tracked source bytes/modes changed')
                result['source_before_after_identical'] = True
                pinned_files(source, SOURCE_FILES)
            except BaseException:
                result['readback_errors'].append(traceback.format_exc())
        if targets is not None and payloads is not None:
            try:
                readback = {}
                for name, path in targets.items():
                    require(helper.read_file(path) == payloads[name], 'Original restored product/native/phase input changed: ' + name)
                    readback[name] = identity(path)
                release_source.check_product()
                write_json(out / 'original321-payload-after-readback.json', readback)
                result['original321_payload_bytes_modes_unchanged'] = True
            except BaseException:
                result['readback_errors'].append(traceback.format_exc())
        for name, root, before, before_refs in (('diagnostic', diagnostic, diagnostic_before, diagnostic_refs),
                                               ('producer', producer, producer_before, producer_refs)):
            if before is not None:
                try:
                    after = snapshot(root)
                    require(after == before and refs(root) == before_refs, 'Helper tracked files or refs changed: ' + name)
                    write_json(out / (name + '-helper-after.json'), after)
                    result[name + '_helper_tracked_bytes_modes_and_refs_unchanged'] = True
                except BaseException:
                    result['readback_errors'].append(traceback.format_exc())
        if ui is not None:
            result['original_UI_artifact_directory'] = str(ui.OUT)
            traced = ui.WORK / 'application/StatisticsUITests.swift'
            if result['temporary_trace_applications']:
                try:
                    require(identity(traced)['sha256'] == recipe['after_generated_sha256'], 'Compiled temporary trace source changed')
                    result['temporary_traced_source_after'] = identity(traced)
                except BaseException:
                    result['readback_errors'].append(traceback.format_exc())
        sys.path[:] = old_sys_path
        result['finished_utc'] = utc()
        result['result'] = 'DIAGNOSTIC_RECORD_ONLY_NO_GATE_CREDIT'
        result['limits'] = ['Trace logging may affect timing within the unchanged original wait budget.',
                            'Any diagnostic success does not replace candidate26 failures or establish release acceptance.',
                            'All original4 test cases, assertions, socket parameters, UI900/900 and cleanup30 timeouts remain unchanged.',
                            'No extra network probe, host query, prewarm, reset or Simulator lifecycle command is added.']
        write_json(out / 'diagnostic-result.json', result)
    if failure is not None:
        raise failure.with_traceback(failure_traceback)
    require(result['original_ui_called'] == result['original_build_for_testing_calls'] ==
            result['original_test_without_building_calls'] == result['temporary_trace_applications'] == 1,
            'Diagnostic did not execute exactly one original UI/build/test call')
    require(not result['readback_errors'], 'Diagnostic source/product evidence readback failed')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
