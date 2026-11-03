#!/usr/bin/env python3
"""Run the exact current0bcc ui_review.main once with a temporary AppRoot log overlay.

The original four tests, 136 assertion calls, selection order and command
deadlines are not changed. This is diagnostic evidence only, never a candidate
runtime/final gate, selected product, full16, D28, I/C, or project completion.
"""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import subprocess
import sys
import time


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': sha(raw)}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def validate_preflight(preflight, pins, actual):
    require(preflight.get('result') == 'STAGED_RUNTIME_VERIFIED_AND_SELECTED'
            and preflight.get('original_lifecycle_may_run') is True,
            'The current staged preflight did not establish readiness')
    require(preflight.get('helper_sha') == actual['helper']['commit']
            and str(preflight.get('run_id')) == str(actual['run_id'])
            and str(preflight.get('attempt')) == str(actual['run_attempt']),
            'Staged preflight belongs to another actual diagnostic identity')
    require(preflight.get('preflight_sha256') == pins['staged_preflight_sha256'],
            'Staged preflight is not the reviewed exact v3 implementation')
    require(preflight.get('add_invocations') == 1 and preflight.get('verify_invocations') == 1
            and preflight.get('product_pass') is False and preflight.get('candidate_credit') is False,
            'Preflight scope, invocation count or credit differs')
    require(preflight.get('source_dmg_unchanged') is True
            and preflight.get('staged_dmg_unchanged_after_capture') is True,
            'Source/staged DMG preservation was not established')
    row = preflight['scope_after_verify']['new_record']
    require(row.get('runtimeIdentifier') == pins['required_runtime']['identifier']
            and row.get('version') == '27.0' and row.get('build') == '24A434'
            and row.get('state') == 'Ready' and row.get('signatureState') == 'Verified',
            'Verified staged runtime is not exact27.0/24A434 Ready')
    logical = preflight['logical_selection']
    require(logical['expected_later_lifecycle_bundle_path'] == row['runtimeBundlePath'],
            'Preflight expected bundle differs from the verified new image')
    require(all(logical['device_type'].get(k) == v for k, v in pins['required_device'].items()),
            'Preflight selected a different device type')
    return row['runtimeBundlePath']


def load_service_receipt_reader(control, pins):
    """Import only the exact frozen helper's pure receipt readers, never main."""
    expected = pins['service_refresh']['source_sha256']
    require(len(expected) == 6 and 'Bootstrap/ios_runtime_service_refresh.py' in expected,
            'The exact service helper and five unchanged dependencies must be pinned')
    for name, digest in expected.items():
        require(sha((control / name).read_bytes()) == digest, 'Service binding source changed: ' + name)
    dependencies = {Path(name).stem: control / name for name in expected
                    if name != 'Bootstrap/ios_runtime_service_refresh.py'}
    for name, path in dependencies.items():
        if name in sys.modules:
            require(Path(sys.modules[name].__file__).resolve() == path.resolve(),
                    'A service receipt dependency was imported from another directory')
    previous_path = list(sys.path)
    try:
        sys.path.insert(0, str(control / 'Bootstrap'))
        reader = load_module('one_ui_exact_service_receipt_reader', control / 'Bootstrap/ios_runtime_service_refresh.py')
    finally:
        sys.path[:] = previous_path
    require(reader.SOURCE_FILES == {Path(name).name: digest for name, digest in expected.items()
                                    if name != 'Bootstrap/ios_runtime_service_refresh.py'},
            'The unchanged helper dependency declaration differs from the explicit binding pins')
    for name, path in dependencies.items():
        require(Path(sys.modules[name].__file__).resolve() == path.resolve(),
                'The service receipt reader imported a dependency outside the exact control checkout')
    return reader


def bound_command_evidence(directory, commands):
    """Read each original stdout/stderr completely against its producer receipt."""
    ledger, raw = [], {}
    for row in commands:
        label = row['label']
        require(label not in raw and isinstance(label, str), 'Duplicate or invalid evidence command label')
        raw[label] = {}
        for channel in ('stdout', 'stderr'):
            name = row[channel + '_file']
            require(name == label + '.' + channel + '.log' and Path(name).name == name,
                    'A command evidence path differs from its exact direct filename')
            path = directory / name
            require(path.is_file() and not path.is_symlink(), 'Command evidence must remain a direct regular file')
            content = path.read_bytes()
            observed = {'file': name, 'bytes': len(content), 'sha256': sha(content)}
            require(observed['bytes'] == row[channel + '_file_bytes']
                    and observed['sha256'] == row[channel + '_file_sha256'],
                    'Raw command evidence changed: ' + name)
            ledger.append(observed)
            raw[label][channel] = content
    return ledger, raw


def bound_record_matches(descriptor, path):
    observed = record(path)
    return (Path(descriptor['path']).resolve(strict=True) == path.resolve(strict=True)
            and all(descriptor[key] == observed[key] for key in ('bytes', 'sha256')))


