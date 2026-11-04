#!/usr/bin/env python3
"""One unchanged original UI consumer on the runner's installed runtime, diagnosis only."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import time
import zipfile

DEPENDENCY_SHA = 'f0b7930f8fdebc97012053bbb4b2eccd58913bb72152b0e6fe25a43bb1f6439c'
HISTORY_SHA = '6d1dd665951bab87c8df9e44d0b9ab07d68f3c5bcbf3547965b1a94f6db454cd'
TRANSFER_SHA = 'cf46b2fda13531be3fd5219832fe6d90c19ed22018d679c8ece3f600334641c3'
PRODUCER = {'repository': 'AAAHN-AAAHN/heiher-socks5-ios', 'run_id': '41919837795',
            'attempt': '1', 'job': 'build', 'runner_os': 'macOS',
            'helper': {'commit': 'b7216e75ca091b4482bc9a3583a278c8cb4058ea',
                       'tree': '275f43f25e0f11d3d0b0e3effd570eb6c7cf1968'}}
SAFE_ENV = ('GITHUB_ACTIONS', 'GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
            'GITHUB_JOB', 'GITHUB_SHA', 'GITHUB_REF', 'RUNNER_OS', 'RUNNER_ARCH',
            'ImageOS', 'ImageVersion', 'DEVELOPER_DIR')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(folder, *arguments):
    return subprocess.check_output(['git', '-C', str(folder), *arguments], text=True, timeout=60).strip()


def source_snapshot(source, expected):
    require(git(source, 'rev-parse', 'HEAD') == expected['commit']
            and git(source, 'rev-parse', 'HEAD^{tree}') == expected['tree'], 'Wrong isolated source identity')
    git(source, 'diff', '--exit-code', 'HEAD', '--')
    git(source, 'diff', '--cached', '--exit-code', 'HEAD', '--')
    result = {}
    rows = subprocess.check_output(['git', '-C', str(source), 'ls-tree', '-rz', 'HEAD'], timeout=60)
    for row in rows.split(b'\0'):
        if not row:
            continue
        header, encoded = row.split(b'\t', 1)
        mode, kind, blob = header.decode().split()
        name = encoded.decode()
        path = source / name
        require(kind == 'blob' and mode in ('100644', '100755') and stat.S_ISREG(path.lstat().st_mode),
                'Unexpected tracked file type: ' + name)
        raw = path.read_bytes()
        actual_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        require(actual_blob == blob and bool(path.stat().st_mode & 0o111) == (mode == '100755'),
                'Tracked source bytes/mode changed: ' + name)
        result[name] = {'size': len(raw), 'sha256': sha(raw), 'mode': mode}
    return result


def verify_and_restore(artifact, metadata, out, dependency):
    verified = dependency.verify_inputs(artifact, metadata, out)
    with zipfile.ZipFile(artifact) as archive:
        history = archive.read('integrated/history.bundle')
        transfer = archive.read('runtime-input/integrated/runtime-input.tar.gz')
        original_receipt = archive.read('runtime-input/integrated/producer.json')
    require(sha(history) == HISTORY_SHA and sha(transfer) == TRANSFER_SHA, 'Wrong original source history or transfer bytes')
    bundle, tar = out / 'original-history.bundle', out / 'original-runtime-input.tar.gz'
    bundle.write_bytes(history)
    tar.write_bytes(transfer)
    (out / 'original-runtime-export-producer.json').write_bytes(original_receipt)
    receipt = json.loads(original_receipt)
    expected = {'commit': dependency.SOURCE, 'tree': dependency.TREE}
    require(receipt['producer'] == PRODUCER and receipt['source'] == expected
            and receipt['candidate'] == 'integrated' and receipt['archive_sha256'] == TRANSFER_SHA
            and receipt['archive_size'] == len(transfer), 'Original export producer binding differs')
    source = out / 'checkout'
    source.mkdir()
    with (out / 'isolated-git-restore.log').open('xb') as stream:
        for command in (['git', 'init', '--quiet', source],
                        ['git', '-C', source, 'bundle', 'verify', bundle],
                        ['git', '-C', source, 'fetch', '--quiet', '--no-tags', bundle, 'HEAD'],
                        ['git', '-C', source, 'checkout', '--quiet', '--detach', 'FETCH_HEAD']):
            subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=60)
    before = source_snapshot(source, expected)
    require(len(before) == verified['source_files'] == 322, 'Incomplete isolated source tree')
    for name, record in before.items():
        path = out / 'source' / name
        require(path.read_bytes() == (source / name).read_bytes()
                and bool(path.stat().st_mode & 0o111) == (record['mode'] == '100755'),
                'Git bundle differs from actual source archive: ' + name)
    sys.path.insert(0, str(source / 'Build'))
    handoff = load_module('original_integrated_handoff_readers', source / 'Build/review_handoff.py')
    manifest, payloads = handoff.read_archive(tar, TRANSFER_SHA)
    require(manifest['producer'] == PRODUCER and manifest['candidate'] == 'integrated'
            and manifest['source'] == expected and manifest['native_pins'] == receipt['native_pins'],
            'Original transfer manifest identity differs')
    handoff.check_payloads(manifest, payloads, expected)
    for name, (raw, mode) in payloads.items():
        destination = (handoff.PRODUCT / name[len('product/'):] if name.startswith('product/')
                       else handoff.OUT / name[len('phases/'):])
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(raw)
        destination.chmod(mode)
        require(handoff.read_file(destination) == (raw, mode), 'Original product/phase copy differs: ' + name)
    handoff.source.check_product()
    require(before == source_snapshot(source, expected), 'Input restoration changed tracked source')
    write_json(out / 'source-before.json', before)
    write_json(out / 'original-transfer-manifest.json', manifest)
    write_json(out / 'diagnostic-input-copy.json', {
        'scope': 'Cross-run diagnostic input copy only; no official runtime handoff or common-environment receipt.',
        'status': 'DIAGNOSTIC_CROSS_RUN_INPUT_COPY_VERIFIED', 'original_producer': PRODUCER,
        'verified_input': verified, 'history_sha256': HISTORY_SHA, 'original_transfer_sha256': TRANSFER_SHA,
        'restored_files': len(payloads), 'original_check_payloads_passed': True,
        'original_check_product_passed': True, 'actual_diagnostic_environment': {k: os.environ.get(k) for k in SAFE_ENV}})
    return source, handoff, before, expected


def classify_after_original_cleanup(ui, out):
    result = {'baseline_origin_confirmed': False, 'cause_of_original_failure_established': False,
              'extra_core_simulator_calls_before_original_consumer': 0,
              'post_cleanup_runtime_image_list_invocations': 0}
    cleanup = ui / 'cleanup.json'
    if not cleanup.is_file() or json.loads(cleanup.read_bytes()) != []:
        result['reason'] = 'Original cleanup completion is unconfirmed; no extra CoreSimulator call made.'
        return result
    result['post_cleanup_runtime_image_list_invocations'] = 1
    command = ['xcrun', 'simctl', 'runtime', 'list', '-j']
    started = time.time()
    record = {'argv': command, 'timeout_seconds': 10, 'started_unix': started}
    try:
        with (out / 'post-cleanup-runtime-images.json').open('xb') as stdout, (out / 'post-cleanup-runtime-images.stderr.log').open('xb') as stderr:
            completed = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=10)
        record['returncode'] = completed.returncode
        require(completed.returncode == 0, 'Post-cleanup read-only image inventory failed')
        images = json.loads((out / 'post-cleanup-runtime-images.json').read_bytes())
        environment = json.loads((ui / 'environment.json').read_bytes())
        runtimes = json.loads((ui / 'runtimes.json').read_bytes())['runtimes']
        selected = environment['runtime']
        original_first = next(r for r in runtimes if r.get('isAvailable')
                              and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
        require(selected == original_first, 'Original consumer selection differs from its unchanged selection rule')
        result['original_environment'] = environment
        result['same_identifier_build_as_successful_background_observation'] = (
            selected['identifier'] == 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'
            and selected['buildversion'] == '24A434')
        matches = [row for row in images.values()
                   if row.get('runtimeIdentifier') == selected['identifier']
                   and row.get('build') == selected['buildversion']
                   and row.get('runtimeBundlePath') == selected['bundlePath']]
        result['matching_image_records'] = matches
        require(len(matches) == 1, 'Selected runtime image origin is ambiguous or absent after cleanup')
        row = matches[0]
        asset = Path(row.get('path', ''))
        prefix = Path('/System/Library/AssetsV2/com_apple_MobileAsset_iOSSimulatorRuntime')
        result['baseline_origin_confirmed'] = (
            asset.is_absolute() and asset.is_relative_to(prefix) and '..' not in asset.parts
            and asset.name == 'AssetData' and asset.parent.name.endswith('.asset')
            and row.get('kind') == 'Patchable Cryptex Disk Image'
            and row.get('state') == 'Ready'
            and selected.get('runtimeRoot') == selected['bundlePath'] + '/Contents/Resources/RuntimeRoot')
        if not result['baseline_origin_confirmed']:
            result['reason'] = 'Actual selected image is not confirmed as the installed MobileAsset runtime.'
    except Exception as error:
        record['error'] = repr(error)
        result['reason'] = repr(error)
    finally:
        record['finished_unix'] = time.time()
        result['post_cleanup_command'] = record
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--fetch', action='store_true')
    origin.add_argument('--artifact-zip', type=Path)
    parser.add_argument('--metadata-json', type=Path)
    parser.add_argument('--local-helper', type=Path, help='Verify-only dependency location; unavailable to actual CI execution.')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--run-once', action='store_true')
    action.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = {'schema': 1, 'scope': 'ONE_ORIGINAL_UI_CONSUMER_INSTALLED_RUNTIME_DIAGNOSTIC',
              'official_candidate_gate_credit': False, 'full_release_acceptance': False,
              'original_official_failure_replaced': False,
              'preserved_official_statistics_failure': {'run_id': 41919837795, 'attempt': 1,
                  'job_id': 126928985727, 'phase': 'simctl bootstatus before app execution', 'timeout_seconds': 120},
              'execution_kind': 'ACTUAL_DIAGNOSTIC_CI' if args.run_once or args.fetch else 'LOCAL_INPUT_VERIFICATION',
              'actual_diagnostic_environment': {k: os.environ.get(k) for k in SAFE_ENV},
              'original_consumer_invocations': 0, 'original_consumer_returncode': None,
              'extra_core_simulator_calls_before_original_consumer': 0,
              'driver_sha256': sha(Path(__file__).read_bytes()), 'status': 'STARTED'}
    original_status = None
    source = handoff = before = expected = None
    try:
        require(__debug__, 'Assertions must remain enabled')
        sys.dont_write_bytecode = True
        helper = Path(__file__).resolve().parents[1]
        if args.local_helper:
            require(args.verify_only and not args.fetch, 'Local helper override is verification-only')
            helper = args.local_helper.resolve(strict=True)
        dependency_file = helper / 'Bootstrap/ui_compile_diagnostic.py'
        require(sha(dependency_file.read_bytes()) == DEPENDENCY_SHA, 'Reviewed producer-input verifier changed')
        dependency = load_module('unchanged_compile_input_verifier', dependency_file)
        if args.fetch or args.run_once:
            require(sys.platform == 'darwin' and os.environ.get('GITHUB_ACTIONS') == 'true'
                    and os.environ.get('RUNNER_OS') == 'macOS'
                    and os.environ.get('RUNNER_ARCH') == 'ARM64'
                    and platform.machine() == 'arm64' and os.getuid() == os.geteuid() > 0
                    and os.environ.get('GITHUB_REPOSITORY') == dependency.REPOSITORY
                    and os.environ.get('GITHUB_REF') == 'refs/heads/work/udp-echo-udp-20261028'
                    and os.environ.get('GITHUB_JOB') == 'observe_original_ui_installed_runtime'
                    and os.environ.get('GITHUB_RUN_ID', '').isdigit() and int(os.environ['GITHUB_RUN_ID']) > 0
                    and os.environ.get('GITHUB_RUN_ID') != str(dependency.PRODUCER_RUN)
                    and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'Expected one actual independent diagnostic attempt')
            head = git(helper, 'rev-parse', 'HEAD')
            require(head == os.environ.get('GITHUB_SHA'), 'Diagnostic helper differs from the real event')
            git(helper, 'diff', '--exit-code', 'HEAD', '--')
            git(helper, 'diff', '--cached', '--exit-code', 'HEAD', '--')
            require(not git(helper, 'status', '--porcelain=v1', '--untracked-files=all'), 'Diagnostic helper is not clean')
            result['actual_diagnostic_helper'] = {'commit': head, 'tree': git(helper, 'rev-parse', 'HEAD^{tree}'), 'clean': True}
        if args.fetch:
            metadata = {}
            for key, suffix in [('job', f'jobs/{dependency.PRODUCER_JOB}'), ('artifact', f'artifacts/{dependency.ARTIFACT_ID}')]:
                metadata[key] = json.loads(subprocess.check_output(['gh', 'api', f'repos/{dependency.REPOSITORY}/actions/{suffix}'], timeout=60))
            artifact = out / 'original-producer-artifact.zip'
            with artifact.open('xb') as stream:
                subprocess.run(['gh', 'api', f'repos/{dependency.REPOSITORY}/actions/artifacts/{dependency.ARTIFACT_ID}/zip'],
                               stdout=stream, check=True, timeout=300)
        else:
            require(args.metadata_json is not None, 'Actual saved producer API metadata is required')
            artifact = args.artifact_zip.resolve(strict=True)
            metadata = json.loads(args.metadata_json.read_bytes())
        write_json(out / 'actual-producer-api-metadata.json', metadata)
        source, handoff, before, expected = verify_and_restore(artifact, metadata, out, dependency)
        result['input_copy_verified'] = True
        result['source'] = expected
        if args.verify_only:
            result['status'] = 'DIAGNOSTIC_INPUT_COPY_AND_ORIGINAL_PRODUCT_CHECK_PASSED_ONLY'
            return 0
        version = subprocess.check_output(['xcodebuild', '-version'], text=True, timeout=60)
        (out / 'xcode-version.txt').write_text(version)
        require(version == 'Xcode 27.0\nBuild version 27A266a\n'
                and os.environ.get('DEVELOPER_DIR') == '/Applications/Xcode_27.app/Contents/Developer',
                'Expected the unchanged official runtime Xcode 27.0 toolchain')
        result['host'] = {'python': sys.version, 'python_executable': sys.executable, 'uid': os.getuid(), 'euid': os.geteuid(),
                          'machine': platform.machine(), 'macos': platform.mac_ver()[0]}
        ui = source / 'artifacts/integrated/ui'
        require(not ui.exists() and not (source / '.build/integrated-ui').exists(), 'Original consumer requires fresh output and workspace')
        command = ['python3', 'Build/ui_review.py']
        result['original_command'] = {'argv': command, 'cwd': str(source), 'started_unix': time.time(),
            'outer_timeout_added': False, 'original_deadlines_seconds': {'bootstatus': 120, 'build': 900, 'test': 900, 'each_cleanup': 30}}
        with (out / 'original-consumer.stdout.log').open('xb') as stdout, (out / 'original-consumer.stderr.log').open('xb') as stderr:
            process = subprocess.Popen(command, cwd=source, stdout=stdout, stderr=stderr)
            result['original_consumer_invocations'] = 1
            result['original_command']['pid'] = process.pid
            original_status = process.wait()
        result['original_consumer_returncode'] = original_status
        result['original_command']['finished_unix'] = time.time()
        after = source_snapshot(source, expected)
        write_json(out / 'source-after.json', after)
        require(after == before, 'Original consumer changed tracked source')
        handoff.source.check_product()
        result['post_original_source_and_product_checks_passed'] = True
        result['runtime_origin'] = classify_after_original_cleanup(ui, out)
        result['original_cleanup'] = json.loads((ui / 'cleanup.json').read_bytes()) if (ui / 'cleanup.json').is_file() else None
        if original_status != 0:
            result['status'] = 'ORIGINAL_UI_CONSUMER_FAILED_PRESERVED'
            return original_status if 0 < original_status < 256 else 1
        summary = json.loads((ui / 'test-summary.json').read_bytes())
        settings = json.loads((ui / 'final-settings.json').read_bytes())
        require(summary.get('passedTests') == 4 and not summary.get('failedTests', 0)
                and not summary.get('skippedTests', 0) and result['original_cleanup'] == []
                and settings['serverRunning'] is False
                and settings['background'] == {'continuousLocation': False, 'silentAudio': False,
                    'periodicUDPEcho': {'enabled': False, 'destinations': '127.0.0.1,::1', 'period': '00200'}}
                and (ui / 'SUCCESS.txt').is_file() and (ui / 'advisory-check.txt').is_file(),
                'Original four-case, settings, advisory or cleanup result is incomplete')
        result['original_four_ui_tests_passed'] = True
        if not result['runtime_origin']['baseline_origin_confirmed']:
            result['status'] = 'ORIGINAL_UI_PASSED_BASELINE_ORIGIN_UNCONFIRMED'
            return 1
        result['status'] = 'DIAGNOSTIC_ORIGINAL_UI_PASSED_ON_INSTALLED_RUNTIME'
        return 0
    except BaseException as error:
        result['diagnostic_error'] = repr(error)
        result['status'] = 'DIAGNOSTIC_FAILED'
        return original_status if original_status is not None and 0 < original_status < 256 else 1
    finally:
        write_json(out / 'diagnostic-result.json', result)


if __name__ == '__main__':
    sys.exit(main())
