#!/usr/bin/env python3
"""Record installed toolchain state without building, booting or repairing it.

Missing components, nonzero status reads and timeouts remain observations. This
diagnostic cannot accept an application, a runtime gate, or a release.
"""
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE_HELPER = 'd76294e376531c1b64be8620447745296d3de4e3'
OBSERVER_SHA256 = '00ebe8f5c800aacacd3c2b5be66a9ad76fde510d7a4555a78304c628b860cac7'
APP_CANDIDATES = (
    ('27.0', '/Applications/Xcode_27.app'),
    ('27.1', '/Applications/Xcode_27.1.app'),
    ('27.2 Release Candidate', '/Applications/Xcode_27.2_Release_Candidate.app'),
)
GLOBAL_FRAMEWORK = Path('/Library/Developer/PrivateFrameworks/CoreSimulator.framework')
FIXED_QUERIES = (
    ('selected-developer', ('/usr/bin/xcode-select', '-p'), 5),
    ('operating-system', ('/usr/bin/sw_vers',), 5),
    ('hardware', ('/usr/sbin/sysctl', 'hw.ncpu', 'hw.memsize', 'hw.machine', 'kern.boottime'), 5),
    ('processes', ('/bin/ps', '-axo', 'pid,ppid,state,etime,%cpu,%mem,comm'), 5),
)
APP_QUERIES = (
    ('version', ('/usr/bin/xcodebuild', '-version'), 10),
    ('first-launch-status', ('/usr/bin/xcodebuild', '-checkFirstLaunchStatus'), 10),
    ('simctl-path', ('/usr/bin/xcrun', '--find', 'simctl'), 5),
    ('simulator-sdk', ('/usr/bin/xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version'), 5),
)
BOOTSTATUS_HELP_QUERY = ('/usr/bin/xcrun', 'simctl', 'help', 'bootstatus')
IDENTITY_ENV = ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB', 'GITHUB_SHA',
                'RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH', 'DEVELOPER_DIR')
PLIST_KEYS = ('CFBundleIdentifier', 'CFBundleVersion', 'CFBundleShortVersionString',
              'ProductBuildVersion', 'ProductVersion', 'DTXcode', 'DTXcodeBuild',
              'BuildMachineOSBuild')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_argv(command, developer_dirs, bootstatus_help_developer=None):
    """Only fixed status queries, with a verified path in a child-only env."""
    command = tuple(command)
    if command in {argv for _, argv, _ in FIXED_QUERIES}:
        return list(command)
    if (len(command) >= 3 and command[0] == '/usr/bin/env'
            and command[1] in {'DEVELOPER_DIR=' + path for path in developer_dirs}
            and command[2:] in {argv for _, argv, _ in APP_QUERIES}):
        return list(command)
    if (bootstatus_help_developer in developer_dirs
            and command == ('/usr/bin/env', 'DEVELOPER_DIR=' + bootstatus_help_developer,
                            *BOOTSTATUS_HELP_QUERY)):
        return list(command)
    raise ValueError('Command is outside the exact read-only argv allowlist: ' + repr(command))


