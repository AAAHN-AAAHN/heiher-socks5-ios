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
                  'lease-main-issued', 'lease-main-relapse', 'lease-main-cancelled', 'lease-main-resource-reset', 'lease-main-off-on')
APPLICATION_PROVIDER_CASES = ('worker-expiry-before-return', 'expiry-before-receipt', 'reentrant-end',
                              'queued-end-bound', 'settled-lifetime')
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
FINALIZATION_ADAPTER_CASES = ('reused-finish', 'reused-decoder', 'reused-queued-delegate', 'reused-current-mixed',
    'reused-generation-limit', 'failed-allocation-generation', 'owner-unregister-blocked',
    'owner-off-blocked', 'owner-on-preserved', 'owner-release-failure', 'owner-last-off')
FINALIZATION_SERVICE_CASES = ('owner-unregister-paced', 'owner-off-paced', 'inspect-stopped',
    'inspect-misconfigured', 'inspect-error-paced', 'inspect-empty-paced', 'inspect-superseded-paced',
    'inspect-epoch-changed-paced', 'inspect-invalid-asset-paced', 'inspect-wrong-sample-epoch-paced',
    'start-stopped-paced', 'start-error-paced')
FINALIZATION_NEGATIVES = {
    'reused-finish': 'REUSED_PLAYBACK_ACCEPTED_STALE_DELEGATE',
    'reused-decoder': 'REUSED_PLAYBACK_ACCEPTED_STALE_DELEGATE',
    'reused-queued-delegate': 'REUSED_PLAYBACK_ACCEPTED_STALE_DELEGATE',
    'reused-generation-limit': 'SATURATED_REUSE_STARTED_WITH_OLD_CALLBACK_IDENTITY',
    'owner-unregister-blocked': 'OWNER_CLEANUP_REOPENED_BLOCKED_ASSET',
    'owner-off-blocked': 'OWNER_CLEANUP_REOPENED_BLOCKED_ASSET',
    'owner-unregister-paced': 'OWNER_CLEANUP_ERASED_RETRY_DEADLINE',
    'owner-off-paced': 'OWNER_CLEANUP_ERASED_RETRY_DEADLINE',
    'inspect-stopped': 'FIRST_OBSERVED_STOP_ADDED_RETRY_COOLDOWN',
    'inspect-misconfigured': 'FIRST_OBSERVED_STOP_ADDED_RETRY_COOLDOWN',
}
PRECEDENCE_CASES = ('stopped-before-progress', 'misconfigured-before-progress',
                    'stopped-misconfigured-before-progress', 'stopped-before-category',
                    'misconfigured-before-mode', 'mode-misconfigured-before-options',
                    'healthy-progress-preserved')
PRECEDENCE_BASELINE_COMMIT = 'dd8c2b25688a3e59c22b2755fa0bccce6de32261'
PRECEDENCE_BASELINE_SERVICE_SHA256 = 'c9f317de58c90e985082b4374ebf04e27306f0c59ed48cbc9059a0df48f46c1b'
STOPPED_START_CASES = ('healthy', 'ordinary-stopped', 'initial-stopped', 'bad-resume',
                       'persistent-stopped', 'off-after-failed-start')
STOPPED_START_NEGATIVES = {
    'initial-stopped': 'MISSING_L2_AFTER_FAILED_INITIAL_START',
    'bad-resume': 'MISSING_L2_AFTER_FAILED_RESUME',
    'persistent-stopped': 'FAILED_STARTS_NEVER_RECREATE_PLAYER',
}
STOPPED_START_BASELINE_COMMIT = '57b1da44671d8a5b4da6eec2200cd7a2f955403f'
STOPPED_START_BASELINE_SERVICE_SHA256 = '389d1d8cefbd59d114743d9464e85004561f174c4eea4b92a4df5f65b4f66ac5'
ASSET_EPISODE_CASES = ('import-missing', 'import-invalid', 'import-still-invalid', 'coalesced-off-on',
                       'pending-invalid-off-on', 'echo-preserves-block',
                       'surviving-owner-preserves-block', 'off-on-release-pending')
