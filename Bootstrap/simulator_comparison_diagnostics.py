#!/usr/bin/env python3
"""Bounded, read-only evidence for the isolated supported-pair comparison.

Never starts/stops a device, restarts a service, retries a failed gate, or changes
its result. Original process-control calls, deadlines and snapshots remain
unchanged. This proposal adds only a separate NOTE_EXIT observer and timing
markers; the instrumented process runner is no longer byte-identical.
Host evidence is collected even when a device has not finished boot.
"""
import json
from pathlib import Path
import subprocess
import sys
import time


"""Independent NOTE_EXIT observation; no process-control or reaping calls.

Only the existing five lifecycle commands are eligible. This instrumentation
adds scheduling overhead; it does not prove that an uninstrumented run has the
same timing. An event timestamp is delivery observation time, not exit time.
"""
import _thread
import hashlib
import select
import threading


_EXIT_LIMITS = {'create': 60, 'boot': 180, 'bootstatus': 120,
                'shutdown': 30, 'delete': 30}
_EXIT_MAX_ATTEMPTS = 5
_EXIT_SLICE_SECONDS = 0.05
_EXIT_FINISH_WAIT_SECONDS = 0.20
_EXIT_POST_DEADLINE_SECONDS = 2.0
_EXIT_ATTEMPTS = 0
_EXIT_ACTIVE = None
_EXIT_RUNTIME_CAPTURE_ATTEMPTED = False


def _exit_stamp():
    return {'monotonic_ns': time.monotonic_ns(), 'unix': time.time()}


def _exit_error(error):
    return {'type': type(error).__name__, 'message': str(error)[:2000],
            'errno': getattr(error, 'errno', None)}