def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Use a new empty diagnostic output directory')
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + 120
    result = {'scope': 'Read-only toolchain observations; no application/runtime/release acceptance.',
              'base_helper': BASE_HELPER, 'started_unix': time.time(), 'query_budget_seconds': 120,
              'identity_environment': {key: os.environ.get(key) for key in IDENTITY_ENV},
              'actual_job_id': None, 'actual_runner_id': None,
              'actual_ID_binding': 'Bind IDs from the actual attempt jobs API; environment does not invent them.',
              'code_inputs': [], 'commands': [], 'files': [], 'installed_apps': [],
              'default_path_observations': {}, 'global_service_observations': [],
              'bootstatus_help_observation': {
                  'requested_app_label': '27.0', 'maximum_invocations': 1,
                  'status': 'SELECTED_APP_UNAVAILABLE_NOT_QUERIED',
                  'interpretation': 'Installed command help only; no device readiness, app acceptance, or proof of private implementation branches.'},
              'source_assertion_timeout_changes': False, 'repair_performed': False,
              'device_lifecycle_performed': False,
              'read_only_scope': 'No requested setup/service/device mutation. Status queries may implicitly load system services; pre/post identities are observations, not a no-start promise.',
              'application_accepted': False,
              'runtime_accepted': False, 'release_accepted': False,
              'limitations': ['Timeout wall time can include scheduling, termination and reap overhead.',
                             'A newer global component is not by itself evidence of a fault.',
                             'An on-disk version/hash does not prove which binary image a resident process loaded.',
                             'A status-only result does not prove Simulator readiness or independent license state.']}
    developer_dirs = set()
    bootstatus_help_developer = None
    failed_queries = []
    observed_run = None

    def file_identity(path):
        data = path.read_bytes()
        return {'file': str(path.relative_to(out)), 'bytes': len(data), 'sha256': sha(data)}

    def inspect_file(label, path, *, limit=2 * 1024 * 1024, plist=False, manual=False, copy=False):
        row = {'label': label, 'path': str(path), 'maximum_bytes': limit}
        result['files'].append(row)
        try:
            row['is_symlink'] = path.is_symlink()
            resolved = path.resolve(strict=True)
            row['realpath'] = str(resolved)
            info = resolved.stat()
            row.update(size=info.st_size, mode=stat.S_IMODE(info.st_mode))
            if not stat.S_ISREG(info.st_mode):
                row['status'] = 'NOT_REGULAR_FILE'
                return row, None
            if info.st_size > limit:
                row['status'] = 'ABOVE_READ_LIMIT_NOT_READ'
                return row, None
            if time.monotonic() >= deadline:
                row['status'] = 'BUDGET_EXHAUSTED_NOT_READ'
                return row, None
            with resolved.open('rb') as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                row['status'] = 'FILE_GREW_ABOVE_READ_LIMIT'
                return row, None
            row.update(status='READ', bytes=len(data), sha256=sha(data))
            if copy:
                destination = out / 'file-inputs' / (label + '.bin')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                row['preserved_raw'] = file_identity(destination)
            if plist:
                parsed = plistlib.loads(data)
                row['selected_plist_values'] = {key: plain(parsed[key]) for key in PLIST_KEYS if key in parsed}
            if manual:
                decoded = data
                if data[:2] == b'\x1f\x8b':
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                        decoded = gz.read(limit + 1)
                    if len(decoded) > limit:
                        row['manual_status'] = 'DECOMPRESSED_TEXT_ABOVE_LIMIT'
                        return row, data
                text = decoded.decode('utf-8', errors='replace')
                offsets = [match.start() for match in re.finditer('checkFirstLaunchStatus', text)]
                row['manual_status'] = 'STATUS_OPTION_PRESENT' if offsets else 'STATUS_OPTION_NOT_FOUND'
                row['manual_decoded_sha256'] = sha(decoded)
                row['exact_manual_contexts'] = [text[max(0, offset - 120):offset + 900] for offset in offsets[:4]]
            return row, data
        except Exception as error:
            row['status'] = 'READ_ERROR'
            row['error'] = repr(error)
            return row, None

    def query(label, command, limit):
        command = checked_argv(command, developer_dirs, bootstatus_help_developer)
        row = {'label': label, 'command': command, 'requested_timeout_seconds': limit,
               'started_unix': time.time()}
        result['commands'].append(row)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            row.update(status='BUDGET_EXHAUSTED_NOT_STARTED', returncode=None)
            failed_queries.append(label)
            return row, b'', b''
        row['effective_timeout_seconds'] = min(limit, remaining)
        stdout_path = out / (label + '.stdout.log')
        stderr_path = out / (label + '.stderr.log')
        query_started = time.monotonic()
        try:
            with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                completed = observed_run(command, out=out, timeout=row['effective_timeout_seconds'],
                                         cwd=ROOT, stdout=stdout, stderr=stderr, check=False)
            row.update(status='COMPLETED', returncode=completed.returncode)
            if completed.returncode != 0:
                failed_queries.append(label)
        except Exception as error:
            row.update(status='QUERY_ERROR', error_type=type(error).__name__, error=repr(error), returncode=None)
            failed_queries.append(label)
        finally:
            row['finished_unix'] = time.time()
            row['elapsed_seconds'] = time.monotonic() - query_started
            for key, path in [('stdout', stdout_path), ('stderr', stderr_path)]:
                if path.exists():
                    row[key] = file_identity(path)
        return row, stdout_path.read_bytes() if stdout_path.exists() else b'', stderr_path.read_bytes() if stderr_path.exists() else b''

    def inspect_global(phase, process_bytes):
        inspect_file(phase + '-global-framework-info', GLOBAL_FRAMEWORK / 'Resources/Info.plist', plist=True, copy=True)
        inspect_file(phase + '-global-framework-version-A-info', GLOBAL_FRAMEWORK / 'Versions/A/Resources/Info.plist', plist=True, copy=True)
        framework_real = GLOBAL_FRAMEWORK.resolve()
        seen_services = set()
        for line in process_bytes.decode('utf-8', errors='replace').splitlines():
            fields = line.split(None, 6)
            if len(fields) != 7 or not fields[0].isdigit():
                continue
            executable = Path(fields[6])
            if not executable.is_absolute() or not any(word in executable.name for word in ('CoreSimulatorService', 'simdiskimaged')):
                continue
            service = {'phase': phase, 'process_line': line, 'pid': int(fields[0]), 'executable_path': str(executable)}
            result['global_service_observations'].append(service)
            try:
                real = executable.resolve(strict=True)
                real.relative_to(framework_real)
                service['realpath'] = str(real)
                if str(real) in seen_services:
                    service['deduplicated_executable'] = True
                    continue
                seen_services.add(str(real))
                label = phase + '-global-service-' + str(len(seen_services))
                inspect_file(label + '-binary', real, limit=64 * 1024 * 1024)
                # Derive only the executable's actual enclosing bundle plist.
                bundle_contents = next((p for p in real.parents if p.name == 'Contents'), None)
                if bundle_contents is not None:
                    inspect_file(label + '-info', bundle_contents / 'Info.plist', plist=True, copy=True)
            except Exception as error:
                service['read_limit_or_path_error'] = repr(error)

    exit_code = 1
    try:
        if not __debug__ or sys.platform != 'darwin':
            raise RuntimeError('Actual Darwin host and enabled assertions required')
        observer = ROOT / 'Bootstrap/simulator_comparison_diagnostics.py'
        if sha(observer.read_bytes()) != OBSERVER_SHA256:
            raise RuntimeError('Original process observer bytes changed')
        for path in [Path(__file__).resolve(), observer, ROOT / '.github/workflows/udp-echo-ui-diagnostic.yml']:
            data = path.read_bytes()
            saved = out / 'code-inputs' / path.name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(data)
            result['code_inputs'].append({'repository_path': str(path.relative_to(ROOT)), **file_identity(saved)})
        spec = importlib.util.spec_from_file_location('exact_preflight_observer', observer)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        observed_run = module.observed_run
        fixed_outputs = {}
        for label, command, limit in FIXED_QUERIES:
            row, stdout, stderr = query(label, command, limit)
            fixed_outputs[label] = stdout
        inspect_global('pre', fixed_outputs['processes'])
        selected = fixed_outputs['selected-developer'].decode('utf-8', errors='replace').strip()
        result['default_path_observations']['xcode_select_output'] = selected
        for label, path in [('default_alias', Path('/Applications/Xcode.app')),
                            ('selected_developer', Path(selected)) if selected.startswith('/') else ('selected_developer', None)]:
            row = {'path': str(path) if path is not None else None}
            try:
                if path is None:
                    raise ValueError('No absolute selected developer path was observed')
                row.update(realpath=str(path.resolve(strict=True)), is_symlink=path.is_symlink())
            except Exception as error:
                row['error'] = repr(error)
            result['default_path_observations'][label] = row
        distinct = {}
        for label, name in APP_CANDIDATES:
            app = Path(name)
            row = {'requested_label': label, 'path': name}
            result['installed_apps'].append(row)
            try:
                real_app = app.resolve(strict=True)
                developer = (real_app / 'Contents/Developer').resolve(strict=True)
                if not real_app.is_dir() or not developer.is_dir():
                    raise ValueError('App/developer path is not a directory')
                row.update(status='PRESENT', realpath=str(real_app), developer_dir=str(developer), is_symlink=app.is_symlink())
                if label == '27.0':
                    bootstatus_help_developer = str(developer)
                if str(real_app) in distinct:
                    row['deduplicated_to'] = distinct[str(real_app)]['requested_label']
                    continue
                distinct[str(real_app)] = row
                developer_dirs.add(str(developer))
            except Exception as error:
                row.update(status='ABSENT_OR_UNREADABLE', error=repr(error))
        for number, row in enumerate(distinct.values(), 1):
            label = 'app-' + str(number)
            app, developer = Path(row['realpath']), Path(row['developer_dir'])
            row['file_labels'] = []
            for suffix, path, kind in [('info', app / 'Contents/Info.plist', 'plist'),
                                       ('version', app / 'Contents/version.plist', 'plist'),
                                       ('manual', developer / 'usr/share/man/man1/xcodebuild.1', 'manual'),
                                       ('manual-gzip', developer / 'usr/share/man/man1/xcodebuild.1.gz', 'manual')]:
                file_label = label + '-' + suffix
                inspect_file(file_label, path, plist=kind == 'plist', manual=kind == 'manual', copy=True)
                row['file_labels'].append(file_label)
            row['query_labels'] = []
            for suffix, command, limit in APP_QUERIES:
                query_label = label + '-' + suffix
                observed, stdout, stderr = query(query_label, ['/usr/bin/env', 'DEVELOPER_DIR=' + str(developer), *command], limit)
                row['query_labels'].append(query_label)
                if row['requested_label'] == '27.0' and suffix == 'simctl-path':
                    help_label = 'selected-27-bootstatus-help'
                    help_observed, _, _ = query(help_label,
                        ['/usr/bin/env', 'DEVELOPER_DIR=' + str(developer), *BOOTSTATUS_HELP_QUERY], 5)
                    row['query_labels'].append(help_label)
                    result['bootstatus_help_observation'].update(
                        status=help_observed['status'], query_label=help_label,
                        developer_dir=str(developer), returncode=help_observed['returncode'])
                if suffix == 'first-launch-status':
                    if observed['status'] != 'COMPLETED':
                        classification = 'UNOBSERVED_OR_TIMED_OUT'
                    elif observed['returncode'] == 0:
                        classification = 'EXIT_ZERO_STATUS_ONLY_SEE_INSTALLED_MANUAL'
                    elif re.search(rb'(unknown|unrecognized|invalid) (command.line )?(option|argument)', stdout + stderr, re.I):
                        classification = 'UNSUPPORTED_OPTION_REPORTED'
                    else:
                        classification = 'NONZERO_STATUS_OR_QUERY_FAILURE_REQUIRES_REVIEW'
                    row['first_launch_status_classification'] = classification
        for key in ('default_alias', 'selected_developer'):
            row = result['default_path_observations'][key]
            realpath = row.get('realpath')
            row['matches_distinct_app_labels'] = [item['requested_label'] for item in distinct.values()
                if realpath in (item['realpath'], item['developer_dir'])]
            row['does_not_start_an_extra_toolchain'] = True
        _, post_processes, _ = query('processes-after', FIXED_QUERIES[3][1], 5)
        inspect_global('post', post_processes)
        result['global_service_not_observed'] = not result['global_service_observations']
        result['failed_query_labels'] = failed_queries
        result['result'] = 'OBSERVATIONS_RECORDED_WITH_QUERY_FAILURES' if failed_queries else 'OBSERVATIONS_RECORDED'
        exit_code = 1 if failed_queries else 0
    except Exception as error:
        result['result'] = 'PREFLIGHT_COLLECTION_ERROR'
        result['collection_error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        result['finished_unix'] = time.time()
        result['elapsed_seconds'] = time.monotonic() - started
        result['process_exit_code'] = exit_code
        (out / 'preflight-result.json').write_text(json.dumps(result, indent=2) + '\n')
        inventory = [file_identity(path) for path in sorted(out.rglob('*')) if path.is_file() and path.name != 'artifact-manifest.json']
        (out / 'artifact-manifest.json').write_text(json.dumps({'files': inventory, 'acceptance_credit': False}, indent=2) + '\n')
    print(json.dumps({'result': result['result'], 'application_accepted': False, 'repair_performed': False,
                      'commands_recorded': len(result['commands']), 'process_exit_code': exit_code}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