ASSET_EPISODE_NEGATIVES = {
    'import-missing': 'IMPORT_ON_DID_NOT_RETRY_BLOCKED_ASSET',
    'import-invalid': 'IMPORT_ON_DID_NOT_RETRY_BLOCKED_ASSET',
    'import-still-invalid': 'IMPORT_ON_DID_NOT_RETRY_INVALID_ASSET',
    'coalesced-off-on': 'COALESCED_OFF_ON_DID_NOT_RETRY_BLOCKED_ASSET',
}
ASSET_EPISODE_BASELINE_COMMIT = 'bf4eb163ddebded6f414cfd60d8e29968399909e'
ASSET_EPISODE_BASELINE_SERVICE_SHA256 = '0bd5f8bb347d31ff12326bf37b0587c37a2cc5eac3a49d3bf70de647a43b8800'

ASSET_RETRY_CASES = ('available', 'explicit', 'hint', 'echo', 'off-on')
ASSET_RETRY_NEGATIVES = {
    'available': 'NEW_ASSET_RETRY_SIGNAL_LOST_TO_OLD_INVALID_RESULT',
    'explicit': 'NEW_ASSET_RETRY_SIGNAL_LOST_TO_OLD_INVALID_RESULT',
}
ASSET_ADMISSION_CASES = ('pre-admission-available', 'pre-admission-explicit', 'media-reset-parked')
ASSET_ADMISSION_NEGATIVES = {
    'pre-admission-available': 'PRE_ADMISSION_ASSET_SIGNAL_REPLAYED',
    'pre-admission-explicit': 'PRE_ADMISSION_ASSET_SIGNAL_REPLAYED',
}
ASSET_RETRY_BASELINE_COMMIT = 'eb67d07e760380ef363703926318dd40939aba05'
ASSET_RETRY_BASELINE_SERVICE_SHA256 = 'd1e21cc4054c70879451891f53281d0235d5503405ce7f0ed1d2ee244316c6e1'
RETRY_PACING_CASES = ('pre-admission-explicit', 'pre-admission-available',
                      'availability-budget-after-admission', 'stale-explicit-new-available',
                      'new-explicit-old-available', 'new-explicit', 'new-available', 'new-hint')
RETRY_PACING_NEGATIVES = {
    'pre-admission-explicit': 'PRE_ADMISSION_RETRY_SIGNAL_REPLAYED_AFTER_FAILED_START',
    'pre-admission-available': 'PRE_ADMISSION_RETRY_SIGNAL_REPLAYED_AFTER_FAILED_START',
    'availability-budget-after-admission': 'ADMITTED_AVAILABILITY_OPPORTUNITY_REUSED',
    'stale-explicit-new-available': 'STALE_EXPLICIT_PROMOTED_NEW_AVAILABILITY',
}
RETRY_PACING_BASELINE_COMMIT = 'd40120df2a9877c25fc4134e1d3d38a1800bbd45'
RETRY_PACING_BASELINE_SERVICE_SHA256 = 'e826e8a7ea0c1442b53d346ffb4e13452257f76e6a69059ec90b2e91cec52e8e'
INGRESS_PREVIOUS_SERVICE_SHA256 = '90a84615e8c50d470b77711bbacfd30ae2d4b9e89d4bb7b811ab327ba57d8a34'
FINALIZATION_BASELINE_COMMIT = 'eb67d07e760380ef363703926318dd40939aba05'
FINALIZATION_BASELINE_SERVICE_SHA256 = 'd1e21cc4054c70879451891f53281d0235d5503405ce7f0ed1d2ee244316c6e1'
FINALIZATION_PREVIOUS_SERVICE_SHA256 = 'f229417b64aa478259095ea74ee12db13d7262833a283dc497f90f1cc3a4316a'


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


