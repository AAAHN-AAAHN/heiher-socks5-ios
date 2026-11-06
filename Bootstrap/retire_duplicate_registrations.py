#!/usr/bin/env python3
"""One old-iOS retirement, then bounded read-only watch settlement.

This control helper never edits the source or invokes an application consumer.
Its result is not a formal/common-preparation success receipt. A caller may run
the unchanged diagnostic consumers only after this process actually exits zero.
Watch UUIDs are never mutation targets. Their absence is external observation,
not an operation owned by this process or evidence of a particular cause.
The retained V3 rule permits only the two known observation-only Watch registrations to reference
the sole Ready Watch's exact canonical mount/bundle pair. Those shared paths
remain protected even after the old UUIDs disappear. This explicitly expands
V2's input policy; it does not reinterpret any earlier failed execution.
V4 separately observes zero or one exact old tvOS registration. Its U/D/Absent
state is not a success target. The exact Ready tvOS, shared physical paths
and retained DMG identity remain protected through the last observation.
No tvOS mutation, causal claim or reclassification of failed V3 runs is made.
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
PLAN_SCHEMA = 'exact-3a-old-ios-delete-watch-ambient-tvos-observation-plan-v4'
ALIAS_ROLES_SCHEMA = 'exact-watch-and-ambient-tvos-protected-alias-roles-v4'
KNOWN_SHARED_WATCH_IDS = frozenset(('4E2A8325-62E2-427F-A198-FFEE1E5EF15A',
                                  '61FE15D4-6286-4FC9-B531-8FFEAAD0E8D8'))
SHARED_WATCH_MOUNT = '/private/var/run/com.apple.security.cryptexd/mnt/watchOS_24R362'
SHARED_WATCH_BUNDLE = SHARED_WATCH_MOUNT + '/Library/Developer/CoreSimulator/Profiles/Runtimes/watchOS 27.0.simruntime'
EXACT_UNUSABLE_DETAIL = ('Error Domain=SimDiskImageErrorDomain Code=7 "Cryptex Mount Preferred" '
                         'UserInfo={NSLocalizedDescription=Cryptex Mount Preferred, unusableErrorDetail=}')

PROGRESS_SCHEMA = 'exact-watch-and-ambient-tvos-observation-ledger-v4'
AMBIENT_POLICY_SCHEMA = 'exact-known-old-tvos-observation-policy-v4'
AMBIENT_PROGRESS_SCHEMA = 'exact-known-old-tvos-monotone-observation-ledger-v4'
MAX_AMBIENT_OBSERVERS = 1
AMBIENT_TVOS_UUID = '54D35026-7325-4069-BF3A-FDFEA26D5885'
AMBIENT_TVOS_RUNTIME = 'com.apple.CoreSimulator.SimRuntime.tvOS-27-0'
AMBIENT_TVOS_ASSET = '/System/Library/AssetsV2/com_apple_MobileAsset_appleTVOSSimulatorRuntime/f6a3a9321156c52c0d245f50953d9867b2b139ab.asset/AssetData'
AMBIENT_TVOS_MOUNT = '/private/var/run/com.apple.security.cryptexd/mnt/tvOS_24J360'
AMBIENT_TVOS_BUNDLE = AMBIENT_TVOS_MOUNT + '/Library/Developer/CoreSimulator/Profiles/Runtimes/tvOS 27.0.simruntime'
AMBIENT_TVOS_DMG = AMBIENT_TVOS_ASSET + '/Restore/043-16887-522.dmg'


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


def exact_shared_watch_record(common, key, row, *, ready):
    """A narrower complete record contract applies only to the new shared case."""
    expected = {'identifier': key, 'runtimeIdentifier': common.WATCH,
                'platformIdentifier': 'com.apple.platform.watchsimulator',
                'version': '27.0', 'build': '24R362', 'kind': 'Patchable Cryptex Disk Image',
                'state': 'Ready' if ready else 'Unusable', 'signatureState': 'Unknown',
                'deletable': True, 'sizeBytes': 3814435665, 'supportedArchitectures': ['arm64'],
                'path': common.WATCH_ASSET, 'parentMountPath': common.WATCH_ASSET,
                'mountPath': SHARED_WATCH_MOUNT, 'runtimeBundlePath': SHARED_WATCH_BUNDLE}
    if not ready:
        require(key in KNOWN_SHARED_WATCH_IDS, 'Shared alias belongs to an unknown old Watch UUID')
        expected.update(unusableErrorMessage='Cryptex Mount Preferred',
                        unusableSubstate='Cryptex Mount Preferred', unusableErrorDetail=EXACT_UNUSABLE_DETAIL)
    require(canonical(row) == canonical(expected), 'Shared Watch complete metadata differs: ' + key)


def freeze_alias_roles(common, plan, current):
    """Classify literal paths once; no disappearance can later change a role."""
    def path_values(value, location=()):
        if isinstance(value, str) and Path(value).is_absolute():
            yield location, value
        elif isinstance(value, dict):
            for key, child in sorted(value.items()):
                yield from path_values(child, (*location, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from path_values(child, (*location, index))

    data, ready = plan['baseline_inventory'], plan['ready_watch_uuid']
    pair = {'mountPath': SHARED_WATCH_MOUNT, 'runtimeBundlePath': SHARED_WATCH_BUNDLE}
    shared_ids = sorted(key for key in plan['watch_observation_ids']
                        if all(data[key].get(field) == data[ready].get(field) for field in pair))
    if shared_ids:
        exact_shared_watch_record(common, ready, data[ready], ready=True)
        for key in shared_ids:
            exact_shared_watch_record(common, key, data[key], ready=False)
    roles = {}
    for path, references in plan['fixed_paths'].items():
        alias = any(ref['field'] in pair for ref in references)
        role = {'role': 'exclusive_alias' if alias else 'retained_asset',
                'frozen_references': references}
        if shared_ids and path in pair.values():
            field = next(name for name, value in pair.items() if value == path)
            expected_refs = [{'uuid': key, 'field': field} for key in shared_ids]
            require(references == expected_refs, 'Shared path has a nonmatching frozen field or mutation target')
            closure = []
            for key, record in sorted(data.items()):
                for location, value in path_values(record):
                    if overlaps(path, value):
                        # Only the exact matching pair is admitted. Its own
                        # mount contains its own bundle; no other nesting is allowed.
                        require(key in [ready, *shared_ids] and len(location) == 1
                                and location[0] in pair and value == pair[location[0]],
                                'Shared Watch path overlaps an unrelated runtime, field or alias')
                        closure.append({'uuid': key, 'field': location[0], 'value': value})
            observation = current['fixed_path_observations'][path]
            captured = observation['filesystem']
            require(observation['resolved_path'] == path and observation['symlink_components'] == []
                    and captured.get('capture') == 'observed' and captured.get('value') == path
                    and captured.get('resolved_path') == path and captured.get('is_directory') is True
                    and captured == current['filesystem'][ready][field],
                    'Shared Watch path lacks direct protected filesystem identity')
            expected_rows = {path: current['mount_table'].get(path, [])} if field == 'mountPath' else {}
            require(observation['os_path_ismount'] is (field == 'mountPath')
                    and observation['related_mount_rows'] == expected_rows
                    and (field != 'mountPath' or len(expected_rows[path]) == 1),
                    'Shared Watch mount must be unique and its bundle must have no descendant mount')
            proofs = [row for row in current['mount_proofs'] if row['uuid'] == ready]
            require(len(proofs) == 1 and proofs[0]['mount'] == pair['mountPath']
                    and proofs[0]['bundle'] == pair['runtimeBundlePath']
                    and proofs[0]['os_path_ismount'] is True
                    and proofs[0]['mount_device'] == proofs[0]['bundle_device'] == captured['device']
                    and proofs[0]['mount_table'] == current['mount_table'][pair['mountPath']][0],
                    'Shared Watch protected mount proof differs')
            role.update(role='shared_protected', protected_reference={'uuid': ready, 'field': field},
                        reference_closure=closure, initial_observation=observation)
        roles[path] = role
    return {'schema': ALIAS_ROLES_SCHEMA, 'paths': roles}


def validate_shared_path(plan, current, progress, path, role):
    """Preserve a fixed protected object even if every old reference is absent."""
    observation = current['fixed_path_observations'][path]
    reference = role['protected_reference']
    require(path not in progress['missing_paths'], 'A shared protected path cannot enter the missing-path ledger')
    require(observation == role['initial_observation']
            and observation['filesystem'] == plan['path_baselines'][path]
            and observation['filesystem'] == current['filesystem'][reference['uuid']][reference['field']],
            'Shared protected Watch path, physical observation or mount rows changed: ' + path)
    for ref in role['frozen_references']:
        if ref['uuid'] in current['inventory']:
            require(observation['filesystem'] == current['filesystem'][ref['uuid']][ref['field']],
                    'Two reads of one shared protected path disagree')


def absolute_path_values(value, location=()):
    if isinstance(value, str) and Path(value).is_absolute():
        yield location, value
    elif isinstance(value, dict):
        for key, child in sorted(value.items()):
            yield from absolute_path_values(child, (*location, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from absolute_path_values(child, (*location, index))


def exact_ambient_tvos_record(key, row, *, ready):
    """Only the observed 27.0/24J360 pair receives the new ambient policy."""
    require(UUID.fullmatch(key) is not None, 'Malformed tvOS UUID')
    expected = {'identifier': key, 'runtimeIdentifier': AMBIENT_TVOS_RUNTIME,
                'platformIdentifier': 'com.apple.platform.appletvsimulator',
                'version': '27.0', 'build': '24J360', 'kind': 'Patchable Cryptex Disk Image',
                'state': 'Ready' if ready else 'Unusable', 'signatureState': 'Unknown',
                'deletable': True, 'sizeBytes': 3697822545, 'supportedArchitectures': ['arm64'],
                'path': AMBIENT_TVOS_ASSET, 'parentMountPath': AMBIENT_TVOS_ASSET,
                'mountPath': AMBIENT_TVOS_MOUNT, 'runtimeBundlePath': AMBIENT_TVOS_BUNDLE}
    if not ready:
        require(key == AMBIENT_TVOS_UUID, 'Unknown old tvOS cannot become ambient')
        expected.update(unusableErrorMessage='Cryptex Mount Preferred',
                        unusableSubstate='Cryptex Mount Preferred', unusableErrorDetail=EXACT_UNUSABLE_DETAIL)
    require(canonical(row) == canonical(expected), 'Ambient tvOS complete typed metadata differs: ' + key)


def ambient_tvos_identity(preflight, data):
    """Freeze zero or one known observer; it is never an absence or delete target."""
    tvos = {key: row for key, row in data.items()
            if row.get('platformIdentifier') == 'com.apple.platform.appletvsimulator'
            or str(row.get('runtimeIdentifier', '')).startswith('com.apple.CoreSimulator.SimRuntime.tvOS-')}
    require(all(row.get('state') == 'Ready' or key == AMBIENT_TVOS_UUID for key, row in tvos.items()),
            'Unknown non-Ready tvOS registration is outside the ambient policy')
    if AMBIENT_TVOS_UUID not in data or data[AMBIENT_TVOS_UUID].get('state') == 'Ready':
        return None
    exact_ambient_tvos_record(AMBIENT_TVOS_UUID, data[AMBIENT_TVOS_UUID], ready=False)
    before = preflight['runtime_snapshots']['before']['inventory']
    require(AMBIENT_TVOS_UUID in before
            and canonical(before[AMBIENT_TVOS_UUID]) == canonical(data[AMBIENT_TVOS_UUID]),
            'Ambient old tvOS was not the exact original preflight registration')
    same_runtime = [key for key, row in data.items() if row.get('runtimeIdentifier') == AMBIENT_TVOS_RUNTIME]
    ready = [key for key in same_runtime if data[key].get('state') == 'Ready']
    require(len(ready) == 1 and set(same_runtime) == {AMBIENT_TVOS_UUID, ready[0]},
            'Ambient tvOS requires its sole exact Ready counterpart')
    exact_ambient_tvos_record(ready[0], data[ready[0]], ready=True)
    return {'schema': AMBIENT_POLICY_SCHEMA, 'uuid': AMBIENT_TVOS_UUID,
            'ready_uuid': ready[0], 'dmg_path': AMBIENT_TVOS_DMG,
            'absence_required': False, 'delete_invocations_allowed': 0}


def extend_ambient_paths(paths, ambient, data):
    if ambient is None:
        return paths
    original = tuple(paths)
    for field in ('mountPath', 'runtimeBundlePath', 'path', 'parentMountPath'):
        value = data[ambient['uuid']][field]
        require(isinstance(value, str) and Path(value).is_absolute() and Path(value).as_posix() == value
                and '..' not in Path(value).parts and not any(overlaps(value, other) for other in original),
                'Ambient tvOS path overlaps an old iOS/Watch role or is indirect')
        paths.setdefault(value, []).append({'uuid': ambient['uuid'], 'field': field})
    return paths


def freeze_ambient_roles(plan, current):
    """Bind the full recursive reference closure and direct physical evidence."""
    ambient = plan['ambient_tvos']
    if ambient is None:
        require('tvos_dmg' not in current['asset_files'], 'Unexpected ambient DMG evidence')
        return
    old, ready = ambient['uuid'], ambient['ready_uuid']
    data = plan['baseline_inventory']
    pair = {'mountPath': AMBIENT_TVOS_MOUNT, 'runtimeBundlePath': AMBIENT_TVOS_BUNDLE}
    fields = dict(pair, path=AMBIENT_TVOS_ASSET, parentMountPath=AMBIENT_TVOS_ASSET)
    for path in dict.fromkeys(fields.values()):
        same_fields = [field for field, value in fields.items() if value == path]
        references = [{'uuid': old, 'field': field} for field in same_fields]
        require(plan['fixed_paths'][path] == references, 'Ambient path has mixed frozen roles')
        closure = []
        for key, record in sorted(data.items()):
            for location, value in absolute_path_values(record):
                if overlaps(path, value):
                    require(key in (old, ready) and len(location) == 1 and location[0] in fields
                            and value == fields[location[0]],
                            'Ambient tvOS path overlaps an unrelated runtime, nested field or alias')
                    closure.append({'uuid': key, 'field': location[0], 'value': value})
        observation = current['fixed_path_observations'][path]
        captured = observation['filesystem']
        require(set(observation) == {'filesystem', 'resolved_path', 'symlink_components',
                                     'os_path_ismount', 'related_mount_rows'}
                and observation['resolved_path'] == path and observation['symlink_components'] == [],
                'Ambient tvOS path lacks a direct fixed physical observation')
        require(set(captured) == {'value', 'capture', 'resolved_path', 'device', 'inode', 'mode', 'uid', 'gid',
                                  'is_directory', 'is_regular'}
                and captured['value'] == captured['resolved_path'] == path and captured['capture'] == 'observed'
                and captured['is_directory'] is True and captured['is_regular'] is False
                and all(type(captured[key]) is int and captured[key] >= 0 for key in ('device', 'inode', 'mode', 'uid', 'gid'))
                and captured['device'] > 0 and captured['inode'] > 0,
                'Ambient tvOS fixed filesystem metadata is unavailable, indirect or malformed')
        for key in (old, ready):
            for field in same_fields:
                require(canonical(captured) == canonical(current['filesystem'][key][field]),
                        'Ambient tvOS shared filesystem reads disagree')
        is_mount = path == AMBIENT_TVOS_MOUNT
        expected_rows = {path: current['mount_table'].get(path, [])} if is_mount else {}
        require(observation['os_path_ismount'] is is_mount
                and canonical(observation['related_mount_rows']) == canonical(expected_rows)
                and (not is_mount or len(expected_rows[path]) == 1),
                'Ambient tvOS mount must be unique; bundle/asset cannot contain another mount')
        plan['alias_roles']['paths'][path] = {
            'role': 'ambient_shared_protected' if path in pair.values() else 'ambient_retained_asset',
            'frozen_references': references, 'protected_uuid': ready,
            'protected_fields': same_fields, 'reference_closure': closure,
            'initial_observation': observation}
    proofs = [row for row in current['mount_proofs'] if row['uuid'] == ready]
    require(len(proofs) == 1, 'Ambient Ready tvOS lacks one actual mount proof')
    proof = proofs[0]
    fs = current['filesystem'][ready]
    require(set(proof) == {'uuid', 'mount', 'bundle', 'mount_table', 'os_path_ismount', 'mount_device', 'bundle_device'}
            and proof['mount'] == AMBIENT_TVOS_MOUNT and proof['bundle'] == AMBIENT_TVOS_BUNDLE
            and proof['os_path_ismount'] is True
            and type(proof['mount_device']) is int and type(proof['bundle_device']) is int
            and proof['mount_device'] == proof['bundle_device'] == fs['mountPath']['device'] == fs['runtimeBundlePath']['device']
            and canonical(proof['mount_table']) == canonical(current['mount_table'][AMBIENT_TVOS_MOUNT][0]),
            'Ambient Ready tvOS actual mount identity or membership differs')
    dmg = current['asset_files'].get('tvos_dmg')
    require(isinstance(dmg, dict) and set(dmg) == {'path', 'resolved_path', 'identity', 'is_regular',
                                                 'is_symlink', 'symlink_components', 'nlink'}
            and dmg['path'] == dmg['resolved_path'] == AMBIENT_TVOS_DMG
            and dmg['is_regular'] is True and dmg['is_symlink'] is False and dmg['symlink_components'] == []
            and type(dmg['nlink']) is int and dmg['nlink'] > 0,
            'Ambient tvOS requires a new direct DMG stat observation')
    identity = dmg['identity']
    require(set(identity) == {'device', 'inode', 'mode', 'uid', 'gid', 'size', 'mtime_ns', 'ctime_ns'}
            and all(type(value) is int and value >= 0 for value in identity.values())
            and identity['device'] == fs['path']['device'] and identity['inode'] > 0
            and identity['size'] == data[old]['sizeBytes'],
            'Ambient tvOS DMG stat identity or declared size differs')


def ambient_tvos_state(frozen, current):
    if current is None:
        return 'Absent'
    if canonical(current) == canonical(frozen):
        return 'Unusable'
    deleting = {key: value for key, value in frozen.items() if key not in UNUSABLE_FIELDS}
    deleting['state'] = 'Deleting'
    require(canonical(current) == canonical(deleting), 'Ambient tvOS changed beyond its exact typed Deleting transition')
    return 'Deleting'


def validate_ambient_tvos(plan, current, progress, missing_paths):
    """Continue the frozen guard after ambient absence; do not rediscover a role."""
    require(progress.get('schema') == AMBIENT_PROGRESS_SCHEMA
            and set(progress['states']) == set(plan['ambient_observation_ids']), 'Ambient observation ledger differs')
    updated = strict_json(canonical(progress))
    ambient = plan['ambient_tvos']
    if ambient is None:
        require(plan['ambient_observation_ids'] == [], 'Unexpected ambient observation identity')
        return updated
    old, ready = ambient['uuid'], ambient['ready_uuid']
    require(plan['ambient_observation_ids'] == [AMBIENT_TVOS_UUID] and old == AMBIENT_TVOS_UUID
            and old not in plan['target_ids'] and ready in plan['protected_ids'], 'Ambient role became a target or lost its Ready guard')
    data = current['inventory']
    phase = ambient_tvos_state(plan['baseline_inventory'][old], data.get(old))
    previous = progress['states'][old]
    allowed = {'Unusable': {'Unusable', 'Deleting', 'Absent'}, 'Deleting': {'Deleting', 'Absent'}, 'Absent': {'Absent'}}
    require(previous in allowed and phase in allowed[previous], 'Ambient tvOS regressed or its UUID reappeared')
    if old in data:
        require(canonical(current['filesystem'][old]) == canonical(plan['baseline_filesystem'][old]),
                'Ambient tvOS surviving filesystem changed')
    if phase == 'Deleting' and old not in updated['deleting_observed']:
        updated['deleting_observed'].append(old)
    if phase != previous:
        updated['transitions'].append({'uuid': old, 'from': previous, 'to': phase, 'snapshot': current['label'],
                                       'observed_unix': current['finished_unix'], 'tvos_delete_invoked': False})
    updated['states'][old] = phase
    if phase == 'Absent' and old not in updated['absence_dispositions']:
        updated['absence_dispositions'][old] = (
            'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AFTER_OBSERVED_DELETING' if old in updated['deleting_observed'] else
            'OBSERVED_ABSENT_WITHOUT_DELETE_INVOCATION_AND_WITHOUT_OBSERVED_DELETING')
    for path in (AMBIENT_TVOS_MOUNT, AMBIENT_TVOS_BUNDLE, AMBIENT_TVOS_ASSET):
        role = plan['alias_roles']['paths'][path]
        expected_role = 'ambient_retained_asset' if path == AMBIENT_TVOS_ASSET else 'ambient_shared_protected'
        require(role['role'] == expected_role and role['protected_uuid'] == ready,
                'Frozen ambient physical role differs')
        observation = current['fixed_path_observations'][path]
        require(path not in missing_paths
                and canonical(observation) == canonical(role['initial_observation'])
                and canonical(observation['filesystem']) == canonical(plan['path_baselines'][path]),
                'Ambient protected fixed path or physical identity changed: ' + path)
        for field in role['protected_fields']:
            require(canonical(observation['filesystem']) == canonical(current['filesystem'][ready][field]),
                    'Ambient protected Ready filesystem reads disagree')
        for ref in role['frozen_references']:
            if ref['uuid'] in data:
                require(canonical(observation['filesystem']) == canonical(current['filesystem'][ref['uuid']][ref['field']]),
                        'Ambient fixed path and surviving old registration disagree')
    return updated


def replay_plan(common, preflight, service, initial, saved_plan):
    """Recompute a saved V4 plan from bound original inputs; grant no run credit."""
    require(saved_plan.get('schema') == PLAN_SCHEMA, 'Saved retirement plan is not explicit V4')
    replayed = freeze_plan(common, preflight, service, initial)
    require(canonical(saved_plan) == canonical(replayed), 'Saved V4 plan or alias-role ledger differs from replay')
    return replayed


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
    ambient = ambient_tvos_identity(preflight, inventory)
    ambient_ids = [ambient['uuid']] if ambient else []
    require(len(ambient_ids) <= MAX_AMBIENT_OBSERVERS and not set(ambient_ids) & set(targets),
            'Ambient identity cannot enlarge the frozen target set')
    plan = {'schema': PLAN_SCHEMA, 'old_ios_uuid': old, 'new_ios_uuid': new, 'ready_watch_uuid': ready[0],
            'target_ids': targets, 'target_records': {key: inventory[key] for key in targets},
            'mutation_target_ids': [old], 'watch_observation_ids': retired_watches,
            'ambient_observation_ids': ambient_ids, 'ambient_tvos': ambient,
            'baseline_inventory': inventory, 'baseline_filesystem': filesystem,
            'protected_ids': sorted(set(inventory) - set(targets) - set(ambient_ids)),
            'devices': current['devices'], 'asset_files': current['asset_files'],
            'protected_mount_paths': [inventory[new]['mountPath'], inventory[ready[0]]['mountPath']],
            'target_order': 'One old-iOS delete, then only scheduled read-only watch observations; no causal claim.'}
    if ambient:
        plan['protected_mount_paths'].append(inventory[ambient['ready_uuid']]['mountPath'])
    plan['fixed_paths'] = extend_ambient_paths(fixed_paths(plan['target_records'], old, retired_watches),
                                               ambient, inventory)
    require(set(current['fixed_path_observations']) == set(plan['fixed_paths']), 'Initial literal path ledger differs')
    plan['alias_roles'] = freeze_alias_roles(common, plan, current)
    freeze_ambient_roles(plan, current)
    plan['path_baselines'] = {}
    protected_aliases = [inventory[key][field] for key in plan['protected_ids']
                         for field in ('mountPath', 'runtimeBundlePath')]
    for path, references in plan['fixed_paths'].items():
        baseline = current['fixed_path_observations'][path]['filesystem']
        require(all(baseline == filesystem[ref['uuid']][ref['field']] for ref in references),
                'Shared literal-path observations disagree with the original preparation')
        plan['path_baselines'][path] = baseline
        if plan['alias_roles']['paths'][path]['role'] in ('shared_protected', 'ambient_shared_protected', 'ambient_retained_asset'):
            continue
        if any(ref['field'] in ('mountPath', 'runtimeBundlePath') for ref in references):
            require(not any(overlaps(path, protected) for protected in protected_aliases),
                    'A target alias overlaps a protected runtime mount or bundle')
            require((baseline.get('capture') == 'observed' and baseline.get('is_directory') is True)
                    or enoent_path(baseline, path), 'Unsupported initial old runtime alias filesystem')
    expected_proof_ids = [new, ready[0], *([ambient['ready_uuid']] if ambient else [])]
    require([row['uuid'] for row in current['mount_proofs']] == expected_proof_ids,
            'Protected actual mount proof identities or order differ')
    plan['protected_mount_proofs'] = current['mount_proofs']
    plan['protected_mount_rows'] = runtime_mount_rows(inventory, current['mount_table'], plan['protected_ids'])
    plan['initial_alias_limit'] = ('Exclusive aliases retain the V2 non-mount rule. Only the two known observation-only Watch UUIDs '
                                 'may share the sole exact Ready Watch canonical pair; those paths remain protected and never removable. '
                                 'The separate exact known old tvOS observer is not a target; its Ready counterpart, shared physical '
                                 'paths and direct retained DMG stat stay protected even if its UUID is absent.')
    progress = initial_progress(plan)
    validate_state(common, plan, current, progress, old_deleted=False)
    return plan


def initial_progress(plan):
    return {'schema': PROGRESS_SCHEMA,
            'ambient_tvos': {'schema': AMBIENT_PROGRESS_SCHEMA,
                             'states': {key: 'Unusable' for key in plan['ambient_observation_ids']},
                             'deleting_observed': [], 'absence_dispositions': {}, 'transitions': []},
            'watch_states': {key: 'Unusable' for key in plan['watch_observation_ids']},
            'deleting_observed': [], 'absence_dispositions': {}, 'transitions': [],
            'missing_paths': sorted(path for path, row in plan['path_baselines'].items() if enoent_path(row, path))}


def validate_state(common, plan, current, progress, *, old_deleted, final=False):
    """Read-only validation; progress is committed only after every guard passes."""
    require(plan.get('schema') == PLAN_SCHEMA and plan['alias_roles']['schema'] == ALIAS_ROLES_SCHEMA
            and set(plan['alias_roles']['paths']) == set(plan['fixed_paths'])
            and progress.get('schema') == PROGRESS_SCHEMA, 'V4 alias-role plan or observation ledger is incomplete')
    data, baseline = current['inventory'], plan['baseline_inventory']
    require(set(data) <= set(baseline), 'New runtime registration appeared; never select a substitute')
    require(set(baseline) - set(data) <= set(plan['target_ids']) | set(plan['ambient_observation_ids']), 'A protected runtime disappeared')
    require(set(current['filesystem']) == set(data), 'Runtime filesystem inventory differs')
    require(common.require_shutdown_devices(current['raw_devices']) == current['devices'], 'Raw device normalization differs')
    require(current['devices'] == plan['devices'], 'Device identities or Shutdown states changed')
    require(canonical(current['asset_files']) == canonical(plan['asset_files']), 'A retained asset/DMG identity changed')
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
    updated['ambient_tvos'] = validate_ambient_tvos(plan, current, progress['ambient_tvos'], progress['missing_paths'])
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
        role = plan['alias_roles']['paths'][path]
        require(role['frozen_references'] == references
                and role['role'] in ('exclusive_alias', 'retained_asset', 'shared_protected',
                                     'ambient_shared_protected', 'ambient_retained_asset'), 'Frozen alias role differs')
        if role['role'] in ('ambient_shared_protected', 'ambient_retained_asset'):
            continue
        if role['role'] == 'shared_protected':
            validate_shared_path(plan, current, progress, path, role)
            continue
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
    require(canonical(current['mount_proofs']) == canonical(plan['protected_mount_proofs']), 'Protected actual mount identity, source or options changed')
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
        self.ambient_tvos = None
        self.report = {'schema': 'exact-3a-old-ios-delete-watch-shared-alias-ambient-tvos-observation-diagnostic-v4',
                       'started_unix': time.time(), 'source_commit': SOURCE, 'source_tree': TREE,
                       'formal_acceptance_credit': False, 'common_preparation_success_claimed': False,
                       'source_or_ref_modified': False, 'application_consumer_invocations': 0,
                       'candidate_runtime_success_claimed': False, 'caller_actual_exit_required': True,
                       'original_consumers_may_run_after_actual_exit_zero': False,
                       'limits': {'metadata_seconds': META_TIMEOUT, 'delete_seconds': DELETE_TIMEOUT,
                                  'max_frozen_targets': MAX_TARGETS, 'total_mutation_attempts': 1,
                                  'max_ambient_observers': MAX_AMBIENT_OBSERVERS,
                                  'tvos_delete_invocations': 0, 'ambient_absence_required': False,
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
        if self.ambient_tvos is not None:
            self.remaining()
            path = Path(AMBIENT_TVOS_DMG)
            links = [str(item) for item in (path, *path.parents) if item.is_symlink()]
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and not links and path.resolve() == path
                    and file_identity(info) == file_identity(path.stat()),
                    'Retained ambient tvOS DMG is unavailable or indirect')
            result['tvos_dmg'] = {'path': str(path), 'resolved_path': str(path.resolve()),
                                  'identity': common.file_identity(info), 'is_regular': True,
                                  'is_symlink': False, 'symlink_components': links, 'nlink': info.st_nlink}
            self.remaining()
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
        self.ambient_tvos = self.plan['ambient_tvos'] if self.plan else ambient_tvos_identity(self.preflight, data)
        entry['asset_files'] = self.asset_files()
        new = self.preflight['scope_after_verify']['new_uuid']
        watches = common.watch_records(data)
        ready = [key for key, row in watches.items() if row['state'] == 'Ready']
        expected_watch = self.plan['ready_watch_uuid'] if self.plan else (ready[0] if len(ready) == 1 else None)
        entry['mounted_paths'], entry['mount_proofs'] = [], []
        require(new in data and expected_watch in data, 'Required protected runtime is absent')
        expected_tvos = [self.ambient_tvos['ready_uuid']] if self.ambient_tvos else []
        for key in (new, expected_watch, *expected_tvos):
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
            paths = extend_ambient_paths(fixed_paths(data, old, watch_ids), self.ambient_tvos, data)
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
                           tvos_delete_attempts=0, tvos_delete_invocations=0,
                           ambient_tvos_final_states=self.progress['ambient_tvos']['states'],
                           ambient_absence_required=False,
                           original_consumers_may_run_after_actual_exit_zero=True,
                           ready_watch_same_record_and_filesystem=True,
                           complete_frozen_target_set_absent=True,
                           limitation='Watch absence is an external observation, not an owned delete or a cause claim. Exclusive aliases were already non-mounts; exact shared Watch aliases remain protected and cannot become missing. No deletion safety, automatic Watch disappearance, atomic observation or future platform stability is guaranteed. The separately observed old tvOS may finish Unusable, Deleting or Absent; none is a new absence target. Its exact Ready counterpart, fixed shared paths and DMG stat remain protected through the final observation, even after old tvOS absence. No tvOS content hash, deletion safety, causal attribution or continuous stability is claimed. Original UI/Simulator outcomes remain required; formal credit is zero.')


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
    if probe.progress is not None:
        probe.report['ambient_tvos_last_accepted_states'] = probe.progress['ambient_tvos']['states']
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
