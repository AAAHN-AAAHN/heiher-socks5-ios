#!/usr/bin/env python3
"""Bounded process observations around the unchanged Settings host observer.

The run subcommand returns the inner command's actual status. It does NOT report
observer health through that number: verify-result is a separate mandatory gate
after the frozen status reader and common-after have recorded the original exit.
No additional simctl command, lifecycle action, permission change or original
deadline is introduced. Samples can perturb timing and cannot prove causation.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import sys
import time

SOURCE = '206fbbab4569d4e74de7f0febaa3eee5ed6c86bd'
REPOSITORY = 'AAAHN-AAAHN/heiher-socks5-ios'
SERVICE = '/Library/Developer/PrivateFrameworks/CoreSimulator.framework/Versions/A/XPCServices/com.apple.CoreSimulator.CoreSimulatorService.xpc/Contents/MacOS/com.apple.CoreSimulator.CoreSimulatorService'
CORE_SIMCTL = '/Library/Developer/PrivateFrameworks/CoreSimulator.framework/Versions/A/Resources/bin/simctl'
PYTHON_LAUNCHER = '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14'
PYTHON_APPLICATION = '/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python'
FIELDS = 'uid=,ruid=,pid=,ppid=,state=,pcpu=,rss=,etime=,lstart=,comm='
INTERVAL = 5.0
MAX_TICKS = 360
MAX_EVENTS_BYTES = 16 * 1024 * 1024
COMMAND_BYTES = 4 * 1024 * 1024
LATE_BOOT_SECONDS = 60.0
CONTEXT = ('GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
           'GITHUB_JOB', 'GITHUB_REF', 'RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH', 'DEVELOPER_DIR')


def now():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def error_record(exc):
    return {'type': type(exc).__name__, 'message': str(exc)}


def shell_status(code):
    return code if code >= 0 else 128 - code


def safe_bytes(path, maximum=COMMAND_BYTES):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Linked read path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum, 'Unbounded/nonregular read')
        chunks, remaining = [], maximum + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
        after = os.fstat(fd)
        require(len(raw) <= maximum and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), 'File changed while reading')
        return raw
    finally:
        os.close(fd)


def descriptor(path):
    raw = safe_bytes(path, MAX_EVENTS_BYTES)
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def save(output, report):
    temporary = output / 'result.pending.json'
    with temporary.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    os.replace(temporary, output / 'result.json')


class ProcBSDInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid', 'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'jobc', 'tdev', 'tpgid')]
    _fields_ += [('nice', ctypes.c_int32), ('start_seconds', ctypes.c_uint64), ('start_microseconds', ctypes.c_uint64)]


def native_identity(pid):
    require(sys.platform == 'darwin' and ctypes.sizeof(ProcBSDInfo) == 136, 'Darwin identity ABI required')
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    lib.proc_pidpath.restype = ctypes.c_int
    info = ProcBSDInfo()
    size = lib.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
    require(size == 136, 'Process exited or identity unavailable')
    buffer = ctypes.create_string_buffer(4096)
    length = lib.proc_pidpath(pid, buffer, len(buffer))
    require(0 < length < len(buffer) and len(buffer.value) == length, 'Executable identity unavailable')
    return {name: int(getattr(info, name)) for name in ('pid', 'ppid', 'uid', 'ruid', 'svuid',
             'start_seconds', 'start_microseconds')} | {'executable': buffer.value.decode()}


def owned(identity):
    return (identity['pid'] > 1 and os.getuid() > 0 and
            identity['uid'] == identity['ruid'] == identity['svuid'] == os.getuid() and
            identity['start_seconds'] > 0 and 0 <= identity['start_microseconds'] < 1000000)


def verify_descendant(identity, root_identity):
    current, seen = identity, set()
    for _ in range(32):
        require(owned(current) and current['pid'] not in seen, 'Invalid own-UID ancestry')
        require(native_identity(current['pid']) == current, 'Ancestry changed during observation')
        if current['pid'] == root_identity['pid']:
            require({k: v for k, v in current.items() if k != 'executable'} ==
                    {k: v for k, v in root_identity.items() if k != 'executable'},
                    'Original observer birth identity changed')
            executables = {root_identity['executable']}
            if root_identity['executable'] == PYTHON_LAUNCHER:
                executables.add(PYTHON_APPLICATION)
            require(current['executable'] in executables, 'Original observer executable changed')
            return
        seen.add(current['pid'])
        require(current['ppid'] > 1, 'Not an original command descendant')
        current = native_identity(current['ppid'])
    raise RuntimeError('Ancestry depth limit reached')


def parse_ps(text):
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split(None, 13)
        require(len(fields) == 14, 'Unexpected ps fields')
        uid, ruid, pid, ppid = map(int, fields[:4])
        require(uid >= 0 and ruid >= 0 and pid > 0 and ppid >= 0, 'Invalid ps identity')
        rows.append({'uid': uid, 'ruid': ruid, 'pid': pid, 'ppid': ppid, 'state': fields[4],
                     'pcpu': float(fields[5]), 'rss_kib': int(fields[6]), 'elapsed_display': fields[7],
                     'start_display_utc': ' '.join(fields[8:13]), 'comm': fields[13]})
    require(len({r['pid'] for r in rows}) == len(rows), 'Duplicate ps PID')
    return rows


def descendant_ids(rows, root):
    result = {root}
    while True:
        extended = result | {r['pid'] for r in rows if r['ppid'] in result}
        if extended == result:
            return result
        result = extended


def service_comm(path):
    name = Path(path).name
    return path == SERVICE or (path.startswith(('/Library/Developer/', '/Applications/Xcode_27.app/', '/System/Library/'))
                              and name in ('SimLaunchHost.arm64', 'SimLaunchHost.x86_64', 'launchd_sim', 'simdiskimaged'))


def selected_rows(rows, root):
    descendants = descendant_ids(rows, root)
    return [dict(r, original_descendant=r['pid'] in descendants) for r in rows
            if r['uid'] == r['ruid'] == os.getuid() and
            (r['pid'] in descendants or service_comm(r['comm']))]


def child_file_limit():
    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    cap = min([COMMAND_BYTES] + [n for n in (soft, hard) if n != resource.RLIM_INFINITY])
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


def read_command(argv, output, label, timeout=3, persist_stdout=True):
    """Only directly spawned read-only diagnostic commands receive this bound."""
    stdout_path, stderr_path = output / (label + '.stdout'), output / (label + '.stderr')
    row = {'argv': argv, 'started_utc': now(), 'timeout_seconds': timeout,
           'environment_overrides': {'LC_ALL': 'C', 'TZ': 'UTC'}, 'original_process_signals': 0}
    with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
        try:
            completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       env=dict(os.environ, LC_ALL='C', TZ='UTC'), timeout=timeout,
                                       preexec_fn=child_file_limit)
            row['returncode'] = completed.returncode
        except subprocess.TimeoutExpired as exc:
            row['error'] = error_record(exc)
            row['own_diagnostic_child_killed_by_subprocess_run'] = True
        except Exception as exc:
            row['error'] = error_record(exc)
    row['finished_utc'] = now()
    raw = safe_bytes(stdout_path)
    row['stderr'] = descriptor(stderr_path)
    if persist_stdout:
        row['stdout'] = descriptor(stdout_path)
    else:
        # ps comm-only inventory is filtered before persistence; unrelated argv
        # and process environments are never requested.
        row['stdout_filtered_before_persistence'] = True
        stdout_path.unlink()
    return row, raw.decode(errors='replace')


def simctl_executables(report):
    # Xcode's selected command and the actually observed CoreSimulator command
    # are exact paths, never a basename/prefix match or an unrelated process.
    return (report['simctl_executable'], CORE_SIMCTL)


def sample_once(identity, output, label, report):
    row = {'label': label, 'expected_identity': identity, 'started_utc': now(), 'invocations': 0}
    report['samples'].append(row)
    try:
        require(owned(identity), 'Sample target outside own UID')
        require(identity['executable'] in (SERVICE, *simctl_executables(report)), 'Sample executable outside scope')
        current = native_identity(identity['pid'])
        require(current == identity, 'Sample target identity changed before invocation')
        if identity['executable'] in simctl_executables(report):
            verify_descendant(identity, report['inner']['native_identity'])
        row['before_identity'] = current
        row['invocations'] = 1
        path = output / (label + '.sample.txt')
        command, _ = read_command(['/usr/bin/sample', str(identity['pid']), '1', '10', '-file', str(path)],
                                  output, label, timeout=8)
        row['command'] = command
        try:
            row['after_identity'] = native_identity(identity['pid'])
            row['same_identity_after'] = row['after_identity'] == identity
        except Exception as exc:
            row['after_identity_error'] = error_record(exc)
            row['same_identity_after'] = False
        if path.exists():
            row['sample_file'] = descriptor(path)
        row['usable'] = (command.get('returncode') == 0 and row['same_identity_after'] and 'sample_file' in row)
    except Exception as exc:
        row['unavailable'] = error_record(exc)
        row['usable'] = False
    row['finished_utc'] = now()
    # Permission denial/process exit is evidence of an unavailable observation,
    # not grounds for privileged fallbacks or a change to the original result.


def inputs(output, command=None):
    require(sys.platform == 'darwin' and os.getuid() > 0, 'Actual unprivileged macOS runner required')
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REPOSITORY') == REPOSITORY,
            'Actual repository Actions environment required')
    require(all(re.fullmatch(r'[1-9][0-9]*', os.environ.get(k, '')) for k in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')),
            'Actual run and attempt required')
    require(os.environ.get('GITHUB_JOB') == 'runtime' and os.environ.get('CANDIDATE') == 'settings', 'Settings runtime only')
    root, control = Path.cwd().resolve(), Path(os.environ['GITHUB_WORKSPACE']).resolve()
    require(root != control and output.is_absolute() and output == root / 'artifacts/settings-persistence-ui-audit/runtime-preparation/consumers/settings-ui/process-observation', 'Unexpected output/source root')
    def git(directory, *args):
        return subprocess.check_output(['git', '-C', str(directory), *args], timeout=10).decode().strip()
    require(git(root, 'rev-parse', 'HEAD') == SOURCE, 'Different Settings source')
    require(git(control, 'rev-parse', 'HEAD') == os.environ['GITHUB_SHA'], 'Different actual helper')
    require(Path(__file__).resolve() == control / 'Bootstrap/observe_settings_processes.py', 'Different observer path')
    relative = 'Bootstrap/observe_settings_processes.py'
    actual_source = safe_bytes(control / relative)
    blob = hashlib.sha1(b'blob ' + str(len(actual_source)).encode() + b'\0' + actual_source).hexdigest()
    require(git(control, 'ls-tree', os.environ['GITHUB_SHA'], '--', relative) == '100644 blob ' + blob + '\t' + relative,
            'Observer bytes are not tracked by the actual helper commit')
    require(git(control, 'ls-files', '--stage', '--', relative) == '100644 ' + blob + ' 0\t' + relative and
            stat.S_IMODE((control / relative).stat().st_mode) == 0o644, 'Observer index or file mode differs')
    committed_source = subprocess.check_output(['git', '-C', str(control), 'cat-file', 'blob', blob], timeout=10)
    require(committed_source == actual_source, 'Observer raw Git bytes differ')
    for directory in (root, control):
        git(directory, 'diff', '--exit-code', 'HEAD', '--')
        git(directory, 'diff', '--cached', '--exit-code', 'HEAD', '--')
    python = str(Path(os.environ['RUNNER_TOOL_CACHE']) / 'Python/3.14.9/arm64/bin/python3.14')
    host_output = output.parent / 'host-observation'
    expected = [python, '-B', str(root / 'Build/observe_host_during_command.py'), '--output', str(host_output), '--', 'python3', 'Tests/Settings/ui_audit.py']
    if command is not None:
        require(command == expected, 'Inner host-observer command differs')
    refresh_path = output.parents[2] / 'service/refresh-result.json'
    refresh = json.loads(safe_bytes(refresh_path))
    service = refresh['service_snapshots']['service-final']['native_identity'].copy()
    require(service.pop('proc_bsdinfo_bytes') == 136 and owned(service) and service['executable'] == SERVICE,
            'Original preparation lacks the exact own-UID service identity')
    return {'context': {k: os.environ.get(k) for k in CONTEXT}, 'source_commit': SOURCE,
            'control_commit': os.environ['GITHUB_SHA'], 'source_root': str(root), 'control_root': str(control),
            'observer_source': descriptor(Path(__file__).resolve()), 'expected_inner_argv': expected,
            'preparation_service_record': descriptor(refresh_path), 'original_service_identity': service}


def current_device(root, output, tick, seen):
    path = root / 'artifacts/settings-persistence-ui-audit/runtime.json'
    if not path.exists():
        return {'runtime_json_present': False}
    try:
        raw = safe_bytes(path, 256 * 1024)
        runtime = json.loads(raw)
        udid = runtime['udid']
        require(re.fullmatch(r'[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}', udid) is not None, 'Invalid original UDID')
        row = {'udid': udid, 'runtime_json': {'path': str(path), 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest()}, 'existing_log_sizes': {}}
    except Exception as exc:
        return {'runtime_json_unavailable': error_record(exc)}
    for name in ('simulator-boot.log', 'simulator-ready.log', 'ui-test.log', 'cleanup-shutdown.log', 'cleanup-delete.log'):
        candidate = path.parent / name
        try:
            if candidate.exists() and not candidate.is_symlink():
                row['existing_log_sizes'][name] = candidate.stat().st_size
        except FileNotFoundError:
            row['existing_log_sizes'][name] = 'disappeared_during_read'
    device = Path.home() / 'Library/Developer/CoreSimulator/Devices' / udid / 'device.plist'
    try:
        plist = safe_bytes(device, 1024 * 1024)
        digest = hashlib.sha256(plist).hexdigest()
        row['device_plist_sha256'] = digest
        if digest not in seen:
            target = output / f'device-{tick:03d}.plist'
            with target.open('xb') as stream:
                stream.write(plist)
            row['device_plist_copy'] = descriptor(target)
            seen.add(digest)
    except FileNotFoundError:
        row['device_plist_present'] = False
    except Exception as exc:
        row['device_plist_unavailable'] = error_record(exc)
    return row


def snapshot(original_pid, output, report, tick, first_seen, seen_plists):
    row = {'tick': tick, 'started_utc': now(), 'monotonic': time.monotonic()}
    query, text = read_command(['/bin/ps', '-ww', '-x', '-U', str(os.getuid()), '-o', FIELDS], output,
                               f'{tick:03d}-ps', persist_stdout=False)
    row['ps_query'] = query
    row['observer_errors'] = []
    rows = []
    if query.get('returncode') != 0:
        # Preserve the actual command status/exception/timing, then keep the
        # ordinary observation cadence. The mandatory health gate still fails.
        row['observer_errors'].append({'where': 'ps_query', 'tick': tick,
                                       'type': 'RuntimeError', 'message': 'Read-only ps snapshot failed',
                                       'query': query})
    else:
        try:
            rows = selected_rows(parse_ps(text), original_pid)
        except Exception as exc:
            row['observer_errors'].append({'where': 'ps_parse', 'tick': tick,
                                           **error_record(exc), 'query': query})
    row['processes'] = rows
    for proc in rows:
        if not (proc['original_descendant'] and proc['comm'] in simctl_executables(report)):
            continue
        try:
            identity = native_identity(proc['pid'])
            require(owned(identity) and identity['ppid'] == proc['ppid'] and
                    identity['executable'] == proc['comm'], 'CLI identity changed')
            verify_descendant(identity, report['inner']['native_identity'])
            query, args = read_command(['/bin/ps', '-ww', '-p', str(proc['pid']), '-o', 'args='], output,
                                       f'{tick:03d}-args-{proc["pid"]}', persist_stdout=False)
            require(query.get('returncode') == 0 and native_identity(proc['pid']) == identity, 'CLI disappeared during args read')
            proc['native_identity'] = identity
            proc['ps_args_display'] = args.strip()
            proc['args_query'] = query
            key = (identity['pid'], identity['start_seconds'], identity['start_microseconds'])
            first_seen.setdefault(key, time.monotonic())
            age = time.monotonic() - first_seen[key]
            proc['observed_lifetime_seconds'] = age
            # runtime.json is read below on every tick. Use only its verified
            # preceding value; no process launch or device query discovers it.
            udid = report.get('last_original_udid')
            exact_boot = (udid is not None and re.search(r'(?:^|/)simctl bootstatus ' + re.escape(udid) + r' -b\s*$', args.strip()))
            if exact_boot:
                bound = {'identity': identity, 'verified_args': args.strip(), 'udid': udid,
                         'first_seen_monotonic': first_seen[key], 'last_verified_utc': now()}
                previous = report.get('bound_bootstatus')
                require(previous is None or previous['identity'] == identity,
                        'Original bootstatus identity changed')
                report['bound_bootstatus'] = bound
        except Exception as exc:
            proc['cli_observation_unavailable'] = error_record(exc)
    # A failed global ps read must not erase a previously verified exact child.
    # Native UID/birth/path/ancestry checks remain mandatory before late sampling.
    bound = report.get('bound_bootstatus')
    if bound is not None and not report['samples']:
        age = time.monotonic() - bound['first_seen_monotonic']
        if age >= LATE_BOOT_SECONDS:
            try:
                identity = native_identity(bound['identity']['pid'])
                require(identity == bound['identity'], 'Bound bootstatus identity changed')
                verify_descendant(identity, report['inner']['native_identity'])
                row['late_bootstatus_binding'] = {'identity': identity, 'observed_lifetime_seconds': age,
                                                  'last_verified_args_utc': bound['last_verified_utc']}
                sample_once(identity, output, 'late-bootstatus', report)
                sample_once(report['binding']['original_service_identity'], output, 'late-coresimulator', report)
            except Exception as exc:
                row['late_bootstatus_unavailable'] = error_record(exc)
    row['device'] = current_device(Path(report['binding']['source_root']), output, tick, seen_plists)
    if 'udid' in row['device']:
        report['last_original_udid'] = row['device']['udid']
    if tick % 3 == 0:
        row['memory'] = []
        for label, argv in [('vm-stat', ['/usr/bin/vm_stat']), ('memory', ['/usr/sbin/sysctl', 'hw.memsize', 'vm.swapusage'])]:
            query, _ = read_command(argv, output, f'{tick:03d}-{label}')
            row['memory'].append(query)
    row['finished_utc'] = now()
    return row


def run(output, command):
    binding = inputs(output, command)
    require(output.parent.resolve(strict=True) == output.parent, 'Linked output parent')
    output.mkdir(mode=0o700)
    report = {'schema': 'settings-process-observation-v1', 'binding': binding, 'started_utc': now(),
              'wrapper_pid': os.getpid(), 'wrapper_uid': os.getuid(), 'inner': {'argv': command,
              'launch_attempts': 0, 'launches': 0, 'raw_returncode': None, 'environment': 'inherited',
              'stdio': 'inherited', 'added_timeout': None, 'new_session': False},
              'simctl_executable': str(Path(os.environ['DEVELOPER_DIR']) / 'usr/bin/simctl'),
              'observed_core_simctl_executable': CORE_SIMCTL,
              'samples': [], 'observer_errors': [], 'ticks': 0, 'recording_complete': False,
              'limits': {'tick_interval_seconds': INTERVAL, 'maximum_ticks': MAX_TICKS,
                         'late_child_observed_seconds': LATE_BOOT_SECONDS, 'maximum_sample_invocations': 2,
                         'sample_duration_seconds': 1, 'sample_interval_milliseconds': 10,
                         'extra_simctl_commands': 0, 'original_retries': 0, 'original_signals': 0,
                         'service_signals': 0, 'runtime_mutations': 0, 'permission_mutations': 0,
                         'process_snapshot_is_not_an_atomic_lifetime_trace': True,
                         'short_lived_children_between_ticks_may_be_unobserved': True,
                         'ps_pcpu_is_a_decaying_percentage_not_cumulative_cpu_time': True,
                         'ps_start_display_has_second_resolution_native_identity_has_microseconds': True,
                         'sampling_and_observation_can_change_host_timing': True,
                         'sample_target_birth_identity_recheck_has_a_remaining_pid_reuse_race': True,
                         'no_privileged_or_alternative_sampling_fallback': True,
                         'failed_periodic_ps_queries_are_recorded_and_keep_health_failure': True,
                         'late_sampling_may_use_previously_verified_argv_with_fresh_native_birth_and_ancestry': True,
                         'run_exit_represents_inner_status_not_observer_health': True}}
    original = None
    previous = {}
    def interrupted(signum, _frame):
        report['wrapper_interruption'] = {'signal': signum, 'utc': now()}
        raise KeyboardInterrupt('External wrapper interruption')
    save(output, report)
    try:
        report['inner']['launch_attempts'] = 1
        report['inner']['started_utc'] = now()
        # No env, cwd, stdio, deadline, session, limit or signal change.
        original = subprocess.Popen(command)
        report['inner'].update({'launches': 1, 'pid': original.pid})
        try:
            report['inner']['native_identity'] = native_identity(original.pid)
            require(owned(report['inner']['native_identity']) and report['inner']['native_identity']['ppid'] == os.getpid(),
                    'Inner command birth identity differs')
        except Exception as exc:
            report['observer_errors'].append({'where': 'inner_identity', **error_record(exc)})
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, interrupted)
        save(output, report)
        first_seen, seen_plists = {}, set()
        with (output / 'snapshots.jsonl').open('xb') as events:
            for tick in range(MAX_TICKS):
                if original.poll() is not None:
                    break
                began = time.monotonic()
                try:
                    row = snapshot(original.pid, output, report, tick, first_seen, seen_plists)
                    raw = (json.dumps(row, sort_keys=True) + '\n').encode()
                    require(events.tell() + len(raw) <= MAX_EVENTS_BYTES, 'Process observation size limit reached')
                    events.write(raw)
                    events.flush()
                    report['observer_errors'].extend(row.get('observer_errors', []))
                    report['ticks'] += 1
                    save(output, report)
                except Exception as exc:
                    report['observer_errors'].append({'tick': tick, **error_record(exc)})
                    break
                try:
                    original.wait(timeout=max(0.01, INTERVAL - (time.monotonic() - began)))
                    break
                except subprocess.TimeoutExpired:
                    pass
            else:
                report['observation_tick_limit_reached'] = True
        # The observation budget never becomes a deadline on the original.
        report['inner']['raw_returncode'] = original.wait()
        report['inner']['finished_utc'] = now()
    except BaseException as exc:
        report['observer_errors'].append(error_record(exc))
        if original is not None and original.returncode is not None:
            report['inner']['raw_returncode'] = original.returncode
    finally:
        if original is not None and report['inner']['raw_returncode'] is None and 'wrapper_interruption' not in report:
            # Failure to observe or save never aborts an already launched inner
            # command or permits an early, invented inner exit status.
            try:
                report['inner']['raw_returncode'] = original.wait()
                report['inner']['finished_utc'] = now()
            except BaseException as exc:
                report['observer_errors'].append({'where': 'original_wait', **error_record(exc)})
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        code = report['inner']['raw_returncode']
        report['run_exit_code'] = (shell_status(code) if code is not None else
                                  128 + report['wrapper_interruption']['signal'] if 'wrapper_interruption' in report else 1)
        report['finished_utc'] = now()
        report['recording_complete'] = True
        try:
            report['files'] = [descriptor(p) for p in sorted(output.iterdir()) if p.is_file() and p.name not in ('result.json', 'result.pending.json')]
            save(output, report)
        except BaseException as exc:
            # Recording failure cannot replace an already known original exit.
            # The separate mandatory verify-result then rejects missing evidence.
            print(json.dumps({'settings_process_observation_recording_failed': error_record(exc),
                              'actual_inner_returncode': code}), file=sys.stderr)
    return report['run_exit_code']


def verify(output, actual):
    binding = inputs(output)
    report = json.loads(safe_bytes(output / 'result.json', MAX_EVENTS_BYTES))
    require(report['binding'] == binding, 'Observation belongs to a different source/helper/run/attempt')
    require(report['recording_complete'] is True and report['inner']['launch_attempts'] == report['inner']['launches'] == 1,
            'Inner command or observation did not complete')
    raw = report['inner']['raw_returncode']
    require(type(raw) is int and report['run_exit_code'] == shell_status(raw) == actual, 'Different actual inner status')
    require(report['inner']['argv'] == binding['expected_inner_argv'], 'Different actual inner argv')
    require(report['observer_errors'] == [] and 'wrapper_interruption' not in report, 'Additional process observation failed')
    require(report['ticks'] > 0 and not report.get('observation_tick_limit_reached', False), 'Process observation incomplete')
    require(len(report['samples']) <= 2 and sum(r['invocations'] for r in report['samples']) <= 2, 'Sample budget exceeded')
    require(all(descriptor(Path(r['path'])) == r and Path(r['path']).parent == output for r in report['files']), 'Observation bytes changed')
    require({p.name for p in output.iterdir()} == {'result.json', *[Path(r['path']).name for r in report['files']]}, 'Unexpected observation output')
    print(json.dumps({'settings_process_observation_verified': str(output), 'actual_inner_status': actual,
                      'ticks': report['ticks'], 'sample_invocations': sum(r['invocations'] for r in report['samples'])}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'verify-result'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--actual-inner-status', type=int)
    args, remaining = parser.parse_known_args()
    if args.mode == 'run':
        require(remaining and remaining[0] == '--' and args.actual_inner_status is None, 'Require -- unchanged inner command')
        return run(args.output, remaining[1:])
    require(not remaining and args.actual_inner_status is not None and 0 <= args.actual_inner_status <= 255, 'Require actual inner exit')
    return verify(args.output, args.actual_inner_status)


if __name__ == '__main__':
    raise SystemExit(main())