def ingress_previous_admission():
    # Preserve the previously accepted full control input before the retry
    # mailbox gains per-kind identities and admission-time budget consumption.
    source = subprocess.check_output(['git', 'show', RETRY_PACING_BASELINE_COMMIT +
        ':Socks5/BackgroundKeepAlive/LoopAudioService.swift'], cwd=ROOT).decode()
    assert hashlib.sha256(source.encode()).hexdigest() == RETRY_PACING_BASELINE_SERVICE_SHA256
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
    assert hashlib.sha256(source.encode()).hexdigest() == INGRESS_PREVIOUS_SERVICE_SHA256
    return source


def ingress_lease(lease):
    before = '                provider.end(id)\n                state.withValue { $0 = State() }'
    assert lease.count(before) == 1
    return lease.replace(before, before + '\n                IngressObservation.endGateDidClear(id)', 1)


def finalization_previous_source():
    # Preserve the previously accepted historical control byte-for-byte. New
    # independent guards must not mask the older defects this control proves.
    source = subprocess.check_output(['git', 'show', FINALIZATION_BASELINE_COMMIT +
        ':Socks5/BackgroundKeepAlive/LoopAudioService.swift'], cwd=ROOT).decode()
    assert hashlib.sha256(source.encode()).hexdigest() == FINALIZATION_BASELINE_SERVICE_SHA256
    replacements = [
        ('        inbox.explicit = inbox.explicit || (explicit && enabled)',
         '        inbox.explicit = inbox.explicit || explicit'),
        ('        // Owner cleanup preserves any already accepted explicit On signal.',
         '        inbox.explicit = true'),
        ('''                // A first observed stop is not a failed recovery attempt.
                // Start that new episode now; actual failed starts keep pacing.
                if case .inspect = job.command, !episode, reply.error == nil, !reply.invalidAsset,
                   reply.knownFailure != nil || (reply.sample.map {
                       $0.epoch == job.ticket.epoch && (!$0.playing || !$0.configured)
                   } ?? false) {
                    retryAt = returnedAt
                }
''', ''),
        ('''                    do {
                        guard generation < UInt64.max else { throw error("Player generation limit reached") }
                        if player == nil {
                            player = try atStep(.playerCreate, context: context) {
                                try AVAudioPlayer(data: data!, fileTypeHint: "wav")
                            }
                            guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                            atStep(.loops, context: context) { player?.numberOfLoops = -1 }
                        }
                        guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                        // Reusing a stopped player begins a new callback lifetime.
                        generation += 1
                        guard let relay else { preconditionFailure("Audio endpoint relay is missing") }
                        relay.generation(generation)
                        let proxy = DelegateProxy(generation: generation, event: relay.delegate)
                        delegate = proxy
                        atStep(.delegate, context: context) { player?.delegate = proxy }
''',
         '''                    do {
                        if player == nil {
                            guard generation < UInt64.max else { throw error("Player generation limit reached") }
                            player = try atStep(.playerCreate, context: context) {
                                try AVAudioPlayer(data: data!, fileTypeHint: "wav")
                            }
                            generation += 1
                            guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                            atStep(.loops, context: context) { player?.numberOfLoops = -1 }
                            guard context.mayStart() else { discard(context); completion(.init(superseded: true)); return }
                            guard let relay else { preconditionFailure("Audio endpoint relay is missing") }
                            relay.generation(generation)
                            let proxy = DelegateProxy(generation: generation, event: relay.delegate)
                            delegate = proxy
                            atStep(.delegate, context: context) { player?.delegate = proxy }
                        }
'''),
    ]
    for before, after in replacements:
        assert source.count(before) == 1
        source = source.replace(before, after, 1)
    assert hashlib.sha256(source.encode()).hexdigest() == FINALIZATION_PREVIOUS_SERVICE_SHA256
    return source


def finalization_source(source, legacy):
    source = adapter_source(source, legacy)
    observation = '                FinalizationObservation.completed(job.id, returnedAt, retryAt, episode)\n'
    # Observe both the unchanged superseded path and returned unhealthy results.
    for before in (
        '                publish(State(text: Phase.retry.rawValue, detail: "Audio resources changed during recovery"))',
        '                monitor.knownFailure(now: Self.now)\n'
        '                publish(State(text: "Waiting to resume:',
    ):
        assert source.count(before) == 1
        source = source.replace(before, observation + before, 1)
    return source + '\n' + (HERE / 'RecoveryFinalizationAccess.swift.inc').read_text()


