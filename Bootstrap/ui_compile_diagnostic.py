#!/usr/bin/env python3
"""Compile the unchanged current integrated XCUI source; no UI execution or gate credit."""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
import zipfile

REPOSITORY = 'AAAHN-AAAHN/heiher-socks5-ios'
PRODUCER_RUN = 41940618811
PRODUCER_HELPER = '8b227e0e5ca5b01f3dff79bd26938310ff429d13'
PRODUCER_JOB = 126960239409
SOURCE = '850e3d1de780ae716973fc8400ac2a8f7985ee15'
TREE = 'd267e305cbe76717bb5984f83bb3409ff8162232'
ARTIFACT_ID = 13379157974
ARTIFACT_NAME = 'UDP-Echo-build-integrated-macOS-41940618811-1'
ARTIFACT_SIZE = 121490731
ARTIFACT_SHA = 'b521ca3439cbd77dbd9384b72f60332223d4cdeb22e469b99bfe79ceff54de36'
SOURCE_ZIP = 'integrated/Socks5-integrated-source.zip'
SOURCE_ZIP_SHA = '13b3dac82dbaad06513431a3c41f6b768afd7f7347b2ba577d2c28f3aaec76a7'
FRAMEWORK_ZIP = 'native-product/HevSocks5Server.xcframework.zip'
FRAMEWORK_SHA = 'b78ce6f2b23fc6bc184b1ebe0f6f5337707a79c0b806c8fe4212968a556a0dc5'
STATISTICS_OWNER = '89a8dd5a19d51fa9967bb049c41db3cb58a24d6a'
STATISTICS_TEST_SHA = 'ad93936842e1aa777dcf44e6cf1f8ba045031d5856052b3734be5422a3f89b64'
SAFE_ENV = ('GITHUB_ACTIONS', 'GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB',
            'GITHUB_SHA', 'GITHUB_REF', 'RUNNER_OS', 'RUNNER_ARCH', 'DEVELOPER_DIR')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def checked_zip(raw):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    entries = archive.infolist()
    require(len(entries) == len({i.filename for i in entries}), 'Duplicate ZIP entry')
    require(sum(i.file_size for i in entries) < 1024 ** 3, 'Unexpected ZIP expansion')
    for item in entries:
        path = PurePosixPath(item.filename)
        require(item.filename and not path.is_absolute() and '\\' not in item.filename
                and all(p not in ('', '.', '..') for p in item.filename.rstrip('/').split('/')),
                'Unsafe ZIP path')
        require(stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR),
                'Unexpected ZIP file type')
    require(archive.testzip() is None, 'ZIP CRC failure')
    return archive


def git_tree(archive):
    root = {}
    for entry in archive.infolist():
        if entry.is_dir():
            continue
        parts = PurePosixPath(entry.filename).parts
        node = root
        for name in parts[:-1]:
            node = node.setdefault(name, {})
        raw = archive.read(entry)
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).digest()
        node[parts[-1]] = ('100755' if entry.external_attr >> 16 & 0o111 else '100644', blob)

    def tree(node):
        raw = b''
        for name in sorted(node, key=lambda n: n.encode() + (b'/' if isinstance(node[n], dict) else b'')):
            item = node[name]
            mode, digest = ('40000', tree(item)) if isinstance(item, dict) else item
            raw += mode.encode() + b' ' + name.encode() + b'\0' + digest
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).digest()
    return tree(root).hex()


