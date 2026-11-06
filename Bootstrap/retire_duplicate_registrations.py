#!/usr/bin/env python3
"""One old-iOS retirement, then bounded read-only watch settlement.

This control helper never edits the source or invokes an application consumer.
Its result is not a formal/common-preparation success receipt. A caller may run
the unchanged diagnostic consumers only after this process actually exits zero.
Watch UUIDs are never mutation targets. Their absence is external observation,
not an operation owned by this process or evidence of a particular cause.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time

SOURCE = '3a6ba06abcbffc48bb5c7290a5e53709e3809fbc'
TREE = '6e745ac08beb1ab9eeb9e367cdaa28148d2f3600'
COMMON_SHA256 = '32bdd3b00bfcbaebc0239add52fc0094db81f42afb84c342bb8d90a39befcabe'
ORIGINAL_CONSUMERS = {
    'Build/ui_review.py': '3a155a9c78b5acdd5f40b3057d3077c309c4a5ff8545a509e8da1d591e50ad30',
    'Build/simulator_review.py': 'e1897dd4aba4702ad6ee28332fa6d614606260e05c98c310ba6a4464c9e4590f',
}
SELF_PATH = 'Bootstrap/retire_duplicate_registrations.py'
PREPARATION = 'artifacts/integrated/runtime-preparation'
META_TIMEOUT = 10
DELETE_TIMEOUT = 120
MAX_TARGETS = 3
SETTLEMENT_SECONDS = 120
SAMPLE_INTERVAL = 2
MAX_SETTLEMENT_SNAPSHOTS = 61
UNUSABLE_FIELDS = ('unusableErrorDetail', 'unusableErrorMessage', 'unusableSubstate')
UUID = re.compile(r'[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def file_identity(info):
    # Reading can update atime; it is not part of a stable content identity.
    return tuple(getattr(info, field) for field in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid',
                                                  'st_size', 'st_mtime_ns', 'st_ctime_ns'))


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError('Non-finite JSON value: ' + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def exact_directory(value):
    path = Path(value)
    require(path.is_absolute() and path.is_dir() and path.resolve() == path,
            'Require an existing absolute directory without aliases')
    require(not any(item.is_symlink() for item in (path, *path.parents)), 'Linked directory')
    return path


def raw_file(path, limit=64 * 1024 * 1024):
    require(not any(item.is_symlink() for item in (path, *path.parents)), 'Linked input/output file')
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= limit, 'Expected bounded regular file: ' + str(path))
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        require(file_identity(os.fstat(stream.fileno())) == file_identity(before), 'File changed before opening')
        raw = stream.read(limit + 1)
        require(len(raw) <= limit and file_identity(os.fstat(stream.fileno())) == file_identity(before), 'File changed during read')
    require(file_identity(path.lstat()) == file_identity(before), 'File changed after read')
    return raw, {'path': str(path), 'bytes': len(raw), 'sha256': sha256(raw), 'mode': stat.S_IMODE(before.st_mode)}


def unusable_duplicate(row):
    return (row.get('state') == 'Unusable'
            and row.get('unusableErrorMessage') == 'Cryptex Mount Preferred'
            and row.get('unusableSubstate') == 'Cryptex Mount Preferred'
            and ('unusableErrorDetail' not in row or
                 isinstance(row['unusableErrorDetail'], str) and 'Cryptex Mount Preferred' in row['unusableErrorDetail']))


def enoent_path(row, path):
    """Only the original path_snapshot's concrete FileNotFoundError is missing."""
    return row == {'value': path, 'capture': 'unavailable',
                   'error': {'type': 'FileNotFoundError', 'errno': 2,
                             'message': str(FileNotFoundError(2, os.strerror(2), path))}}


def overlaps(left, right):
    a, b = Path(left), Path(right)
    return a.is_relative_to(b) or b.is_relative_to(a)


def fixed_paths(records, old, watches):
    """Key the ledger by literal path; both watch UUIDs may share one alias."""
    paths = {}
    for key in [old, *watches]:
        fields = ('mountPath',) if key == old else ('mountPath', 'runtimeBundlePath', 'path', 'parentMountPath')
        for field in fields:
            value = records[key][field]
            require(isinstance(value, str) and Path(value).is_absolute() and Path(value).as_posix() == value
                    and '..' not in Path(value).parts, 'Malformed frozen path')
            paths.setdefault(value, []).append({'uuid': key, 'field': field})
    return paths


def runtime_mount_rows(data, mounts, keys):
    paths = {data[key][field] for key in keys for field in ('mountPath', 'runtimeBundlePath')}
    return {path: mounts.get(path, []) for path in sorted(paths)}


def watch_state(frozen, current):
    if current is None:
        return 'Absent'
    if current == frozen and unusable_duplicate(current):
        return 'Unusable'
    deleting = {key: value for key, value in frozen.items() if key not in UNUSABLE_FIELDS}
    deleting['state'] = 'Deleting'
    require(current == deleting, 'Watch record changed beyond the exact observed Deleting transition')
    return 'Deleting'


