#!/usr/bin/env python3
"""Add observations to a temporary copy of the exact failed historical fixture.

This is not a product change or replacement gate. Removing recorded insertions
restores every original byte. All original predicates and deadlines stay intact.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path

HISTORICAL_COMMIT = '618b3d2b413937aaad7373ee2af9e693ec81b84a'
ORIGINALS = {
    'Controller.swift': '0595d9f05d35f1f63d5e5b6ab6ce8e7487bf8e96560e10403febce382f34a6ec',
    'PlatformMocks.swift': '59f9aed88294a478bd54c1d5a548a213b2d8c38c37bce6b7d800806d1a678648',
    'Test.swift': '91d5f6acdcbae6a32269cfa42653acf33aba1048b297a4314f68774f9e10519f',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def instrument(original):
    text = original
    operations = []

    def add(label, anchor, inserted, before=False):
        nonlocal text
        require(text.count(anchor) == 1, 'Exact anchor count differs: ' + label)
        require(inserted.endswith('\n'), 'Inserted text lacks final newline')
        indent = inserted[:len(inserted) - len(inserted.lstrip(' '))]
        block = (indent + '// LEGACY_WORKER_DIAGNOSTIC_BEGIN ' + label + '\n' + inserted
                 + indent + '// LEGACY_WORKER_DIAGNOSTIC_END ' + label + '\n')
        require(block not in text, 'Repeated diagnostic block')
        text = text.replace(anchor, block + anchor if before else anchor + block)
        operations.append({'label': label, 'exact_anchor': anchor,
                           'position': 'before' if before else 'after', 'occurrences': 1,
                           'inserted_block': block, 'inserted_block_sha256': sha(block.encode())})

    add('stderr-observer', '        let state = ResultState()\n', r'''        let diagnosticStarted = ProcessInfo.processInfo.systemUptime
        var diagnosticSequence = 0
        func observe(_ stage: String, requested: Bool? = nil, deadline: Date? = nil) {
            diagnosticSequence += 1
            // The main completion follows every worker write. Pending snapshots
            // must not read mock fields while that worker may be mutating them.
            let workerSnapshot: String
            if state.result != nil {
                workerSnapshot = "worker_snapshot=completed active=\(session.isActive) " +
                    "onMain=\(session.synchronousOnMain) calls=\(session.synchronousCalls) " +
                    "activations=\(session.activations) deactivations=\(session.deactivations) " +
                    "rejectActivation=\(session.rejectActivation)"
            } else {
                workerSnapshot = "worker_snapshot=unavailable"
            }
            let detail = "LEGACY_WORKER_TRACE seq=\(diagnosticSequence) stage=\(stage) " +
                "uptime=\(ProcessInfo.processInfo.systemUptime) elapsed=\(ProcessInfo.processInfo.systemUptime - diagnosticStarted) " +
                "requested=\(String(describing: requested)) result=\(String(describing: state.result)) " +
                "beats=\(state.beats) callerMain=\(Thread.isMainThread) " + workerSnapshot +
                " deadlineRemaining=\(String(describing: deadline?.timeIntervalSinceNow))\n"
            // Direct stderr writes avoid relying on buffered stdout at a trap.
            FileHandle.standardError.write(Data(detail.utf8))
        }
        observe("main.initialized")
''')
    add('timer-before-mainactor-assume',
        '            MainActor.assumeIsolated { state.beats += 1 }\n',
        '            FileHandle.standardError.write(Data("LEGACY_WORKER_BOUNDARY stage=timer.before_assume uptime=\\(ProcessInfo.processInfo.systemUptime) threadMain=\\(Thread.isMainThread)\\n".utf8))\n', before=True)
    add('timer-after-mainactor-assume',
        '            MainActor.assumeIsolated { state.beats += 1 }\n',
        '            FileHandle.standardError.write(Data("LEGACY_WORKER_BOUNDARY stage=timer.after_assume uptime=\\(ProcessInfo.processInfo.systemUptime) threadMain=\\(Thread.isMainThread)\\n".utf8))\n')
    add('worker-callback-before-enqueue',
        '                DispatchQueue.main.async { state.result = success }\n',
        '                FileHandle.standardError.write(Data("LEGACY_WORKER_BOUNDARY stage=callback.before_main_enqueue success=\\(success) uptime=\\(ProcessInfo.processInfo.systemUptime) threadMain=\\(Thread.isMainThread)\\n".utf8))\n', before=True)
    add('transition-enter', '        func transition(_ active: Bool) {\n',
        '            observe("transition.enter", requested: active)\n')
    add('transition-before-request', '            state.result = nil\n',
        '            observe("transition.before_request", requested: active)\n')
    add('transition-request-returned',
        '            let limit = Date().addingTimeInterval(2)\n',
        '            observe("transition.request_returned", requested: active, deadline: limit)\n')
    add('transition-before-completion-predicate',
        '            precondition(state.result != nil)\n',
        '            observe("predicate.completion_present", requested: active, deadline: limit)\n', before=True)
    add('transition-completion-predicate-returned',
        '            precondition(state.result != nil)\n',
        '            observe("predicate.completion_present.returned", requested: active, deadline: limit)\n')
    add('on-before-predicate',
        '        precondition(state.result == true && session.isActive && !session.synchronousOnMain && state.beats >= 3)\n',
        '        observe("predicate.on_active_worker_and_main_progress", requested: true)\n', before=True)
    add('on-predicate-returned',
        '        precondition(state.result == true && session.isActive && !session.synchronousOnMain && state.beats >= 3)\n',
        '        observe("predicate.on_active_worker_and_main_progress.returned", requested: true)\n')
    add('off-before-predicate',
        '        precondition(state.result == true && !session.isActive && !session.synchronousOnMain)\n',
        '        observe("predicate.off_inactive_worker", requested: false)\n', before=True)
    add('off-predicate-returned',
        '        precondition(state.result == true && !session.isActive && !session.synchronousOnMain)\n',
        '        observe("predicate.off_inactive_worker.returned", requested: false)\n')
    add('rejection-before-predicate',
        '        precondition(state.result == false && !session.isActive)\n',
        '        observe("predicate.rejected_activation_inactive", requested: true)\n', before=True)
    add('rejection-predicate-returned',
        '        precondition(state.result == false && !session.isActive)\n',
        '        observe("predicate.rejected_activation_inactive.returned", requested: true)\n')
    restored = text
    for op in reversed(operations):
        require(restored.count(op['inserted_block']) == 1, 'Diagnostic block count changed')
        restored = restored.replace(op['inserted_block'], '')
    require(restored == original, 'Original fixture bytes or statement order changed')
    return text, operations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    root = args.fixture.resolve(strict=True)
    receipt = args.receipt.resolve()
    require(not (root / '.git').exists() and '/resume/worktrees/' not in root.as_posix(), 'Refusing to instrument a canonical checkout')
    require(not receipt.exists() and not receipt.with_suffix('.diff').exists(), 'Refusing to replace existing diagnostic evidence')
    originals = {}
    for name, expected in ORIGINALS.items():
        path = root / name
        require(path.is_file() and not path.is_symlink(), 'Fixture is missing or linked: ' + name)
        raw = path.read_bytes()
        require(sha(raw) == expected, 'Exact historical fixture hash differs: ' + name)
        originals[name] = raw
    after, operations = instrument(originals['Test.swift'].decode())
    diff = ''.join(difflib.unified_diff(originals['Test.swift'].decode().splitlines(keepends=True), after.splitlines(keepends=True),
                                      fromfile='original/Test.swift', tofile='diagnostic-only/Test.swift'))
    (root / 'Test.swift').write_text(after)
    for name in ('Controller.swift', 'PlatformMocks.swift'):
        require((root / name).read_bytes() == originals[name], 'A non-test fixture source changed')
    require((root / 'Test.swift').read_bytes() == after.encode(), 'Diagnostic write differs')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.with_suffix('.diff').write_text(diff)
    result = {'schema': 2, 'status': 'EPHEMERAL_HISTORICAL_LEGACY_WORKER_DIAGNOSTIC_ONLY',
        'historical_commit': HISTORICAL_COMMIT, 'fixture': str(root),
        'origin': {'run_id': 41281429043, 'run_attempt': 1, 'artifact_id': 13073983955,
                   'artifact_sha256': '0ac8fd966f88c8066fb8784963a06ddd2e9377fa06879d105c127b4da453859d',
                   'fixture_member_prefix': 'background-historical/check_async_session-failure-background-history-iens6bic/legacy-worker/optimized/'},
        'files': [{'path': name, 'before_bytes': len(originals[name]), 'after_bytes': len((root / name).read_bytes()),
                   'before_sha256': ORIGINALS[name], 'after_sha256': sha((root / name).read_bytes()),
                   'modified': name == 'Test.swift'} for name in ORIGINALS],
        'operations': operations, 'removing_only_recorded_insertions_exactly_restores_original': True,
        'original_predicates_deadlines_statement_order_preserved': True,
        'original_transition_deadline_seconds': 2, 'original_process_cap_seconds_required': 30,
        'original_optimization_required': '-O', 'original_language_required': '-swift-version 5 -warnings-as-errors',
        'logging': {'prefix': 'LEGACY_WORKER_TRACE', 'boundary_prefix': 'LEGACY_WORKER_BOUNDARY',
                    'api': 'Foundation.FileHandle.standardError.write',
                    'scope': 'MainActor test snapshots; pure local/constant Thread and monotonic-time receipts around timer isolation and before worker completion enqueues main delivery',
                    'worker_fields_read_only_after_main_completion': True,
                    'pending_snapshot': 'result nil: worker_snapshot=unavailable; only main-owned state, Thread and clocks read',
                    'timer_boundary': 'No actor-owned state is read before/after the original MainActor.assumeIsolated line',
                    'completion_boundary': 'Only the original success parameter, Thread and monotonic clock are read; no shared mutable worker/test state is read',
                    'no_credentials': True,
                    'limitations': ['Observations can perturb scheduling; a passing diagnostic does not explain an earlier failure.',
                                    'The original completion callback discards its Error argument with underscore. Its signature is unchanged and no error object/presence is directly observed. The unchanged adapter source still maps its thrown error to success=false.']},
        'superseded_local_proposal': {'name': 'instrument_legacy_worker-v1-pending-race-proposal.py',
                                     'sha256': '82839084fecab29cf2c631562a1bce9eccf9379e193731415b4d637cba555d8e',
                                     'reason': 'Review found added reads of mutable mock worker fields before completion; the v1 diagnostic Swift fixture was never compiled or executed.'},
        'diff': {'path': str(receipt.with_suffix('.diff')), 'bytes': len(diff.encode()), 'sha256': sha(diff.encode())},
        'product_or_test_gate_replaced': False}
    receipt.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'receipt': str(receipt), 'bytes': receipt.stat().st_size, 'sha256': sha(receipt.read_bytes()),
                      'insertions': len(operations), 'changed_file': 'Test.swift', 'after_sha256': sha(after.encode())}))


if __name__ == '__main__':
    main()