def extract(archive, folder):
    folder.mkdir(parents=True, exist_ok=False)
    for entry in archive.infolist():
        path = folder / entry.filename
        if entry.is_dir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(entry))
            path.chmod(0o755 if entry.external_attr >> 16 & 0o111 else 0o644)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_inputs(artifact, metadata, out):
    job, record = metadata['job'], metadata['artifact']
    require(job['id'] == PRODUCER_JOB and job['run_id'] == PRODUCER_RUN
            and job['status'] == 'completed' and job['conclusion'] == 'success'
            and job['name'] == f'build (integrated, {SOURCE}, xcode-27, true)',
            'Wrong or unsuccessful actual producer job')
    require(record['id'] == ARTIFACT_ID and record['name'] == ARTIFACT_NAME
            and record['size_in_bytes'] == ARTIFACT_SIZE
            and record['digest'] == 'sha256:' + ARTIFACT_SHA
            and record['workflow_run']['id'] == PRODUCER_RUN
            and record['workflow_run']['head_sha'] == PRODUCER_HELPER
            and not record['expired'], 'Wrong actual producer artifact metadata')
    raw = artifact.read_bytes()
    require(len(raw) == ARTIFACT_SIZE and sha(raw) == ARTIFACT_SHA, 'Artifact bytes changed')
    outer = checked_zip(raw)
    source_raw, framework_raw = outer.read(SOURCE_ZIP), outer.read(FRAMEWORK_ZIP)
    require(sha(source_raw) == SOURCE_ZIP_SHA and sha(framework_raw) == FRAMEWORK_SHA,
            'Wrong nested source or generated framework')
    source, framework = checked_zip(source_raw), checked_zip(framework_raw)
    require(source.comment.decode() == SOURCE and git_tree(source) == TREE, 'Source Git identity differs')
    native = json.loads(outer.read('native-product/identity.json'))
    require(native['commit'] == SOURCE and native['tree'] == TREE
            and native['helper_commit'] == PRODUCER_HELPER
            and native['run_id'] == str(PRODUCER_RUN) and native['run_attempt'] == '1',
            'Generated native product belongs to a different source/run/attempt')
    actual = {}
    for entry in framework.infolist():
        if not entry.is_dir():
            require(entry.filename.startswith('HevSocks5Server.xcframework/'), 'Wrong framework root')
            actual[entry.filename.split('/', 1)[1]] = {
                'size': entry.file_size, 'sha256': sha(framework.read(entry)),
                'mode': stat.S_IMODE(entry.external_attr >> 16)}
    require(actual == native['framework'], 'Generated framework inventory changed')
    built = json.loads(outer.read('integrated/built-framework.json'))
    require(built['commit'] == SOURCE and built['tree'] == TREE
            and built['framework'] == {k: {'sha256': v['sha256'],
                'mode': '100755' if v['mode'] & 0o111 else '100644'} for k, v in actual.items()},
            'Generated framework differs from actual integrated archive input')
    require(sha(source.read('Tests/Statistics/StatisticsUITests.swift')) == STATISTICS_TEST_SHA,
            'Integrated Statistics test differs from the current Statistics owner')
    extract(source, out / 'source')
    extract(framework, out / 'generated-native')
    (out / 'native-product-identity.json').write_bytes(outer.read('native-product/identity.json'))
    (out / 'built-framework.json').write_bytes(outer.read('integrated/built-framework.json'))
    return {'source_commit': SOURCE, 'source_tree': TREE, 'artifact_id': ARTIFACT_ID,
            'artifact_sha256': ARTIFACT_SHA, 'producer_run_id': PRODUCER_RUN,
            'producer_attempt': 1, 'producer_job_id': PRODUCER_JOB,
            'producer_helper_commit': PRODUCER_HELPER, 'source_files': len([
                x for x in source.infolist() if not x.is_dir()]),
            'generated_framework_files': len(actual), 'statistics_owner': STATISTICS_OWNER,
            'statistics_ui_source_sha256': STATISTICS_TEST_SHA}


