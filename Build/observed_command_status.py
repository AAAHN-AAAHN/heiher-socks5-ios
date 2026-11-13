#!/usr/bin/env python3
"""Inline caller binding; never launches an original command or a host observer."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

OBSERVER_SHA256 = '277f667fd17d96e9b3f6fbd733282d9b3622d782e20d2e2a4ab3a35d2b4575f8'
OBSERVER_BYTES = 18796
COMMON_SHA256 = '2a878ba7c6f8a138ce1b37585a3e7d3b716c28d44bddbfcda83b1ac62666a6f5'
OBSERVER_PATH = 'Build/observe_host_during_command.py'
CONTEXT_KEYS = ('GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
                'GITHUB_JOB', 'GITHUB_REF', 'RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH', 'DEVELOPER_DIR')
PROFILES = {
    'statistics-ui': ('statistics', ['python3', 'Tests/Statistics/ui_audit.py'], 'artifacts/statistics-ui-audit'),
    'server-ui': ('server', ['python3', 'Tests/ServerControl/ui_audit.py'], 'artifacts/server-control-ui-audit'),
    'settings-ui': ('settings', ['python3', 'Tests/Settings/ui_audit.py'], 'artifacts/settings-persistence-ui-audit'),
    'integrated-ui': ('integrated', ['python3', 'Build/ui_review.py'], 'artifacts/integrated'),
    'integrated-simulator': ('integrated', ['python3', 'Build/simulator_review.py'], 'artifacts/integrated'),
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate JSON key: ' + key)
        value[key] = item
    return value


def within_root(path, root):
    require(path.is_absolute() and path != root and root in path.parents, 'Evidence path escaped source root')
    for item in (path, *path.parents):
        require(not item.is_symlink(), 'Linked evidence path is rejected: ' + str(item))
        if item == root:
            break
    return path


def regular_bytes(path, root, maximum=4 * 1024 * 1024):
    within_root(path, root)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= maximum,
                'Evidence is not a bounded unlinked regular file: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(fd)
        identity = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_nlink, row.st_uid,
                                row.st_gid, row.st_size, row.st_mtime_ns, row.st_ctime_ns)
        require(identity(before) == identity(after) and len(raw) == before.st_size,
                'Evidence changed while reading: ' + str(path))
        return raw, {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                     'device': after.st_dev, 'inode': after.st_ino, 'mode': stat.S_IMODE(after.st_mode),
                     'uid': after.st_uid, 'gid': after.st_gid, 'mtime_ns': after.st_mtime_ns}
    finally:
        os.close(fd)


def read_json(path, root):
    raw, record = regular_bytes(path, root)
    return json.loads(raw, object_pairs_hook=unique_object), record


def save_new(path, value, root):
    within_root(path, root)
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb', buffering=0) as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'Output is not a regular file')
        remaining = memoryview(raw)
        while remaining:
            written = stream.write(remaining)
            require(bool(written), 'Output write made no progress')
            remaining = remaining[written:]


def checked_common_before(root, source, owner, consumer, before_path):
    value, record = read_json(before_path, root)
    require(value['schema'] == 'installed-runtime-consumer-before-v1'
            and value['consumer'] == consumer and value['result'] == 'BOUND_BEFORE_ORIGINAL_CONSUMER',
            'Original common before did not bind this consumer')
    identity = value['identity']
    require(identity['owner'] == owner and identity['source_root'] == str(root)
            and identity['source'] == source and identity['own_helper_sha256'] == COMMON_SHA256,
            'Common before source/owner/helper identity differs')
    require(identity['helper_files'] and set(identity['helper_files'].values()) == {COMMON_SHA256},
            'Common helper copy identities differ')
    actual = identity['consumer']
    for key, env in [('repository', 'GITHUB_REPOSITORY'), ('run_id', 'GITHUB_RUN_ID'),
                     ('attempt', 'GITHUB_RUN_ATTEMPT'), ('job', 'GITHUB_JOB')]:
        require(actual[key] == os.environ[env], 'Common before actual caller differs: ' + key)
    if identity['mode'] == 'workflow-input':
        require(owner == 'statistics' and identity['control'] is None and identity['control_root'] is None
                and actual['github_sha'] == os.environ['GITHUB_SHA']
                and identity['workflow_input_binding']['raw_input_ref'] == os.environ.get('RUNTIME_COMMON_SOURCE_REF')
                and identity['workflow_input_binding']['actual_source'] == source,
                'Explicit workflow-input source/caller axes differ')
    else:
        require(identity['mode'] in ('canonical', 'candidate')
                and identity['control']['commit'] == os.environ['GITHUB_SHA']
                and actual['helper'] == identity['control'], 'Current control context differs')
    return value, record


def observer_file(root, source):
    raw, record = regular_bytes(root / OBSERVER_PATH, root)
    require(record['bytes'] == OBSERVER_BYTES and record['sha256'] == OBSERVER_SHA256
            and record['mode'] == 0o644, 'Observer is not the exact reviewed bytes/mode')
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    command = ['git', '-C', str(root), 'ls-tree', source['commit'], '--', OBSERVER_PATH]
    result = subprocess.run(command, capture_output=True, timeout=10)
    require(result.returncode == 0 and result.stderr == b''
            and result.stdout == ('100644 blob ' + blob + '\t' + OBSERVER_PATH + '\n').encode(),
            'Exact observer must be tracked by the actual source commit')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('before', 'after'))
    parser.add_argument('owner')
    parser.add_argument('consumer', choices=tuple(PROFILES))
    parser.add_argument('source_root')
    parser.add_argument('source_commit')
    parser.add_argument('source_tree')
    parser.add_argument('actual_wrapper_status', nargs='?')
    args = parser.parse_args()
    root = Path(args.source_root)
    require(root.is_absolute() and root.resolve(strict=True) == root and Path.cwd().resolve() == root,
            'Caller must use the unchanged explicit source cwd')
    require(all(re.fullmatch('[0-9a-f]{40}', value) for value in (args.source_commit, args.source_tree)),
            'Source commit/tree are not full identities')
    owner, command, artifact = PROFILES[args.consumer]
    require(owner == args.owner, 'Consumer belongs to another owner')
    source = {'commit': args.source_commit, 'tree': args.source_tree}
    parent = root / artifact / 'runtime-preparation/consumers' / args.consumer
    within_root(parent, root)
    require(parent.is_dir(), 'Original common before must create this consumer parent')
    output = parent / 'host-observation'
    before_path = parent / 'before.json'
    context = {key: os.environ.get(key) for key in CONTEXT_KEYS}
    report = {'schema': 'formal-host-observer-caller-binding-v1', 'phase': args.phase,
              'started_utc': utc_now(), 'source': source, 'source_root': str(root),
              'owner': owner, 'consumer': args.consumer, 'context': context,
              'observer_output': str(output), 'original_argv': command,
              'original_status_recovered': False, 'formal_credit': False, 'product_pass': False,
              'result': 'FAILED', 'actual_wrapper_status': None}
    failure = None
    try:
        before, common_info = checked_common_before(root, source, owner, args.consumer, before_path)
        observer_info = observer_file(root, source)
        report['common_before'] = common_info
        report['common_identity'] = before['identity']
        report['observer_file'] = observer_info
        if args.phase == 'before':
            require(args.actual_wrapper_status is None and not output.exists(),
                    'Host observation must be a fresh single original invocation')
            require(not (parent / 'host-observer-after.json').exists(), 'Old observer after evidence is present')
            report['result'] = 'BOUND_BEFORE_ONE_OBSERVED_ORIGINAL'
        else:
            require(args.actual_wrapper_status is not None and re.fullmatch(r'0|[1-9][0-9]{0,2}', args.actual_wrapper_status),
                    'Actual captured wrapper shell status is malformed')
            actual_status = int(args.actual_wrapper_status)
            require(0 <= actual_status <= 255, 'Actual wrapper status is outside shell range')
            report['actual_wrapper_status'] = actual_status
            prior, prior_info = read_json(parent / 'host-observer-before.json', root)
            require(prior['schema'] == report['schema'] and prior['phase'] == 'before'
                    and prior['result'] == 'BOUND_BEFORE_ONE_OBSERVED_ORIGINAL'
                    and all(prior[key] == report[key] for key in ('source', 'source_root', 'owner', 'consumer',
                        'context', 'observer_output', 'original_argv', 'common_before', 'common_identity', 'observer_file')),
                    'Observer before context or immutable source binding changed')
            report['observer_before'] = prior_info
            observed, observed_info = read_json(output / 'host-observation-result.json', root)
            report['observer_report'] = observed_info
            require(type(observed['schema']) is int and observed['schema'] == 1
                    and observed['scope'] == 'host_log_observation_around_one_original_command'
                    and observed['context'] == context and observed['wrapper_cwd'] == str(root)
                    and observed['wrapper_source'] == observer_info,
                    'Actual observer report belongs to another source/run/cwd/observer')
            require(observed['wrapper_argv'][0] == str(root / OBSERVER_PATH)
                    and observed['wrapper_argv'][1:] == ['--output', str(output), '--', *command],
                    'Actual observer invocation differs')
            child = observed['original_command']
            require(child['argv'] == command and type(child['launch_attempts']) is int and child['launch_attempts'] == 1
                    and type(child['launches']) is int and child['launches'] == 1
                    and type(child['pid']) is int and child['pid'] > 0
                    and child['timeout_seconds'] is None and child['stdio'] == 'inherited'
                    and child['environment'] == 'inherited_without_modification',
                    'Original command argv/launch/stdio/environment/deadline differs')
            raw = child['raw_popen_returncode']
            require(type(raw) is int and -127 <= raw <= 255, 'No trustworthy original process return code')
            original_status = raw if raw >= 0 else 128 - raw
            require(type(child['shell_numeric_exit_code']) is int
                    and child['shell_numeric_exit_code'] == original_status
                    and child['terminated_by_signal'] is (raw < 0), 'Original signal/shell mapping differs')
            if raw < 0:
                require(type(child['signal_number']) is int and child['signal_number'] == -raw,
                        'Original native signal differs')
            require(type(observed['wrapper_exit_code']) is int and observed['wrapper_exit_code'] == actual_status,
                    'Actual wrapper exit differs from its report')
            if raw != 0:
                require(actual_status == original_status and observed['wrapper_exit_reason'] == 'original_command_nonzero',
                        'Wrapper did not preserve actual original nonzero status')
            # The numeric stdout is deliberately before all secondary evidence
            # checks and writes. Bash keeps this value even if a later write fails.
            report['original_status_recovered'] = True
            report['original_raw_returncode'] = raw
            report['original_shell_status'] = original_status
            print(original_status, flush=True)
            require(observed['recording_complete'] is True, 'Observer did not finish its report')
            if actual_status == 0:
                require(raw == 0 and observed['result'] == 'OBSERVED_ORIGINAL_COMMAND_COMPLETED'
                        and observed['wrapper_exit_reason'] == 'original_exit_zero_and_observer_completed'
                        and observed['observer_errors'] == [] and observed['received_wrapper_signals'] == [],
                        'Actual wrapper success lacks complete original/observer evidence')
            limits = observed['limits']
            require(limits['no_original_command_timeout_added'] is True
                    and all(type(limits[key]) is int and limits[key] == 0 for key in (
                        'original_command_retry_count', 'original_command_signals_sent_by_wrapper',
                        'other_infrastructure_signals_sent_by_wrapper',
                        'runtime_device_cache_or_logging_configuration_mutations')),
                    'Observer modified an original command or runtime contract')
            collector = observed['collector']
            records = collector.get('files', [])
            report['actual_original'] = child
            report['actual_observer_result'] = observed['result']
            report['actual_observer_errors'] = observed['observer_errors']
            report['collector_file_bindings'] = []
            for name in ('host-stream.stdout.log', 'host-stream.stderr.log'):
                matching = [item for item in records if item.get('path') == str(output / name)]
                require(len(matching) == 1, 'Observer collector file is missing or duplicated: ' + name)
                _, file_info = regular_bytes(output / name, root, maximum=32 * 1024 * 1024)
                require(matching[0] == file_info, 'Observer collector bytes/modes changed: ' + name)
                report['collector_file_bindings'].append(file_info)
            if actual_status == 0:
                require(type(collector['launch_attempts']) is int and collector['launch_attempts'] == 1
                        and type(collector['launches']) is int and collector['launches'] == 1
                        and collector['direct_child_reaped'] is True and collector['new_session'] is True,
                        'Successful observer lacks completed owned collector')
            report['result'] = 'BOUND_ACTUAL_ORIGINAL_AND_OBSERVER_EXITS'
    except BaseException as error:
        failure = error
        report['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        report['finished_utc'] = utc_now()
        try:
            save_new(parent / ('host-observer-' + args.phase + '.json'), report, root)
        except BaseException as error:
            if failure is None:
                failure = error
            print('Host observer caller record failed: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
    if failure is not None:
        print('Host observer caller binding failed: ' + type(failure).__name__ + ': ' + str(failure), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