def stopped_start_source(source, legacy):
    source = adapter_source(source, legacy)
    # Observe the actual assigned deadline and rebuild decision on both inputs.
    # This callback does not change the service, API outcomes or timer policy.
    before = ('                monitor.knownFailure(now: Self.now)\n'
              '                publish(State(text: "Waiting to resume:')
    assert source.count(before) == 1
    source = source.replace(before,
        '                StoppedStartObservation.failed(job.id, job.command, reply.knownFailure, returnedAt, retryAt, rebuild)\n'
        + before, 1)
    return source + '\n' + (HERE / 'RecoveryFinalizationAccess.swift.inc').read_text()


def asset_retry_source(source, legacy):
    source = asset_episode_source(source, legacy)
    # Hold identical immutable read results in both revisions while a newer
    # retry signal crosses the actual control queue; this changes no outcome.
    before = '                    let bytes = try atStep(.assetRead, context: context) { try Data(contentsOf: url) }'
    assert source.count(before) == 1
    return source.replace(before, before + '\n                    AssetReadObservation.didRead()', 1)


def asset_admission_source(source, legacy):
    source = asset_episode_source(source, legacy)
    # The same external holds separate accepted ingress from its queued drain,
    # and separate start admission from adoption of that accepted ticket.
    before = '        adopt(latest())\n        let command: Command'
    assert source.count(before) == 1
    source = source.replace(before, '        AssetRetryAdmissionObservation.beforeBegin()\n' + before, 1)
    before = '        if schedule { control.async { self.drain() } }'
    assert source.count(before) == 3
    return source.replace(before, '        AssetRetryAdmissionObservation.afterIngressAccepted()\n' + before)


def retry_pacing_source(source, legacy):
    # The same external holds separate accepted ingress from dispatch and start
    # admission. The read-only drain observation sees the assigned deadline;
    # host wake-up latency is never used as an upper-bound timing oracle.
    source = adapter_source(source, legacy)
    before = '        adopt(latest())\n        let command: Command'
    assert source.count(before) == 1
    source = source.replace(before, '        RetrySignalObservation.beforeBegin()\n' + before, 1)
    before = '        if schedule { control.async { self.drain() } }'
    assert source.count(before) == 3
    source = source.replace(before, '        RetrySignalObservation.afterIngressAccepted()\n' + before)
    before = '        if !current.on || overflow {'
    assert source.count(before) == 1
    return source.replace(before, '        RetrySignalObservation.afterDrain(retryAt)\n' + before, 1)