def validate_service_binding(service_path, exit_path, preflight_path, preflight, pins, actual, control, step_outcome):
    """Bind actual helper exit, raw receipts and the post-refresh runtime as data.

    No service main, native identity call, signal, simctl query or lifecycle runs
    here. The exact helper's pure validators are reused without changing it.
    """
    reader = load_service_receipt_reader(control, pins)
    expected_sources = pins['service_refresh']['source_sha256']
    context = {'helper_sha': actual['helper']['commit'], 'checked_out_sha': actual['helper']['commit'],
               'run_id': str(actual['run_id']), 'attempt': str(actual['run_attempt'])}
    old_uuid, new_uuid = reader.validate_preflight(preflight, context)
    require(service_path.name == 'refresh-result.json' and exit_path.name == 'workflow-exit-zero.json'
            and service_path.parent.resolve() == exit_path.parent.resolve(),
            'Service and post-exit receipts must share the exact owned evidence directory')
    service_raw = service_path.read_bytes()
    service = json.loads(service_raw)
    handoff = json.loads(exit_path.read_bytes())
    expected_exit_context = {'helper_sha': context['helper_sha'], 'run_id': context['run_id'],
                             'attempt': context['attempt'], 'repository': actual['repository'], 'job': actual['job']}
    require(step_outcome == 'success' and handoff.get('schema') == 1
            and handoff.get('scope') == 'actual_workflow_post_service_process_exit'
            and handoff.get('workflow_step_id') == 'audio_service_once'
            and type(handoff.get('service_process_exit_code')) is int and handoff['service_process_exit_code'] == 0
            and handoff.get('context') == expected_exit_context,
            'Actual service process exit zero and this GitHub step success are both required')
    require(handoff.get('source_sha256') == expected_sources
            and bound_record_matches(handoff['refresh_result'], service_path)
            and bound_record_matches(handoff['preflight_result'], preflight_path)
            and bound_record_matches(handoff['workflow'], control / '.github/workflows/udp-echo-ui-diagnostic.yml'),
            'Post-exit receipt does not bind the exact source/workflow/preflight/service bytes')
    require(service.get('result') == 'OWN_SERVICE_REFRESHED_AND_SAME_RUNTIME_SELECTED'
            and service.get('original_lifecycle_may_run') is True
            and service.get('success_requires_helper_process_exit_zero') is True
            and service.get('product_pass') is False and service.get('candidate_credit') is False
            and not service.get('failure') and not service.get('recording_errors')
            and all(service.get(key) == value for key, value in context.items()),
            'Service preparation did not succeed for this exact actual run/head/attempt')
    require(service.get('helper_source_sha256') == expected_sources['Bootstrap/ios_runtime_service_refresh.py']
            and service.get('source_files') == reader.SOURCE_FILES
            and service.get('original_limits_seconds') == reader.LIMITS
            and service.get('metadata_timeout_seconds') == reader.METADATA_TIMEOUT == 10
            and service.get('service_exit_wait_seconds') == reader.EXIT_TIMEOUT == 10,
            'Service helper, five unchanged sources or original deadline declarations differ')
    require(bound_record_matches(service['preflight_binding'], preflight_path)
            and (service_path.parent / 'bound-preflight-result.json').read_bytes() == preflight_path.read_bytes()
            and service['preflight_binding']['old_uuid'] == old_uuid
            and service['preflight_binding']['new_uuid'] == new_uuid,
            'Service preflight binding does not match the wrapper original raw file and UUIDs')
    preflight_ledger, preflight_raw = bound_command_evidence(preflight_path.parent, preflight['commands'])
    require(preflight_ledger == service['bound_preflight_command_files']
            and preflight_raw['source-head']['stdout'].decode().strip() == context['helper_sha']
            and preflight_raw['verify-new-staged-ios']['stdout'] == b'Signature verified, signature is valid.\n'
            and preflight_raw['verify-new-staged-ios']['stderr'] == b'',
            'The unchanged preflight raw command/verification evidence differs')
    commands = service['commands']
    require([row['label'] for row in commands] == list(reader.READ_COMMANDS),
            'Service command order/count differs from the single successful helper path')
    for row in commands:
        require(row['argv'] == reader.READ_COMMANDS[row['label']] and row.get('returncode') == 0
                and row.get('requested_timeout_seconds') == reader.METADATA_TIMEOUT
                and row.get('timeout') is not True and not row.get('error')
                and not row.get('recording_errors') and not row.get('cleanup_error'),
                'Service metadata command did not complete unchanged and successfully')
    service_ledger, raw = bound_command_evidence(service_path.parent, commands)
    require(raw['source-head']['stdout'].decode().strip() == context['helper_sha']
            and service.get('owned_metadata_child_cleanup_signals') == [],
            'Successful service evidence contains another source or a failed metadata-child cleanup path')
    uid = service.get('own_uid')
    require(type(uid) is int and uid > 0 and uid == service.get('own_euid') == os.getuid() == os.geteuid(),
            'Service signal owner differs from this actual non-root runner identity')
    natives = {}
    for label in ('service-before', 'service-before-signal', 'service-after-exit', 'service-final'):
        snapshot = service['service_snapshots'][label]
        rows = reader.service_rows(raw[label]['stdout'].decode())
        require(snapshot['candidate_rows'] == rows, 'Raw ps rows differ from the recorded service snapshot')
        selected = reader.select_owned_service(rows, uid, allow_absent=label == 'service-after-exit')
        if selected is None:
            require(snapshot.get('own_service_observed') is False, 'Absent replacement snapshot contradicts raw ps')
            natives[label] = None
        else:
            require(snapshot.get('own_service_observed') is True and snapshot['ps_identity'] == selected,
                    'Service selection differs from the unchanged own-UID reader')
            native = snapshot['native_identity']
            reader.validate_native(selected, native, uid)
            require(snapshot['executable_filesystem'].get('capture') == 'observed'
                    and snapshot['executable_filesystem'].get('is_regular') is True,
                    'Exact service executable filesystem evidence is unavailable')
            natives[label] = native
    observed = service['service_refresh']
    before, replacement = natives['service-before'], natives['service-final']
    require(observed.get('target_executable') == reader.SERVICE_PATH
            and observed.get('sigterm_attempts') == observed.get('sigterm_invocations') == 1
            and observed.get('signal_returned_successfully') is True
            and observed.get('old_service_exit_observed') is True
            and observed.get('force_fallbacks') == observed.get('other_infrastructure_service_signals') == 0
            and not observed.get('failure') and not observed.get('recording_errors')
            and before == natives['service-before-signal'] == observed['target_native_identity']
            == observed['final_native_identity'] == observed['immediate_native_identity'],
            'The one exact own-UID service signal or its immediate native identity differs')
    registration = observed['registration']
    change = registration['change']
    kq = reader.select
    require(registration.get('returned_without_error') is True and registration.get('events') == []
            and change['ident'] == before['pid'] and change['filter'] == kq.KQ_FILTER_PROC
            and change['flags'] == kq.KQ_EV_ADD | kq.KQ_EV_ENABLE | kq.KQ_EV_ONESHOT
            and change['fflags'] == kq.KQ_NOTE_EXIT | kq.KQ_NOTE_EXEC
            and observed.get('events_before_signal') == [],
            'Service EXIT/EXEC watcher registration or the pre-signal boundary differs')
    events = observed['events_after_signal']
    require(len(events) == 1 and events[0]['ident'] == before['pid']
            and events[0]['filter'] == kq.KQ_FILTER_PROC and not events[0]['flags'] & kq.KQ_EV_ERROR
            and events[0]['fflags'] & kq.KQ_NOTE_EXIT and not events[0]['fflags'] & kq.KQ_NOTE_EXEC,
            'Raw kernel event did not establish the original target NOTE_EXIT')
    require(replacement == observed['replacement_native_identity'] and replacement['pid'] != before['pid']
            and (replacement['start_seconds'], replacement['start_microseconds'])
            > (before['start_seconds'], before['start_microseconds'])
            and observed['replacement_observed_before_reinit'] == (natives['service-after-exit'] is not None)
            and (natives['service-after-exit'] is None or natives['service-after-exit'] == replacement)
            and service['service_snapshots']['service-before']['executable_filesystem']
            == service['service_snapshots']['service-final']['executable_filesystem'],
            'The final service is not one distinct newer native identity with the unchanged executable')
    for phase in ('before', 'after'):
        snapshot = service['runtime_snapshots'][phase]
        inventory = reader.decode(raw['runtime-images-' + phase]['stdout'].decode())
        require(inventory == snapshot['inventory']
                and reader.validate_runtime(preflight, inventory, snapshot['filesystem']) == snapshot['scope_validation'],
                'Actual service runtime inventory/filesystem differs from the original preflight constraints')
        for key in ('source_dmg_after', 'staged_dmg_after'):
            recorded = service['dmg_stats'][phase][key]
            require(recorded.get('capture') == 'observed' and recorded.get('matches_verified_receipt') is True
                    and recorded.get('is_regular') is True and recorded.get('is_symlink') is False
                    and recorded.get('additional_content_hash_performed') is False
                    and recorded.get('bound_preflight_sha256') == preflight[key]['sha256']
                    and all(recorded[field] == preflight[key][field] for field in ('path', 'resolved_path', 'identity')),
                    'Immediate DMG stat/path binding differs from its same-run verified content receipt')
    new_image = service['runtime_snapshots']['after']['inventory'][new_uuid]
    logical = reader.staged.require_logical_selection(reader.decode(raw['logical-runtimes-after']['stdout'].decode()),
                reader.decode(raw['device-types-after']['stdout'].decode()), new_image, preflight['sdk'])
    require(logical == service['logical_selection']
            and logical['expected_later_lifecycle_bundle_path'] == preflight['logical_selection']['expected_later_lifecycle_bundle_path']
            and new_image == preflight['runtime_snapshots']['after-verify']['inventory'][new_uuid],
            'The complete post-refresh selected runtime/device or same verified UUID/bundle changed')
    devices_before = reader.require_shutdown_devices(reader.decode(raw['devices-before']['stdout'].decode()))
    devices_after = reader.require_shutdown_devices(reader.decode(raw['devices-after']['stdout'].decode()))
    previous_devices = reader.require_shutdown_devices(reader.decode(preflight_raw['devices-after']['stdout'].decode()))
    require(devices_before == service['devices_before'] and devices_after == service['devices_after']
            and previous_devices == service['preflight_devices_after']
            and devices_before['device_identities'] == devices_after['device_identities'] == previous_devices['device_identities'],
            'All actual device identities/states must remain unchanged and Shutdown during the service probe')
    return {'service_receipt': record(service_path), 'post_exit_receipt': record(exit_path),
            'preflight_receipt': record(preflight_path), 'actual_step_outcome': step_outcome,
            'service_process_exit_code': handoff['service_process_exit_code'], 'actual_context': expected_exit_context,
            'source_sha256': expected_sources, 'preflight_command_files': preflight_ledger,
            'service_command_files': service_ledger, 'physical_runtime_uuid': new_uuid,
            'physical_runtime': new_image, 'logical_runtime': logical['logical_runtime'],
            'device_type': logical['device_type'], 'expected_bundle_path': logical['expected_later_lifecycle_bundle_path'],
            'old_service_native_identity': before, 'replacement_service_native_identity': replacement,
            'service_main_invoked_by_validator': False, 'external_platform_commands_or_signals_by_validator': 0,
            'candidate_credit': False, 'actual_UI_execution_still_required': True}


