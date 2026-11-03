#!/usr/bin/env python3
"""Restore pinned historical producer bytes for diagnostics, never candidate CI.

This is a proposal file outside the repository. A future diagnostic helper may
run it with its real GitHub identity. The origin run and the new diagnostic run
remain distinct; no GITHUB_* identity is overridden and no candidate gate runs.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def api(repository, path):
    request = urllib.request.Request('https://api.github.com/repos/' + repository + path,
                                    headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                                             'Accept': 'application/vnd.github+json',
                                             'X-GitHub-Api-Version': '2022-11-28'})
    return urllib.request.build_opener(NoRedirect).open(request, timeout=30)


def api_json(repository, path):
    with api(repository, path) as response:
        return json.load(response)


def download(repository, artifact_id, destination):
    try:
        response = api(repository, f'/actions/artifacts/{artifact_id}/zip')
    except urllib.error.HTTPError as error:
        require(error.code in (301, 302, 303, 307, 308), 'Artifact download failed')
        location = error.headers['Location']
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == 'https' and parsed.hostname and
                any(parsed.hostname.endswith(suffix) for suffix in
                    ('.blob.core.windows.net', '.githubusercontent.com')),
                'Unexpected artifact storage host')
        # No GitHub token follows the signed storage redirect; the URL is not saved.
        response = urllib.request.urlopen(location, timeout=60)
    with response, destination.open('xb') as stream:
        shutil.copyfileobj(response, stream)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, 'Assertions must be enabled')
    helper, root = args.helper.resolve(strict=True), args.root.resolve(strict=True)
    pins = json.loads(args.pins.read_bytes())
    require(os.environ['GITHUB_REPOSITORY'] == pins['repository'], 'Wrong diagnostic repository')
    require(os.environ['RUNNER_OS'] == 'macOS', 'Diagnostic requires the Apple runner')
    require(os.environ['GITHUB_JOB'] == 'diagnose_audio_only', 'Unexpected diagnostic job')
    require(re.fullmatch(r'[0-9a-f]{40}', os.environ['GITHUB_SHA']), 'Invalid actual helper SHA')
    require(int(os.environ['GITHUB_RUN_ID']) != pins['origin_run_id'],
            'Diagnostic must not impersonate the historical candidate run')
    out = args.output.resolve()
    require(not out.exists(), 'Refusing to overwrite prior diagnostic input evidence')
    out.mkdir(parents=True)
    runtime_path = helper / 'Bootstrap/runtime_handoff.py'
    require(sha256(runtime_path.read_bytes()) == pins['validator_sha256']['Bootstrap/runtime_handoff.py'],
            'Original runtime payload validator changed')
    rh = module('diagnostic_original_runtime_handoff', runtime_path)
    helper_identity = rh.identity(helper)
    require(helper_identity['commit'] == os.environ['GITHUB_SHA'], 'Actual helper checkout differs')
    source = rh.identity(root)
    require(source == pins['source'], 'Diagnostic source differs from the pinned historical source')
    for name, expected in pins['validator_sha256'].items():
        if name.startswith('Build/'):
            require(sha256((root / name).read_bytes()) == expected, 'Changed source validator: ' + name)
    for name, expected in pins['ui_source_sha256'].items():
        require(sha256((root / name).read_bytes()) == expected, 'Changed original UI source: ' + name)
    diagnostic = {'repository': os.environ['GITHUB_REPOSITORY'],
                  'run_id': int(os.environ['GITHUB_RUN_ID']),
                  'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']),
                  'job': os.environ['GITHUB_JOB'], 'helper': helper_identity,
                  'runner_os': os.environ['RUNNER_OS'],
                  'purpose': 'DIAGNOSTIC_ONLY_HISTORICAL_PRODUCER_INPUT'}
    save(out / 'diagnostic-context.json', diagnostic)
    shutil.copyfile(args.pins, out / 'historical-input-pins.json')

    repo = pins['repository']
    origin_run = api_json(repo, f"/actions/runs/{pins['origin_run_id']}/attempts/{pins['origin_attempt']}")
    producer_job = api_json(repo, f"/actions/jobs/{pins['origin_producer_job_id']}")
    producer_metadata = api_json(repo, f"/actions/artifacts/{pins['producer_artifact']['id']}")
    input_metadata = api_json(repo, f"/actions/artifacts/{pins['input_artifact']['id']}")
    for name, value in (('origin-run-attempt-api.json', origin_run),
                        ('origin-producer-job-api.json', producer_job),
                        ('origin-producer-artifact-api.json', producer_metadata),
                        ('origin-input-artifact-api.json', input_metadata)):
        save(out / name, value)
    require(origin_run['id'] == pins['origin_run_id'] and
            origin_run['run_attempt'] == pins['origin_attempt'] and
            origin_run['head_sha'] == pins['origin_helper']['commit'] and
            origin_run['path'] == pins['origin_workflow_path'], 'Historical run identity differs')
    # A failed historical runtime is expected. Only its actual producer succeeded.
    require(producer_job['id'] == pins['origin_producer_job_id'] and
            producer_job['name'] == pins['origin_producer_job_name'] and
            producer_job['run_id'] == pins['origin_run_id'] and
            producer_job['run_attempt'] == pins['origin_attempt'] and
            producer_job['head_sha'] == pins['origin_helper']['commit'] and
            producer_job['status'] == 'completed' and producer_job['conclusion'] == 'success',
            'Historical producer job differs or did not succeed')
    for name in ('Execute the exact candidate owner gates',
                 'Package source-bound inputs for a fresh macOS runtime'):
        steps = [step for step in producer_job['steps'] if step['name'] == name]
        require(len(steps) == 1 and steps[0]['status'] == 'completed' and
                steps[0]['conclusion'] == 'success', 'Historical producer step did not succeed: ' + name)
    for kind, metadata in (('input_artifact', input_metadata), ('producer_artifact', producer_metadata)):
        expected = pins[kind]
        require(all(metadata[key] == expected[key] for key in ('id', 'name', 'size_in_bytes', 'digest')),
                'Pinned artifact identity changed: ' + kind)
        require(metadata['workflow_run']['id'] == pins['origin_run_id'] and
                metadata['workflow_run']['head_sha'] == pins['origin_helper']['commit'],
                'Artifact belongs to a different historical generation')
    require(input_metadata['expired'] is False, 'Historical input artifact expired')
    archive_zip = out / 'historical-runtime-input.zip'
    download(repo, input_metadata['id'], archive_zip)
    raw = archive_zip.read_bytes()
    require(len(raw) == input_metadata['size_in_bytes'] and
            'sha256:' + sha256(raw) == input_metadata['digest'], 'Raw API artifact ZIP digest/size differs')
    producer_receipt, archive_raw = rh.read_artifact(archive_zip, input_metadata)
    with zipfile.ZipFile(archive_zip) as archive:
        require(archive.testzip() is None, 'Historical ZIP CRC mismatch')
        receipt_raw = archive.read('producer.json')
        require(len(receipt_raw) == pins['producer_receipt_bytes'] and
                sha256(receipt_raw) == pins['producer_receipt_sha256'], 'Pinned producer receipt differs')
    require(len(archive_raw) == pins['archive_size'] and sha256(archive_raw) == pins['archive_sha256'],
            'Pinned historical TAR differs')
    expected_producer = {'repository': repo, 'run_id': str(pins['origin_run_id']),
                         'attempt': str(pins['origin_attempt']), 'job': 'build',
                         'helper': pins['origin_helper'], 'runner_os': 'macOS'}
    require(producer_receipt['producer'] == expected_producer and
            producer_receipt['source'] == source and producer_receipt['native_pins'] == pins['native_pins'] and
            producer_receipt['candidate'] == 'integrated' and
            producer_receipt['status'] == 'VERIFIED_RUNTIME_INPUT_EXPORTED', 'Historical producer receipt differs')
    tar_path = out / 'historical-runtime-input.tar.gz'
    with tar_path.open('xb') as stream:
        stream.write(archive_raw)
    manifest, payloads = rh.read_archive(tar_path, pins['archive_sha256'], 'integrated', root)
    require(manifest['producer'] == expected_producer and manifest['source'] == source and
            manifest['native_pins'] == pins['native_pins'] and manifest['candidate'] == 'integrated' and
            len(manifest['files']) == pins['manifest_file_count'], 'Historical manifest identity differs')
    rh.validate_payloads('integrated', root, source, manifest, payloads)
    targets = rh.destinations('integrated', root, payloads)
    root.joinpath('.build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='diagnostic-origin-', dir=root / '.build') as temporary:
        staging = Path(temporary)
        for name, (data, mode) in payloads.items():
            destination = staging / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(data)
            destination.chmod(mode)
        for name, destination in targets.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging / name), destination)
    for name, destination in targets.items():
        require(rh.read_file(destination) == payloads[name], 'Historical restore bytes/mode differ: ' + name)
    rh.integrated(root).source.check_product()
    require(rh.identity(root) == source and rh.identity(helper) == helper_identity,
            'Source/helper identity changed during diagnostic restoration')
    save(out / 'historical-manifest.json', manifest)
    save(out / 'diagnostic-input-receipt.json', {
        'status': 'HISTORICAL_PRODUCER_INPUT_VERIFIED_FOR_DIAGNOSTIC_ONLY',
        'origin': {'run_id': pins['origin_run_id'], 'attempt': pins['origin_attempt'],
                   'producer_job_id': pins['origin_producer_job_id'], 'helper': pins['origin_helper'],
                   'source': source, 'producer_artifact': pins['producer_artifact'],
                   'input_artifact': pins['input_artifact'], 'archive_sha256': pins['archive_sha256']},
        'diagnostic': diagnostic, 'all_payload_hashes_sizes_and_modes_preserved': True,
        'payload_file_count': len(payloads), 'framework_file_count': pins['framework_file_count'],
        'ipa_identity': pins['ipa'], 'manifest': manifest,
        'producer_artifact_zip_redownloaded': False,
        'producer_artifact_scope': 'Prior verified producer ZIP identity is pinned; this job downloads and revalidates its separately pinned runtime-input ZIP.',
        'candidate_execution': False, 'canonical_execution': False,
        'selected_product': False, 'same_run_candidate_receipt': False})
    print(json.dumps({'diagnostic_only': True, 'historical_input_artifact_id': input_metadata['id'],
                      'origin_run_id': pins['origin_run_id'], 'actual_diagnostic_run_id': diagnostic['run_id'],
                      'restored_files': len(payloads)}))


if __name__ == '__main__':
    main()