def asset_episode_source(source, legacy):
    # The same read-only queue fence observes both actual source revisions.
    return adapter_source(source, legacy) + '\n' + (HERE / 'RecoveryFinalizationAccess.swift.inc').read_text()


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
    if fixture in ('LeaseLifecycleTests.swift', 'ApplicationProviderBoundaryTests.swift'):
        lease += '\n' + (HERE / 'ApplicationProviderAccess.swift.inc').read_text()
    if fixture == 'ApplicationProviderBoundaryTests.swift':
        # The same copied-input observation counts actual main cleanup jobs in
        # normal and invalid variants. It does not alter queueing or ownership.
        before = '            DispatchQueue.main.async {\n                self.state.withValue { value in'
        assert lease.count(before) == 1
        lease = lease.replace(before, '            DispatchQueue.main.async {\n'
            '                ApplicationProviderBoundaryTests.mainEndJobDequeued()\n'
            '                self.state.withValue { value in', 1)
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
    parser.add_argument('--group', choices=('all', 'service', 'boundary', 'adapter', 'facade', 'finalization', 'precedence', 'stopped-start', 'asset-episode', 'asset-retry', 'retry-pacing'), default='all')
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
                if args.group in ('all', 'adapter', 'retry-pacing'):
                    previous = subprocess.check_output(['git', 'show', RETRY_PACING_BASELINE_COMMIT +
                        ':Socks5/BackgroundKeepAlive/LoopAudioService.swift'], cwd=ROOT).decode()
                    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
                    assert previous_sha == RETRY_PACING_BASELINE_SERVICE_SHA256
                    report['retry_pacing_baseline_commit'] = RETRY_PACING_BASELINE_COMMIT
                    report['retry_pacing_previous_source_sha256'] = previous_sha
                    for legacy in (False, True):
                        label = 'retry-pacing-' + ('legacy-' if legacy else 'async-') + suffix
                        for old in (True, False):
                            if not old and args.negative_only:
                                continue
                            prefix = 'previous-' + label if old else label
                            exe = compile_fixture(folder, prefix,
                                                  retry_pacing_source(previous if old else source, legacy),
                                                  monitor, lease, 'RetrySignalPacingTests.swift', optimize, records,
                                                  mocks='AudioEndpointMocks.swift')
                            for case in RETRY_PACING_CASES:
                                run_checked_cleanup([exe, case, OWNED / 'Silence.wav'], records, prefix + '-' + case,
                                                    expected=RETRY_PACING_NEGATIVES.get(case) if old else None)
                                observed = json.loads(records[-1]['stdout'])
                                if case not in ('new-explicit', 'new-available', 'new-hint'):
                                    assert observed['pre_admission_signal_incorporation_proven'] is True
                    consumed_availability = ('''            // Admission can precede a signal's queued drain. Consume the same
            // one-per-episode availability opportunity at that actual boundary.
            if inbox.available > lastAssetAttempt, inbox.available <= input.assetRetry,
               inbox.explicit <= lastAssetAttempt {
                expedited = true
            }
''')
                    assert source.count(consumed_availability) == 1
                    exe = compile_fixture(folder, 'bad-availability-admission-' + suffix,
                                          retry_pacing_source(source.replace(consumed_availability, '', 1), False),
                                          monitor, lease, 'RetrySignalPacingTests.swift', optimize, records,
                                          mocks='AudioEndpointMocks.swift')
                    run_checked_cleanup([exe, 'availability-budget-after-admission', OWNED / 'Silence.wav'], records,
                                        suffix + '-bad-availability-admission',
                                        expected='ADMITTED_AVAILABILITY_OPPORTUNITY_REUSED')
                if args.group in ('all', 'adapter', 'asset-retry'):
                    previous = subprocess.check_output(['git', 'show', ASSET_RETRY_BASELINE_COMMIT +
                        ':Socks5/BackgroundKeepAlive/LoopAudioService.swift'], cwd=ROOT).decode()
                    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
                    assert previous_sha == ASSET_RETRY_BASELINE_SERVICE_SHA256
                    report['asset_retry_baseline_commit'] = ASSET_RETRY_BASELINE_COMMIT
                    report['asset_retry_previous_source_sha256'] = previous_sha
                    for kind, fixture, translate, cases, negatives in (
                            ('signal', 'AssetRetrySignalTests.swift', asset_retry_source,
                             ASSET_RETRY_CASES, ASSET_RETRY_NEGATIVES),
                            ('admission', 'AssetRetryAdmissionTests.swift', asset_admission_source,
                             ASSET_ADMISSION_CASES, ASSET_ADMISSION_NEGATIVES)):
                        for legacy in (False, True):
                            label = 'asset-retry-' + kind + '-' + ('legacy-' if legacy else 'async-') + suffix
                            for old in (True, False):
                                if not old and args.negative_only:
                                    continue
                                prefix = 'previous-' + label if old else label
                                exe = compile_fixture(folder, prefix,
                                                      translate(previous if old else source, legacy),
                                                      monitor, lease, fixture, optimize, records,
                                                      mocks='AudioEndpointMocks.swift')
                                for case in cases:
                                    run_checked_cleanup([exe, case, OWNED / 'Silence.wav', invalid], records,
                                                        prefix + '-' + case,
                                                        expected=negatives.get(case) if old else None)
                                    observed = json.loads(records[-1]['stdout'])
                                    if kind == 'signal':
                                        assert observed['new_signal_consumed_while_old_read_pending'] is True
                                    elif case != 'media-reset-parked':
                                        assert observed['pre_admission_signal_incorporation_proven'] is True
                if args.group in ('all', 'adapter', 'asset-episode'):
                    previous = subprocess.check_output(['git', 'show', ASSET_EPISODE_BASELINE_COMMIT +
                        ':Socks5/BackgroundKeepAlive/LoopAudioService.swift'], cwd=ROOT).decode()
                    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
                    assert previous_sha == ASSET_EPISODE_BASELINE_SERVICE_SHA256
                    report['asset_episode_baseline_commit'] = ASSET_EPISODE_BASELINE_COMMIT
                    report['asset_episode_previous_source_sha256'] = previous_sha
                    for legacy in (False, True):
                        label = 'asset-episode-' + ('legacy-' if legacy else 'async-') + suffix
                        for old in (False, True):
                            if not old and args.negative_only:
                                continue
                            prefix = 'previous-' + label if old else label
                            exe = compile_fixture(folder, prefix,
                                                  asset_episode_source(previous if old else source, legacy),
                                                  monitor, lease, 'AssetEpisodeRecoveryTests.swift', optimize, records,
                                                  mocks='AudioEndpointMocks.swift')
                            for case in ASSET_EPISODE_CASES:
                                run_checked_cleanup([exe, case, OWNED / 'Silence.wav', invalid], records,
                                                    prefix + '-' + case,
                                                    expected=ASSET_EPISODE_NEGATIVES.get(case) if old else None)
                if args.group in ('all', 'adapter', 'stopped-start'):
                    previous = subprocess.check_output(['git', 'show', STOPPED_START_BASELINE_COMMIT +
                        ':Socks5/BackgroundKeepAlive/LoopAudioService.swift'], cwd=ROOT).decode()
                    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
                    assert previous_sha == STOPPED_START_BASELINE_SERVICE_SHA256
                    report['stopped_start_baseline_commit'] = STOPPED_START_BASELINE_COMMIT
                    report['stopped_start_previous_source_sha256'] = previous_sha
                    for legacy in (False, True):
                        label = 'stopped-start-' + ('legacy-' if legacy else 'async-') + suffix
                        for old in (False, True):
                            if not old and args.negative_only:
                                continue
                            prefix = 'previous-' + label if old else label
                            exe = compile_fixture(folder, prefix,
                                                  stopped_start_source(previous if old else source, legacy),
                                                  monitor, lease, 'StoppedStartRecoveryTests.swift', optimize, records,
                                                  mocks='AudioEndpointMocks.swift')
                            for case in STOPPED_START_CASES:
                                run_checked_cleanup([exe, case, OWNED / 'Silence.wav'], records,
                                                    prefix + '-' + case,
                                                    expected=STOPPED_START_NEGATIVES.get(case) if old else None)
                if args.group in ('all', 'adapter', 'precedence'):
                    # The actual pre-fix product, not a synthetic whole-source
                    # "previous" reconstruction. Its identity is fixed and
                    # tested with the same fixture, mocks, compiler and limits.
                    previous = subprocess.check_output(['git', 'show', PRECEDENCE_BASELINE_COMMIT +
                        ':Socks5/BackgroundKeepAlive/LoopAudioService.swift'], cwd=ROOT).decode()
                    previous_sha = hashlib.sha256(previous.encode()).hexdigest()
                    assert previous_sha == PRECEDENCE_BASELINE_SERVICE_SHA256
                    report['precedence_baseline_commit'] = PRECEDENCE_BASELINE_COMMIT
                    report['precedence_previous_source_sha256'] = previous_sha
                    for legacy in (False, True):
                        label = 'precedence-' + ('legacy-' if legacy else 'async-') + suffix
                        for old in (False, True):
                            if not old and args.negative_only:
                                continue
                            prefix = 'previous-' + label if old else label
                            exe = compile_fixture(folder, prefix, adapter_source(previous if old else source, legacy),
                                                  monitor, lease, 'KnownFailurePrecedenceTests.swift', optimize, records,
                                                  mocks='AudioEndpointMocks.swift')
                            for case in PRECEDENCE_CASES:
                                expected = ('KNOWN_FAILURE_NOT_ADMITTED_BEFORE_UNNECESSARY_GETTER'
                                            if old and case != 'healthy-progress-preserved' else None)
                                run_checked_cleanup([exe, case, OWNED / 'Silence.wav'], records,
                                                    prefix + '-' + case, expected=expected)
                if args.group in ('all', 'finalization'):
                    previous = finalization_previous_source()
                    report['finalization_baseline_commit'] = FINALIZATION_BASELINE_COMMIT
                    report['finalization_baseline_service_sha256'] = FINALIZATION_BASELINE_SERVICE_SHA256
                    report['finalization_previous_source_sha256'] = hashlib.sha256(previous.encode()).hexdigest()
                    for legacy in (False, True):
                        label = 'finalization-' + ('legacy-' if legacy else 'async-') + suffix
                        cases = FINALIZATION_ADAPTER_CASES + (() if legacy else FINALIZATION_SERVICE_CASES)
                        if not args.negative_only:
                            exe = compile_fixture(folder, label, finalization_source(source, legacy), monitor, lease,
                                                  'RecoveryFinalizationTests.swift', optimize, records,
                                                  mocks='AudioEndpointMocks.swift')
                            for case in cases:
                                run_checked_cleanup([exe, case, OWNED / 'Silence.wav', invalid], records, label + '-' + case)
                        exe = compile_fixture(folder, 'previous-' + label, finalization_source(previous, legacy), monitor, lease,
                                              'RecoveryFinalizationTests.swift', optimize, records,
                                              mocks='AudioEndpointMocks.swift')
                        for case in cases:
                            run_checked_cleanup([exe, case, OWNED / 'Silence.wav', invalid], records,
                                                'previous-' + label + '-' + case,
                                                expected=FINALIZATION_NEGATIVES.get(case))
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
                    exe = compile_fixture(folder, 'application-provider-' + suffix, source, monitor, lease,
                                          'ApplicationProviderBoundaryTests.swift', optimize, records)
                    for case in APPLICATION_PROVIDER_CASES:
                        run([exe, case], records, suffix + '-application-provider-' + case)
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
                    report['ingress_baseline_commit'] = RETRY_PACING_BASELINE_COMMIT
                    report['ingress_baseline_service_sha256'] = RETRY_PACING_BASELINE_SERVICE_SHA256
                    report['ingress_previous_source_sha256'] = INGRESS_PREVIOUS_SERVICE_SHA256
                    exe = compile_fixture(folder, 'previous-ingress-' + suffix,
                                          ingress_source(ingress_previous_admission()), monitor,
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
                    denial_receipt = ('                        // A denied assertion may report only expired=true. Settle\n'
                                      '                        // that no-grant receipt so the shared gate can admit again.\n'
                                      '                        // Existing receipt/identity gates ignore it after a grant.\n'
                                      '                        receipt(nil)\n')
                    assert lease.count(denial_receipt) == 1
                    exe = compile_fixture(folder, 'bad-extension-denial-' + suffix, source, monitor,
                                          lease.replace(denial_receipt, '', 1), 'LeaseLifecycleTests.swift', optimize, records)
                    run_checked_cleanup([exe, 'extension-denial'], records, suffix + '-bad-extension-denial',
                                        expected='EXTENSION_DENIAL_BLOCKED_FUTURE_CLAIM')
                    assert records[-1]['stderr'] == 'EXTENSION_DENIAL_BLOCKED_FUTURE_CLAIM\n', records[-1]
                    application_variants = [
                        ('expiry-end-deferred',
                         '            if action == 1 { finish(request) }',
                         '            if action == 1 { DispatchQueue.main.async { self.finish(request) } }',
                         'APPLICATION_EXPIRY_RETURNED_BEFORE_ACTUAL_END'),
                        ('continuation-before-begin',
                         '                holder.request(allowed: allowed, expire: expire, receipt: receipt, returned: returned)',
                         '                returned()\n'
                         '                holder.request(allowed: allowed, expire: expire, receipt: receipt, returned: returned)',
                         'APPLICATION_CONTINUATION_BEFORE_BEGIN_RETURN'),
                        ('queued-off-still-begins',
                         '            guard allowed() else {',
                         '            guard request.id > 0 else {',
                         'APPLICATION_QUEUED_OFF_ISSUED_PLATFORM_BEGIN'),
                        ('early-expiry-loses-id',
                         '                if value.ended { return true }',
                         '                if value.ended { return false }',
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
                    application_issue = '                holder.request(allowed: allowed, expire: expire, receipt: receipt, returned: returned)'
                    assert lease.count(application_issue) == 1
                    old_main_issue = lease.replace(application_issue,
                        '                DispatchQueue.main.async {\n' + application_issue + '\n                }', 1)
                    exe = compile_fixture(folder, 'bad-application-main-hop-' + suffix, source + admission, monitor,
                                          old_main_issue, 'RecoveryBoundaryTests.swift', optimize, records)
                    run([exe, 'lease-main-issued'], records, suffix + '-bad-application-main-hop',
                        expected='APPLICATION_BEGIN_WAITED_FOR_MAIN')
                    provider_variants = [
                        ('unknown-expiry-deferred',
                         '                    value.expiryNotified = true\n                    return 2',
                         '                    return 0',
                         'worker-expiry-before-return', 'APPLICATION_UNKNOWN_ID_EXPIRY_WAITED_FOR_BEGIN'),
                        ('worker-early-end-skipped',
                         '                    DispatchQueue.main.async { self.finish(request) }',
                         '                    receipt(id == nil ? nil : request.id)\n                    returned()',
                         'worker-expiry-before-return', 'APPLICATION_EARLY_EXPIRY_CONTINUATION_PRECEDED_END'),
                        ('end-releases-ownership-early',
                         '            if let id = action.1 { platformEnd(id) }',
                         '            state.withValue { $0.current = nil }\n            if let id = action.1 { platformEnd(id) }',
                         'reentrant-end', 'APPLICATION_END_RELEASED_CLAIM_EARLY'),
                        ('reentrant-end-duplicates',
                         '                guard value.received, !value.ending else { return (false, nil, nil) }',
                         '                guard value.received else { return (false, nil, nil) }',
                         'reentrant-end', 'APPLICATION_DUPLICATE_END_IN_FLIGHT'),
                        ('late-receipt-ignores-identity',
                         'guard let request = value.current, request.id == id, value.queuedEnd == nil else',
                         'guard let request = value.current, value.queuedEnd == nil else',
                         'expiry-before-receipt', 'APPLICATION_LATE_RECEIPT_ENDED_REUSED_RAW_ID'),
                        ('queued-end-admission-ignored',
                         'guard value.current == nil, value.queuedEnd == nil, value.sequence < Int.max else',
                         'guard value.current == nil, value.sequence < Int.max else',
                         'queued-end-bound', 'APPLICATION_QUEUED_END_ADMITTED_ANOTHER_CLAIM'),
                        ('duplicate-end-reservation',
                         'guard let request = value.current, request.id == id, value.queuedEnd == nil else',
                         'guard let request = value.current, request.id == id else',
                         'queued-end-bound', 'APPLICATION_DUPLICATE_END_JOB_QUEUED'),
                        ('settled-completion-retained',
                         '                if value.ended { return true }\n                value.completion = nil',
                         '                if value.ended { return true }\n                // Invalid variant: retain a delivered issue completion.',
                         'settled-lifetime', 'APPLICATION_SETTLED_CALLBACK_RETAINED_LEASE'),
                    ]
                    for label, before, after, case, expected in provider_variants:
                        assert lease.count(before) == 1, label
                        exe = compile_fixture(folder, 'bad-' + label + '-' + suffix, source, monitor,
                                              lease.replace(before, after, 1), 'ApplicationProviderBoundaryTests.swift',
                                              optimize, records)
                        run([exe, case], records, suffix + '-bad-' + label, expected=expected)
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
