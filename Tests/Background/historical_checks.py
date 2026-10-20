#!/usr/bin/env python3
"""Retain old tests against their exact old implementation, never the new facade.

This local-only disposable Git worktree executes no build, archive or remote action.
Its evidence is labeled historical. Current-service tests run in separate drivers.
"""
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

if not __debug__:
    raise SystemExit('Assertions must be enabled.')

ROOT = Path(__file__).resolve().parents[2]
BASE = '618b3d2b413937aaad7373ee2af9e693ec81b84a'
ENTRIES = {'run_checks.py', 'check_async_session.py', 'check_interruption_policy.py',
           'check_subscription.py', 'check_live_scheduling.py', 'check_mixed_notifications.py',
           'check_final_recovery.py', 'check_session_ownership.py'}


def run_historical(entry, arguments=()):
    assert entry in ENTRIES
    source = subprocess.check_output(['git', '-C', str(ROOT), 'show', BASE + ':Tests/Background/' + entry])
    directory = ROOT / 'artifacts/background-historical'
    directory.mkdir(parents=True, exist_ok=True)
    label = Path(entry).stem + ('-' + '-'.join(arguments) if arguments else '')
    print('HISTORICAL BASELINE ONLY:', BASE, entry, *arguments, flush=True)
    with tempfile.TemporaryDirectory(prefix='background-history-') as temporary:
        checkout = Path(temporary) / 'source'
        subprocess.run(['git', '-C', str(ROOT), 'worktree', 'add', '-q', '--detach', str(checkout), BASE], check=True)
        try:
            assert (checkout / 'Tests/Background' / entry).read_bytes() == source
            result = subprocess.run([sys.executable, str(checkout / 'Tests/Background' / entry), *arguments],
                                    cwd=checkout, capture_output=True, text=True)
            (directory / (label + '.log')).write_text(result.stdout + result.stderr)
            (directory / (label + '.json')).write_text(json.dumps({
                'historical_commit': BASE, 'entry': entry, 'arguments': list(arguments),
                'entry_sha256': hashlib.sha256(source).hexdigest(), 'exit': result.returncode,
                'scope': 'Exact historical controller and retained negative controls; no current-code or Apple playback claim.'
            }, indent=2) + '\n')
            print(result.stdout, end='', flush=True)
            if result.stderr: print(result.stderr, end='', file=sys.stderr, flush=True)
            result.check_returncode()
        finally:
            had_original_error = sys.exc_info()[0] is not None
            try:
                failure = checkout / 'artifacts/audio-checks/async-session-failure'
                if failure.is_dir():
                    if failure.is_symlink() or any(path.is_symlink() for path in failure.rglob('*')):
                        raise RuntimeError('Unexpected symlink in historical failure evidence')
                    destination = directory / (label + '-failure-' + checkout.parent.name)
                    shutil.copytree(failure, destination)
                    (destination / 'historical-provenance.json').write_text(json.dumps({
                        'historical_commit': BASE, 'entry': entry, 'arguments': list(arguments),
                        'entry_sha256': hashlib.sha256(source).hexdigest(),
                        'source_relative_path': 'artifacts/audio-checks/async-session-failure',
                        'scope': 'Generated historical failure evidence copied before disposable checkout cleanup; no current-code pass claim.'
                    }, indent=2) + '\n')
                    print('PRESERVED HISTORICAL FAILURE EVIDENCE:', destination, flush=True)
            except Exception as preservation_error:
                print('FAILED TO PRESERVE HISTORICAL FAILURE EVIDENCE:', repr(preservation_error),
                      file=sys.stderr, flush=True)
                if not had_original_error:
                    raise
            finally:
                subprocess.run(['git', '-C', str(ROOT), 'worktree', 'remove', '--force', str(checkout)], check=True)
    print('PASS HISTORICAL BASELINE ONLY:', entry, flush=True)