def _exit_worker(state, queue):
    """Own and close this queue; never access the Popen object."""
    record = {'started': _exit_stamp(), 'events': [], 'empty_returns': 0,
              'control_calls': 0, 'error': None, 'close_error': None}
    try:
        # Fixed iteration cap also bounds a pathological early-return loop.
        for _ in range(state['max_control_calls']):
            if state['stop'].is_set():
                record['stop_reason'] = 'caller_finished_original_command'
                break
            remaining = (state['observer_deadline_monotonic_ns']
                         - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0:
                record['stop_reason'] = 'observer_budget_exhausted'
                break
            entered = _exit_stamp()
            events = queue.control(None, 1, min(_EXIT_SLICE_SECONDS, remaining))
            returned = _exit_stamp()
            record['control_calls'] += 1
            if not events:
                record['empty_returns'] += 1
                continue
            for event in events:
                raw = {'ident': event.ident, 'filter': event.filter,
                       'flags': event.flags, 'fflags': event.fflags,
                       'data': event.data, 'udata': event.udata,
                       'control_entered': entered, 'delivery_observed': returned}
                raw['is_requested_pid_note_exit'] = bool(
                    event.ident == state['pid']
                    and event.filter == select.KQ_FILTER_PROC
                    and event.fflags & select.KQ_NOTE_EXIT
                    and not event.flags & select.KQ_EV_ERROR)
                record['events'].append(raw)
                if event.flags & select.KQ_EV_ERROR:
                    record['stop_reason'] = 'kevent_error_event'
                    return
                if raw['is_requested_pid_note_exit']:
                    record['stop_reason'] = 'requested_note_exit_delivered'
                    return
            if len(record['events']) >= 8:
                record['stop_reason'] = 'unexpected_event_buffer_limit'
                break
        else:
            record['stop_reason'] = 'control_call_limit'
    except BaseException as error:
        # Observation failure never calls into or changes the original child.
        record['error'] = _exit_error(error)
        record['stop_reason'] = 'observer_exception'
    finally:
        try:
            queue.close()
        except BaseException as error:
            record['close_error'] = _exit_error(error)
        record['finished'] = _exit_stamp()
        # Publish once, after all writes and closing. The main thread reads the
        # completed result only after done; partial mutable records are omitted.
        state['worker_result'] = record
        state['done'].set()


def _exit_begin(command, pid, timeout):
    """Best effort: one registration, zero readiness wait, no retry."""
    global _EXIT_ATTEMPTS, _EXIT_ACTIVE
    state = None
    queue = None
    try:
        argv = list(map(str, command))
        if (len(argv) < 3 or argv[:2] != ['xcrun', 'simctl']
                or argv[2] not in _EXIT_LIMITS):
            return None
        state = {'schema': 1, 'command': argv, 'pid': pid,
                 'original_timeout_seconds': timeout,
                 'requested': _exit_stamp(), 'boundaries': [],
                 'registration': {}, 'worker_result': None,
                 'stop': threading.Event(), 'done': threading.Event(),
                 'status': 'not_started', 'error': None,
                 'observer_wait_slice_seconds': _EXIT_SLICE_SECONDS,
                 'finish_wait_budget_seconds': _EXIT_FINISH_WAIT_SECONDS}
        if timeout != _EXIT_LIMITS[argv[2]]:
            state['status'] = 'ineligible_timeout_observation_missing'
            return state
        if _EXIT_ATTEMPTS >= _EXIT_MAX_ATTEMPTS:
            state['status'] = 'attempt_limit_observation_missing'
            return state
        _EXIT_ATTEMPTS += 1
        state['attempt_number'] = _EXIT_ATTEMPTS
        if _EXIT_ACTIVE is not None and not _EXIT_ACTIVE['done'].is_set():
            state['status'] = 'prior_observer_not_finished_observation_missing'
            return state
        required = ('kqueue', 'kevent', 'KQ_FILTER_PROC', 'KQ_NOTE_EXIT',
                    'KQ_EV_ADD', 'KQ_EV_ONESHOT', 'KQ_EV_ERROR')
        if sys.platform != 'darwin' or any(not hasattr(select, n) for n in required):
            state['status'] = 'unsupported_platform_observation_missing'
            return state
        state['registration']['started'] = _exit_stamp()
        queue = select.kqueue()
        event = select.kevent(pid, filter=select.KQ_FILTER_PROC,
                              flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                              fflags=select.KQ_NOTE_EXIT)
        # Register only. No event wait, re-registration, status query, or reap.
        # Errors with no event-list capacity are reported by kevent as OSError.
        queue.control([event], 0, 0)
        state['registration']['completed'] = _exit_stamp()
        state['registration']['requested_flags'] = event.flags
        state['registration']['requested_fflags'] = event.fflags
        state['observer_deadline_monotonic_ns'] = (
            state['registration']['completed']['monotonic_ns']
            + int((timeout + _EXIT_POST_DEADLINE_SECONDS) * 1_000_000_000))
        state['max_control_calls'] = int(
            (timeout + _EXIT_POST_DEADLINE_SECONDS) / _EXIT_SLICE_SECONDS) + 4
        _EXIT_ACTIVE = state
        # This API returns the identifier without Thread.start's Python-level
        # startup Event.wait. No readiness handshake is added to the main path.
        state['thread_request_started'] = _exit_stamp()
        state['thread_identifier'] = _thread.start_new_thread(_exit_worker, (state, queue))
        queue = None  # sole close ownership has passed to the worker
        state['thread_request_returned'] = _exit_stamp()
        state['status'] = 'registered_worker_requested'
        return state
    except BaseException as error:
        if state is not None:
            state['status'] = 'observer_setup_error_observation_missing'
            state['error'] = _exit_error(error)
        else:
            warning('Kernel exit observer setup unavailable: ' + repr(error))
        return state
    finally:
        if queue is not None:
            try:
                queue.close()
            except BaseException as error:
                if state is not None:
                    state['setup_close_error'] = _exit_error(error)
        if state is not None and state['status'] != 'registered_worker_requested':
            state['done'].set()


def _exit_mark(state, label):
    if state is None:
        return
    try:
        state['boundaries'].append({'label': label, **_exit_stamp()})
    except BaseException as error:
        state['boundary_error'] = _exit_error(error)


def _exit_runtime_capture(out):
    """Actual executing interpreter and stdlib bytes; no subprocess/probe."""
    global _EXIT_RUNTIME_CAPTURE_ATTEMPTED
    if _EXIT_RUNTIME_CAPTURE_ATTEMPTED:
        return {'status': 'capture_already_attempted',
                'receipt': 'kernel-exit-python-runtime.json'}
    _EXIT_RUNTIME_CAPTURE_ATTEMPTED = True
    record = {'schema': 1, 'observed': _exit_stamp(),
              'sys_version': sys.version, 'sys_executable': sys.executable,
              'sys_implementation_name': sys.implementation.name,
              'subprocess_file': getattr(subprocess, '__file__', None),
              'subprocess_can_use_kqueue': getattr(subprocess, '_CAN_USE_KQUEUE', None),
              'subprocess_can_use_pidfd_open': getattr(subprocess, '_CAN_USE_PIDFD_OPEN', None),
              'source_status': 'not_read', 'source_error': None}
    try:
        source = Path(subprocess.__file__)
        with source.open('rb') as stream:
            data = stream.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('subprocess module exceeds observation source-byte budget')
        record['source_bytes'] = len(data)
        record['source_sha256'] = hashlib.sha256(data).hexdigest()
        record['source_output'] = 'kernel-exit-actual-subprocess.py'
        with (Path(out) / record['source_output']).open('xb') as stream:
            stream.write(data)
        record['source_status'] = 'whole_actual_module_bytes_saved'
    except BaseException as error:
        record['source_status'] = 'source_observation_missing'
        record['source_error'] = _exit_error(error)
    try:
        with (Path(out) / 'kernel-exit-python-runtime.json').open('x') as stream:
            stream.write(json.dumps(record, indent=2) + '\n')
        return {'status': 'receipt_saved', 'receipt': 'kernel-exit-python-runtime.json',
                'source_status': record['source_status']}
    except BaseException as error:
        return {'status': 'runtime_receipt_observation_missing', 'error': _exit_error(error),
                'runtime_record': record}


def _exit_finish(state, out, original_observation):
    """Persist after the original command; failures cannot replace its result."""
    if state is None:
        return
    try:
        state['finish_requested'] = _exit_stamp()
        state['stop'].set()
        done = state['done'].wait(_EXIT_FINISH_WAIT_SECONDS)
        state['finish_returned'] = _exit_stamp()
        record = {key: value for key, value in state.items()
                  if key not in ('stop', 'done', 'worker_result')}
        record['worker_completed_before_snapshot'] = done
        record['worker_result'] = state['worker_result'] if done else None
        record['incomplete_worker_data_omitted'] = not done
        record['original_process_observation'] = dict(original_observation)
        record['runtime_capture'] = _exit_runtime_capture(out)
        record['interpretation'] = {
            'event_times_are_delivery_observation_not_exact_exit': True,
            'missing_or_late_event_does_not_prove_child_alive': True,
            'data_is_not_interpreted_as_exit_status': True,
            'original_wait_reap_and_result_unchanged': True,
            'observer_setup_and_thread_scheduling_perturb_timing': True,
            'same_kqueue_mechanism_is_not_an_independent_kernel_or_python_implementation': True,
            'application_gate_credit': 0}
        with (Path(out) / 'kernel-exit-observations.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        original_observation['kernel_exit_observer'] = {
            'status': 'observation_saved', 'worker_completed': done,
            'setup_status': state['status'], 'evidence': 'kernel-exit-observations.jsonl'}
    except BaseException as error:
        original_observation['kernel_exit_observer'] = {
            'status': 'observation_missing', 'error': _exit_error(error)}
        warning('Kernel exit observation could not be saved: ' + repr(error))



def warning(message):
    try:
        print(message, file=sys.stderr, flush=True)
    except Exception:
        pass


def record_command(out, filename, command, timeout, started, started_unix,
                   failure=None, returncode=None):
    record = {'command': list(map(str, command)), 'timeout_seconds': timeout,
              'started_unix': started_unix, 'finished_unix': time.time(),
              'elapsed_seconds': time.monotonic() - started,
              'failure': type(failure).__name__ if failure else None,
              'returncode': returncode}
    try:
        with (Path(out) / filename).open('a') as stream:
            stream.write(json.dumps(record) + '\n')
    except Exception as error:
        if failure is None:
            raise
        warning('Command timing evidence could not be saved: ' + repr(error))


def output_bytes(value):
    if value is None:
        return b''
    return value if isinstance(value, bytes) else value.encode('utf-8')


def observed_run(command, *, out, timeout, cwd=None, capture_output=False,
                 text=False, stdout=None, stderr=None, check=False):
    """Run one command with the original deadline and observe its process boundary.

    A timeout remains a timeout even if poll() observes that the child exited.
    This distinguishes a live child from an exited child with inherited PIPEs;
    it does not infer when the Simulator itself finished changing state.
    """
    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError('capture_output cannot be combined with stdout/stderr')
        stdout = stderr = subprocess.PIPE
    started = time.monotonic()
    observation = {'command': list(map(str, command)), 'timeout_seconds': timeout,
                   'started_unix': time.time(), 'pid': None,
                   'stdout_is_pipe': stdout == subprocess.PIPE,
                   'stderr_is_pipe': stderr == subprocess.PIPE}
    failure = None
    kernel_observer = None
    try:
        with subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                              text=text) as process:
            observation['pid'] = process.pid
            kernel_observer = _exit_begin(command, process.pid, timeout)
            observation['communication_started_unix'] = time.time()
            observation['deadline_unix'] = observation['communication_started_unix'] + timeout
            try:
                _exit_mark(kernel_observer, 'communicate_enter')
                output, errors = process.communicate(timeout=timeout)
                _exit_mark(kernel_observer, 'communicate_return')
            except subprocess.TimeoutExpired:
                _exit_mark(kernel_observer, 'original_timeout_caught_before_poll')
                # Record before killing/reaping our child or starting any other
                # simctl command. poll() never changes a timeout into a pass.
                observation['timeout_observation'] = {
                    'observed_unix': time.time(),
                    'elapsed_seconds': time.monotonic() - started,
                    'poll_returncode': process.poll(),
                    'stdout_pipe_closed': getattr(process.stdout, 'closed', None),
                    'stderr_pipe_closed': getattr(process.stderr, 'closed', None)}
                _exit_mark(kernel_observer, 'original_timeout_kill_enter')
                process.kill()
                process.wait()
                _exit_mark(kernel_observer, 'original_timeout_wait_return')
                raise
            except BaseException:
                _exit_mark(kernel_observer, 'original_exception_kill_enter')
                process.kill()
                raise
            observation['returncode'] = process.poll()
            if check and observation['returncode']:
                raise subprocess.CalledProcessError(observation['returncode'], command,
                                                    output=output, stderr=errors)
            return subprocess.CompletedProcess(command, observation['returncode'], output, errors)
    except BaseException as error:
        failure = error
        raise
    finally:
        observation['finished_unix'] = time.time()
        observation['elapsed_seconds'] = time.monotonic() - started
        observation['failure'] = type(failure).__name__ if failure else None
        _exit_finish(kernel_observer, out, observation)
        try:
            with (Path(out) / 'process-observations.jsonl').open('a') as stream:
                stream.write(json.dumps(observation) + '\n')
        except Exception as error:
            if failure is None:
                raise
            warning('Process boundary evidence could not be saved: ' + repr(error))