def cross_check_service_selection(runtime, device, binding):
    require(runtime == binding['logical_runtime'] and device == binding['device_type']
            and runtime['bundlePath'] == binding['expected_bundle_path']
            == binding['physical_runtime']['runtimeBundlePath'],
            'Original first-match UI selection differs from the complete post-refresh runtime/device/bundle')


def selected_original_runtime(runtimes, types, pins, preflight, service_binding):
    # These are the original selection predicates, evaluated for observation.
    # Their results are checked, never reordered, replaced or written into ui.
    runtime = next(r for r in runtimes if r.get('isAvailable')
                   and r['identifier'].startswith('com.apple.CoreSimulator.SimRuntime.iOS-27'))
    device = next(d for d in types if d['name'] == 'iPhone 16')
    require(all(runtime.get(k) == v for k, v in pins['required_runtime'].items()),
            'Original runtime selection is not staged27.0/24A434')
    require(all(device.get(k) == v for k, v in pins['required_device'].items()),
            'Original device selection is not iPhone16')
    expected = preflight['logical_selection']['expected_later_lifecycle_bundle_path']
    require(isinstance(runtime.get('bundlePath'), str) and runtime['bundlePath'] == expected,
            'Original selected runtime bundle is not the exact staged verified bundle')
    cross_check_service_selection(runtime, device, service_binding)
    require(Path(expected).is_absolute() and Path(expected).is_dir()
            and Path(runtime['bundlePath']).resolve(strict=True) == Path(expected).resolve(strict=True),
            'Selected staged bundle path is unavailable or indirect')
    return {'runtime': runtime, 'device': device,
            'expected_staged_bundle_path': expected, 'original_selection_unmodified': True,
            'service_refresh_runtime_uuid': service_binding['physical_runtime_uuid'],
            'service_refresh_receipt': service_binding['service_receipt']}


