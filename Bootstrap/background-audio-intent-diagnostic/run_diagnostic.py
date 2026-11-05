#!/usr/bin/env python3
"""Restore genuine BG producer inputs and run one instrumented Audio consumer.

Historical producer identity and the actual new diagnostic job remain separate.
The only application change is explicit logging in the original driver's
temporary app. This workflow grants no formal/source-direct candidate credit.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zipfile


HERE = Path(__file__).resolve().parent
HELPER = HERE.parents[1]
JOB = 'background_audio_intent_diagnostic'
REF = 'refs/heads/work/udp-echo-udp-20261028'
STAGED = ('check_async_ui_intent_diagnostic.py', 'instrument_audio_intent.py')
SAFE_ENV = ('GITHUB_ACTIONS', 'GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_REF',
            'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB',
            'RUNNER_OS', 'RUNNER_ARCH', 'DEVELOPER_DIR')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], timeout=60).decode().strip()


def record(path):
    require(path.is_file() and not path.is_symlink(), 'Nonregular input: ' + str(path))
    raw = path.read_bytes()
    return {'size': len(raw), 'sha256': sha(raw), 'mode': stat.S_IMODE(path.stat().st_mode)}


def check_diagnostic_staging(root, pins, staged):
    raw = subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '--others', '--exclude-standard', '-z'],
        timeout=60)
    actual = [os.fsdecode(name) for name in raw.split(b'\0') if name]
    expected = {'Tests/Background/' + name for name in STAGED} if staged else set()
    require(len(actual) == len(set(actual)) and set(actual) == expected,
            'Unexpected nonignored untracked files in isolated source')
    records = {name: record(root / name) for name in sorted(expected)}
    require(all(item['sha256'] == pins['diagnostic_files'][Path(name).name]
                for name, item in records.items()),
            'Staged diagnostic script differs from approved pins')
    return records


def snapshot_source(root, expected):
    require({'commit': git(root, 'rev-parse', 'HEAD'),
             'tree': git(root, 'rev-parse', 'HEAD^{tree}')} == expected, 'Source identity moved')
    git(root, 'diff', '--cached', '--no-ext-diff', '--no-textconv', '--exit-code', 'HEAD', '--')
    files = {}
    raw_tree = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-rz', 'HEAD'], timeout=60)
    for entry in raw_tree.split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        name = os.fsdecode(raw_name)
        require(kind == 'blob' and mode in ('100644', '100755'), 'Nonregular tracked source')
        path = root / name
        item = record(path)
        raw = path.read_bytes()
        require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob
                and bool(item['mode'] & 0o100) == (mode == '100755'),
                'Changed raw source blob or Git mode: ' + name)
        files[name] = item
    return {'identity': expected, 'files': files}


def checked_zip(raw, dependency):
    archive = dependency.checked_zip(raw)
    names = [item.filename.rstrip('/') for item in archive.infolist()]
    require(len(names) == len({name.casefold() for name in names}), 'Case-colliding ZIP entries')
    files = {item.filename.casefold() for item in archive.infolist() if not item.is_dir()}
    for name in names:
        require(all(parent.as_posix().casefold() not in files
                    for parent in PurePosixPath(name).parents if parent.as_posix() != '.'),
                'ZIP file/directory collision')
    return archive


def validate_metadata(metadata, pins):
    origin = pins['producer']
    job = metadata['job']
    require(job['id'] == origin['job_id'] and job['run_id'] == origin['run_id']
            and job['run_attempt'] == origin['run_attempt']
            and job['head_sha'] == origin['helper']['commit']
            and job['status'] == 'completed' and job['conclusion'] == 'success'
            and job['name'] == 'build (background, ' + pins['source']['commit'] + ', xcode-27, true)',
            'Actual original Background producer job differs')
    for name in ('Execute the exact candidate owner gates',
                 'Preserve exact generated native products',
                 'Package source-bound inputs for a fresh macOS runtime'):
        matching = [step for step in job['steps'] if step['name'] == name]
        require(len(matching) == 1 and matching[0]['conclusion'] == 'success',
                'Original producer step did not succeed: ' + name)
    for field, key in (('build_artifact', 'build'), ('runtime_artifact', 'runtime_input')):
        actual, expected = metadata[field], pins['artifacts'][key]
        require(all(actual[name] == expected[name] for name in ('id', 'name', 'size_in_bytes', 'digest'))
                and actual['expired'] is False, 'Wrong immutable artifact metadata: ' + field)
        run = actual['workflow_run']
        require(run['id'] == origin['run_id'] and run['head_sha'] == origin['helper']['commit']
                and run['head_branch'] == 'work/udp-echo-build-20261028',
                'Artifact belongs to another original producer')


def actual_context(pins, out):
    require(sys.platform == 'darwin' and platform.machine() == 'arm64'
            and os.getuid() == os.geteuid() > 0
            and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_OS') == 'macOS'
            and os.environ.get('RUNNER_ARCH') == 'ARM64'
            and os.environ.get('GITHUB_REPOSITORY') == pins['repository']
            and os.environ.get('GITHUB_JOB') == JOB
            and os.environ.get('GITHUB_REF') == REF
            and re.fullmatch(r'[1-9][0-9]*', os.environ.get('GITHUB_RUN_ID', ''))
            and os.environ['GITHUB_RUN_ID'] != str(pins['producer']['run_id'])
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1',
            'Requires one actual independent macOS ARM64 diagnostic attempt')
    head = git(HELPER, 'rev-parse', 'HEAD')
    require(head == os.environ.get('GITHUB_SHA')
            and not git(HELPER, 'status', '--porcelain=v1', '--untracked-files=all'),
            'Actual diagnostic helper checkout is not the clean triggering SHA')
    identity = {'commit': head, 'tree': git(HELPER, 'rev-parse', 'HEAD^{tree}')}
    snapshot_source(HELPER, identity)
    version = subprocess.check_output(['xcodebuild', '-version'], text=True, timeout=60)
    (out / 'xcode-version.txt').write_text(version)
    require(version == 'Xcode 27.0\nBuild version 27A266a\n'
            and os.environ.get('DEVELOPER_DIR') == '/Applications/Xcode_27.app/Contents/Developer',
            'Requires the original observed Xcode27.0 profile')
    return {'helper': identity, 'repository': pins['repository'],
            'run_id': int(os.environ['GITHUB_RUN_ID']), 'attempt': 1, 'job': JOB,
            'host': {'python': sys.version, 'uid': os.getuid(), 'euid': os.geteuid(),
                     'machine': platform.machine(), 'macos': platform.mac_ver()[0]},
            'original_producer_context_replaced_or_impersonated': False}


def fetch(pins, out):
    api = 'repos/' + pins['repository'] + '/actions/'
    metadata = {'job': json.loads(subprocess.check_output(
        ['gh', 'api', api + 'jobs/' + str(pins['producer']['job_id'])], timeout=60))}
    paths = {}
    for field, key in (('build_artifact', 'build'), ('runtime_artifact', 'runtime_input')):
        artifact_id = str(pins['artifacts'][key]['id'])
        metadata[field] = json.loads(subprocess.check_output(
            ['gh', 'api', api + 'artifacts/' + artifact_id], timeout=60))
        destination = out / (key + '-original-artifact.zip')
        with destination.open('xb') as stream:
            subprocess.run(['gh', 'api', api + 'artifacts/' + artifact_id + '/zip'],
                           stdout=stream, check=True, timeout=300)
        paths[key] = destination
    return paths['build'], paths['runtime_input'], metadata


def restore_inputs(build_path, runtime_path, metadata, pins, out, dependency, handoff):
    validate_metadata(metadata, pins)
    build_raw, runtime_raw = build_path.read_bytes(), runtime_path.read_bytes()
    for raw, key in ((build_raw, 'build'), (runtime_raw, 'runtime_input')):
        expected = pins['artifacts'][key]
        require(len(raw) == expected['size_in_bytes'] and 'sha256:' + sha(raw) == expected['digest'],
                'Original artifact size/digest mismatch: ' + key)
    build = checked_zip(build_raw, dependency)
    runtime_zip = checked_zip(runtime_raw, dependency)
    receipt, archive_raw = handoff.read_artifact(runtime_path, metadata['runtime_artifact'])
    origin = pins['producer']
    expected_producer = {
        'repository': pins['repository'], 'run_id': str(origin['run_id']),
        'attempt': str(origin['run_attempt']), 'job': 'build',
        'helper': origin['helper'], 'runner_os': 'macOS'}
    require(type(receipt['schema']) is int and receipt['schema'] == 1
            and receipt['status'] == 'VERIFIED_RUNTIME_INPUT_EXPORTED'
            and receipt['candidate'] == 'background'
            and receipt['source'] == pins['source'] and receipt['native_pins'] == pins['native_pins']
            and receipt['producer'] == expected_producer
            and receipt['artifact_name'] == pins['artifacts']['runtime_input']['name'],
            'Bound historical producer identity differs')
    for name, expected in pins['artifacts']['build_archive_members'].items():
        raw = build.read(name)
        require(len(raw) == expected['bytes'] and sha(raw) == expected['sha256'],
                'Original producer member differs: ' + name)
    require(runtime_zip.read('producer.json') == build.read('runtime-input/background/producer.json')
            and archive_raw == build.read('runtime-input/background/runtime-input.tar.gz'),
            'Dedicated runtime input differs from original successful build artifact')
    (out / 'original-producer.json').write_bytes(runtime_zip.read('producer.json'))
    tar_path = out / 'original-runtime-input.tar.gz'
    tar_path.write_bytes(archive_raw)
    history = out / 'original-history.bundle'
    history.write_bytes(build.read('background/history.bundle'))
    original_zip = checked_zip(build.read('background/Socks5-background-source.zip'), dependency)
    require(dependency.git_tree(original_zip) == pins['source']['tree'],
            'Original source ZIP Git tree differs')

    root = out / 'checkout'
    root.mkdir()
    with (out / 'isolated-git-restore.log').open('xb') as log:
        for command in (
            ['git', 'init', '-q', root],
            ['git', '-C', root, 'bundle', 'verify', history],
            ['git', '-C', root, 'bundle', 'unbundle', history],
            ['git', '-C', root, 'fsck', '--full', '--no-reflogs'],
            ['git', '-C', root, 'checkout', '--detach', pins['source']['commit']],
        ):
            subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=180)
    before = snapshot_source(root, pins['source'])
    require(len(before['files']) == pins['source_file_count'], 'Unexpected exact source file count')
    require(set(before['files']) == {entry.filename for entry in original_zip.infolist() if not entry.is_dir()},
            'History/source ZIP inventory differs')
    for name, item in before['files'].items():
        require(sha(original_zip.read(name)) == item['sha256'], 'History/source ZIP bytes differ: ' + name)
    config = json.loads((root / 'Build/features.json').read_bytes())
    require(config['name'] == 'background' and config['sources'] == pins['native_pins'],
            'Restored composition/native pins differ')
    require(sha((root / 'Tests/Background/AsyncAudioUITests.swift').read_bytes()) == pins['source_test_sha256']
            and sha((root / 'Tests/Background/check_async_ui.py').read_bytes()) == pins['original_driver_sha256'],
            'Original Audio test or consumer differs')
    manifest, payloads = handoff.read_archive(tar_path, receipt['archive_sha256'], 'background', root)
    require({key: value for key, value in manifest.items() if key != 'files'} ==
            {key: receipt[key] for key in ('schema', 'candidate', 'source', 'native_pins', 'producer')}
            and len(payloads) == pins['payload_count'], 'Original transfer manifest identity/count differs')
    handoff.validate_payloads('background', root, pins['source'], manifest, payloads)
    native_identity = json.loads(build.read('native-product/identity.json'))
    require(native_identity['commit'] == pins['source']['commit']
            and native_identity['tree'] == pins['source']['tree']
            and native_identity['helper_commit'] == origin['helper']['commit']
            and str(native_identity['run_id']) == str(origin['run_id'])
            and str(native_identity['run_attempt']) == str(origin['run_attempt']),
            'Native product identity differs from original producer')
    framework = {}
    for name, (raw, mode) in payloads.items():
        if name.startswith('evidence/'):
            require(raw == build.read(name[len('evidence/'):]), 'Transferred original evidence differs: ' + name)
        else:
            require(name.startswith('framework/'), 'Unexpected payload class')
            framework[name[len('framework/'):]] = {'size': len(raw), 'sha256': sha(raw), 'mode': mode}
    require(len(framework) == pins['framework_file_count'] and framework == native_identity['framework'],
            'Transferred native framework differs from producer product identity')
    native_zip = pins['original_native_framework_zip']
    native_raw = build.read(native_zip['path'])
    require(len(native_raw) == native_zip['bytes'] and sha(native_raw) == native_zip['sha256'],
            'Original native framework package differs')
    targets = handoff.destinations('background', root, payloads)
    for name, path in targets.items():
        raw, mode = payloads[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
        path.chmod(mode)
        require(record(path) == manifest['files'][name], 'Restored payload bytes/mode differ: ' + name)
    with (out / 'original-native-verifier-before.log').open('xb') as log:
        subprocess.run(['python3', 'Tests/Background/native_inputs.py', 'verify'], cwd=root,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
    require(snapshot_source(root, pins['source']) == before, 'Restoration modified original source')
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as archive:
        (out / 'original-transfer-manifest.json').write_bytes(archive.extractfile('MANIFEST.json').read())
    save(out / 'source-before.json', before)
    save(out / 'diagnostic-input-receipt.json', {
        'status': 'ORIGINAL_BG_INPUTS_VERIFIED_FOR_SEPARATE_DIAGNOSTIC_ONLY',
        'source': pins['source'], 'historical_producer': origin,
        'artifacts': pins['artifacts'], 'source_file_count': len(before['files']),
        'payload_count': len(payloads), 'framework_file_count': len(framework),
        'native_verifier_original_subprocess_passed': True,
        'source_direct_candidate_pass_credit': False,
        'original_receipts_rewritten': False,
        'formal_consumer_receipt_created': False,
        'context_free_handoff_functions_used': ['read_artifact', 'read_archive', 'validate_payloads', 'destinations'],
    })
    return root, before, {name: (path, manifest['files'][name]) for name, path in targets.items()}


def post_checks(root, before, targets, pins, out, staged):
    after = snapshot_source(root, pins['source'])
    save(out / 'source-after.json', after)
    require(after == before, 'Diagnostic consumer changed original tracked source')
    actual = {name: record(path) for name, (path, _) in targets.items()}
    require(actual == {name: expected for name, (_, expected) in targets.items()},
            'Diagnostic consumer changed original native/prepared evidence inputs')
    save(out / 'original-native-after.json', actual)
    with (out / 'original-native-verifier-after.log').open('xb') as log:
        subprocess.run(['python3', 'Tests/Background/native_inputs.py', 'verify'], cwd=root,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
    save(out / 'staged-diagnostic-files-after.json', check_diagnostic_staging(root, pins, staged))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--run-once', action='store_true')
    action.add_argument('--verify-only', action='store_true')
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--build-zip', type=Path)
    parser.add_argument('--runtime-zip', type=Path)
    parser.add_argument('--metadata-json', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    require(not out.is_relative_to(HELPER), 'Diagnostic output must be outside the helper checkout')
    out.mkdir(parents=True, exist_ok=False)
    result = {'schema': 1, 'status': 'STARTED',
              'execution_kind': 'ACTUAL_BG_DIAGNOSTIC' if args.run_once else 'LOCAL_INPUT_VERIFY_ONLY',
              'formal_gate_credit': False, 'source_direct_candidate_pass_credit': False,
              'original_failure_replaced': False, 'consumer_invocations': 0,
              'consumer_returncode': None, 'extra_core_simulator_calls': 0,
              'actual_environment': {key: os.environ.get(key) for key in SAFE_ENV},
              'wrapper_sha256': sha(Path(__file__).read_bytes())}
    root = before = targets = pins = None
    staged = False
    status = None
    return_code = 1
    try:
        require(__debug__, 'Assertions must remain enabled')
        sys.dont_write_bytecode = True
        pins = json.loads((HERE / 'input-pins.json').read_bytes())
        for name, expected in pins['dependencies'].items():
            require(sha((HELPER / name).read_bytes()) == expected, 'Pinned context-free reader changed: ' + name)
        for name, expected in pins['diagnostic_files'].items():
            require(sha((HERE / name).read_bytes()) == expected, 'Reviewed diagnostic file changed: ' + name)
        dependency = load_module('bg_diagnostic_zip_readers', HELPER / 'Bootstrap/ui_compile_diagnostic.py')
        handoff = load_module('bg_diagnostic_handoff_readers', HELPER / 'Bootstrap/runtime_handoff.py')
        if args.run_once:
            require(args.fetch and not any((args.build_zip, args.runtime_zip, args.metadata_json)),
                    'Actual execution must fetch genuine inputs with no local override')
            result['actual_diagnostic_context'] = actual_context(pins, out)
            build_path, runtime_path, metadata = fetch(pins, out)
        else:
            require(not args.fetch and all((args.build_zip, args.runtime_zip, args.metadata_json)),
                    'Local verification requires both saved ZIPs and genuine saved API metadata')
            build_path, runtime_path = args.build_zip.resolve(strict=True), args.runtime_zip.resolve(strict=True)
            metadata = json.loads(args.metadata_json.read_bytes())
            result['local_mode_scope'] = 'Source/native input verification only; no CI identity or host/UI execution claim.'
        save(out / 'actual-original-api-metadata.json', metadata)
        root, before, targets = restore_inputs(build_path, runtime_path, metadata, pins, out, dependency, handoff)
        result['original_inputs_verified'] = True
        require(check_diagnostic_staging(root, pins, False) == {},
                'Fresh restored input unexpectedly contains diagnostic scripts')
        result['nonignored_untracked_empty_before_staging'] = True
        if args.verify_only:
            result['status'] = 'LOCAL_ORIGINAL_BG_INPUT_AND_NATIVE_VERIFY_PASS_ONLY'
            return_code = 0
        else:
            staged_files = {}
            for name in STAGED:
                destination = root / 'Tests/Background' / name
                require(not destination.exists(), 'Refusing to replace original source with diagnostic code')
                shutil.copyfile(HERE / name, destination)
                staged_files[str(destination.relative_to(root))] = record(destination)
            require(check_diagnostic_staging(root, pins, True) == staged_files,
                    'Staged diagnostic script inventory differs')
            staged = True
            save(out / 'staged-diagnostic-files.json', staged_files)
            command = ['python3', 'Tests/Background/check_async_ui_intent_diagnostic.py']
            result['consumer_command'] = {'argv': command, 'cwd': str(root), 'outer_timeout_added': False,
                                          'started_unix': time.time()}
            save(out / 'diagnostic-result.json', result)
            with (out / 'consumer.stdout.log').open('xb') as stdout, (out / 'consumer.stderr.log').open('xb') as stderr:
                process = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr)
                result['consumer_invocations'] = 1
                result['consumer_command']['pid'] = process.pid
                save(out / 'diagnostic-result.json', result)
                status = process.wait()
            result['consumer_returncode'] = status
            result['consumer_command']['finished_unix'] = time.time()
            result['status'] = 'INSTRUMENTED_AUDIO_DIAGNOSTIC_COMPLETED' if status == 0 else 'INSTRUMENTED_AUDIO_FAILURE_PRESERVED'
            return_code = status if 0 <= status <= 255 else 128 - status if -127 <= status < 0 else 1
            ui = root / 'artifacts/audio-async-ui'
            if (ui / 'test-summary.json').is_file():
                result['actual_test_summary'] = json.loads((ui / 'test-summary.json').read_bytes())
            if (ui / 'cleanup.json').is_file():
                result['original_cleanup'] = json.loads((ui / 'cleanup.json').read_bytes())
            if (ui / 'intent-diagnostic/IDENTITY.json').is_file():
                variant = json.loads((ui / 'intent-diagnostic/IDENTITY.json').read_bytes())
                require(variant['status'] == 'INSTRUMENTED_TEMPORARY_APP_DIAGNOSTIC_ONLY'
                        and variant['original_input_baseline_commit'] == pins['source']['commit']
                        and variant['formal_gate_credit'] is False
                        and variant['source_direct_candidate_pass_credit'] is False
                        and variant['instrumented_app_is_original_producer_product'] is False,
                        'Instrumented variant scope/identity differs')
                for name, expected in pins['instrumented_sources'].items():
                    require(sha((root / '.build/audio-async-ui/application' / name).read_bytes()) == expected,
                            'Actual instrumented source differs from reviewed proposal: ' + name)
                result['instrumented_variant_identity'] = variant
            copied_test = root / '.build/audio-async-ui/application/AsyncAudioUITests.swift'
            if copied_test.is_file():
                require(sha(copied_test.read_bytes()) == pins['source_test_sha256'], 'Copied original XCTest changed')
                result['copied_original_test_sha256'] = sha(copied_test.read_bytes())
            if status == 0:
                summary = result.get('actual_test_summary', {})
                require(summary.get('passedTests') == 1 and summary.get('failedTests') == 0
                        and summary.get('skippedTests', 0) == 0
                        and result.get('original_cleanup') == []
                        and 'instrumented_variant_identity' in result
                        and (ui / 'SUCCESS.txt').is_file(),
                        'Completed original single-Audio diagnostic evidence is incomplete')
    except BaseException as error:
        result['diagnostic_error'] = repr(error)
        result['status'] = 'DIAGNOSTIC_FAILED_WITH_ORIGINAL_OUTCOME_PRESERVED'
        return_code = status if status is not None and 0 < status <= 255 else 1
    finally:
        if root is not None and before is not None and targets is not None:
            try:
                post_checks(root, before, targets, pins, out, staged)
                result['original_source_and_native_preserved_after'] = True
            except BaseException as error:
                result['post_preservation_error'] = repr(error)
                result['original_source_and_native_preserved_after'] = False
                result['status'] = 'DIAGNOSTIC_POST_PRESERVATION_FAILED'
                if return_code == 0:
                    return_code = 1
        result['wrapper_returncode'] = return_code
        save(out / 'diagnostic-result.json', result)
    return return_code


if __name__ == '__main__':
    sys.exit(main())