def check_delete_request(plan, attempted, invoked, target, argv, timeout):
    require(plan is not None and target == plan['old_ios_uuid'] and plan['mutation_target_ids'] == [target]
            and not attempted and not invoked, 'Only the frozen old iOS may receive one total mutation attempt')
    require(argv == ['xcrun', 'simctl', 'runtime', 'delete', target, '--keep-asset']
            and timeout == DELETE_TIMEOUT, 'Mutation is outside the single old-iOS keep-asset command')


def freeze_plan(common, preflight, service, current):
    """Pure planning: freeze existing identities, never discover replacement targets."""
    inventory, filesystem = current['inventory'], current['filesystem']
    expected = service['runtime_snapshots']['after']
    require(canonical(inventory) == canonical(expected['inventory']),
            'Runtime registrations changed since completed original preparation')
    require(canonical(filesystem) == canonical(expected['filesystem']),
            'Runtime filesystem identities changed since completed original preparation')
    common.validate_runtime(preflight, inventory, filesystem)
    old = preflight['selected_original_runtime']['target_uuid']
    new = preflight['scope_after_verify']['new_uuid']
    require(old != new and unusable_duplicate(inventory[old]), 'Exactly the original old iOS duplicate must be Unusable')
    require(inventory[new]['state'] == 'Ready' and inventory[new]['signatureState'] == 'Verified',
            'New staged iOS image is not Ready/Verified')
    watches = common.watch_records(inventory)
    ready = [key for key, row in watches.items() if row['state'] == 'Ready']
    retired_watches = sorted(key for key, row in watches.items() if unusable_duplicate(row))
    require(len(ready) == 1 and len(retired_watches) <= 2 and set(watches) == set(ready + retired_watches),
            'Require one exact Ready watch27.0 and at most two exact Unusable duplicates; no Copying/Deleting')
    original_watch_ids = set(common.watch_records(preflight['runtime_snapshots']['before']['inventory']))
    require(set(retired_watches) <= original_watch_ids, 'A new or unrelated watch UUID cannot become a target')
    targets = [old, *retired_watches]
    require(1 <= len(targets) <= MAX_TARGETS and len(set(targets)) == len(targets)
            and all(UUID.fullmatch(key) for key in targets) and new not in targets and ready[0] not in targets,
            'Invalid bounded target set')
    for key in targets:
        require(unusable_duplicate(inventory[key]), 'Target is not the exact Unusable duplicate class')
    require(all(all(field in inventory[key] for field in UNUSABLE_FIELDS) for key in retired_watches),
            'Watch freeze requires all three actual Unusable fields')
    plan = {'old_ios_uuid': old, 'new_ios_uuid': new, 'ready_watch_uuid': ready[0],
            'target_ids': targets, 'target_records': {key: inventory[key] for key in targets},
            'mutation_target_ids': [old], 'watch_observation_ids': retired_watches,
            'baseline_inventory': inventory, 'baseline_filesystem': filesystem,
            'protected_ids': sorted(set(inventory) - set(targets)),
            'devices': current['devices'], 'asset_files': current['asset_files'],
            'protected_mount_paths': [inventory[new]['mountPath'], inventory[ready[0]]['mountPath']],
            'target_order': 'One old-iOS delete, then only scheduled read-only watch observations; no causal claim.'}
    plan['fixed_paths'] = fixed_paths(plan['target_records'], old, retired_watches)
    require(set(current['fixed_path_observations']) == set(plan['fixed_paths']), 'Initial literal path ledger differs')
    plan['path_baselines'] = {}
    protected_aliases = [inventory[key][field] for key in plan['protected_ids']
                         for field in ('mountPath', 'runtimeBundlePath')]
    for path, references in plan['fixed_paths'].items():
        baseline = current['fixed_path_observations'][path]['filesystem']
        require(all(baseline == filesystem[ref['uuid']][ref['field']] for ref in references),
                'Shared literal-path observations disagree with the original preparation')
        plan['path_baselines'][path] = baseline
        if any(ref['field'] in ('mountPath', 'runtimeBundlePath') for ref in references):
            require(not any(overlaps(path, protected) for protected in protected_aliases),
                    'A target alias overlaps a protected runtime mount or bundle')
            require((baseline.get('capture') == 'observed' and baseline.get('is_directory') is True)
                    or enoent_path(baseline, path), 'Unsupported initial old runtime alias filesystem')
    plan['protected_mount_proofs'] = current['mount_proofs']
    plan['protected_mount_rows'] = runtime_mount_rows(inventory, current['mount_table'], plan['protected_ids'])
    plan['initial_alias_limit'] = 'Every frozen old alias must already be an actual non-mount; this probe accepts no initially mounted target alias.'
    progress = initial_progress(plan)
    validate_state(common, plan, current, progress, old_deleted=False)
    return plan


def initial_progress(plan):
    return {'watch_states': {key: 'Unusable' for key in plan['watch_observation_ids']},
            'deleting_observed': [], 'absence_dispositions': {}, 'transitions': [],
            'missing_paths': sorted(path for path, row in plan['path_baselines'].items() if enoent_path(row, path))}


