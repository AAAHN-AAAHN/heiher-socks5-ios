#!/usr/bin/env python3
"""Restore one failed historical fixture and record a fixed diagnostic plan.

The original failed executable is preserved, never executed. Two fresh binaries
use the original Swift5/-warnings-as-errors/-O command and90-second compile cap.
One uninstrumented trial and three instrumented trials each keep the original
30-second process cap and all fixture predicates/deadlines. No candidate gate,
publication, product selection, test-until-success loop, or source mutation runs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': sha(raw), 'mode': stat.S_IMODE(path.stat().st_mode)}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def copy_exact(source, target):
    require(not source.is_symlink() and source.is_file(), 'Missing or linked source evidence')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(source.read_bytes())
    target.chmod(stat.S_IMODE(source.stat().st_mode))
    require(record(source) == record(target), 'Copied evidence bytes or mode differ')


def git(helper, *args):
    return subprocess.check_output(['git', '-C', str(helper), *args])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def api(repository, path):
    token = os.environ.get('GH_TOKEN')
    require(bool(token), 'The read-only GitHub token is unavailable')
    request = urllib.request.Request('https://api.github.com/repos/' + repository + path,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28'})
    return urllib.request.build_opener(NoRedirect).open(request, timeout=30)


def api_json(repository, path, output):
    started = utc()
    try:
        with api(repository, path) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        require(len(raw) <= 4 * 1024 * 1024, 'Unexpectedly large GitHub metadata response')
    except urllib.error.HTTPError as error:
        raise RuntimeError('GitHub metadata GET failed with HTTP ' + str(error.code)) from None
    except urllib.error.URLError:
        raise RuntimeError('GitHub metadata GET transport failed') from None
    data = json.loads(raw)
    with output.open('xb') as stream:
        stream.write(raw)
    save(output.with_suffix('.receipt.json'), {
        'url': 'https://api.github.com/repos/' + repository + path,
        'started_utc': started, 'finished_utc': utc(), **record(output),
        'raw_http_response_bytes_preserved': True})
    return data


def download(repository, artifact, destination):
    # Signed redirect URLs are used only in memory and never saved or printed.
    try:
        response = api(repository, f"/actions/artifacts/{artifact['id']}/zip")
    except urllib.error.HTTPError as error:
        require(error.code in (301, 302, 303, 307, 308), 'Artifact download API did not redirect successfully')
        location = error.headers.get('Location', '')
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                and any(parsed.hostname.endswith(suffix) for suffix in ('.blob.core.windows.net', '.githubusercontent.com')),
                'Unexpected artifact storage host')
        try:
            response = urllib.request.build_opener(NoRedirect).open(location, timeout=60)
        except Exception:
            raise RuntimeError('Signed artifact storage request failed; transport URL omitted') from None
    except urllib.error.URLError:
        raise RuntimeError('Artifact download API transport failed') from None
    try:
        with response, destination.open('xb') as stream:
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                require(total <= artifact['size_in_bytes'], 'Artifact download exceeds the pinned size')
                stream.write(chunk)
    except Exception as error:
        # Never expose exception arguments that could contain a signed location.
        raise RuntimeError('Artifact transfer failed (' + type(error).__name__ + '); transport URL omitted') from None
    actual = record(destination)
    require(actual['bytes'] == artifact['size_in_bytes'] and 'sha256:' + actual['sha256'] == artifact['digest'],
            'Downloaded artifact exact size or digest differs')
    return actual


def stop_group(process, receipt):
    cleanup_started = time.monotonic()
    receipt.update({'signal': 'SIGKILL', 'signal_sent': False,
                    'cleanup_started_monotonic': cleanup_started, 'reap_timeout_seconds': 10})
    if process.poll() is None:
        try:
            receipt['signal_requested_monotonic'] = time.monotonic()
            os.killpg(process.pid, signal.SIGKILL)
            receipt['signal_sent'] = True
        except ProcessLookupError:
            receipt['group_already_exited_before_signal'] = True
    receipt['reap_started_monotonic'] = time.monotonic()
    try:
        process.wait(timeout=10)
    finally:
        receipt['reap_finished_monotonic'] = time.monotonic()
        receipt['reap_elapsed_monotonic_seconds'] = receipt['reap_finished_monotonic'] - receipt['reap_started_monotonic']
        receipt['cleanup_elapsed_monotonic_seconds'] = receipt['reap_finished_monotonic'] - cleanup_started


class Commands:
    def __init__(self, output):
        self.output = output
        self.records = []

    def run(self, argv, directory, label, timeout):
        directory.mkdir(parents=True, exist_ok=True)
        stdout, stderr = directory / 'stdout.log', directory / 'stderr.log'
        started, monotonic = utc(), time.monotonic()
        pid, code, error, timed_out = None, None, None, False
        wait_started, timeout_detected, termination = None, None, None
        with stdout.open('xb') as out, stderr.open('xb') as err:
            try:
                child_env = {key: value for key, value in os.environ.items()
                             if key not in ('GH_TOKEN', 'GITHUB_TOKEN')}
                process = subprocess.Popen([str(arg) for arg in argv], cwd=directory,
                    stdout=out, stderr=err, start_new_session=True, env=child_env)
                pid = process.pid
                try:
                    wait_started = time.monotonic()
                    code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    timeout_detected = time.monotonic()
                    termination = {}
                    stop_group(process, termination)
                    code = process.returncode
            except Exception as exc:
                error = {'type': type(exc).__name__, 'message': str(exc)}
        item = {'label': label, 'argv': [str(arg) for arg in argv], 'cwd': str(directory),
                'started_utc': started, 'finished_utc': utc(), 'elapsed_monotonic_seconds': time.monotonic() - monotonic,
                'timeout_seconds': timeout, 'process_wait_started_monotonic': wait_started,
                'process_wait_deadline_monotonic': wait_started + timeout if wait_started is not None else None,
                'timeout_detected_monotonic': timeout_detected,
                'termination_policy': 'Immediate process-group SIGKILL on timeout, then bounded reap; no extra execution grace',
                'termination': termination,
                'timed_out': timed_out, 'pid': pid, 'returncode': code, 'error': error,
                'stdout': {'path': str(stdout.relative_to(self.output)), **record(stdout)},
                'stderr': {'path': str(stderr.relative_to(self.output)), **record(stderr)},
                'command_succeeded': code == 0 and not timed_out and error is None}
        self.records.append(item)
        with (self.output / 'commands.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(item) + '\n')
        return item


def json_values(text):
    """Apple IPS may contain a metadata JSON object followed by a second object."""
    values, position, decoder = [], 0, json.JSONDecoder()
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        try:
            value, position = decoder.raw_decode(text, position)
        except ValueError:
            break
        values.append(value)
    return values


def collect_ips(output, executables, trials, seen, diagnostic_started_epoch):
    """Snapshot immediately; no waiting for crash reports and no invented report."""
    reports = Path.home() / 'Library/Logs/DiagnosticReports'
    collected = []
    for path in sorted(reports.glob('test-True*.ips')):
        if not path.is_file() or path.is_symlink():
            continue
        modified_epoch = path.stat().st_mtime
        if modified_epoch < diagnostic_started_epoch:
            continue
        raw = path.read_bytes()
        text = raw.decode(errors='replace')
        matched = [str(exe) for exe in executables if str(exe) in text or str(exe.resolve()) in text]
        if not matched:
            continue
        digest = sha(raw)
        if digest in seen:
            continue
        seen.add(digest)
        pids = {value['pid'] for value in json_values(text)
                if isinstance(value, dict) and isinstance(value.get('pid'), int)}
        time_checks = []
        attributed = []
        for trial in trials:
            execution = trial.get('execution') or {}
            if execution.get('pid') in pids:
                trial_started_epoch = datetime.fromisoformat(execution['started_utc']).timestamp()
                time_matches = modified_epoch >= trial_started_epoch
                time_checks.append({'trial_number': trial['number'], 'pid': execution['pid'],
                                    'trial_started_utc': execution['started_utc'],
                                    'report_mtime_at_or_after_trial_start': time_matches})
                if time_matches:
                    attributed.append(trial['number'])
        target = output / 'crash-reports' / (digest + '-' + path.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        collected.append({'path': str(target.relative_to(output)), **record(target),
                          'source_basename': path.name, 'observed_utc': utc(),
                          'matching_diagnostic_executable_paths': matched,
                          'diagnostic_started_unix_seconds': diagnostic_started_epoch,
                          'source_report_mtime_unix_seconds': modified_epoch,
                          'source_report_mtime_utc': datetime.fromtimestamp(modified_epoch, timezone.utc).isoformat(),
                          'report_mtime_at_or_after_diagnostic_start': True,
                          'trial_time_attribution_checks': time_checks,
                          'parsed_pids': sorted(pids), 'attributed_trial_numbers_by_pid': attributed,
                          'attribution': 'PID_TIME_AND_DIAGNOSTIC_PATH_MATCH' if len(attributed) == 1 else 'DIAGNOSTIC_PATH_MATCH_ONLY_UNATTRIBUTED',
                          'no_wait_for_report': True})
    return collected


def restore(helper, pins, output):
    repository = pins['repository']
    meta = output / 'origin-api'
    meta.mkdir()
    run = api_json(repository, f"/actions/runs/{pins['origin_run_id']}/attempts/{pins['origin_attempt']}", meta / 'run-attempt.json')
    job = api_json(repository, f"/actions/jobs/{pins['origin_producer_job_id']}", meta / 'failed-producer-job.json')
    origin_helper = api_json(repository, '/git/commits/' + pins['origin_helper']['commit'], meta / 'helper-commit.json')
    artifact = api_json(repository, f"/actions/artifacts/{pins['artifact']['id']}", meta / 'artifact.json')
    require(run['id'] == pins['origin_run_id'] and run['run_attempt'] == pins['origin_attempt']
            and run['head_sha'] == pins['origin_helper']['commit'] and run['path'] == pins['origin_workflow_path'],
            'Pinned origin run attempt identity differs')
    require(origin_helper['sha'] == pins['origin_helper']['commit'] and origin_helper['tree']['sha'] == pins['origin_helper']['tree'],
            'Pinned origin helper tree differs')
    require(job['id'] == pins['origin_producer_job_id'] and job['run_id'] == pins['origin_run_id']
            and job['run_attempt'] == pins['origin_attempt'] and job['head_sha'] == pins['origin_helper']['commit']
            and job['name'] == pins['origin_producer_job_name'] and job['status'] == 'completed' and job['conclusion'] == 'failure',
            'Pinned producer must remain an actual failed historical producer')
    required_steps = {'Execute the exact candidate owner gates': 'failure',
                      'Build exact Apple products for the audited owner': 'skipped',
                      'Preserve exact generated native products': 'skipped',
                      'Package source-bound inputs for a fresh macOS runtime': 'skipped',
                      'Record immutable tested source': 'success'}
    for name, outcome in required_steps.items():
        steps = [step for step in job['steps'] if step['name'] == name]
        require(len(steps) == 1 and steps[0]['status'] == 'completed' and steps[0]['conclusion'] == outcome,
                'Pinned producer step identity/outcome differs: ' + name)
    require(all(artifact[key] == pins['artifact'][key] for key in ('id', 'name', 'size_in_bytes', 'digest'))
            and artifact['expired'] is False and artifact['workflow_run']['id'] == pins['origin_run_id']
            and artifact['workflow_run']['head_sha'] == pins['origin_helper']['commit'],
            'Pinned failed-producer artifact identity differs')
    archive_path = output / 'historical-failed-producer-13073983955.zip'
    downloaded = download(repository, pins['artifact'], archive_path)
    original = output / 'original-failed-fixture'
    original.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and len(names) == pins['archive_member_count'], 'Unexpected original archive inventory')
        require(archive.testzip() is None, 'Original archive CRC failure')
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            require(not name.is_absolute() and '..' not in name.parts and '\\' not in info.filename
                    and name.as_posix() == info.filename.rstrip('/'), 'Unsafe original archive path')
            kind = stat.S_IFMT(info.external_attr >> 16)
            require(kind in (0, stat.S_IFREG, stat.S_IFDIR), 'Unexpected linked or special original archive member')
        require(archive.read('candidate-prepare/tested-commit.txt').decode().strip() == pins['origin_candidate_source'],
                'Candidate source identity differs in historical producer')
        prepared = json.loads(archive.read('candidate-prepare/result.json'))
        require(prepared['helper_commit'] == pins['origin_helper']['commit'] and
                prepared['candidates'] == [{'name': 'integrated', 'sha': pins['origin_candidate_source'],
                                           'ref': 'refs/heads/work/udp-echo-integrated-20261028'}],
                'Historical candidate preparation identity differs')
        for item in pins['members']:
            raw = archive.read(item['member'])
            require(len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'Pinned historical fixture/member differs')
            require(archive.getinfo(item['member']).external_attr >> 16 == item['zip_external_mode'],
                    'Pinned historical fixture ZIP mode differs')
            target = original / item['saved_name']
            with target.open('xb') as stream:
                stream.write(raw)
            target.chmod(stat.S_IMODE(item['zip_external_mode']))
        failure = json.loads((original / 'failure.json').read_bytes())
        require(failure['commit'] == pins['historical_commit'] and failure['label'] == 'legacy-worker'
                and failure['optimized'] is True and failure['returncode'] == -5,
                'Original failure must remain the unexpected optimized legacy-worker SIGTRAP')
        for name, digest in failure['fixture_sha256'].items():
            require(sha((original / name).read_bytes()) == digest, 'Original failure receipt fixture hash differs')
        provenance = json.loads((original / 'historical-provenance.json').read_bytes())
        require(provenance['historical_commit'] == pins['historical_commit']
                and provenance['entry'] == 'check_async_session.py'
                and provenance['entry_sha256'] == pins['historical_entry_sha256'], 'Historical controller provenance differs')
    save(output / 'input-verification.json', {
        'status': 'VERIFIED_FAILED_HISTORICAL_FIXTURE_FOR_DIAGNOSTIC_ONLY',
        'origin_run_id': pins['origin_run_id'], 'origin_attempt': pins['origin_attempt'],
        'origin_failed_producer_job_id': pins['origin_producer_job_id'],
        'origin_helper': pins['origin_helper'], 'candidate_source': pins['origin_candidate_source'],
        'historical_controller_commit': pins['historical_commit'],
        'raw_artifact': {'artifact_id': pins['artifact']['id'], 'path': archive_path.name, **downloaded},
        'original_member_count': pins['archive_member_count'], 'all_original_crc_checked': True,
        'original_fixture': {path.name: record(path) for path in sorted(original.iterdir())},
        'original_failed_binary_execution_count': 0, 'candidate_execution': False,
        'canonical_execution': False, 'selected_product': False})
    return original


def verify_instrumentation(original, folder, receipt_path, pins):
    receipt = json.loads(receipt_path.read_bytes())
    require(receipt['schema'] == 2 and len(receipt['operations']) == pins['instrumentation']['insertion_blocks'],
            'Instrumentation recipe generation differs')
    for name in ('Controller.swift', 'PlatformMocks.swift'):
        require((folder / name).read_bytes() == (original / name).read_bytes(), 'Controller or platform mocks changed')
    current = (folder / 'Test.swift').read_bytes()
    require(sha(current) == pins['instrumentation']['after_test_sha256'], 'Instrumented test bytes differ')
    restored = current.decode()
    for operation in reversed(receipt['operations']):
        block = operation['inserted_block']
        require(operation['occurrences'] == 1 and restored.count(block) == 1
                and sha(block.encode()) == operation['inserted_block_sha256'], 'Instrumentation restoration ledger differs')
        restored = restored.replace(block, '')
    require(restored.encode() == (original / 'Test.swift').read_bytes(), 'Removing only insertions does not restore original bytes')
    return {'receipt': str(receipt_path), **record(receipt_path),
            'actual_removed_insertion_blocks': len(receipt['operations']),
            'restored_original_test_sha256': sha(restored.encode()), 'originals_preserved': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--pins', type=Path, required=True)
    parser.add_argument('--patcher', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(__debug__, 'Assertions must be enabled')
    helper, output = args.helper.resolve(strict=True), args.output.resolve()
    require(output != helper and not output.is_relative_to(helper), 'Diagnostic output must be outside the helper checkout')
    require(not output.exists(), 'Refusing to overwrite earlier diagnostic evidence')
    output.mkdir(parents=True)
    diagnostic_started_epoch = time.time()
    commands = Commands(output)
    result = {'schema': 1, 'status': 'DIAGNOSTIC_PLAN_NOT_FINISHED', 'candidate_execution': False,
              'canonical_execution': False, 'selected_product': False, 'original_failed_binary_executed': False,
              'retry_until_success': False, 'compile_cap_seconds_each': 90,
              'execution_cap_seconds_each': 30, 'original_transition_deadline_seconds': 2,
              'scope': 'Historical positive legacy-worker fixture only; neither an expected-negative waiver nor current product/candidate acceptance.',
              'plan': [{'number': 1, 'variant': 'uninstrumented'},
                       {'number': 2, 'variant': 'instrumented'}, {'number': 3, 'variant': 'instrumented'},
                       {'number': 4, 'variant': 'instrumented'}],
              'compilations': [], 'trials': [], 'crash_reports': [], 'errors': []}
    executables, ips_seen, original, originals_before, recipe_before = [], set(), None, {}, {}

    def snapshot_crash_reports():
        try:
            result['crash_reports'].extend(collect_ips(output, executables, result['trials'], ips_seen, diagnostic_started_epoch))
        except Exception as error:
            result['errors'].append({'type': type(error).__name__, 'message': 'Crash-report snapshot failed; fixed remaining trials are not cancelled'})

    try:
        pins = json.loads(args.pins.read_bytes())
        require(os.environ.get('GITHUB_REPOSITORY') == pins['repository'] and os.environ.get('RUNNER_OS') == 'macOS'
                and os.environ.get('GITHUB_JOB') == 'diagnose_legacy_worker_only', 'Unexpected actual diagnostic execution identity')
        current_sha = os.environ.get('GITHUB_SHA', '')
        require(re.fullmatch('[0-9a-f]{40}', current_sha) and git(helper, 'rev-parse', 'HEAD').decode().strip() == current_sha,
                'Actual diagnostic helper checkout differs from GITHUB_SHA')
        require(int(os.environ['GITHUB_RUN_ID']) != pins['origin_run_id'], 'Diagnostic must not impersonate the failed historical run')
        recipe = output / 'recipe'
        recipe.mkdir()
        for relative in pins['helper_recipe_paths']:
            source = helper / relative
            require(source.resolve(strict=True).is_relative_to(helper) and not source.is_symlink(), 'Unexpected helper recipe path')
            raw = source.read_bytes()
            require(raw == git(helper, 'show', 'HEAD:' + relative), 'Uncommitted helper recipe bytes differ')
            copy_exact(source, recipe / Path(relative).name)
            recipe_before[relative] = record(source)
        require(args.patcher.resolve() == (helper / pins['instrumentation']['helper_path']).resolve(), 'Wrong diagnostic patcher path')
        require(sha(args.patcher.read_bytes()) == pins['instrumentation']['patcher_sha256'], 'Diagnostic patcher bytes differ')
        require(args.pins.resolve() == (helper / 'Bootstrap/legacy-worker-diagnostic/historical-fixture-pins.json').resolve(), 'Wrong fixture pins path')
        require(Path(__file__).resolve() == (helper / 'Bootstrap/legacy-worker-diagnostic/run_legacy_worker_diagnostic.py').resolve(), 'Unexpected runner recipe path')
        context = {'repository': pins['repository'], 'run_id': int(os.environ['GITHUB_RUN_ID']),
                   'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']), 'job': os.environ['GITHUB_JOB'],
                   'helper': {'commit': current_sha, 'tree': git(helper, 'rev-parse', 'HEAD^{tree}').decode().strip()},
                   'recorded_utc': utc(), 'historical_origin_run_id': pins['origin_run_id'],
                   'recipe': recipe_before, 'source_product_and_candidate_gate_execution': False}
        save(output / 'diagnostic-context.json', context)
        result['diagnostic_context'] = context
        original = restore(helper, pins, output)
        originals_before = {path.name: record(path) for path in original.iterdir()}
        for label, argv in [('swift-version', ['swiftc', '--version']), ('xcode-version', ['xcodebuild', '-version'])]:
            capture = commands.run(argv, output / 'toolchain' / label, label, 30)
            require(capture['command_succeeded'], 'Unable to record actual diagnostic toolchain')
        for variant, numbers in [('uninstrumented', [1]), ('instrumented', [2, 3, 4])]:
            folder = output / 'compiled-inputs' / variant
            folder.mkdir(parents=True)
            for name in ('Controller.swift', 'PlatformMocks.swift', 'Test.swift'):
                copy_exact(original / name, folder / name)
            if variant == 'instrumented':
                receipt_path = output / 'instrumentation.json'
                patched = commands.run([sys.executable, args.patcher.resolve(), '--fixture', folder, '--receipt', receipt_path],
                                       output / 'patcher-command', 'instrument-temporary-Test-only', 30)
                require(patched['command_succeeded'], 'Diagnostic instrumentation did not complete')
                result['instrumentation_verification'] = verify_instrumentation(original, folder, receipt_path, pins)
            source_before = {name: record(folder / name) for name in ('Controller.swift', 'PlatformMocks.swift', 'Test.swift')}
            executable = folder / 'test-True'
            compile_command = ['swiftc', '-swift-version', '5', '-warnings-as-errors', '-O',
                               folder / 'PlatformMocks.swift', folder / 'Controller.swift', folder / 'Test.swift', '-o', executable]
            compiled = commands.run(compile_command, output / 'compile' / variant, 'compile-' + variant, 90)
            compiled_ok = compiled['command_succeeded'] and executable.is_file() and not executable.is_symlink()
            result['compilations'].append({'variant': variant, 'execution': compiled,
                                           'sources_before': source_before, 'binary': record(executable) if executable.is_file() else None,
                                           'compiled_executable_available': compiled_ok})
            if compiled_ok:
                executables.append(executable)
            for number in numbers:
                trial = {'number': number, 'variant': variant}
                if not compiled_ok:
                    trial.update({'status': 'NOT_RUN_COMPILE_FAILED', 'passed': False, 'execution': None})
                else:
                    execution = commands.run([executable], output / 'trials' / ('trial-' + str(number)), 'trial-' + str(number), 30)
                    stdout = (output / execution['stdout']['path']).read_text(errors='replace')
                    stderr = (output / execution['stderr']['path']).read_text(errors='replace')
                    markers = {text: stdout.count(text) for text in pins['required_stdout_pass_markers']}
                    trace_present = 'LEGACY_WORKER_TRACE ' in stderr
                    final_trace = 'stage=predicate.rejected_activation_inactive.returned ' in stderr
                    passed = execution['command_succeeded'] and all(count == 1 for count in markers.values())
                    if variant == 'instrumented':
                        passed = passed and trace_present and final_trace
                    trial_status = ('NOT_RUN_PROCESS_LAUNCH_FAILURE' if execution['pid'] is None else
                                    'DIAGNOSTIC_TRIAL_PASSED' if passed else 'DIAGNOSTIC_TRIAL_FAILED')
                    trial.update({'status': trial_status,
                                  'passed': passed, 'execution': execution, 'original_stdout_marker_counts': markers,
                                  'trace_prefix_observed': trace_present, 'final_original_predicate_return_trace_observed': final_trace,
                                  'candidate_gate_credit': False})
                result['trials'].append(trial)
                snapshot_crash_reports()
            require(source_before == {name: record(folder / name) for name in source_before}, 'Diagnostic compile or trial changed fixture source bytes')
            if variant == 'instrumented':
                verify_instrumentation(original, folder, output / 'instrumentation.json', pins)
        require(originals_before == {path.name: record(path) for path in original.iterdir()}, 'Original failed fixture evidence changed')
        require(recipe_before == {name: record(helper / name) for name in recipe_before}, 'Diagnostic helper recipe changed')
        require(git(helper, 'rev-parse', 'HEAD').decode().strip() == current_sha, 'Diagnostic helper commit changed')
        for label, argv in [('helper-worktree', ['git', '-C', str(helper), 'diff', '--exit-code', 'HEAD', '--']),
                            ('helper-index', ['git', '-C', str(helper), 'diff', '--cached', '--exit-code', 'HEAD', '--'])]:
            checked = commands.run(argv, output / 'post-run' / label, label, 30)
            require(checked['command_succeeded'], 'Helper tracked files/index changed during diagnosis')
        result['original_fixture_and_helper_preserved_after_plan'] = True
    except Exception as error:
        result['errors'].append({'type': type(error).__name__, 'message': str(error)})
    finally:
        for planned in result['plan']:
            if not any(trial['number'] == planned['number'] for trial in result['trials']):
                result['trials'].append({**planned, 'status': 'NOT_RUN_PREREQUISITE_FAILURE', 'passed': False, 'execution': None})
        result['trials'].sort(key=lambda row: row['number'])
        snapshot_crash_reports()
        passed = not result['errors'] and len(result['compilations']) == 2 and all(trial['passed'] for trial in result['trials'])
        result['status'] = ('DIAGNOSTIC_FIXED_PLAN_PASSED_NOT_CANDIDATE' if passed else
                            'DIAGNOSTIC_FIXED_PLAN_RECORDED_WITH_FAILURES_NOT_CANDIDATE')
        result['finished_utc'] = utc()
        result['commands_recorded'] = len(commands.records)
        result['attempted_trial_count'] = sum(trial['execution'] is not None for trial in result['trials'])
        result['executed_trial_count'] = sum((trial.get('execution') or {}).get('pid') is not None for trial in result['trials'])
        result['crash_report_limit'] = 'Immediate snapshots only; no wait/retry for IPS. No retained IPS does not prove no crash report was later generated. PID/path/report-mtime attribution is explicit; unmatched reports stay unattributed.'
        result['interpretation_limit'] = 'Passing diagnostics do not identify or resolve the earlier unexpected trap; original failure and every fixed trial remain visible. Instrumentation can perturb scheduling.'
        save(output / 'diagnostic-result.json', result)
        print(json.dumps({'status': result['status'], 'executed_trials': result['executed_trial_count'],
                          'diagnostic_only': True, 'original_failure_preserved': original is not None,
                          'candidate_execution': False, 'canonical_execution': False}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
