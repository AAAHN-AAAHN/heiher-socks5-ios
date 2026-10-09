#!/usr/bin/env python3
"""Observe the unchanged failed Release app; diagnostic completion is not a product PASS."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import stat
import subprocess
import sys
import tarfile
import threading
import time
import uuid

SOURCE = '5b99743bc867fecb108b0c5cc2e37c95b6e1425f'
TREE = 'ba9d4c2f5d969e08e9a0058b9fdbf3080b33e09d'
TAR_SHA = '2609b061a3d4963634f68e79e786d365f17674bc6559efbc6679019837d9fed4'
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-27-0'
DEVICE = 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'
PREDICATE = ('process == "CoreSimulatorService" OR process == "launchd_sim" OR '
             'process == "installd" OR process == "lsd" OR process == "SpringBoard" OR '
             'process == "installcoordinationd" OR process == "mobile_installation_proxy" OR '
             'subsystem BEGINSWITH "com.apple.CoreSimulator"')
OUT = None
LOCK = threading.Lock()
ACTIVE = {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def event(value):
    value = dict(utc=datetime.now(timezone.utc).isoformat(), **value)
    with LOCK:
        with (OUT / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(value) + '\n')
        print(json.dumps(value), flush=True)


def inventory(app):
    result = {}
    for path in [app, *sorted(app.rglob('*'))]:
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise RuntimeError('Unexpected app file type: ' + str(path))
        result[path.relative_to(app.parent).as_posix()] = dict(
            mode=stat.S_IMODE(mode), sha256=sha(path.read_bytes()) if stat.S_ISREG(mode) else None)
    return result


def frozen_app(args):
    source = json.loads(args.source_json.read_bytes())
    data = args.app_tar.read_bytes()
    if source.get('commit') != SOURCE or source.get('tree') != TREE:
        raise RuntimeError('Source identity is not the approved failed Release')
    if len(data) != 364121 or sha(data) != TAR_SHA:
        raise RuntimeError('App archive is not the approved, unchanged failure artifact')
    save('input.json', dict(source=source, source_json_sha256=sha(args.source_json.read_bytes()),
                           app_tar_sha256=sha(data), app_tar_bytes=len(data)))
    destination = OUT / 'frozen'
    destination.mkdir()
    expected = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (str(path) != member.name or path.is_absolute() or '..' in path.parts
                    or not path.parts or path.parts[0] != 'Socks5.app'
                    or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE)
                    or member.mode & ~0o777 or member.name.casefold() in names):
                raise RuntimeError('Unsafe or duplicate archive member: ' + member.name)
            names.add(member.name.casefold())
        for member in members:
            path = destination / member.name
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                digest = None
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                content = archive.extractfile(member).read()
                with path.open('xb') as stream:
                    stream.write(content)
                digest = sha(content)
            expected[member.name] = dict(mode=member.mode, sha256=digest)
        for member in reversed(members):
            path = destination / member.name
            os.chmod(path, member.mode)
            os.utime(path, (member.mtime, member.mtime))
    app = destination / 'Socks5.app'
    if inventory(app) != expected:
        raise RuntimeError('Extracted app bytes or modes differ from the archive')
    save('frozen-manifest.json', expected)
    save('app-info.json', plistlib.loads((app / 'Info.plist').read_bytes()))
    return app, expected


def stop_process(process):
    if process.poll() is None:
        process.kill()  # This command only; never a service or process group.
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run(name, args, timeout=15, pipe=False, observe=False):
    """Preserve the timeout state before killing; never await pipe EOF a second time."""
    base = OUT / name
    base.parent.mkdir(parents=True, exist_ok=True)
    result = dict(command=list(map(str, args)), timeout_seconds=timeout, timed_out=False,
                  started_at_utc=datetime.now(timezone.utc).isoformat())
    process = watcher = None
    stopped = threading.Event()
    beginning = time.monotonic()
    with base.with_suffix('.stdout.log').open('wb') as stdout, base.with_suffix('.stderr.log').open('wb') as stderr:
        try:
            process = subprocess.Popen(result['command'], stdout=subprocess.PIPE if pipe else stdout,
                                       stderr=subprocess.PIPE if pipe else stderr)
            result['pid'] = process.pid
            with LOCK:
                ACTIVE[process.pid] = process
            if observe:
                watcher = threading.Thread(target=at_ninety, args=(name, process, stopped), daemon=True)
                watcher.start()
            try:
                if pipe:
                    output, errors = process.communicate(timeout=timeout)
                    stdout.write(output); stderr.write(errors)
                else:
                    process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                result.update(timed_out=True, poll_before_kill=process.poll(),
                              timeout_observed_at_utc=datetime.now(timezone.utc).isoformat(),
                              elapsed_at_timeout_seconds=round(time.monotonic() - beginning, 3))
                stop_process(process)  # Preserve the snapshot in memory, kill before diagnostic writes.
                save(name + '-before-kill.json', result)
                event(dict(stage='timeout-before-kill', name=name, **result))
                if pipe:
                    stdout.write(error.stdout or b''); stderr.write(error.stderr or b'')
        except Exception as error:
            result['error'] = repr(error)
        finally:
            stopped.set()
            if process:
                stop_process(process)
                for stream in (process.stdout, process.stderr):
                    if stream:
                        stream.close()
                result['returncode'] = process.poll()
                if result['returncode'] is not None:
                    with LOCK:
                        ACTIVE.pop(process.pid, None)
            if watcher:
                watcher.join(timeout=30)
                result['observer_unfinished'] = watcher.is_alive()
    result['elapsed_seconds'] = round(time.monotonic() - beginning, 3)
    save(name + '.json', result)
    event(dict(stage='command-finished', name=name, **result))
    return result


def ok(result):
    return result.get('returncode') == 0 and not result['timed_out'] and 'error' not in result


def read_output(name):
    return (OUT / name).with_suffix('.stdout.log').read_text(errors='replace').strip()


def at_ninety(name, process, stopped):
    if stopped.wait(90):
        return
    event(dict(stage='install-90-seconds', name=name, pid=process.pid, poll=process.poll()))
    pids = [process.pid]
    state = run(name + '-90-ps', ['/bin/ps', '-axo', 'pid=,uid=,ppid=,stat=,etime=,comm='], timeout=5)
    if ok(state):
        for line in read_output(name + '-90-ps').splitlines():
            fields = line.split(None, 5)
            if (len(fields) == 6 and fields[1] == str(os.getuid())
                    and any(s in fields[5] for s in ('CoreSimulatorService', '/installd',
                                                    '/installcoordinationd', '/mobile_installation_proxy'))):
                pids.append(int(fields[0]))
    for pid in list(dict.fromkeys(pids))[:4]:
        if stopped.is_set():
            return
        label = name + '-90-sample-' + str(pid)
        run(label, ['/usr/bin/sample', str(pid), '2', '1', '-file', str(OUT / (label + '.txt'))], timeout=5)


def device_case(mode, app, expected, cases, cleanup_errors):
    prefix = mode.lower()
    name = 'Immutable Install Probe ' + uuid.uuid4().hex
    case = dict(mode=mode, device_name=name, installed_container_observed=None)
    cases.append(case)
    device = None
    try:
        made = run(prefix + '/create', ['xcrun', 'simctl', 'create', name, DEVICE, RUNTIME], timeout=30)
        candidate = read_output(prefix + '/create')
        if not ok(made) or not re.fullmatch(r'[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}', candidate):
            raise RuntimeError('Fresh device creation did not return a valid identifier')
        device = case['device'] = candidate
        if not ok(run(prefix + '/boot', ['xcrun', 'simctl', 'boot', device], timeout=120)):
            raise RuntimeError('Fresh device boot failed')
        if not ok(run(prefix + '/bootstatus', ['xcrun', 'simctl', 'bootstatus', device, '-b'], timeout=240)):
            raise RuntimeError('Fresh device bootstatus did not complete')
        if inventory(app) != expected:
            raise RuntimeError('Frozen app changed before installation')
        case['install'] = run(prefix + '/install', ['xcrun', 'simctl', 'install', device, str(app)],
                              timeout=120, pipe=mode == 'PIPE', observe=True)
        case['container_kind'] = 'app'
        container = run(prefix + '/container', ['xcrun', 'simctl', 'get_app_container', device, 'hev.Socks5', 'app'])
        if ok(container) and read_output(prefix + '/container'):
            case['installed_container_observed'] = True
            case['container'] = read_output(prefix + '/container')
        run(prefix + '/listapps', ['xcrun', 'simctl', 'listapps', device])
        run(prefix + '/guest-services', ['xcrun', 'simctl', 'spawn', device, 'log', 'show', '--last', '5m',
                                      '--style', 'compact', '--info', '--predicate', PREDICATE], timeout=20)
    except Exception as error:
        case['error'] = repr(error)
    finally:
        run(prefix + '/host-services', ['/usr/bin/log', 'show', '--last', '5m', '--style', 'compact',
                                      '--info', '--predicate', PREDICATE], timeout=20)
        if device is None:
            # A create request may have succeeded even when its reply was lost.
            listed = run(prefix + '/recover-created-device', ['xcrun', 'simctl', 'list', 'devices', '-j'])
            if ok(listed):
                try:
                    matches = [d['udid'] for group in json.loads(read_output(prefix + '/recover-created-device'))['devices'].values()
                               for d in group if d['name'] == name]
                    if len(matches) == 1:
                        device = case['device'] = matches[0]
                except (ValueError, KeyError) as error:
                    case['recovery_error'] = repr(error)
        if device:
            for action in ('shutdown', 'delete'):
                result = run(prefix + '/cleanup-' + action, ['xcrun', 'simctl', action, device], timeout=30)
                if not ok(result):
                    cleanup_errors.append(dict(device=device, action=action, result=result))
        case['app_unchanged'] = inventory(app) == expected
        save('cases.json', cases)


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-tar', type=Path, required=True)
    parser.add_argument('--source-json', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    OUT = args.output.resolve()
    OUT.mkdir(parents=True, exist_ok=False)
    summary = dict(diagnostics_status='INCOMPLETE', product_gate_pass=False, source_commit=SOURCE,
                   source_tree=TREE, tar_sha256=TAR_SHA, cases=[], cleanup_errors=[], limitations=[
        'No product gate, UI, app launch, network relay, physical installation or app rebuild is performed.',
        'PIPE and FILE use different fresh devices in sequence; timing and service readiness confound causal attribution.',
        'A failed container query leaves installation status unknown; command timeout alone does not prove installation failure.'])
    app = expected = reader = None
    try:
        app, expected = frozen_app(args)
        if sys.platform != 'darwin':
            raise RuntimeError('Actual macOS is required')
        save('context.json', {key: os.environ.get(key) for key in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT',
             'RUNNER_NAME', 'RUNNER_OS', 'RUNNER_ARCH', 'ImageOS', 'ImageVersion', 'DEVELOPER_DIR')})
        for name, command in [('host-os', ['/usr/bin/sw_vers']), ('xcode', ['xcodebuild', '-version']),
             ('selected-xcode', ['xcode-select', '-p']), ('sdk', ['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-version']),
             ('runtimes', ['xcrun', 'simctl', 'list', 'runtimes', '-j']),
             ('device-types', ['xcrun', 'simctl', 'list', 'devicetypes', '-j']),
             ('xattrs-before', ['xattr', '-lr', str(app)]),
             ('signature', ['codesign', '--verify', '--deep', '--strict', '--verbose=4', str(app)])]:
            result = run(name, command, timeout=30)
            if name != 'xattrs-before' and not ok(result):
                raise RuntimeError('Required setup observation failed: ' + name)
        runtimes = json.loads(read_output('runtimes'))['runtimes']
        if not any(r['identifier'] == RUNTIME and r['isAvailable'] for r in runtimes):
            raise RuntimeError('Required iOS 27.0 runtime is unavailable')
        with (OUT / 'live-services.log').open('wb') as stream:
            try:
                reader = subprocess.Popen(['/usr/bin/log', 'stream', '--style', 'compact', '--info',
                                           '--predicate', PREDICATE], stdout=stream, stderr=subprocess.STDOUT)
            except OSError as error:
                summary['log_reader_error'] = repr(error)
            device_case('PIPE', app, expected, summary['cases'], summary['cleanup_errors'])
            if summary['cases'][0].get('install', {}).get('timed_out'):
                device_case('FILE', app, expected, summary['cases'], summary['cleanup_errors'])
            if reader:
                stop_process(reader)
                summary['log_reader_returncode'] = reader.poll()
                if reader.returncode is not None:
                    reader = None
        run('xattrs-after', ['xattr', '-lr', str(app)])
        if (all('install' in c and 'error' not in c and c['app_unchanged']
                and 'pid' in c['install'] and 'error' not in c['install']
                and c['install'].get('returncode') is not None
                and not c['install'].get('observer_unfinished') for c in summary['cases'])
                and not summary['cleanup_errors']):
            summary['diagnostics_status'] = 'COMPLETE'
    except Exception as error:
        summary['error'] = repr(error)
    finally:
        if reader:
            stop_process(reader)
            summary['log_reader_returncode'] = reader.poll()
            if reader.returncode is None:
                summary['cleanup_errors'].append(dict(log_reader_pid=reader.pid, error='reader did not exit'))
        with LOCK:
            pending = list(ACTIVE.values())
        for process in pending:
            stop_process(process)
        summary['unfinished_command_pids'] = [process.pid for process in pending if process.poll() is None]
        if summary['unfinished_command_pids'] or summary['cleanup_errors']:
            summary['diagnostics_status'] = 'INCOMPLETE'
        if app:
            try:
                summary['app_unchanged'] = inventory(app) == expected and sha(args.app_tar.read_bytes()) == TAR_SHA
            except Exception as error:
                summary['app_unchanged'] = False
                summary['integrity_error'] = repr(error)
            if not summary['app_unchanged']:
                summary['diagnostics_status'] = 'INCOMPLETE'
        save('summary.json', summary)
    return 0 if summary['diagnostics_status'] == 'COMPLETE' else 1


if __name__ == '__main__':
    sys.exit(main())
