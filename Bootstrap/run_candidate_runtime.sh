#!/usr/bin/env bash
# Run the frozen candidate commands; Integrated phases share one runtime job.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  printf 'Require one exact runtime phase.\n' >&2
  exit 2
fi
runtime_phase=$1
case "${CANDIDATE:?}:$runtime_phase" in
  server:all|settings:all|statistics:all|icon:all|background:all|integrated:prepare|integrated:ui|integrated:simulator) ;;
  *) printf 'Unsupported candidate/runtime phase: %s/%s\n' "$CANDIDATE" "$runtime_phase" >&2; exit 2 ;;
esac
runtime_observer_bind() {
  "$runtime_common_python" -B - "$runtime_common_source_root" "$runtime_common_source_commit" "$@" <<'HOST_OBSERVER_BINDING'
import hashlib, pathlib, stat, subprocess, sys
root = pathlib.Path(sys.argv[1])
relative = 'Build/observed_command_status.py'
path = root / relative
if not root.is_absolute() or root.resolve(strict=True) != root or path.is_symlink() or path.parent.is_symlink():
    raise SystemExit('Status reader must be an unlinked file in the exact source root')
info = path.stat()
if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o644 or info.st_nlink != 1 or info.st_size != 16069:
    raise SystemExit('Status reader file type, mode, links or size differs')
raw = path.read_bytes()
expected_reader_sha256 = {
    'server': '8b1bc14a9ea2cc9c4fef28ed02bc69b8df171da201df7f0768047ab3d296ed90',
    'settings': '8b1bc14a9ea2cc9c4fef28ed02bc69b8df171da201df7f0768047ab3d296ed90',
    'statistics': '0c0b30dfa7613b41ab64a9f14c0d6af8423583010a6554d9124858264612801a',
    'integrated': '8b1bc14a9ea2cc9c4fef28ed02bc69b8df171da201df7f0768047ab3d296ed90',
}[sys.argv[4]]
if len(raw) != 16069 or hashlib.sha256(raw).hexdigest() != expected_reader_sha256:
    raise SystemExit('Status reader bytes differ from the frozen reader')
blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
entry = subprocess.run(['git', '-C', str(root), 'ls-tree', sys.argv[2], '--', relative], capture_output=True, timeout=10)
if entry.returncode != 0 or entry.stderr != b'' or entry.stdout != ('100644 blob ' + blob + '\t' + relative + '\n').encode():
    raise SystemExit('Status reader is not tracked exactly by the actual source commit')
sys.argv = [str(path), *sys.argv[3:]]
exec(compile(raw, str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})
HOST_OBSERVER_BINDING
}
case "$CANDIDATE" in
  server|settings) core=.build/core ;;
  statistics) core=.build/statistics-final-audit/core ;;
  *) core= ;;
esac
if [ -n "$core" ]; then
  server_ref=$(python3 -c 'import json; print(json.load(open("Build/upstream.json"))["sources"]["."])')
  git clone --no-checkout https://github.com/heiher/hev-socks5-server.git "$core"
  git -C "$core" checkout --detach "$server_ref"
  git -C "$core" submodule update --init --recursive
  python3 Build/check.py checkout "$core"
fi
case "$CANDIDATE" in
  server|settings|statistics|icon|integrated)
    runtime_common_source_root="$(pwd -P)"
    runtime_common_source_commit="$(git rev-parse HEAD)"
    runtime_common_source_tree="$(git rev-parse 'HEAD^{tree}')"
    runtime_common_cache="${RUNNER_TOOL_CACHE:?}/Python/3.14.9/arm64"
    runtime_common_python="$runtime_common_cache/bin/python3.14"
    if [[ ! -f "${runtime_common_cache}.complete" || ! -x "$runtime_common_python" ]]; then
      printf 'Required completed CPython3.14.9 arm64 cache is unavailable.\n' >&2
      exit 1
    fi
    runtime_common_helper=Build/runtime_environment.py
    if [ "$CANDIDATE" = icon ]; then runtime_common_helper=Tests/AppIcon/runtime_environment.py; fi
    runtime_common_args=(--mode candidate --owner "$CANDIDATE"
      --source-root "$runtime_common_source_root" --source-commit "$runtime_common_source_commit" --source-tree "$runtime_common_source_tree")
    runtime_common_control_root="${GITHUB_WORKSPACE:?}"
    runtime_common_control_tree="$(git -C "$runtime_common_control_root" rev-parse 'HEAD^{tree}')"
    runtime_common_args+=(--control-root "$runtime_common_control_root" --control-commit "$GITHUB_SHA" --control-tree "$runtime_common_control_tree")
    runtime_common_invoke() {
      "$runtime_common_python" "$runtime_common_helper" "$@" "${runtime_common_args[@]}"
    }
    if [[ "$runtime_phase" == all || "$runtime_phase" == prepare ]]; then
      # Capture real process status even under the original set -e discipline.
      if runtime_common_invoke prepare; then
        runtime_common_prepare_status=0
      else
        runtime_common_prepare_status=$?
      fi
      if runtime_common_invoke record-prepare-exit --actual-status "$runtime_common_prepare_status"; then
        runtime_common_record_status=0
      else
        runtime_common_record_status=$?
      fi
      if [ "$runtime_common_prepare_status" -ne 0 ]; then exit "$runtime_common_prepare_status"; fi
      if [ "$runtime_common_record_status" -ne 0 ]; then exit "$runtime_common_record_status"; fi
    fi
    ;;