class Observation:
    def __init__(self, ui, pins, preflight, out, source_input, service_binding):
        self.ui, self.pins, self.preflight, self.out = ui, pins, preflight, out
        self.source_input = source_input
        self.service_binding = service_binding
        self.original_run, self.original_output = ui.run, ui.output
        self.runtimes = self.types = self.selection = self.device = None
        self.collector = self.trace_stream = None
        self.collector_stopped = False
        self.first_observation_error = None
        self.report = {'main_invocations': 0, 'build_invocations': 0, 'test_invocations': 0,
                       'create_invocations': 0, 'boot_invocations': 0,
                       'overlay_applications': 0, 'collector_start_invocations': 0,
                       'collector_stop_invocations': 0, 'observation_errors': [],
                       'original_command_failures': [], 'command_forwarding': [],
                       'candidate_credit': False}

    def observation_error(self, stage, error):
        if self.first_observation_error is None:
            self.first_observation_error = error
        self.report['observation_errors'].append({'stage': stage, 'type': type(error).__name__, 'message': str(error)})

    def note(self, kind, **fields):
        row = {'kind': kind, 'unix_seconds': time.time(), 'monotonic_seconds': time.monotonic(), **fields}
        try:
            with (self.out / 'observation-events.jsonl').open('a') as stream:
                stream.write(json.dumps(row) + '\n')
        except Exception as error:
            self.observation_error('event-recording', error)

    def verify_environment(self):
        require(self.selection is not None and self.device is not None, 'No original selection/device to bind')
        path = self.ui.OUT / 'environment.json'
        actual = json.loads(path.read_bytes())
        require(actual == {'runtime': self.selection['runtime'], 'device': self.selection['device'], 'udid': self.device},
                'Actual original environment differs from the pre-create selected runtime/device')
        require(actual['runtime']['bundlePath'] == self.selection['expected_staged_bundle_path'],
                'Actual environment is not bound to the staged verified bundle')
        cross_check_service_selection(actual['runtime'], actual['device'], self.service_binding)
        self.report['service_refresh_runtime_uuid'] = self.service_binding['physical_runtime_uuid']
        self.report['actual_original_environment'] = actual
        self.report['actual_original_environment_file'] = record(path)
        save(self.out / 'actual-environment-binding-before-boot.json',
             {'environment': actual, 'staged_bundle': self.selection['expected_staged_bundle_path'],
              'no_selection_value_modified': True})

    def apply_overlay(self):
        require(self.report['overlay_applications'] == 0, 'AppRoot overlay may be applied only once')
        app = self.ui.WORK / 'application'
        source = app / 'Socks5/AppRoot.swift'
        info = source.lstat()
        require(stat.S_ISREG(info.st_mode) and not source.is_symlink(), 'Temporary AppRoot must be a regular file')
        original = source.read_bytes()
        require(sha(original) == self.pins['minimal_observation']['original_AppRoot_sha256'],
                'Temporary AppRoot differs from actual0bcc before observation overlay')
        generated = app / 'StatisticsUITests.swift'
        generated_raw = generated.read_bytes()
        expected = self.pins['original_ui_generated_source']
        require(len(generated_raw) == expected['bytes'] and sha(generated_raw) == expected['sha256'],
                'Original generated four-test source changed')
        counts = {'XCTAssert_calls': len(re.findall(rb'\bXCTAssert\w*\s*\(', generated_raw)),
                  'XCTFail_calls': len(re.findall(rb'\bXCTFail\s*\(', generated_raw))}
        require(all(counts[k] == expected[k] for k in counts) and sum(counts.values()) == 136,
                'Original136 assertion calls differ')
        for name, digest in self.pins['ui_source_sha256'].items():
            require(sha((self.ui.ROOT / name).read_bytes()) == digest, 'Canonical original UI source changed: ' + name)
            if name.startswith('Tests/'):
                require((app / name).read_bytes() == (self.ui.ROOT / name).read_bytes(),
                        'A temporary original XCTest file changed: ' + name)
        patcher_path = self.source_input / 'Bootstrap/audio-diagnostic/instrument_audio_intent.py'
        expected_patcher = self.pins['source_input_files']['Bootstrap/audio-diagnostic/instrument_audio_intent.py']
        require(sha(patcher_path.read_bytes()) == expected_patcher['sha256'], 'Existing root observation template changed')
        patcher = load_module('current_original_root_observation_template', patcher_path)
        plan = patcher.root_plan(original.decode())
        plan.prove_original_preserved()
        retained = self.pins['minimal_observation']['retained_labels']
        require(len(retained) == 8 and len(set(retained)) == 8, 'Expected the reviewed eight observation blocks')
        proposed = plan.text
        for block in reversed(plan.operations):
            if block['label'] not in retained:
                require(proposed.count(block['inserted_block']) == block['occurrences'], 'Observation template count changed')
                proposed = proposed.replace(block['inserted_block'], '')
        kept = [block for block in plan.operations if block['label'] in retained]
        require([block['label'] for block in kept] == retained, 'Retained observation block order changed')
        stripped = proposed
        for block in reversed(kept):
            require(block['occurrences'] == 1
                    and sha(block['inserted_block'].encode()) == self.pins['minimal_observation']['retained_block_sha256'][block['label']],
                    'Retained existing observation bytes changed')
            require(stripped.count(block['inserted_block']) == 1, 'Repeated or missing observation block')
            stripped = stripped.replace(block['inserted_block'], '')
        require(stripped.encode() == original, 'Overlay changed an original AppRoot byte')
        proposed_raw = proposed.encode()
        require(sha(proposed_raw) == self.pins['minimal_observation']['diagnostic_AppRoot_sha256']
                and len(proposed_raw) == self.pins['minimal_observation']['diagnostic_AppRoot_bytes'],
                'Runtime overlay differs from the reviewed minimal proposal')
        (self.out / 'original-AppRoot.swift').write_bytes(original)
        (self.out / 'diagnostic-AppRoot.swift').write_bytes(proposed_raw)
        (self.out / 'original-generated-StatisticsUITests.swift').write_bytes(generated_raw)
        diff = ''.join(difflib.unified_diff(original.decode().splitlines(keepends=True), proposed.splitlines(keepends=True),
                                           fromfile='actual0bcc/AppRoot.swift', tofile='diagnostic-only/AppRoot.swift'))
        (self.out / 'actual-observation-overlay.diff').write_text(diff)
        source.write_bytes(proposed_raw)
        require(source.read_bytes() == proposed_raw and stat.S_IMODE(source.stat().st_mode) == stat.S_IMODE(info.st_mode),
                'Temporary overlay write or mode differs')
        require(generated.read_bytes() == generated_raw, 'Observation overlay changed generated XCTest source')
        self.report['overlay_applications'] = 1
        self.report['overlay'] = {'path': str(source), 'original_sha256': sha(original),
                                  'diagnostic_sha256': sha(proposed_raw), 'retained_blocks': kept,
                                  'strip_insertions_restores_original_exactly': True,
                                  'generated_test': record(generated), 'assertion_counts': counts,
                                  'other_production_files_changed': 0, 'test_source_changes': 0}
        save(self.out / 'actual-overlay-receipt.json', self.report['overlay'])

    def start_collector(self):
        require(self.collector is None and self.report['collector_start_invocations'] == 0,
                'Trace collector may be started only once')
        require(self.device is not None, 'Collector requires the actual original UI device UUID')
        self.verify_environment()
        command = ['xcrun', 'simctl', 'spawn', self.device, 'log', 'stream', '--style', 'compact',
                   '--level', 'debug', '--predicate', 'eventMessage CONTAINS "AUDIO_INTENT_TRACE"']
        self.report['collector_start_invocations'] = 1
        self.report['collector_command'] = command
        self.trace_stream = (self.out / 'audio-intent-live.log').open('xb')
        self.collector = subprocess.Popen(command, stdout=self.trace_stream, stderr=subprocess.STDOUT,
                                          start_new_session=True)
        self.report['collector_pid'] = self.collector.pid
        self.note('collector-started', command=command, pid=self.collector.pid)
        early = self.collector.poll()
        require(early is None, 'Trace collector exited before original XCTest execution: ' + str(early))

    def stop_collector(self):
        # Collection failures are recorded, but cannot skip original shutdown/delete
        # or replace the original UI command failure. Final status is fail-closed.
        if self.collector_stopped:
            return
        self.collector_stopped = True
        if self.collector is not None:
            self.report['collector_stop_invocations'] += 1
            self.report['collector_exit_before_stop'] = self.collector.poll()
            try:
                if self.collector.returncode is None:
                    try:
                        os.killpg(self.collector.pid, signal.SIGTERM)
                        self.report['collector_own_group_sigterm'] = True
                    except ProcessLookupError:
                        pass
                    try:
                        self.collector.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(self.collector.pid, signal.SIGKILL)
                            self.report['collector_own_group_sigkill'] = True
                        except ProcessLookupError:
                            pass
                        self.collector.wait(timeout=1)
                else:
                    self.observation_error('collector-ended-early', RuntimeError(
                        'Trace stream ended before original device cleanup: ' + str(self.collector.returncode)))
                self.report['collector_exit_after_stop'] = self.collector.returncode
            except Exception as error:
                self.observation_error('collector-stop', error)
        if self.trace_stream is not None:
            try:
                self.trace_stream.close()
            except Exception as error:
                self.observation_error('collector-stream-close', error)
        self.note('collector-stopped-before-original-cleanup', collector_started=self.collector is not None)

    def output(self, *args, **kwargs):
        command = list(map(str, args))
        if command[:3] == ['xcrun', 'simctl', 'create']:
            require(self.report['create_invocations'] == 0, 'Original UI device may be created only once')
            require(self.runtimes is not None and self.types is not None, 'Missing original selection inputs')
            self.selection = selected_original_runtime(self.runtimes, self.types, self.pins, self.preflight, self.service_binding)
            require(command == ['xcrun', 'simctl', 'create', 'Integrated UI Review',
                                self.selection['device']['identifier'], self.selection['runtime']['identifier']],
                    'Original create command differs from the validated unmodified selection')
            save(self.out / 'selection-binding-before-create.json', self.selection)
            self.report['create_invocations'] += 1
        self.note('original-output-forward', command=command, kwargs=kwargs)
        result = self.original_output(*args, **kwargs)
        if command == ['xcrun', 'simctl', 'list', 'runtimes', '-j']:
            self.runtimes = json.loads(result)['runtimes']
        elif command == ['xcrun', 'simctl', 'list', 'devicetypes', '-j']:
            self.types = json.loads(result)['devicetypes']
        elif command[:3] == ['xcrun', 'simctl', 'create']:
            require(re.fullmatch(r'[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}', result),
                    'Original create did not return one actual UUID')
            self.device = result
            self.report['actual_device_uuid'] = result
        return result

    def run(self, *args, **kwargs):
        command = list(map(str, args[0]))
        timeout = kwargs.get('timeout', 180)
        if command[:3] == ['xcrun', 'simctl', 'boot']:
            require(timeout == 180 and command[3:] == [self.device], 'Original boot command/deadline changed')
            self.verify_environment()
            self.report['boot_invocations'] += 1
        elif command[:3] == ['xcrun', 'simctl', 'bootstatus']:
            require(timeout == 120, 'Original bootstatus deadline changed')
        elif command[:3] in (['xcrun', 'simctl', 'shutdown'], ['xcrun', 'simctl', 'delete']):
            try:
                self.stop_collector()
            except BaseException as error:
                self.observation_error('collector-stop-boundary-before-cleanup', error)
            require(timeout == 30 and command[3:] == [self.device], 'Original cleanup command/deadline changed')
        elif command[:2] == ['xcodebuild', 'build-for-testing']:
            require(self.report['build_invocations'] == 0 and timeout == 900, 'Original build count/deadline changed')
            self.apply_overlay()
            self.report['build_invocations'] += 1
        elif command[:2] == ['xcodebuild', 'test-without-building']:
            require(self.report['test_invocations'] == 0 and self.report['build_invocations'] == 1
                    and timeout == 900 and not any(x.startswith('-only-testing') for x in command),
                    'Original four-test execution/count/deadline changed')
            self.start_collector()
            self.report['test_invocations'] += 1
        row = {'command': command, 'log': str(args[1]) if len(args) > 1 else kwargs.get('log'),
               'timeout_seconds': timeout, 'timing': kwargs.get('timing', False),
               'cwd': str(kwargs.get('cwd', self.ui.ROOT)), 'arguments_forwarded_unmodified': True}
        self.report['command_forwarding'].append(row)
        self.note('original-run-forward', **row)
        try:
            return self.original_run(*args, **kwargs)
        except BaseException as error:
            self.report['original_command_failures'].append({**row, 'type': type(error).__name__,
                                                             'message': str(error), 'returncode': getattr(error, 'returncode', None)})
            raise

    def finish_trace(self):
        self.stop_collector()
        path = self.out / 'audio-intent-live.log'
        if path.exists():
            self.report['trace_file'] = record(path)
            text = path.read_text(errors='replace')
            events = re.findall(r'AUDIO_INTENT_TRACE seq=([0-9]+) uptime=([0-9]+\.[0-9]+) event=([^\s]+)', text)
            self.report['trace_events_observed'] = len(events)
            self.report['trace_event_counts'] = {name: sum(row[2] == name for row in events) for name in sorted({row[2] for row in events})}
        else:
            self.report['trace_events_observed'] = 0
        if self.report['test_invocations'] and not self.report['trace_events_observed']:
            self.observation_error('trace-content', RuntimeError('Original tests executed but no application intent trace was retained'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--source-input', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--input-receipt', type=Path, required=True)
    parser.add_argument('--preflight', type=Path, required=True)
    parser.add_argument('--service-refresh', type=Path, required=True)
    parser.add_argument('--service-exit-receipt', type=Path, required=True)
    parser.add_argument('--service-step-outcome', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__ and sys.platform == 'darwin' and platform.machine() == 'arm64',
            'Use assertions and the actual Apple arm64 runner')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and os.environ.get('GITHUB_JOB') == 'diagnose_audio_only', 'Use the declared actual hosted diagnostic job')
    out = args.output.resolve()
    require(not out.exists(), 'Refusing to overwrite another diagnostic observation')
    out.mkdir(parents=True)
    report = {'schema': 1, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'DIAGNOSTIC_FAILED_NOT_CANDIDATE', 'candidate_credit': False,
              'selected_product': False, 'full16': False, 'D28': False, 'I_C': False,
              'original_ui_main_returned_success': False, 'new_UI_taps_or_assertions': 0,
              'test_retries': 0, 'scope': 'One exact original0bcc UI main; temporary AppRoot8block observation only',
              'secondary_errors': []}
    primary = traceback = None
    observation = ui = rh = None
    env_identity = {k: os.environ.get(k) for k in
                    ('GITHUB_SHA', 'GITHUB_REPOSITORY', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB')}
    try:
        control, source_input, root = (p.resolve(strict=True) for p in (args.control, args.source_input, args.root))
        pins = json.loads(args.pins.read_bytes())
        require(os.environ['GITHUB_REPOSITORY'] == pins['repository'], 'Wrong actual diagnostic repository')
        validator = control / 'Bootstrap/runtime_handoff.py'
        require(sha(validator.read_bytes()) == pins['validator_sha256']['Bootstrap/runtime_handoff.py'],
                'Original source identity/payload validator changed')
        rh = load_module('one_ui_original_runtime_handoff', validator)
        control_id, source_input_id, source_id = rh.identity(control), rh.identity(source_input), rh.identity(root)
        require(control_id['commit'] == os.environ['GITHUB_SHA'], 'Actual control checkout differs from GITHUB_SHA')
        require(source_input_id == pins['source_input_helper'] and source_id == pins['source'],
                'Current source-input/worktree identity changed')
        restored = json.loads(args.input_receipt.read_bytes())
        require(restored['status'] == 'HISTORICAL_PRODUCER_INPUT_VERIFIED_FOR_DIAGNOSTIC_ONLY'
                and restored['candidate_execution'] is False and restored['canonical_execution'] is False
                and restored['selected_product'] is False, 'Input is not explicitly diagnostic-only preserved producer evidence')
        actual = restored['diagnostic']
        require(actual['helper'] == control_id and actual['repository'] == os.environ['GITHUB_REPOSITORY']
                and actual['run_id'] == int(os.environ['GITHUB_RUN_ID'])
                and actual['run_attempt'] == int(os.environ['GITHUB_RUN_ATTEMPT'])
                and actual['job'] == os.environ['GITHUB_JOB'], 'Input restoration belongs to another actual diagnostic')
        origin = restored['origin']
        require(origin['run_id'] == pins['origin_run_id'] and origin['attempt'] == pins['origin_attempt']
                and origin['source'] == pins['source'] and origin['helper'] == pins['origin_helper']
                and origin['producer_job_id'] == pins['origin_producer_job_id']
                and origin['producer_artifact'] == pins['producer_artifact']
                and origin['input_artifact'] == pins['input_artifact']
                and origin['archive_sha256'] == pins['archive_sha256']
                and restored['all_payload_hashes_sizes_and_modes_preserved'] is True
                and restored['payload_file_count'] == pins['manifest_file_count'], 'Restored producer-origin binding differs')
        preflight = json.loads(args.preflight.read_bytes())
        validate_preflight(preflight, pins, actual)
        service_binding = validate_service_binding(args.service_refresh, args.service_exit_receipt,
            args.preflight, preflight, pins, actual, control, args.service_step_outcome)
        require(sha((control / 'Bootstrap/ios_runtime_staged_preflight.py').read_bytes()) == pins['staged_preflight_sha256'],
                'Actual control staged preflight source changed')
        for name, digest in pins['ui_source_sha256'].items():
            require(sha((root / name).read_bytes()) == digest, 'Original current UI source differs: ' + name)
        require(not (root / '.build/integrated-ui').exists(), 'Original UI main requires a fresh UI workspace')
        report.update(actual_diagnostic=actual, preserved_origin=origin,
                      control_identity=control_id, source_input_identity=source_input_id, source_identity=source_id,
                      input_receipt=record(args.input_receipt), preflight=record(args.preflight), pins=record(args.pins),
                      same_run_service_binding=service_binding)
        sys.path.insert(0, str(root / 'Build'))
        # The original imports and globals still point at exact current0bcc.
        sys.modules['release_source'] = load_module('release_source', root / 'Build/release_source.py')
        sys.modules['simulator_diagnostics'] = load_module('simulator_diagnostics', root / 'Build/simulator_diagnostics.py')
        ui = load_module('current_original_ui_review', root / 'Build/ui_review.py')
        require(ui.ROOT == root and ui.OUT == root / 'artifacts/integrated/ui'
                and ui.WORK == root / '.build/integrated-ui', 'Original UI ROOT/OUT/WORK values changed')
        observation = Observation(ui, pins, preflight, out, source_input, service_binding)
        ui.run, ui.output = observation.run, observation.output
        observation.report['main_invocations'] = 1
        ui.main()
        report['original_ui_main_returned_success'] = True
        require((ui.OUT / 'SUCCESS.txt').is_file(), 'Original UI main returned without its own success evidence')
        report['original_ui_success_marker'] = record(ui.OUT / 'SUCCESS.txt')
    except BaseException as error:
        primary, traceback = error, error.__traceback__
        report['primary_failure'] = {'type': type(error).__name__, 'message': str(error),
                                     'returncode': getattr(error, 'returncode', None)}
    finally:
        if observation is not None:
            try:
                observation.finish_trace()
            except BaseException as error:
                observation.observation_error('trace-final-evidence', error)
            if ui is not None:
                ui.run, ui.output = observation.original_run, observation.original_output
            report['observation'] = observation.report
        try:
            require({k: os.environ.get(k) for k in env_identity} == env_identity, 'Diagnostic GitHub identity changed')
            if rh is not None and 'source_identity' in report:
                require(rh.identity(root) == report['source_identity']
                        and rh.identity(control) == report['control_identity']
                        and rh.identity(source_input) == report['source_input_identity'],
                        'Actual original source/control/input bytes changed during diagnostic')
                report['all_canonical_source_identities_preserved'] = True
                if observation and observation.report['overlay_applications']:
                    app = ui.WORK / 'application'
                    require(sha((app / 'Socks5/AppRoot.swift').read_bytes()) == pins['minimal_observation']['diagnostic_AppRoot_sha256'],
                            'Temporary AppRoot overlay changed during original execution')
                    require(sha((app / 'StatisticsUITests.swift').read_bytes()) == pins['original_ui_generated_source']['sha256'],
                            'Original generated XCTest source changed during execution')
                    report['temporary_overlay_and_original_test_bytes_preserved'] = True
        except BaseException as error:
            if primary is None:
                primary, traceback = error, error.__traceback__
                report['primary_failure'] = {'type': type(error).__name__, 'message': str(error)}
            else:
                report['secondary_errors'].append({'stage': 'final-source-identity', 'type': type(error).__name__, 'message': str(error)})
        if primary is None and observation and observation.first_observation_error is not None:
            primary = observation.first_observation_error
            traceback = primary.__traceback__
            report['primary_failure'] = {'type': type(primary).__name__, 'message': str(primary), 'scope': 'diagnostic-observation'}
        if primary is None and report['original_ui_main_returned_success']:
            report['status'] = 'DIAGNOSTIC_ORIGINAL_UI_SUCCESS_NOT_CANDIDATE'
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            save(out / 'diagnostic-outcome.json', report)
        except BaseException as error:
            report['status'] = 'DIAGNOSTIC_FAILED_NOT_CANDIDATE'
            if primary is None:
                primary, traceback = error, error.__traceback__
                report['primary_failure'] = {'type': type(error).__name__, 'message': str(error), 'scope': 'final-evidence-save'}
            else:
                report['secondary_errors'].append({'stage': 'final-evidence-save', 'type': type(error).__name__, 'message': str(error)})
            try:
                sys.stderr.write('Could not save diagnostic outcome: ' + type(error).__name__ + '\n')
            except BaseException:
                pass
    try:
        print(report['status'] + ' candidate_credit=false original_main_invocations=' +
              str(observation.report['main_invocations'] if observation else 0))
    except BaseException as error:
        report['status'] = 'DIAGNOSTIC_FAILED_NOT_CANDIDATE'
        if primary is None:
            primary, traceback = error, error.__traceback__
            report['primary_failure'] = {'type': type(error).__name__, 'message': str(error), 'scope': 'final-console-output'}
        else:
            report['secondary_errors'].append({'stage': 'final-console-output', 'type': type(error).__name__, 'message': str(error)})
        try:
            save(out / 'diagnostic-outcome.json', report)
        except BaseException:
            pass
    if primary is not None:
        raise primary.with_traceback(traceback)


if __name__ == '__main__':
    main()