def capture_failure(out, phase, device, failure):
    """Best effort, at most 20 seconds of diagnostic command time per capture."""
    try:
        folder = Path(out) / ('failure-' + phase)
        folder.mkdir(parents=True, exist_ok=True)
        receipt = {'phase': phase, 'device': device, 'original_error': repr(failure),
                   'started_unix': time.time(), 'budget_seconds': 20, 'commands': [],
                   'scope': 'Read-only failure evidence; no gate retry or device/service mutation.'}
        deadline = time.monotonic() + 20
        predicate = ('process == "CoreSimulatorService" OR process == "simulatord" '
                     'OR process == "Simulator" OR subsystem BEGINSWITH "com.apple.CoreSimulator" '
                     'OR process == "simdiskimaged" OR process == "diskarbitrationd" '
                     'OR process == "cryptexd" OR subsystem CONTAINS[c] "cryptex"')
        if device:
            # Device identifiers come from simctl create; JSON quoting prevents
            # interpretation as additional log-predicate syntax.
            predicate += ' OR eventMessage CONTAINS[c] ' + json.dumps(device)
        checks = [
            ('runtime-images', ['xcrun', 'simctl', 'runtime', 'list', '-j'], 4),
            ('processes', ['/bin/ps', '-axo', 'pid,ppid,state,etime,%cpu,%mem,comm'], 2),
            ('virtual-memory', ['/usr/bin/vm_stat'], 2),
            ('disk', ['/bin/df', '-k', str(Path(out).resolve())], 2),
            ('devices', ['xcrun', 'simctl', 'list', 'devices', '-j'], 4),
            ('host-core-simulator', ['/usr/bin/log', 'show', '--last', '5m',
                                    '--style', 'compact', '--info', '--predicate', predicate], 10),
        ]
        for label, command, limit in checks:
            remaining = deadline - time.monotonic()
            item = {'name': label, 'command': command}
            if remaining <= 0:
                item['error'] = 'Diagnostic capture budget exhausted; command not started'
            else:
                item['timeout_seconds'] = min(limit, remaining)
                started = time.monotonic()
                try:
                    # File output retains partial bytes even if the command times
                    # out, without borrowing subprocess PIPEs after its exit.
                    with (folder / (label + '.log')).open('wb') as log:
                        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                                timeout=item['timeout_seconds'])
                    item['returncode'] = result.returncode
                except Exception as error:
                    item['error'] = repr(error)
                item['elapsed_seconds'] = time.monotonic() - started
            receipt['commands'].append(item)
        receipt['finished_unix'] = time.time()
        (folder / 'capture.json').write_text(json.dumps(receipt, indent=2) + '\n')
    except Exception as error:
        warning('Failed to preserve Simulator diagnostics: ' + repr(error))