def validate_state(common, plan, current, progress, *, old_deleted, final=False):
    """Read-only validation; progress is committed only after every guard passes."""
    data, baseline = current['inventory'], plan['baseline_inventory']
    require(set(data) <= set(baseline), 'New runtime registration appeared; never select a substitute')
    require(set(baseline) - set(data) <= set(plan['target_ids']), 'A protected runtime disappeared')
    require(set(current['filesystem']) == set(data), 'Runtime filesystem inventory differs')
    require(common.require_shutdown_devices(current['raw_devices']) == current['devices'], 'Raw device normalization differs')
    require(current['devices'] == plan['devices'], 'Device identities or Shutdown states changed')
    require(current['asset_files'] == plan['asset_files'], 'A retained asset/DMG identity changed')
    for key in plan['protected_ids']:
        require(key in data and canonical(data[key]) == canonical(baseline[key]), 'Protected runtime record changed: ' + key)
        require(canonical(current['filesystem'][key]) == canonical(plan['baseline_filesystem'][key]),
                'Protected runtime filesystem changed: ' + key)
    old = plan['old_ios_uuid']
    if old_deleted:
        require(old not in data, 'Own successful old-iOS delete must be followed by its exact UUID absence')
    else:
        require(old in data and data[old] == plan['target_records'][old] and unusable_duplicate(data[old]),
                'The one old-iOS mutation target is absent or changed before its invocation')
        require(current['filesystem'][old] == plan['baseline_filesystem'][old], 'Old iOS filesystem changed before deletion')
    updated = strict_json(canonical(progress))
    phases = {}
    allowed = {'Unusable': {'Unusable', 'Deleting', 'Absent'}, 'Deleting': {'Deleting', 'Absent'}, 'Absent': {'Absent'}}
    require(set(progress['watch_states']) == set(plan['watch_observation_ids']), 'Watch observation identities differ')
    for key in plan['watch_observation_ids']:
        phase = watch_state(plan['target_records'][key], data.get(key))
        previous = progress['watch_states'][key]
        require(previous in allowed and phase in allowed[previous], 'Watch state regressed or its frozen UUID reappeared: ' + key)
        phases[key] = phase
        if phase == 'Deleting' and key not in updated['deleting_observed']:
            updated['deleting_observed'].append(key)
        if phase != previous:
            updated['transitions'].append({'uuid': key, 'from': previous, 'to': phase, 'snapshot': current['label'],
                                           'observed_unix': current['finished_unix'], 'watch_delete_invoked': False})
        updated['watch_states'][key] = phase
        if phase == 'Absent' and key not in updated['absence_dispositions']:
            updated['absence_dispositions'][key] = (
                'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AFTER_OBSERVED_DELETING' if key in updated['deleting_observed'] else
                'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AND_WITHOUT_OBSERVED_DELETING')
    require(set(current['fixed_path_observations']) == set(plan['fixed_paths']), 'Fixed old path ledger changed')
    for path, references in plan['fixed_paths'].items():
        observation = current['fixed_path_observations'][path]
        require(observation['resolved_path'] == path and observation['symlink_components'] == [],
                'An old path is an indirect alias: ' + path)
        # This narrowly supported diagnostic starts with old aliases already
        # unmounted. No alias is allowed to appear at any later observation.
        require(observation['os_path_ismount'] is False and observation['related_mount_rows'] == {},
                'An old path or a child acquired an actual mount: ' + path)
        captured, original = observation['filesystem'], plan['path_baselines'][path]
        require(captured.get('value') == path, 'Fixed path observation refers to another path')
        for ref in references:
            if ref['uuid'] in data:
                require(captured == current['filesystem'][ref['uuid']][ref['field']], 'Two reads of one old path disagree')
        watch_refs = [ref for ref in references if ref['uuid'] in phases]
        removable = (all(ref['field'] in ('mountPath', 'runtimeBundlePath') for ref in references)
                     and ((bool(watch_refs) and all(phases[ref['uuid']] in ('Deleting', 'Absent') for ref in watch_refs))
                          or (not watch_refs and old_deleted)))
        require(captured == original or (removable and enoent_path(captured, path)),
                'Old path changed beyond exact identity or permitted ENOENT: ' + path)
        require(path not in progress['missing_paths'] or enoent_path(captured, path), 'An absent old path reappeared: ' + path)
        if enoent_path(captured, path) and path not in updated['missing_paths']:
            updated['missing_paths'].append(path)
    new = data[plan['new_ios_uuid']]
    require(new['state'] == 'Ready' and new['signatureState'] == 'Verified', 'Selected iOS lost Ready/Verified')
    watches = common.watch_records(data)
    ready = [key for key, row in watches.items() if row['state'] == 'Ready']
    require(ready == [plan['ready_watch_uuid']], 'Sole Ready watch identity changed; a new Ready UUID is not accepted')
    require(current['mounted_paths'] == plan['protected_mount_paths'], 'Protected actual mount proof is incomplete')
    require(current['mount_proofs'] == plan['protected_mount_proofs'], 'Protected actual mount identity, source or options changed')
    require(runtime_mount_rows(data, current['mount_table'], plan['protected_ids']) == plan['protected_mount_rows'],
            'Non-target runtime mount membership or rows changed')
    if final:
        require(old_deleted, 'No successful own old-iOS deletion was bound')
        require(not (set(plan['target_ids']) & set(data)), 'A frozen duplicate remains')
        require(set(watches) == {plan['ready_watch_uuid']}, 'Watch27.0 is not a single unchanged Ready registration')
        ios = [key for key, row in data.items() if row.get('runtimeIdentifier') == common.IOS]
        require(ios == [plan['new_ios_uuid']], 'Selected iOS runtime still has duplicate registrations')
    return updated