def generate(out, build_project):
    source, app = out / 'source', out / 'application'
    shutil.copytree(source, app)
    shutil.rmtree(app / 'HevSocks5Server.xcframework')
    shutil.copytree(out / 'generated-native/HevSocks5Server.xcframework', app / 'HevSocks5Server.xcframework')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / 'Build'))
    ui = load_module('diagnostic_frozen_integrated_ui', source / 'Build/ui_review.py')
    builder = load_module('diagnostic_frozen_statistics_builder', source / 'Tests/Statistics/ui_audit.py')
    generated = ui.ui_test_source()
    (out / 'generated-StatisticsUITests.swift').write_bytes(generated)
    if build_project:
        builder.OUT = out
        builder.add_test_target(app)
        (app / 'StatisticsUITests.swift').write_bytes(generated)
    return {'test_source_sha256': sha(generated), 'test_source_bytes': len(generated),
            'project_built_by_original_function': build_project,
            'ui_consumer_sha256': sha((source / 'Build/ui_review.py').read_bytes()),
            'test_builder_sha256': sha((source / 'Tests/Statistics/ui_audit.py').read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--fetch', action='store_true')
    origin.add_argument('--artifact-zip', type=Path)
    parser.add_argument('--metadata-json', type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--compile', action='store_true')
    action.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = {'schema': 1, 'scope': 'DIAGNOSTIC_ONLY_XCUI_COMPILATION',
              'official_candidate_gate_credit': False, 'ui_tests_executed': False,
              'execution_kind': 'ACTUAL_DIAGNOSTIC_CI' if args.fetch or args.compile else 'LOCAL_VERIFY_ONLY',
              'toolchain_scope': 'Producer-matched Xcode 27.1/SDK 27.1 compile only; official runtime uses Xcode 27.0 and is not replaced by this result.',
              'actual_diagnostic_environment': {k: os.environ.get(k) for k in SAFE_ENV},
              'driver_sha256': sha(Path(__file__).read_bytes()), 'status': 'STARTED'}
    try:
        require(__debug__, 'Assertions must remain enabled')
        if args.fetch or args.compile:
            require(os.environ.get('GITHUB_ACTIONS') == 'true'
                    and os.environ.get('GITHUB_REPOSITORY') == REPOSITORY
                    and os.environ.get('GITHUB_REF') == 'refs/heads/work/udp-echo-udp-20261028'
                    and os.environ.get('GITHUB_JOB') == 'compile_current_xcui_only'
                    and os.environ.get('GITHUB_RUN_ID', '').isdigit()
                    and int(os.environ['GITHUB_RUN_ID']) > 0
                    and os.environ.get('GITHUB_RUN_ATTEMPT', '').isdigit()
                    and int(os.environ['GITHUB_RUN_ATTEMPT']) > 0
                    and os.environ.get('GITHUB_RUN_ID') != str(PRODUCER_RUN),
                    'Expected a separate real diagnostic run in the same repository')
            helper = Path(__file__).resolve().parents[1]
            checkout = subprocess.check_output(['git', '-C', str(helper), 'rev-parse', 'HEAD'],
                                               text=True, timeout=30).strip()
            require(checkout == os.environ.get('GITHUB_SHA'), 'Diagnostic checkout/event identity differs')
            for arguments in [('diff', '--exit-code', 'HEAD', '--'),
                              ('diff', '--cached', '--exit-code', 'HEAD', '--')]:
                subprocess.run(['git', '-C', str(helper), *arguments], check=True, timeout=30)
            status = subprocess.check_output(['git', '-C', str(helper), 'status', '--porcelain=v1',
                                               '--untracked-files=all'], text=True, timeout=30)
            require(not status, 'Diagnostic helper checkout is not clean')
            tree = subprocess.check_output(['git', '-C', str(helper), 'rev-parse', 'HEAD^{tree}'],
                                           text=True, timeout=30).strip()
            result['actual_diagnostic_helper'] = {'commit': checkout, 'tree': tree, 'clean': True}
        if args.fetch:
            metadata = {}
            for key, suffix in [('job', f'jobs/{PRODUCER_JOB}'), ('artifact', f'artifacts/{ARTIFACT_ID}')]:
                data = subprocess.check_output(['gh', 'api', f'repos/{REPOSITORY}/actions/{suffix}'], timeout=60)
                metadata[key] = json.loads(data)
            artifact = out / 'original-producer-artifact.zip'
            with artifact.open('xb') as stream:
                subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}/zip'],
                               stdout=stream, check=True, timeout=300)
        else:
            require(args.metadata_json is not None, 'Saved actual API metadata is required')
            artifact = args.artifact_zip.resolve(strict=True)
            metadata = json.loads(args.metadata_json.read_bytes())
        write_json(out / 'actual-producer-api-metadata.json', metadata)
        result['verified_input'] = verify_inputs(artifact, metadata, out)
        require(not args.compile or sys.platform == 'darwin', 'Apple compilation requires macOS')
        result['generated'] = generate(out, args.compile)
        if not args.compile:
            result['status'] = 'DIAGNOSTIC_INPUT_AND_TEST_SOURCE_VERIFIED_ONLY'
            return
        version = subprocess.check_output(['xcodebuild', '-version'], text=True, timeout=60)
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'], text=True, timeout=60).strip()
        (out / 'xcode-version.txt').write_text(version)
        (out / 'simulator-sdk-version.txt').write_text(sdk + '\n')
        require(version == 'Xcode 27.1\nBuild version 27A9275\n' and sdk == '27.1',
                'Diagnostic toolchain differs from the actual v3 producer toolchain')
        command = ['xcodebuild', 'build-for-testing', '-project', str(out / 'application/Socks5.xcodeproj'),
                   '-scheme', 'StatisticsUIAudit', '-sdk', 'iphonesimulator',
                   '-destination', 'generic/platform=iOS Simulator', '-parallel-testing-enabled', 'NO',
                   '-derivedDataPath', str(out / 'DerivedData'), 'CODE_SIGNING_ALLOWED=NO',
                   'SWIFT_TREAT_WARNINGS_AS_ERRORS=YES', 'MARKETING_VERSION=3.0.0', 'CURRENT_PROJECT_VERSION=1']
        result['compile_command'] = {'argv': command, 'timeout_seconds': 900, 'started_unix': time.time()}
        with (out / 'build-for-testing.log').open('xb') as stream:
            completed = subprocess.run(command, cwd=out / 'application', stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, timeout=900)
        result['compile_command'].update(returncode=completed.returncode, finished_unix=time.time())
        require(completed.returncode == 0, 'Actual build-for-testing failed; see diagnostic build log')
        products = out / 'DerivedData/Build/Products'
        require((products / 'Debug-iphonesimulator/Socks5.app/Socks5').is_file(), 'Missing built app')
        tests = sorted(products.rglob('StatisticsUITests.xctest/StatisticsUITests'))
        runs = sorted(products.glob('*.xctestrun'))
        require(tests and runs, 'Missing compiled XCUI bundle or xctestrun')
        app_binary = products / 'Debug-iphonesimulator/Socks5.app/Socks5'
        result['compiled_products'] = {str(p.relative_to(out)): sha(p.read_bytes()) for p in [app_binary] + tests + runs}
        result['status'] = 'DIAGNOSTIC_BUILD_FOR_TESTING_PASSED'
    except BaseException as error:
        result.update(status='DIAGNOSTIC_FAILED', error=repr(error))
        raise
    finally:
        write_json(out / 'diagnostic-result.json', result)


if __name__ == '__main__':
    main()
