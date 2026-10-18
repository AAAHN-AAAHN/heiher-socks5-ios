#!/usr/bin/env python3
"""Execute the exact service and actual adapter body with explicit platform doubles.

The adapter body's imports/availability selection are the only test translation.
Both OS API branches are additionally typechecked unchanged by check_audio_sdk.sh.
Named invalid variants must compile and fail the intended runtime invariant.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if not __debug__:
    raise SystemExit('Assertions must be enabled.')

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OWNED = ROOT / 'Socks5/BackgroundKeepAlive'
SERVICE_CASES = ('normal', 'finite-failure', 'pending-off-on', 'pending-reset', 'pending-owner',
                 'pending-deactivation', 'pending-inspection', 'storm', 'stopped-player', 'duplicate-completion')
BOUNDARY_CASES = ('race-tick', 'race-admit', 'lease-blocked', 'progress-clock', 'lease-matrix',
                  'lease-main-issued', 'lease-main-cancelled', 'lease-main-resource-reset', 'lease-main-off-on')
RELAPSE_CASES = ('early-relapse', 'healthy-inspection-relapse', 'continuous-granted',
                 'continuous-denied', 'continuous-expired', 'continuous-missing', 'stale-success')
INGRESS_CASES = ('recovered-interrupted', 'recovered-media-reset', 'pending-interrupted',
                 'pending-media-reset', 'pending-inspection', 'off-before-drain', 'off-on-before-drain',
                 'second-during-replacement', 'second-after-recovery',
                 'admit-inspect-invalidated', 'admit-reuse-invalidated')
INGRESS_NEGATIVES = {
    'recovered-interrupted': 'ACCEPTED_HEALTHY_REPLACEMENT_INVALIDATION_REPLAYED',
    'recovered-media-reset': 'ACCEPTED_HEALTHY_REPLACEMENT_INVALIDATION_REPLAYED',
    'off-on-before-drain': 'ACCEPTED_HEALTHY_REPLACEMENT_INVALIDATION_REPLAYED',
    'second-during-replacement': 'SECOND_INVALIDATION_DID_NOT_REVOKE_REPLACEMENT',
    'second-after-recovery': 'SECOND_INVALIDATION_COALESCED_WITH_RECOVERED_EPOCH',
    'admit-inspect-invalidated': 'INVALIDATED_RESOURCE_ADMITTED_WITHOUT_REBUILD',
    'admit-reuse-invalidated': 'INVALIDATED_RESOURCE_ADMITTED_WITHOUT_REBUILD',
}
FACADE_CASES = ('reentry-intent', 'reentry-publication', 'echo', 'owner', 'notifications', 'inactive-source',
                'scheduling', 'location')
API_BOUNDARIES = ('asset', 'session', 'category-get', 'mode-get', 'options-get', 'category-set',
                  'alerts', 'disconnect', 'activate', 'player-init', 'loops', 'delegate',
                  'prepare', 'play', 'playing-get', 'position-get', 'clock-get',
                  'duration-get', 'rate-enabled-get', 'rate-get', 'buffer-get')
ADAPTER_CASES = ('healthy', 'preferences', 'category-failure', 'prepare-failure', 'play-failure',
                 'player-failure', 'silent-stop', 'configuration-drift', 'compatible-route', 'decoder',
                 'asset-missing', 'asset-invalid', 'cache', 'release-failure', 'duplicate-completion',
                 'failure-1', 'failure-100', 'failure-1000', 'stale-delegate', 'mixed-delegate',
                 'delayed-consumption')
ASYNC_CASES = ('pending-owner', 'pending-reset', 'pending-off-on', 'pending-deactivation', 'pending-final-owner')


def run(command, records, label, timeout=30, expected=None):
    try:
        result = subprocess.run([str(x) for x in command], cwd=ROOT, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        records.append({'label': label, 'command': [str(x) for x in command],
                        'timeout': timeout, 'expected_failure': expected,
                        'stdout': (error.stdout or b'').decode(errors='replace'),
                        'stderr': (error.stderr or b'').decode(errors='replace')})
        raise AssertionError('Timeout is not a successful negative control: ' + label) from error
    record = {'label': label, 'command': [str(x) for x in command], 'exit': result.returncode,
              'expected_failure': expected, 'stdout': result.stdout, 'stderr': result.stderr}
    records.append(record)
    print(label, 'exit=', result.returncode, flush=True)
    if expected is None:
        if result.returncode:
            failure = ROOT / 'artifacts/background-loop/failures' / (str(time.time_ns()) + '-' + label)
            failure.mkdir(parents=True, exist_ok=True)
            executable = Path(command[0])
            if executable.is_file() and executable.name == 'fixture':
                shutil.copytree(executable.parent, failure / 'compiled-input')
                for argument in command[1:]:
                    path = Path(argument)
                    if path.is_file():
                        shutil.copy2(path, failure / path.name)
            (failure / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
            print(result.stdout, end='', file=sys.stderr)
            print(result.stderr, end='', file=sys.stderr)
            raise AssertionError(label)
        assert 'PASS' in result.stdout or label.startswith('compile-'), label
    else:
        assert result.returncode != 0 and expected in result.stdout + result.stderr, (label, record)
        print('EXPECTED INVALID-VARIANT REJECTION:', expected, flush=True)



def relapse_lease(lease):
    # Both normal and invalid copied inputs use this one observation. It runs
    # after the original gate clear, outside the lock. Product lease stays exact.
    before = '                provider.end(id)\n                state.withValue { $0 = State() }'
    assert lease.count(before) == 1
    return lease.replace(before, before + '\n                RelapseObservation.endGateDidClear(id)', 1)


def relapse_was_inspect_only(source):
    # Restore the exact old episode condition as a compiled runtime negative.
    accepted = '            } else if let sample = reply.sample, sample.playing && sample.configured {\n'
    assert source.count(accepted) == 1
    source = source.replace(accepted, accepted +
        '                let wasInspect: Bool\n'
        '                if case .inspect = job.command { wasInspect = true } else { wasInspect = false }\n', 1)
    before = ('                // The same accepted healthy result ends protection and its episode.\n'
              '                // A real relapse before the next inspection needs a new recovery claim.\n'
              '                episode = false\n'
              '                expedited = false')
    assert source.count(before) == 1
    return source.replace(before,
        '                // Only a subsequent healthy observation closes a failed episode.\n'
        '                if wasInspect { episode = false; expedited = false }', 1)


def run_checked_cleanup(command, records, label, expected=None):
    run(command, records, label, expected=expected)
    record = records[-1]
    result = json.loads(record['stdout'])
    assert result['case'] == command[1] and result['cleanup_passed'] is True, (label, result)
    if expected is None:
        assert record['exit'] == 0 and result['status'] == 'PASS' and result['failures'] == [], (label, result)
    else:
        # A wrong signal, extra failure, failed cleanup or a timeout is not this
        # state-machine regression's accepted intended failure.
        assert record['exit'] == 74 and result['status'] == 'FAIL' and result['failures'] == [expected], (label, result)


def ingress_source(source):
    # Identical copied-input holds expose the real posting-thread dispatch and
    # admission boundaries. Product queues, locks and timing remain unchanged.
    marker = '    func notify(_ event: Event) {\n        lock.lock()'
    start = source.index(marker)
    end = source.index('    // Called only with lock held.', start)
    body = source[start:end]
    before = '        lock.unlock()\n        if schedule { control.async { self.drain() } }'
    assert body.count(before) == 1
    changed = body.replace(before, '        lock.unlock()\n'
        '        IngressObservation.beforeDrainEnqueue(event, scheduled: schedule)\n'
        '        if schedule { control.async { self.drain() } }', 1)
    source = source[:start] + changed + source[end:]
    parameter = 'requested' if '    private func begin(_ requested: Command) {' in source else 'command'
    before = '    private func begin(_ ' + parameter + ': Command) {\n'
    assert source.count(before) == 1
    source = source.replace(before, before + '        IngressObservation.beforeAdmission(' + parameter + ')\n', 1)
    return source + '\n' + (HERE / 'IngressReplayAccess.swift.inc').read_text()


def ingress_previous_admission(source):
    # Restore the exact previous admission and invalidation-consumption behavior.
    replacements = [
        (
            '''    private func begin(_ requested: Command) {
''',
            '''    private func begin(_ command: Command) {
''',
        ),
        (
            '''        adopt(latest())
        let command: Command
        switch requested {
        case .inspect where rebuild: command = .start(rebuild: true)
        case .start(let recreate): command = .start(rebuild: recreate || rebuild)
        default: command = requested
        }
        if releaseBarrier {
            if case .stop = command {} else { begin(.stop); return }
        }
''',
            '''        adopt(latest())
        if releaseBarrier {
            if case .stop = command {} else { begin(.stop); return }
        }
''',
        ),
        (
            '''        lock.lock()
        // This start incorporates the pending invalidation into its resources.
        // A later event must revoke it even if an earlier drain is still queued.
        if case .start = command, ticket.on, ticket.stop == input.stop, ticket.epoch == input.epoch {
            inbox.invalidated = false
        }
        timing = Timing(id: job.id, phase: .queued)
        lock.unlock()
''',
            '''        lock.lock()
        timing = Timing(id: job.id, phase: .queued)
        lock.unlock()
''',
        ),
    ]
    for before, after in replacements:
        assert source.count(before) == 1
        source = source.replace(before, after, 1)
    return source


def ingress_lease(lease):
    before = '                provider.end(id)\n                state.withValue { $0 = State() }'
    assert lease.count(before) == 1
    return lease.replace(before, before + '\n                IngressObservation.endGateDidClear(id)', 1)


def adapter_source(service, legacy):
    marker = '#if canImport(AVFAudio) && canImport(UIKit)\n/// Only the service I/O queue'
    assert service.count(marker) == 1
    result = service.replace(marker, '#if true\n/// Only the service I/O queue', 1)
    availability = 'if #available(iOS 27.0, *) {'
    assert result.count(availability) == 1
    # The two original branch bodies are retained; only platform selection changes.
    result = result.replace(availability, 'if AudioEndpointTestPlatform.legacy == false {', 1)
    result += '\nprivate enum AudioEndpointTestPlatform { static let legacy = ' + str(legacy).lower() + ' }\n'
    result += '''
extension LoopAudioService {
    static func auditEndpoint(queue: DispatchQueue, event: @escaping @Sendable (Event) -> Void) -> any LoopAudioEndpoint {
        AudioEndpoint(queue: queue, event: event)
    }
    func auditOwnerLifetime() -> @Sendable () -> Bool {
        { [weak queueOwner] in queueOwner != nil }
    }
    func auditAfterQueueDrain(_ completion: @escaping @Sendable () -> Void) {
        queueOwner.auditAfterQueueDrain(completion)
    }
    func auditEndpointQueueDepth() -> Int { queueOwner.auditEndpointQueueDepth() }
    func auditHoldControl(entered: @escaping @Sendable () -> Void, release: DispatchSemaphore) {
        queueOwner.auditHoldControl(entered: entered, release: release)
    }
    func auditAvailableResult() -> Double? { queueOwner.auditAvailableResult() }
    func auditRetryDeadline(_ completion: @escaping @Sendable (Double) -> Void) {
        queueOwner.auditRetryDeadline(completion)
    }
}
extension LoopAudioQueueOwner {
    func auditAfterQueueDrain(_ completion: @escaping @Sendable () -> Void) {
        // Capture the immutable queues only, so this barrier cannot retain the
        // owner whose pending-receipt lifetime the test is trying to observe.
        let control = self.control
        let io = self.io
        control.async { io.async { DispatchQueue.main.async(execute: completion) } }
    }
    func auditEndpointQueueDepth() -> Int {
        lock.lock(); defer { lock.unlock() }
        return ioDeliveryQueued ? 1 : 0
    }
    func auditHoldControl(entered: @escaping @Sendable () -> Void, release: DispatchSemaphore) {
        control.async {
            entered()
            precondition(release.wait(timeout: .now() + 3) == .success, "TEST_CONTROL_HOLD_NOT_RELEASED")
        }
    }
    func auditAvailableResult() -> Double? {
        lock.lock(); defer { lock.unlock() }
        return timing.resultAvailableAt
    }
    func auditRetryDeadline(_ completion: @escaping @Sendable (Double) -> Void) {
        control.async { completion(self.retryAt) }
    }
}
'''
    return result


def compile_fixture(folder, label, source, monitor, lease, fixture, optimize, records, mocks=None, facade=None):
    work = folder / label
    work.mkdir()
    paths = []
    for name, body in [('Service.swift', source), ('Monitor.swift', monitor), ('Lease.swift', lease)]:
        path = work / name
        path.write_text(body)
        paths.append(path)
    if mocks:
        paths.append(HERE / mocks)
    if facade:
        path = work / 'Facade.swift'
        path.write_text(facade)
        paths.append(path)
    paths.append(HERE / fixture)
    executable = work / 'fixture'
    run(['swiftc', '-swift-version', '5', '-strict-concurrency=complete', '-warnings-as-errors',
         '-parse-as-library', '-O' if optimize else '-Onone', *paths, '-o', executable],
        records, 'compile-' + label, timeout=90)
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=('all', 'service', 'boundary', 'adapter', 'facade'), default='all')
    parser.add_argument('--mode', choices=('all', 'debug', 'optimized'), default='all')
    parser.add_argument('--negative-only', action='store_true')
    parser.add_argument('--case', choices=FACADE_CASES)
    args = parser.parse_args()
    source = (OWNED / 'LoopAudioService.swift').read_text()
    monitor = (OWNED / 'PlaybackProgressMonitor.swift').read_text()
    lease = (OWNED / 'RecoveryExecutionLease.swift').read_text()
    facade = (OWNED / 'BackgroundKeepAlive.swift').read_text()
    imports = 'import AVFAudio\nimport CoreLocation\nimport SwiftUI\n'
    assert facade.startswith(imports)
    assert '#if canImport(Combine)\nimport Combine\n#endif' in facade
    facade = facade.replace(imports, 'import Foundation\n', 1)
    admission = (HERE / 'RecoveryAdmissionAccess.swift.inc').read_text()
    out = ROOT / 'artifacts/background-loop' / (args.group + '-' + args.mode + ('-' + args.case if args.case else ''))
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'results.json').exists():
        shutil.copy2(out / 'results.json', out / ('previous-' + str(time.time_ns()) + '.json'))
    (out / 'SUCCESS.txt').unlink(missing_ok=True)
    records = []
    report = {'group': args.group, 'mode': args.mode,
              'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OWNED.glob('*.swift')},
              'tested_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'scope': 'Actual service/adapter bodies; controlled AV outcomes and real host Dispatch. Not Apple playback or physical-device execution.',
              'commands': records}
    try:
        with tempfile.TemporaryDirectory(prefix='loop-audio-') as directory:
            folder = Path(directory)
            invalid = folder / 'invalid.wav'
            invalid.write_bytes(b'X' + (OWNED / 'Silence.wav').read_bytes()[1:])
            modes = [False, True] if args.mode == 'all' else [args.mode == 'optimized']
            for optimize in modes:
                suffix = 'optimized' if optimize else 'debug'
                if not args.negative_only and args.group in ('all', 'service'):
                    exe = compile_fixture(folder, 'service-' + suffix, source, monitor, lease,
                                          'LoopAudioServiceTests.swift', optimize, records)
                    for case in SERVICE_CASES:
                        run([exe, case], records, suffix + '-service-' + case)
                if not args.negative_only and args.group in ('all', 'boundary'):
                    exe = compile_fixture(folder, 'boundary-' + suffix, source + admission, monitor, lease,
                                          'RecoveryBoundaryTests.swift', optimize, records)
                    for case in BOUNDARY_CASES:
                        run([exe, case], records, suffix + '-boundary-' + case)
                    for label, fixture in [('progress', 'PlaybackProgressTests.swift'),
                                           ('lease-lifecycle', 'LeaseLifecycleTests.swift')]:
                        exe = compile_fixture(folder, label + '-' + suffix, source, monitor, lease,
                                              fixture, optimize, records)
                        run([exe], records, suffix + '-' + label)
                    exe = compile_fixture(folder, 'early-relapse-' + suffix, source, monitor, relapse_lease(lease),
                                          'EarlyRelapseTests.swift', optimize, records)
                    for case in RELAPSE_CASES:
                        run_checked_cleanup([exe, case], records, suffix + '-early-relapse-' + case)
                    exe = compile_fixture(folder, 'ingress-' + suffix, ingress_source(source), monitor,
                                          ingress_lease(lease), 'IngressReplayTests.swift', optimize, records)
                    for case in INGRESS_CASES:
                        run_checked_cleanup([exe, case], records, suffix + '-ingress-' + case)
                if not args.negative_only and args.group in ('all', 'adapter'):
                    for legacy in (False, True):
                        label = ('legacy-' if legacy else 'async-') + suffix
                        exe = compile_fixture(folder, label, adapter_source(source, legacy), monitor, lease,
                                              'AudioEndpointBoundaryTests.swift', optimize, records,
                                              mocks='AudioEndpointMocks.swift')
                        cases = [*ADAPTER_CASES, *('off-at-' + x for x in API_BOUNDARIES),
                                 *('blocked-' + x for x in (*API_BOUNDARIES, 'stop', 'deactivate'))]
                        if not legacy:
                            cases += ASYNC_CASES
                        for case in cases:
                            run([exe, case, OWNED / 'Silence.wav', invalid], records, label + '-' + case)
                if not args.negative_only and args.group in ('all', 'facade'):
                    exe = compile_fixture(folder, 'facade-' + suffix, source, monitor, lease,
                                          'FacadeBoundaryTests.swift', optimize, records,
                                          mocks='FacadePlatformMocks.swift', facade=facade)
                    for case in ([args.case] if args.case else FACADE_CASES):
                        run([exe, case], records, suffix + '-facade-' + case)
                if args.group in ('all', 'boundary'):
                    exe = compile_fixture(folder, 'previous-ingress-' + suffix,
                                          ingress_source(ingress_previous_admission(source)), monitor,
                                          ingress_lease(lease), 'IngressReplayTests.swift', optimize, records)
                    for case in INGRESS_CASES:
                        run_checked_cleanup([exe, case], records, suffix + '-previous-ingress-' + case,
                                            expected=INGRESS_NEGATIVES.get(case))
                    exe = compile_fixture(folder, 'bad-early-relapse-' + suffix, relapse_was_inspect_only(source),
                                          monitor, relapse_lease(lease), 'EarlyRelapseTests.swift', optimize, records)
                    run_checked_cleanup([exe, 'early-relapse'], records, suffix + '-bad-early-relapse',
                                expected='ACCEPTED_HEALTHY_RELAPSE_DID_NOT_REQUEST_NEW_CLAIM')
                    claim_continuation = '                let admitted = executionClaim.start(mayIssue: { [weak self] in self?.mayRequestClaim(job.ticket) == true }) { [self] in'
                    assert source.count(claim_continuation) == 1
                    premature = source.replace(claim_continuation, '                self.perform(job)\n' + claim_continuation, 1)
                    exe = compile_fixture(folder, 'bad-before-claim-return-' + suffix, premature + admission, monitor, lease,
                                          'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'lease-main-issued'], records, suffix + '-bad-before-claim-return',
                        expected='AV_PREPARATION_BEFORE_MAIN_REQUEST_RETURN')
                    unchecked_issue = source.replace(claim_continuation,
                        '                let admitted = executionClaim.start { [self] in', 1)
                    exe = compile_fixture(folder, 'bad-claim-ticket-' + suffix, unchecked_issue + admission, monitor, lease,
                                          'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'lease-main-cancelled'], records, suffix + '-bad-claim-ticket',
                        expected='QUEUED_OFF_ISSUED_AUDIO_OR_CLAIM')
                    # A claim protects the surviving On/Stop episode, while AV
                    # preparation must retain its narrower resource epoch guard.
                    epoch_bound_claim = source.replace(claim_continuation,
                        claim_continuation.replace('mayRequestClaim(job.ticket)', 'valid(job.ticket)'), 1)
                    exe = compile_fixture(folder, 'bad-claim-resource-epoch-' + suffix, epoch_bound_claim + admission,
                                          monitor, lease, 'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'lease-main-resource-reset'], records, suffix + '-bad-claim-resource-epoch',
                        expected='RESOURCE_RESET_DROPPED_EPISODE_CLAIM')
                    claim_stop_guard = '        return !exhausted && ticket.on && ticket.stop == input.stop\n'
                    assert source.count(claim_stop_guard) == 1
                    claim_without_stop = source.replace(claim_stop_guard, '        return !exhausted && ticket.on\n', 1)
                    exe = compile_fixture(folder, 'bad-claim-stop-' + suffix, claim_without_stop + admission,
                                          monitor, lease, 'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'lease-main-off-on'], records, suffix + '-bad-claim-stop',
                        expected='QUEUED_CLAIM_OFF_ON_BARRIER_LOST')
                    stop_guard = '        if next.stop != current.stop { releaseBarrier = true }'
                    assert source.count(stop_guard) == 1
                    bad_stop = source.replace(stop_guard, '        // Deliberate invalid control: discard stop admission.', 1)
                    exe = compile_fixture(folder, 'bad-stop-' + suffix, bad_stop + admission, monitor, lease,
                                          'RecoveryBoundaryTests.swift', optimize, records)
                    for case in ('race-tick', 'race-admit'):
                        run([exe, case], records, suffix + '-bad-stop-' + case, expected='ACCEPTED_STOP_BARRIER_LOST')
                    clock_guard = '''            && abs((b.deviceTime - a.deviceTime) - (b.finishedAt - a.finishedAt))
                <= max(0.01, max(a.bufferDuration, b.bufferDuration) * 4)
                    + (a.finishedAt - a.startedAt) + (b.finishedAt - b.startedAt)'''
                    assert monitor.count(clock_guard) == 1
                    exe = compile_fixture(folder, 'bad-clock-' + suffix, source + admission,
                                          monitor.replace(clock_guard, '', 1), lease,
                                          'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'progress-clock'], records, suffix + '-bad-clock', expected='PROGRESS_CLOCK_DISCONTINUITY')
                    end_guard = '        if let id { provider.end(id) }'
                    assert lease.count(end_guard) == 1
                    exe = compile_fixture(folder, 'bad-end-' + suffix, source + admission, monitor,
                                          lease.replace(end_guard, '        if let id { _ = id }', 1),
                                          'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'lease-matrix'], records, suffix + '-bad-end', expected='LEASE_TOKEN_END_COUNT')
                    assert source.count('                // Request on I/O: a slow provider cannot occupy control.') == 1
                    bad_claim = source.replace('                // Request on I/O: a slow provider cannot occupy control.',
                                               '                claim.start()', 1)
                    exe = compile_fixture(folder, 'bad-claim-' + suffix, bad_claim + admission, monitor, lease,
                                          'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'lease-blocked'], records, suffix + '-bad-claim', expected='LEASE_BLOCKED_CONTROL')
                    assert lease.count('            queue.async { [self] in') == 1
                    exe = compile_fixture(folder, 'bad-blocking-end-' + suffix, source, monitor,
                                          lease.replace('            queue.async { [self] in', '            do {', 1),
                                          'LeaseLifecycleTests.swift', optimize, records)
                    run([exe], records, suffix + '-bad-blocking-end', expected='LEASE_END_BLOCKED_CALLER')
                    holder_identity = 'guard let holder = value.current, holder.id == id else'
                    assert lease.count(holder_identity) == 1
                    exe = compile_fixture(folder, 'bad-holder-' + suffix, source, monitor,
                                          lease.replace(holder_identity, 'guard let holder = value.current else', 1),
                                          'LeaseLifecycleTests.swift', optimize, records)
                    run([exe], records, suffix + '-bad-holder', expected='EXTENSION_OLD_SIGNAL_RELEASED_NEW_HOLDER')
                    application_variants = [
                        ('expiry-end-deferred',
                         '            finish(request)\n            request.expire()',
                         '            DispatchQueue.main.async { self.finish(request) }\n            request.expire()',
                         'APPLICATION_EXPIRY_RETURNED_BEFORE_ACTUAL_END'),
                        ('continuation-before-begin',
                         '                    holder.request(allowed: allowed, expire: expire, receipt: receipt)\n                    returned()',
                         '                    returned()\n                    holder.request(allowed: allowed, expire: expire, receipt: receipt)',
                         'APPLICATION_CONTINUATION_BEFORE_BEGIN_RETURN'),
                        ('queued-off-still-begins',
                         '            guard allowed(), current == nil, sequence < Int.max else { receipt(nil); return }',
                         '            guard current == nil, sequence < Int.max else { receipt(nil); return }',
                         'APPLICATION_QUEUED_OFF_ISSUED_PLATFORM_BEGIN'),
                        ('early-expiry-loses-id',
                         '                finish(request)\n            } else if id == nil {',
                         '                // Invalid variant: omit the first safe end after begin.\n            } else if id == nil {',
                         'APPLICATION_EARLY_EXPIRY_LEAKED_RETURNED_ID'),
                        ('generic-return-waits-receipt',
                         '                if allowed() { request(expire, receipt) } else { receipt(nil) }\n'
                         '                // A provider may return before its receipt, or never deliver a\n'
                         '                // receipt. This boundary does not wait for a grant.\n'
                         '                returned()',
                         '                if allowed() {\n'
                         '                    request(expire, { id in receipt(id); returned() })\n'
                         '                } else { receipt(nil); returned() }',
                         'GENERIC_REQUEST_RETURN_WAITED_FOR_RECEIPT'),
                        ('latest-issue-ticket-ignored',
                         '            return mayIssue()',
                         '            return true',
                         'APPLICATION_LATEST_OFF_BEFORE_CONTROL_DRAIN_ISSUED_BEGIN'),
                    ]
                    for label, before, after, expected in application_variants:
                        assert lease.count(before) == 1, label
                        exe = compile_fixture(folder, 'bad-' + label + '-' + suffix, source, monitor,
                                              lease.replace(before, after, 1), 'LeaseLifecycleTests.swift', optimize, records)
                        run([exe], records, suffix + '-bad-' + label, expected=expected)
                    sample_span = ' && s.finishedAt - s.startedAt <= 0.1'
                    assert monitor.count(sample_span) == 1
                    exe = compile_fixture(folder, 'bad-sample-' + suffix, source,
                                          monitor.replace(sample_span, '', 1), lease,
                                          'PlaybackProgressTests.swift', optimize, records)
                    run([exe], records, suffix + '-bad-sample', expected='INVALID_PROGRESS_WAS_TRUSTED')
                    precision_guard = ', a.positionQuantum != nil, s.positionQuantum != nil'
                    assert monitor.count(precision_guard) == 1
                    exe = compile_fixture(folder, 'bad-unknown-precision-' + suffix, source,
                                          monitor.replace(precision_guard, '', 1), lease,
                                          'PlaybackProgressTests.swift', optimize, records)
                    run([exe], records, suffix + '-bad-unknown-precision',
                        expected='NORMAL_INDEPENDENT_QUANTIZATION_REBUILT')
                    position_error = '            + max(a.positionQuantum ?? 0, b.positionQuantum ?? 0)'
                    assert monitor.count(position_error) == 1
                    exe = compile_fixture(folder, 'bad-position-bound-' + suffix, source,
                                          monitor.replace(position_error, '', 1), lease,
                                          'PlaybackProgressTests.swift', optimize, records)
                    run([exe], records, suffix + '-bad-position-bound',
                        expected='NORMAL_INDEPENDENT_QUANTIZATION_REBUILT')
                if args.group in ('all', 'adapter'):
                    step_entry = '        context.step(step, false)'
                    assert source.count(step_entry) == 1
                    bad = source.replace(step_entry, '        // Deliberately omit exact API entry.', 1)
                    exe = compile_fixture(folder, 'bad-step-entry-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'blocked-category-get', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-step-entry', expected='API_STEP_IDENTITY_MISSING')
                    step_return = '        defer { context.step(step, true) }'
                    assert source.count(step_return) == 1
                    bad = source.replace(step_return, '        // Deliberately hide the request return.', 1)
                    exe = compile_fixture(folder, 'bad-step-return-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'pending-owner', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-step-return', expected='RETURNED_REQUEST_NOT_DISTINGUISHED_FROM_PENDING_CALLBACK')
                    retry_origin = 'retryAt = returnedAt + policy.interval'
                    assert source.count(retry_origin) == 2
                    bad = source.replace(retry_origin, 'retryAt = max(returnedAt, Self.now) + policy.interval')
                    exe = compile_fixture(folder, 'bad-retry-origin-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'delayed-consumption', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-retry-origin', expected='CONSUMPTION_DELAY_ADDED_ANOTHER_COOLDOWN')
                    fired_state = '                timerDeadline = nil\n                timerOperation = nil\n                tick()'
                    assert source.count(fired_state) == 1
                    bad = source.replace(fired_state, '                tick()', 1)
                    exe = compile_fixture(folder, 'bad-fired-deadline-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'blocked-prepare', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-fired-deadline', expected='CONTROL_DID_NOT_OBSERVE_DELAY')
                    cancellation = 'mayStart: { [weak self] in self?.valid(input) == true }'
                    assert source.count(cancellation) == 1
                    bad = source.replace(cancellation, 'mayStart: { true }', 1)
                    exe = compile_fixture(folder, 'bad-cancel-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'off-at-prepare', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-cancel', expected='NEW_PLAYBACK_API_AFTER_OFF')
                    delegate_identity = 'guard ioDelegateGeneration == receipt.generation else'
                    delegate_consume = 'guard receipt.generation == generation, player != nil else'
                    assert source.count(delegate_identity) == source.count(delegate_consume) == 1
                    bad = source.replace(delegate_identity, 'guard ioDelegateGeneration != nil else', 1)
                    bad = bad.replace(delegate_consume, 'guard player != nil else', 1)
                    exe = compile_fixture(folder, 'bad-delegate-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'stale-delegate', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-delegate', expected='STALE_DELEGATE_REBUILT_NEW_PLAYER')
                    # Leaving the consumption check intact is insufficient if
                    # stale ingress can erase a current pending decoder event.
                    bad = source.replace(delegate_identity, 'guard ioDelegateGeneration != nil else', 1)
                    exe = compile_fixture(folder, 'bad-mixed-delegate-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'mixed-delegate', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-mixed-delegate', expected='CURRENT_DELEGATE_RECEIPT_LOST')
                    retained_completion = 'self.endpoint?.perform(command, context: context) { [self] reply in'
                    assert source.count(retained_completion) == 1
                    bad = source.replace(retained_completion, retained_completion.replace('[self]', '[weak self]') +
                                         '\n                guard let self else { return }', 1)
                    exe = compile_fixture(folder, 'bad-pending-owner-' + suffix, adapter_source(bad, False), monitor, lease,
                                          'AudioEndpointBoundaryTests.swift', optimize, records, mocks='AudioEndpointMocks.swift')
                    run([exe, 'pending-final-owner', OWNED / 'Silence.wav', invalid], records,
                        suffix + '-bad-pending-owner', expected='PENDING_RECEIPT_LOST_OWNER')
                if not args.case and args.group in ('all', 'facade'):
                    inactive_source = '''        if #available(iOS 27.0, *), name == AVAudioSession.didBecomeInactiveNotification {
            let context = notification.userInfo?[AVAudioSession.deactivationContextKey] as? AVAudioSession.DeactivationContext
            // Our completed release may be reported after a newer On. Inspect
            // app-requested deactivation without invalidating healthy new work.
            // A real stopped player still recovers through the ordinary check.
            return context?.source == .app ? .hint : .interrupted
        }'''
                    assert facade.count(inactive_source) == 1
                    bad = facade.replace(inactive_source,
                        '        if #available(iOS 27.0, *), name == AVAudioSession.didBecomeInactiveNotification { return .interrupted }', 1)
                    exe = compile_fixture(folder, 'bad-inactive-source-' + suffix, source, monitor, lease,
                                          'FacadeBoundaryTests.swift', optimize, records,
                                          mocks='FacadePlatformMocks.swift', facade=bad)
                    run([exe, 'inactive-source'], records, suffix + '-bad-inactive-source',
                        expected='APP_DEACTIVATION_INVALIDATED_RENEWED_PLAYBACK')
                    ordering = '        audio.setEnabled(enabled, owner: audioOwner)\n        showAudioIntent(enabled)'
                    assert facade.count(ordering) == 1
                    bad = facade.replace(ordering, '        showAudioIntent(enabled)\n        audio.setEnabled(enabled, owner: audioOwner)', 1)
                    exe = compile_fixture(folder, 'bad-facade-' + suffix, source, monitor, lease,
                                          'FacadeBoundaryTests.swift', optimize, records,
                                          mocks='FacadePlatformMocks.swift', facade=bad)
                    run([exe, 'reentry-intent'], records, suffix + '-bad-facade', expected='FACADE_REENTRANT_OFF_LOST')
        (out / 'SUCCESS.txt').write_text('PASS: recorded current-source host fixtures and named runtime negative controls. No Apple/physical execution.\n')
    finally:
        (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS:', len(records), 'recorded compile/runtime commands;', out)


if __name__ == '__main__':
    main()