class Probe:
    def __init__(self, source, output):
        self.source, self.output = source, output
        self.labels, self.attempted, self.invoked = set(), set(), set()
        self.common = self.preflight = self.service = self.plan = None
        self.settlement_deadline = None
        self.progress = None
        self.watch_dmg = None
        self.report = {'schema': 'exact-3a-old-ios-delete-watch-observation-diagnostic-v2',
                       'started_unix': time.time(), 'source_commit': SOURCE, 'source_tree': TREE,
                       'formal_acceptance_credit': False, 'common_preparation_success_claimed': False,
                       'source_or_ref_modified': False, 'application_consumer_invocations': 0,
                       'candidate_runtime_success_claimed': False, 'caller_actual_exit_required': True,
                       'original_consumers_may_run_after_actual_exit_zero': False,
                       'limits': {'metadata_seconds': META_TIMEOUT, 'delete_seconds': DELETE_TIMEOUT,
                                  'max_frozen_targets': MAX_TARGETS, 'total_mutation_attempts': 1,
                                  'watch_delete_invocations': 0, 'settlement_seconds': SETTLEMENT_SECONDS,
                                  'sample_interval_seconds': SAMPLE_INTERVAL,
                                  'max_settlement_snapshots': MAX_SETTLEMENT_SNAPSHOTS,
                                  'settlement_budget_covers_final_metadata_and_guards': True,
                                  'retries': 0, 'replacement_targets': 0, 'service_signals': 0,
                                  'consumer_deadlines_changed': False},
                       'commands': [], 'snapshots': [], 'target_actions': []}

    def save(self):
        pending = self.output / 'result.pending.json'
        pending.write_text(json.dumps(self.report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        pending.replace(self.output / 'result.json')

    def remaining(self):
        if self.settlement_deadline is None:
            return None
        value = self.settlement_deadline - time.monotonic()
        require(value > 0, 'The single read-only settlement deadline expired; no consumer may run')
        return value

    def run(self, label, argv, timeout=META_TIMEOUT, target=None):
        require(label not in self.labels, 'Command cannot be retried: ' + label)
        self.labels.add(label)
        if target is not None:
            check_delete_request(self.plan, self.attempted, self.invoked, target, argv, timeout)
        else:
            git_root = argv[:3] == ['git', '-C', str(self.source)] or (
                self.report.get('control_root') and argv[:3] == ['git', '-C', self.report['control_root']])
            git_read = git_root and (argv[3:] == ['rev-parse', 'HEAD', 'HEAD^{tree}'] or
                                    argv[3:8] == ['ls-tree', '-r', '-z', 'HEAD', '--'] or
                                    argv[3:7] == ['ls-files', '--stage', '-z', '--'])
            require(timeout == META_TIMEOUT and
                    (git_read or
                     argv in (['xcrun', '--find', 'simctl'], ['xcrun', 'simctl', 'runtime', 'list', '-j'],
                              ['xcrun', 'simctl', 'list', 'devices', '-j'], ['/sbin/mount'],
                              ['xcrun', 'simctl', 'list', 'runtimes', '-j'],
                              ['xcrun', 'simctl', 'list', 'devicetypes', '-j'])),
                    'Command is outside diagnostic metadata operations')
        row = {'label': label, 'argv': argv, 'requested_timeout_seconds': timeout,
               'started_unix': time.time(), 'returncode': None, 'timed_out': False,
               'stdout_file': label + '.stdout.log', 'stderr_file': label + '.stderr.log'}
        self.report['commands'].append(row)
        process, failure, started = None, None, time.monotonic()
        try:
            self.remaining()
            self.save()
            with (self.output / row['stdout_file']).open('xb') as out, (self.output / row['stderr_file']).open('xb') as err:
                remaining = self.remaining()
                effective = min(timeout, remaining) if remaining is not None else timeout
                row['effective_timeout_seconds'] = effective
                row['settlement_remaining_at_launch_seconds'] = remaining
                launched = time.monotonic()
                command_deadline = min(launched + timeout, self.settlement_deadline) if self.settlement_deadline is not None else launched + timeout
                if target is not None:
                    self.attempted.add(target)
                    row['mutation_attempted'] = True
                process = subprocess.Popen(argv, cwd=self.source, stdout=out, stderr=err,
                                           env=dict(os.environ, LC_ALL='C', TZ='UTC'))
                row['pid'] = process.pid
                if target is not None:
                    self.invoked.add(target)
                    row['mutation_invoked'] = True
                wait_budget = command_deadline - time.monotonic()
                if wait_budget <= 0:
                    raise subprocess.TimeoutExpired(argv, effective)
                row['returncode'] = process.wait(timeout=wait_budget)
                completed = time.monotonic()
                row['command_finished_monotonic'] = completed
                if row['returncode']:
                    raise subprocess.CalledProcessError(row['returncode'], argv)
                require(completed <= command_deadline, 'Command completed beyond its bounded deadline')
                if target is not None:
                    require(self.settlement_deadline is None, 'The settlement deadline cannot be restarted')
                    self.settlement_deadline = completed + SETTLEMENT_SECONDS
                    self.report['settlement_clock'] = {
                        'starts_after_successful_command': label, 'command_returncode': 0,
                        'started_monotonic': completed, 'deadline_monotonic': self.settlement_deadline,
                        'budget_seconds': SETTLEMENT_SECONDS, 'reset_count': 0}
                self.remaining()
        except Exception as error:
            failure = error
            row['failure'] = {'type': type(error).__name__, 'message': str(error)}
            row['timed_out'] = isinstance(error, subprocess.TimeoutExpired)
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                    row['owned_cli_kill_requested'] = True
                    cleanup_budget = min(1, max(0, self.settlement_deadline - time.monotonic())) if self.settlement_deadline is not None else 1
                    row['reaped_returncode'] = process.wait(timeout=cleanup_budget)
                except Exception as cleanup:
                    row['owned_cli_cleanup_error'] = str(cleanup)
                row['server_side_operation_stopped_claimed'] = False
        finally:
            row['finished_unix'] = time.time()
            row['elapsed_seconds'] = time.monotonic() - started
            for channel in ('stdout', 'stderr'):
                path = self.output / row[channel + '_file']
                if path.exists():
                    try:
                        _, info = raw_file(path)
                        row[channel] = info
                    except Exception as error:
                        row.setdefault('recording_errors', []).append(str(error))
                        failure = failure or error
            try:
                self.save()
            except Exception as error:
                failure = failure or error
        if failure is not None:
            raise failure
        raw = raw_file(self.output / row['stdout_file'], 4 * 1024 * 1024)[0]
        self.remaining()
        return raw

    def bind_git(self, root, identity, entries, prefix):
        value = self.run(prefix + '-head', ['git', '-C', str(root), 'rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines()
        require(value == [identity['commit'], identity['tree']], 'Actual source/control HEAD or tree differs')
        names = sorted(entries)
        tree = self.run(prefix + '-entries', ['git', '-C', str(root), 'ls-tree', '-r', '-z', 'HEAD', '--', *names])
        index = self.run(prefix + '-index', ['git', '-C', str(root), 'ls-files', '--stage', '-z', '--', *names])
        expected_tree, expected_index = [], []
        for name in names:
            entry = entries[name]
            require(Path(name).as_posix() == name and not Path(name).is_absolute() and '..' not in Path(name).parts,
                    'Unsafe Git entry path')
            raw, info = raw_file(root / name)
            blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            require(info['bytes'] == entry['bytes'] and info['sha256'] == entry['sha256'] and blob == entry['git_blob'],
                    'Bound Git/source bytes changed: ' + name)
            require(entry['git_mode'] in ('100644', '100755') and bool(info['mode'] & 0o100) == (entry['git_mode'] == '100755'),
                    'Bound Git/source mode changed: ' + name)
            expected_tree.append((entry['git_mode'] + ' blob ' + blob + '\t' + name + '\0').encode())
            expected_index.append((entry['git_mode'] + ' ' + blob + ' 0\t' + name + '\0').encode())
        require(tree == b''.join(expected_tree) and index == b''.join(expected_index), 'Current Git tree/index entries differ')

    def bind_inputs(self):
        require(sys.platform == 'darwin' and platform.machine() == 'arm64' and __debug__
                and sys.implementation.name == 'cpython' and tuple(sys.version_info) == (3, 14, 9, 'final', 0),
                'Require actual asserted Darwin arm64 cached CPython3.14.9')
        prep = self.source / PREPARATION
        raw, prepare_info = raw_file(prep / 'prepare-result.json')
        saved = strict_json(raw)
        ctx = saved['identity']
        require(ctx['owner'] == 'integrated' and ctx['mode'] == 'candidate'
                and ctx['source_root'] == str(self.source) and ctx['source'] == {'commit': SOURCE, 'tree': TREE},
                'Only the exact original3a Integrated candidate preparation is accepted')
        control = exact_directory(ctx['control_root'])
        require(str(control) == os.environ['GITHUB_WORKSPACE'] and ctx['control']['commit'] == os.environ['GITHUB_SHA'],
                'Control checkout differs from actual caller')
        require(ctx['consumer'] == {'repository': os.environ['GITHUB_REPOSITORY'], 'run_id': os.environ['GITHUB_RUN_ID'],
                                   'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'job': 'runtime',
                                   'helper': ctx['control'], 'runner_os': 'macOS'}
                and os.environ['GITHUB_JOB'] == 'runtime', 'Preparation belongs to another actual run/attempt/job')
        require(os.environ['GITHUB_REPOSITORY'] == 'AAAHN-AAAHN/heiher-socks5-ios', 'Unexpected repository')
        require(ctx['helper_files'].get('Build/runtime_environment.py') == COMMON_SHA256
                and set(ctx['helper_files']) == {'Build/runtime_environment.py', 'Tests/AppIcon/runtime_environment.py'}
                and set(ctx['helper_files'].values()) == {COMMON_SHA256}, 'Original3a common helper bytes differ')
        require(set(ctx['original_consumer_files']) == set(ORIGINAL_CONSUMERS)
                and all(ctx['original_consumer_files'][name]['sha256'] == expected
                        and ctx['original_consumer_files'][name]['git_mode'] == '100644'
                        for name, expected in ORIGINAL_CONSUMERS.items()), 'Original consumer bindings changed')
        self.report.update(identity=ctx, control_root=str(control), original_prepare=prepare_info)
        own_path = control / SELF_PATH
        require(Path(__file__).resolve() == own_path and not own_path.is_symlink(), 'Invoke the committed control helper at its exact path')
        own, own_info = raw_file(own_path)
        own_entry = dict(own_info, relative_path=SELF_PATH, git_mode='100644',
                         git_blob=hashlib.sha1(b'blob ' + str(len(own)).encode() + b'\0' + own).hexdigest())
        source_entries = {**ctx['helper_git_entries'], **ctx['original_consumer_files'], 'Build/features.json': ctx['features_file']}
        restorer = ctx['original_restorer_binding']
        control_entries = {restorer['matrix']['relative_path']: restorer['matrix'],
                           restorer['restorer']['relative_path']: restorer['restorer'], SELF_PATH: own_entry}
        self.bind_git(self.source, ctx['source'], source_entries, 'source')
        self.bind_git(control, ctx['control'], control_entries, 'control')
        self.bound_git = [(self.source, ctx['source'], source_entries, 'final-source'),
                          (control, ctx['control'], control_entries, 'final-control')]
        self.report['probe_script'] = own_info
        common_raw, _ = raw_file(self.source / 'Build/runtime_environment.py')
        require(sha256(common_raw) == COMMON_SHA256, 'Untrusted common helper')
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('bound_original_common_preparation', self.source / 'Build/runtime_environment.py')
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        common.validate_host()
        require(restorer['restorer']['sha256'] == common.ORIGINAL_RESTORER_SHA256,
                'Original successful restorer was modified')
        prepared, bindings, preflight, service = common.load_preparation(ctx)
        require(prepared == saved, 'Original preparation changed while binding')
        self.common, self.preflight, self.service = common, preflight, service
        self.report.update(original_preparation_bindings=bindings,
                           original_preflight=prepared['staged_result'], original_service=prepared['service_result'],
                           original_consumer_files=ctx['original_consumer_files'])
        help_raw, help_info = raw_file(prep / 'staged/runtime-help.stderr.log')
        require(b'delete (<identifier>|' in help_raw and b'--keep-asset' in help_raw
                and b'Keep the associated mobile asset' in help_raw, 'Actual tool help does not advertise the required official operation')
        self.report['official_runtime_help'] = help_info
        actual_tool = self.run('simctl-path', ['xcrun', '--find', 'simctl']).decode().strip()
        require(str(Path(actual_tool).resolve()) == preflight['toolchain']['resolved_tools']['simctl'],
                'Actual simctl changed after original preparation')
        for path in ('artifacts/integrated/ui/environment.json', 'artifacts/integrated/simulator/environment.json',
                     PREPARATION + '/consumers/integrated-ui', PREPARATION + '/consumers/integrated-simulator'):
            require(not (self.source / path).exists(), 'An original consumer has already begun; this probe is preboot only')
        restore = exact_directory(str(Path(common.WATCH_ASSET) / 'Restore'))
        children = list(restore.iterdir())
        require(len(children) <= 64, 'Unexpectedly large watch Restore directory')
        dmgs = [path for path in children if path.suffix == '.dmg']
        require(len(dmgs) == 1 and not dmgs[0].is_symlink() and stat.S_ISREG(dmgs[0].lstat().st_mode),
                'Require the one direct original watch asset DMG for keep-asset identity proof')
        self.watch_dmg = dmgs[0]
        self.report['watch_asset_content_limit'] = 'Original asset directory and direct DMG stat/path identities are preserved; no independent watch DMG content hash is claimed.'

    def asset_files(self):
        common, preflight = self.common, self.preflight
        result = {name: common.bound_file_stat(preflight[name]) for name in ('source_dmg_after', 'staged_dmg_after')}
        require(all(item['matches_verified_receipt'] for item in result.values()), 'Original iOS source/staged DMG differs')
        result['ios_asset'] = common.path_snapshot(str(common.IOS_ASSET))
        result['watch_asset'] = common.path_snapshot(common.WATCH_ASSET)
        for key in ('ios_asset', 'watch_asset'):
            require(result[key].get('capture') == 'observed' and result[key].get('is_directory') is True, 'Retained asset directory unavailable')
        info = self.watch_dmg.lstat()
        require(stat.S_ISREG(info.st_mode) and not self.watch_dmg.is_symlink() and info.st_size > 0
                and self.watch_dmg.resolve() == self.watch_dmg, 'Retained watch DMG unavailable or indirect')
        result['watch_dmg'] = {'path': str(self.watch_dmg), 'identity': common.file_identity(info)}
        return result

    def snapshot(self, label):
        common = self.common
        self.remaining()
        entry = {'label': label, 'started_unix': time.time()}
        self.report['snapshots'].append(entry)
        data = common.inventory(strict_json(self.run(label + '-runtimes', ['xcrun', 'simctl', 'runtime', 'list', '-j'])))
        entry['inventory'], entry['filesystem'] = data, common.filesystem_snapshot(data)
        raw_devices = strict_json(self.run(label + '-devices', ['xcrun', 'simctl', 'list', 'devices', '-j']))
        entry['raw_devices'] = raw_devices
        entry['devices'] = common.require_shutdown_devices(raw_devices)
        mount_text = self.run(label + '-mounts', ['/sbin/mount']).decode()
        mounts = {}
        for line in mount_text.splitlines():
            match = re.fullmatch(r'(.+) on (/.*) \(([^\n]*)\)', line)
            require(match is not None, 'An actual mount-table row could not be parsed')
            mounts.setdefault(match[2], []).append({'source': match[1], 'options': match[3], 'raw_line': line})
        entry['mount_table'] = mounts
        entry['mount_paths'] = sorted(mounts)
        entry['asset_files'] = self.asset_files()
        new = self.preflight['scope_after_verify']['new_uuid']
        watches = common.watch_records(data)
        ready = [key for key, row in watches.items() if row['state'] == 'Ready']
        expected_watch = self.plan['ready_watch_uuid'] if self.plan else (ready[0] if len(ready) == 1 else None)
        entry['mounted_paths'], entry['mount_proofs'] = [], []
        require(new in data and expected_watch in data, 'Required protected runtime is absent')
        for key in (new, expected_watch):
            row = data[key]
            mount_path, bundle_path = Path(row['mountPath']), Path(row['runtimeBundlePath'])
            require(mount_path.is_absolute() and mount_path.resolve() == mount_path
                    and bundle_path.resolve() == bundle_path and bundle_path.is_relative_to(mount_path),
                    'Protected mount/bundle is indirect or outside its exact mount')
            require(len(mounts.get(str(mount_path), [])) == 1 and os.path.ismount(mount_path),
                    'Directory existence is insufficient: protected path is not an actual unique mount')
            mount_stat, bundle_stat = mount_path.stat(), bundle_path.stat()
            require(stat.S_ISDIR(mount_stat.st_mode) and stat.S_ISDIR(bundle_stat.st_mode)
                    and mount_stat.st_dev == bundle_stat.st_dev, 'Runtime bundle is not on its declared mounted filesystem')
            entry['mounted_paths'].append(str(mount_path))
            entry['mount_proofs'].append({'uuid': key, 'mount': str(mount_path), 'bundle': str(bundle_path),
                                         'mount_table': mounts[str(mount_path)][0], 'os_path_ismount': True,
                                         'mount_device': mount_stat.st_dev, 'bundle_device': bundle_stat.st_dev})
        if self.plan is None:
            old = self.preflight['selected_original_runtime']['target_uuid']
            watch_ids = sorted(key for key, row in watches.items() if unusable_duplicate(row))
            require(old in data, 'Original old iOS is absent before freezing')
            paths = fixed_paths(data, old, watch_ids)
        else:
            paths = self.plan['fixed_paths']
        entry['fixed_path_observations'] = {}
        for value in paths:
            self.remaining()
            path = Path(value)
            require(len(path.parts) <= 64, 'Old path depth is outside the bounded ledger')
            links = []
            for component in (path, *path.parents):
                try:
                    if stat.S_ISLNK(component.lstat().st_mode):
                        links.append(str(component))
                except FileNotFoundError:
                    pass
            entry['fixed_path_observations'][value] = {
                'filesystem': common.path_snapshot(value), 'resolved_path': str(path.resolve(strict=False)),
                'symlink_components': links, 'os_path_ismount': os.path.ismount(path),
                'related_mount_rows': {key: rows for key, rows in mounts.items() if Path(key).is_relative_to(path)}}
        self.remaining()
        entry['finished_unix'] = time.time()
        self.save()
        self.remaining()
        return entry

    def execute(self):
        self.bind_inputs()
        current = self.snapshot('initial')
        self.plan = freeze_plan(self.common, self.preflight, self.service, current)
        self.progress = initial_progress(self.plan)
        self.report['frozen_plan'] = self.plan
        self.save()
        before = self.snapshot('old-ios-before')
        self.progress = validate_state(self.common, self.plan, before, self.progress, old_deleted=False)
        self.report['watch_observations'] = self.progress
        target = self.plan['old_ios_uuid']
        action = {'uuid': target, 'frozen_record': self.plan['target_records'][target],
                  'started_unix': time.time(), 'disposition': 'ONE_EXACT_OLD_IOS_KEEP_ASSET_DELETE_ATTEMPT'}
        self.report['target_actions'].append(action)
        try:
            self.run('old-ios-delete', ['xcrun', 'simctl', 'runtime', 'delete', target, '--keep-asset'],
                     DELETE_TIMEOUT, target=target)
        finally:
            action['delete_attempts'] = int(target in self.attempted)
            action['delete_invocations'] = int(target in self.invoked)
        for sample in range(1, MAX_SETTLEMENT_SNAPSHOTS):
            after = self.snapshot('settlement-' + str(sample).zfill(3))
            self.progress = validate_state(self.common, self.plan, after, self.progress, old_deleted=True)
            self.report['watch_observations'] = self.progress
            if sample == 1:
                action.update(disposition='OWN_DELETE_EXIT_ZERO_AND_OLD_IOS_UUID_ABSENT',
                              absence_snapshot=after['label'], finished_unix=time.time())
                self.report['own_delete_completed_uuids'] = [target]
            self.save()
            if all(value == 'Absent' for value in self.progress['watch_states'].values()):
                break
            require(sample < MAX_SETTLEMENT_SNAPSHOTS - 1, 'Finite read-only snapshot count exhausted')
            require(self.remaining() > SAMPLE_INTERVAL, 'Insufficient budget for the next fixed read-only interval')
            time.sleep(SAMPLE_INTERVAL)
        # These original selection and source bindings share the same remaining
        # settlement budget. There is no unbounded final sweep after it expires.
        runtimes = strict_json(self.run('final-logical-runtimes', ['xcrun', 'simctl', 'list', 'runtimes', '-j']))
        types = strict_json(self.run('final-device-types', ['xcrun', 'simctl', 'list', 'devicetypes', '-j']))
        selections = {}
        for consumer in ('integrated-ui', 'integrated-simulator'):
            selection = self.common.original_selection(consumer, runtimes['runtimes'], types['devicetypes'])
            self.common.check_selection(selection, self.service['logical_selection'], consumer)
            selections[consumer] = selection
        self.report['actual_original_first_choice'] = selections
        for root, identity, entries, prefix in self.bound_git:
            self.bind_git(root, identity, entries, prefix)
        final = self.snapshot('settlement-final')
        self.progress = validate_state(self.common, self.plan, final, self.progress, old_deleted=True, final=True)
        self.remaining()
        self.report.update(result='OLD_IOS_DELETED_WATCH_ABSENCE_OBSERVED_PENDING_CALLER_EXIT',
                           watch_observations=self.progress,
                           externally_observed_watch_absent_uuids=sorted(self.plan['watch_observation_ids']),
                           watch_delete_attempts=0, watch_delete_invocations=0,
                           original_consumers_may_run_after_actual_exit_zero=True,
                           ready_watch_same_record_and_filesystem=True,
                           complete_frozen_target_set_absent=True,
                           limitation='Watch absence is an external observation, not an owned delete or a cause claim. Old aliases were already non-mounts at initial freeze; no target unmount is claimed. Point-in-time evidence does not guarantee future platform stability. Original UI/Simulator outcomes remain required; formal credit is zero.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = exact_directory(args.source_root)
    runner_temp = exact_directory(os.environ['RUNNER_TEMP'])
    output = Path(args.output)
    require(output.is_absolute() and output.parent == runner_temp and output.name == 'runtime-duplicate-retirement'
            and not output.exists() and not output.is_symlink(), 'Output must be one fresh direct child of actual RUNNER_TEMP')
    output.mkdir(mode=0o700)
    probe = Probe(source, output)
    failure = None
    try:
        probe.execute()
    except Exception as error:
        failure = error
        probe.report.update(result='DUPLICATE_RETIREMENT_FAILED_CLOSED',
                            original_consumers_may_run_after_actual_exit_zero=False,
                            failure={'type': type(error).__name__, 'message': str(error)})
        # Keep all partial raw samples, but issue no post-failure metadata
        # commands outside the single budget. The caller owns host observation.
    probe.report['finished_unix'] = time.time()
    probe.report['delete_attempted_uuids'] = sorted(probe.attempted)
    probe.report['delete_invoked_uuids'] = sorted(probe.invoked)
    try:
        probe.save()
        if failure is None:
            probe.remaining()
        print(json.dumps({'result': probe.report['result'], 'report': str(output / 'result.json'),
                          'delete_invoked_uuids': sorted(probe.invoked), 'formal_acceptance_credit': False}))
        if failure is None:
            probe.remaining()
    except Exception as error:
        failure = failure or error
        probe.report.update(result='DUPLICATE_RETIREMENT_FAILED_CLOSED',
                            original_consumers_may_run_after_actual_exit_zero=False,
                            final_recording_error={'type': type(error).__name__, 'message': str(error)})
        try:
            probe.save()
        except Exception:
            pass
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