esac
case "$CANDIDATE" in
  server)
    runtime_common_invoke before --consumer server-ui
    runtime_observer_bind before server server-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree"
    runtime_observer_output="$runtime_common_source_root/artifacts/server-control-ui-audit/runtime-preparation/consumers/server-ui/host-observation"
    if "$runtime_common_python" -B "$runtime_common_source_root/Build/observe_host_during_command.py" --output "$runtime_observer_output" -- python3 Tests/ServerControl/ui_audit.py; then
      runtime_observer_actual_status=0
    else
      runtime_observer_actual_status=$?
    fi
    runtime_common_original_status=
    if runtime_common_original_status="$(runtime_observer_bind after server server-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree" "$runtime_observer_actual_status")"; then
      runtime_observer_binding_status=0
    else
      runtime_observer_binding_status=$?
    fi
    if [[ "$runtime_common_original_status" =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$runtime_common_original_status" -le 255 ]; then
      if runtime_common_invoke after --consumer server-ui --actual-status "$runtime_common_original_status"; then
        runtime_common_after_status=0
      else
        runtime_common_after_status=$?
      fi
    else
      printf 'No trustworthy original exit status; no original-status after binding is claimed.\n' >&2
      if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
      exit 1
    fi
    if [ "$runtime_common_original_status" -ne 0 ]; then exit "$runtime_common_original_status"; fi
    if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
    if [ "$runtime_observer_binding_status" -ne 0 ]; then exit "$runtime_observer_binding_status"; fi
    if [ "$runtime_common_after_status" -ne 0 ]; then exit "$runtime_common_after_status"; fi
    ;;
  settings)
    runtime_common_invoke before --consumer settings-ui
    runtime_observer_bind before settings settings-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree"
    runtime_observer_output="$runtime_common_source_root/artifacts/settings-persistence-ui-audit/runtime-preparation/consumers/settings-ui/host-observation"
    if "$runtime_common_python" -B "$runtime_common_source_root/Build/observe_host_during_command.py" --output "$runtime_observer_output" -- python3 Tests/Settings/ui_audit.py; then
      runtime_observer_actual_status=0
    else
      runtime_observer_actual_status=$?
    fi
    runtime_common_original_status=
    if runtime_common_original_status="$(runtime_observer_bind after settings settings-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree" "$runtime_observer_actual_status")"; then
      runtime_observer_binding_status=0
    else
      runtime_observer_binding_status=$?
    fi
    if [[ "$runtime_common_original_status" =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$runtime_common_original_status" -le 255 ]; then
      if runtime_common_invoke after --consumer settings-ui --actual-status "$runtime_common_original_status"; then
        runtime_common_after_status=0
      else
        runtime_common_after_status=$?
      fi
    else
      printf 'No trustworthy original exit status; no original-status after binding is claimed.\n' >&2
      if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
      exit 1
    fi
    if [ "$runtime_common_original_status" -ne 0 ]; then exit "$runtime_common_original_status"; fi
    if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
    if [ "$runtime_observer_binding_status" -ne 0 ]; then exit "$runtime_observer_binding_status"; fi
    if [ "$runtime_common_after_status" -ne 0 ]; then exit "$runtime_common_after_status"; fi
    ;;
  icon)
    runtime_common_invoke before --consumer icon-ui
    if bash Tests/AppIcon/run_checks.sh; then
      runtime_common_original_status=0
    else
      runtime_common_original_status=$?
    fi
    if runtime_common_invoke after --consumer icon-ui --actual-status "$runtime_common_original_status"; then
      runtime_common_after_status=0
    else
      runtime_common_after_status=$?
    fi
    if [ "$runtime_common_original_status" -ne 0 ]; then exit "$runtime_common_original_status"; fi
    if [ "$runtime_common_after_status" -ne 0 ]; then exit "$runtime_common_after_status"; fi
    ;;
  background)
    python3 Tests/Background/native_inputs.py verify
    python3 Tests/Background/check_async_ui.py
    ;;
  statistics)
    runtime_common_invoke before --consumer statistics-ui
    runtime_observer_bind before statistics statistics-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree"
    runtime_observer_output="$runtime_common_source_root/artifacts/statistics-ui-audit/runtime-preparation/consumers/statistics-ui/host-observation"
    if "$runtime_common_python" -B "$runtime_common_source_root/Build/observe_host_during_command.py" --output "$runtime_observer_output" -- python3 Tests/Statistics/ui_audit.py; then
      runtime_observer_actual_status=0
    else
      runtime_observer_actual_status=$?
    fi
    runtime_common_original_status=
    if runtime_common_original_status="$(runtime_observer_bind after statistics statistics-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree" "$runtime_observer_actual_status")"; then
      runtime_observer_binding_status=0
    else
      runtime_observer_binding_status=$?
    fi
    if [[ "$runtime_common_original_status" =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$runtime_common_original_status" -le 255 ]; then
      if runtime_common_invoke after --consumer statistics-ui --actual-status "$runtime_common_original_status"; then
        runtime_common_after_status=0
      else
        runtime_common_after_status=$?
      fi
    else
      printf 'No trustworthy original exit status; no original-status after binding is claimed.\n' >&2
      if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
      exit 1
    fi
    if [ "$runtime_common_original_status" -ne 0 ]; then exit "$runtime_common_original_status"; fi
    if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
    if [ "$runtime_observer_binding_status" -ne 0 ]; then exit "$runtime_observer_binding_status"; fi
    if [ "$runtime_common_after_status" -ne 0 ]; then exit "$runtime_common_after_status"; fi
    ;;
  integrated)
    case "$runtime_phase" in
      prepare) ;;
      ui)
        runtime_common_invoke before --consumer integrated-ui
        runtime_observer_bind before integrated integrated-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree"
        runtime_observer_output="$runtime_common_source_root/artifacts/integrated/runtime-preparation/consumers/integrated-ui/host-observation"
        if "$runtime_common_python" -B "$runtime_common_source_root/Build/observe_host_during_command.py" --output "$runtime_observer_output" -- python3 Build/ui_review.py > artifacts/integrated/ui-review.log 2>&1; then
          runtime_observer_actual_status=0
        else
          runtime_observer_actual_status=$?
        fi
        runtime_common_original_status=
        if runtime_common_original_status="$(runtime_observer_bind after integrated integrated-ui "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree" "$runtime_observer_actual_status")"; then
          runtime_observer_binding_status=0
        else
          runtime_observer_binding_status=$?
        fi
        if [[ "$runtime_common_original_status" =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$runtime_common_original_status" -le 255 ]; then
          if runtime_common_invoke after --consumer integrated-ui --actual-status "$runtime_common_original_status"; then
            runtime_common_after_status=0
          else
            runtime_common_after_status=$?
          fi
        else
          printf 'No trustworthy original exit status; no original-status after binding is claimed.\n' >&2
          if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
          exit 1
        fi
        if [ "$runtime_common_original_status" -ne 0 ]; then exit "$runtime_common_original_status"; fi
        if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
        if [ "$runtime_observer_binding_status" -ne 0 ]; then exit "$runtime_observer_binding_status"; fi
        if [ "$runtime_common_after_status" -ne 0 ]; then exit "$runtime_common_after_status"; fi
        ;;
      simulator)
        runtime_common_invoke before --consumer integrated-simulator
        runtime_observer_bind before integrated integrated-simulator "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree"
        runtime_observer_output="$runtime_common_source_root/artifacts/integrated/runtime-preparation/consumers/integrated-simulator/host-observation"
        if "$runtime_common_python" -B "$runtime_common_source_root/Build/observe_host_during_command.py" --output "$runtime_observer_output" -- python3 Build/simulator_review.py > artifacts/integrated/simulator-review.log 2>&1; then
          runtime_observer_actual_status=0
        else
          runtime_observer_actual_status=$?
        fi
        runtime_common_original_status=
        if runtime_common_original_status="$(runtime_observer_bind after integrated integrated-simulator "$runtime_common_source_root" "$runtime_common_source_commit" "$runtime_common_source_tree" "$runtime_observer_actual_status")"; then
          runtime_observer_binding_status=0
        else
          runtime_observer_binding_status=$?
        fi
        if [[ "$runtime_common_original_status" =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$runtime_common_original_status" -le 255 ]; then
          if runtime_common_invoke after --consumer integrated-simulator --actual-status "$runtime_common_original_status"; then
            runtime_common_after_status=0
          else
            runtime_common_after_status=$?
          fi
        else
          printf 'No trustworthy original exit status; no original-status after binding is claimed.\n' >&2
          if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
          exit 1
        fi
        if [ "$runtime_common_original_status" -ne 0 ]; then exit "$runtime_common_original_status"; fi
        if [ "$runtime_observer_actual_status" -ne 0 ]; then exit "$runtime_observer_actual_status"; fi
        if [ "$runtime_observer_binding_status" -ne 0 ]; then exit "$runtime_observer_binding_status"; fi
        if [ "$runtime_common_after_status" -ne 0 ]; then exit "$runtime_common_after_status"; fi
        ;;
    esac
    ;;
  *) echo "Unsupported runtime candidate: $CANDIDATE" >&2; exit 1 ;;
esac
