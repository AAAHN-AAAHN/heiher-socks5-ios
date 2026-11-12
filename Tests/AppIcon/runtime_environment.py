#!/usr/bin/env python3
"""Observe installed runtime selection and bind unchanged original consumers.

Four CLI actions preserve source/control and actual original-status evidence.
They do not prepare a managed image, launch a consumer, or award product success.
"""
import argparse
import platform
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
import time

DEVELOPER = "/Applications/Xcode_27.app/Contents/Developer"

UUID_PATTERN = r"[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}"

TIMESTAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z"

META = 10

def require(ok, message):
    if not ok:
        raise ValueError(message)

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

def decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "Duplicate JSON key")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _value: require(False, "Nonfinite JSON number"))

def utc():
    return datetime.now(timezone.utc).isoformat()

def selection_identity(selection):
    runtime = selection["runtime"]
    if "lastUsage" in runtime:
        value = runtime["lastUsage"]
        require(type(value) is dict and set(value) == {"arm64"}
                and all(type(v) is str and re.fullmatch(TIMESTAMP, v) for v in value.values()),
                "Malformed logical lastUsage observation")
    return {"runtime": {k: v for k, v in runtime.items() if k != "lastUsage"}, "device": selection["device"]}

def file_identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid, "gid": info.st_gid, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}

class Capture:
    def __init__(self, root, output, report, save):
        self.root, self.output, self.report, self.save = root, output, report, save

    def run(self, label, argv, timeout=META, check=True, max_bytes=16 * 1024 * 1024, limit_files=False):
        require(not any(row["label"] == label for row in self.report["commands"]), "Repeated command label")
        item = {"label": label, "argv": argv, "cwd": str(self.root), "timeout_seconds": timeout,
                "started_utc": utc(), "started_monotonic": time.monotonic(), "launches": 0,
                "returncode": None, "timed_out": False, "owned_cli_kill_on_timeout": False,
                "environment_overrides": {"LC_ALL": "C", "TZ": "UTC"}, "capture_read_limit_bytes": max_bytes,
                "child_rlimit_fsize": max_bytes if limit_files else None,
                "owned_cli_reap_timeout_seconds": 5}
        self.report["commands"].append(item)
        self.save()
        streams, process, error = [], None, None
        try:
            for kind in ("stdout", "stderr"):
                path = self.output / (label + "." + kind + ".log")
                streams.append(path.open("xb"))
                path.chmod(0o600)
                item[kind] = str(path)
            def limit():
                old = resource.getrlimit(resource.RLIMIT_FSIZE)
                finite = [n for n in old if n != resource.RLIM_INFINITY]
                actual = min([max_bytes, *finite])
                resource.setrlimit(resource.RLIMIT_FSIZE, (actual, actual))
            process = subprocess.Popen(argv, cwd=self.root, stdin=subprocess.DEVNULL,
                stdout=streams[0], stderr=streams[1], env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
                preexec_fn=limit if limit_files else None)
            item.update(launches=1, pid=process.pid)
            try:
                item["returncode"] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                item["timed_out"] = True
                item["owned_cli_kill_on_timeout"] = True
                process.kill()
                try:
                    item["returncode"] = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    item["reaped"] = False
                    raise TimeoutError("Owned CLI was not reaped within the separate five-second cleanup limit")
            item["reaped"] = process.returncode is not None
        except Exception as exc:
            error = exc
            item["error"] = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            for stream in streams:
                stream.close()
            item.update(finished_utc=utc(), elapsed_seconds=time.monotonic() - item["started_monotonic"])
            item["files"] = {}
            for kind in ("stdout", "stderr"):
                if kind in item and Path(item[kind]).exists():
                    path = Path(item[kind])
                    stable = process is None or item.get("reaped") is True
                    item["files"][kind] = {"bytes_observed": path.stat().st_size, "stable_after_reap": stable}
                    if stable:
                        with path.open("rb") as stream:
                            item["files"][kind]["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            self.save()
        # Optional observation can tolerate a reaped failure, never a live child.
        require(process is None or item.get("reaped") is True, "Owned CLI was not reaped; no later live action is allowed")
        require(all(row["bytes_observed"] <= max_bytes for row in item["files"].values()), "Captured output exceeds read bound")
        if check:
            if error:
                raise error
            require(not item["timed_out"] and item["returncode"] == 0, "Command failed: " + label)
        if "stdout" in item and Path(item["stdout"]).exists():
            require(Path(item["stdout"]).stat().st_size <= max_bytes, "Captured stdout exceeds read bound")
            return Path(item["stdout"]).read_bytes()
        return b""

OWNER_PROFILES = {'server': {'feature_name': 'server-control',
            'helper_paths': ['Build/runtime_environment.py'],
            'consumers': {'server-ui': {'command': 'python3 Tests/ServerControl/ui_audit.py',
                                        'receipt': 'artifacts/server-control-ui-audit/runtime.json',
                                        'runtime_key': 'runtime',
                                        'device_key': 'deviceType',
                                        'bootstatus_seconds': 120}},
            'original_files': {'Tests/ServerControl/ui_audit.py': {'sha256': 'e037912a1a4a0caad1ea3fe221dd02d9ed2509ce2661727da0fc65dd74438363',
                                                                   'git_mode': '100644'}},
            'original_consumer_deadlines': {'server-ui': {'create': 60,
                                                          'boot': 180,
                                                          'bootstatus': 120,
                                                          'shutdown': 30,
                                                          'delete': 30,
                                                          'ui_test': 900}},
            'preparation_root': 'artifacts/server-control-ui-audit/runtime-preparation',
            'existing_canonical_job_minutes': 30},
 'statistics': {'feature_name': 'traffic-statistics',
                'helper_paths': ['Build/runtime_environment.py'],
                'consumers': {'statistics-ui': {'command': 'python3 Tests/Statistics/ui_audit.py',
                                                'receipt': 'artifacts/statistics-ui-audit/runtime.json',
                                                'runtime_key': 'runtime',
                                                'device_key': 'deviceType',
                                                'bootstatus_seconds': 120}},
                'original_files': {'Tests/Statistics/ui_audit.py': {'sha256': '0e517eebbf8ffb59edde9f3cc12ec0919b6955e297917a902c014a35cbcd9d54',
                                                                    'git_mode': '100644'}},
                'original_consumer_deadlines': {'statistics-ui': {'create': 60,
                                                                  'boot': 180,
                                                                  'bootstatus': 120,
                                                                  'shutdown': 30,
                                                                  'delete': 30,
                                                                  'ui_test': 900}},
                'preparation_root': 'artifacts/statistics-ui-audit/runtime-preparation',
                'existing_canonical_job_minutes': 35},
 'settings': {'feature_name': 'settings-persistence',
              'helper_paths': ['Build/runtime_environment.py'],
              'consumers': {'settings-ui': {'command': 'python3 Tests/Settings/ui_audit.py',
                                            'receipt': 'artifacts/settings-persistence-ui-audit/runtime.json',
                                            'runtime_key': 'runtime',
                                            'device_key': 'deviceType',
                                            'bootstatus_seconds': 120}},
              'original_files': {'Tests/Settings/ui_audit.py': {'sha256': '4c336a80d96afbbcd169061987a4a09e976c499f9e833b95e9c857232ac15074',
                                                                'git_mode': '100644'}},
              'original_consumer_deadlines': {'settings-ui': {'create': 60,
                                                              'boot': 180,
                                                              'bootstatus': 120,
                                                              'shutdown': 30,
                                                              'delete': 30,
                                                              'ui_test': 900,
                                                              'build_for_testing': 900}},
              'preparation_root': 'artifacts/settings-persistence-ui-audit/runtime-preparation',
              'existing_canonical_job_minutes': 30},
 'icon': {'feature_name': 'app-icon',
          'helper_paths': ['Tests/AppIcon/runtime_environment.py'],
          'consumers': {'icon-ui': {'command': 'bash Tests/AppIcon/run_checks.sh',
                                    'receipt': 'artifacts/icon-checks/runtime.json',
                                    'runtime_key': None,
                                    'device_key': None,
                                    'bootstatus_seconds': 240}},
          'original_files': {'Tests/AppIcon/run_checks.sh': {'sha256': 'deb568cfc732699922a23bfd09dee909d8a0d82e0866ffc0b2a8c879eb02a68b',
                                                             'git_mode': '100755'},
                             'Tests/AppIcon/check_compiled.py': {'sha256': '2c08bd5dcd416aafa06d1850c134226e8ce7af75eacd386b0c43b44c4ef524ce',
                                                                 'git_mode': '100644'}},
          'original_consumer_deadlines': {'icon-ui': {'create': 120,
                                                      'boot': 120,
                                                      'bootstatus': 240,
                                                      'shutdown': 30,
                                                      'delete': 30}},
          'preparation_root': 'artifacts/icon-checks/runtime-preparation',
          'existing_canonical_job_minutes': 20},
 'integrated': {'feature_name': 'integrated',
                'helper_paths': ['Build/runtime_environment.py', 'Tests/AppIcon/runtime_environment.py'],
                'consumers': {'integrated-ui': {'command': 'python3 Build/ui_review.py > '
                                                           'artifacts/integrated/ui-review.log 2>&1',
                                                'receipt': 'artifacts/integrated/ui/environment.json',
                                                'runtime_key': 'runtime',
                                                'device_key': 'device',
                                                'bootstatus_seconds': 120},
                              'integrated-simulator': {'command': 'python3 Build/simulator_review.py > '
                                                                  'artifacts/integrated/simulator-review.log '
                                                                  '2>&1',
                                                       'receipt': 'artifacts/integrated/simulator/environment.json',
                                                       'runtime_key': 'runtime',
                                                       'device_key': 'device_type',
                                                       'bootstatus_seconds': 240}},
                'original_files': {'Build/ui_review.py': {'sha256': '8543e09fc88eb4d7d38f83eec65284bf8be8c1460991c600ac363434076d6344',
                                                          'git_mode': '100644'},
                                   'Build/simulator_review.py': {'sha256': 'e1897dd4aba4702ad6ee28332fa6d614606260e05c98c310ba6a4464c9e4590f',
                                                                 'git_mode': '100644'}},
                'original_consumer_deadlines': {'integrated-ui': {'create': 60,
                                                                  'boot': 180,
                                                                  'bootstatus': 120,
                                                                  'shutdown': 30,
                                                                  'delete': 30,
                                                                  'ui_test': 1800,
                                                                  'build_for_testing': 900},
                                                'integrated-simulator': {'create': 120,
                                                                         'boot': 120,
                                                                         'bootstatus': 240,
                                                                         'shutdown': 30,
                                                                         'delete': 30}},
                'preparation_root': 'artifacts/integrated/runtime-preparation',
                'existing_canonical_job_minutes': 75}}

ORIGINAL_RESTORER_SHA256 = "228dbcc1e3e28e682e1d956fd91a9100add223e613bb4aa09d47231e16499580"

def original_selection(consumer, runtimes, types):
    if consumer in ("server-ui", "statistics-ui", "settings-ui"):
        runtime = next(r for r in runtimes if r.get("isAvailable") and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27-"))
        device = next(d for d in types if d["name"] == "iPhone 16")
    elif consumer == "integrated-ui":
        runtime = next(r for r in runtimes if r.get("isAvailable") and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27"))
        device = next(d for d in types if d["name"] == "iPhone 16")
    elif consumer == "integrated-simulator":
        runtime = next(r for r in runtimes if r["isAvailable"] and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27"))
        device = next(t["identifier"] for t in types if t["name"] == "iPhone 16")
    elif consumer == "icon-ui":
        runtime = next(r for r in runtimes if r["isAvailable"] and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-27"))
        device = "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
    else:
        raise ValueError("Unknown original consumer")
    return {"runtime": runtime, "device": device}

def full_sha(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value),
                     "An exact full Git SHA is required")
    return value

def positive_decimal(value):
    require(type(value) in (str, int) and re.fullmatch(r"[1-9][0-9]*", str(value)),
                     "A positive run/attempt/artifact/job ID is required")
    return str(value)

def safe_relative(value):
    require(type(value) is str and value not in ("", ".") and "\\" not in value
                     and not any(ord(c) < 32 or ord(c) == 127 for c in value), "Unsafe relative path")
    path = Path(value)
    require(not path.is_absolute() and path.as_posix() == value and ".." not in path.parts,
                     "Unsafe relative path")
    return value

def unlinked_path(path, root):
    require(path.is_absolute() and root.is_absolute() and path.is_relative_to(root),
                     "Path must be inside the declared absolute source root")
    for item in (path, *path.parents):
        require(not item.is_symlink(), "Symlink in source/evidence path: " + str(item))
        if item == root:
            break
    return path

def absolute_root(value):
    path = Path(value)
    require(path.is_absolute() and path.is_dir() and path.resolve() == path,
                     "Require an existing exact absolute source/control root without aliases")
    for item in (path, *path.parents):
        require(not item.is_symlink(), "Linked source/control root")
    return path

def regular_bytes(path, root, maximum=8 * 1024 * 1024):
    unlinked_path(path, root)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= maximum,
                     "Expected a bounded non-symlink regular evidence/source file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(file_identity(os.fstat(stream.fileno())) == file_identity(before),
                         "File changed before opening")
        raw = stream.read(maximum + 1)
        require(len(raw) <= maximum and file_identity(os.fstat(stream.fileno())) == file_identity(before),
                         "File changed or exceeded its read limit")
    require(file_identity(path.lstat()) == file_identity(before), "File changed during read")
    return raw, {"path": str(path), "bytes": len(raw), "sha256": digest(raw),
                 "mode": stat.S_IMODE(before.st_mode)}

def git_read(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments], timeout=META)

def git_root_identity(root, declared_commit, declared_tree):
    full_sha(declared_commit); full_sha(declared_tree)
    require(git_read(root, "rev-parse", "--show-toplevel").decode().strip() == str(root),
                     "The declared root is not the exact Git worktree root")
    commit = git_read(root, "rev-parse", "HEAD").decode().strip()
    tree = git_read(root, "rev-parse", "HEAD^{tree}").decode().strip()
    require(commit == declared_commit and tree == declared_tree, "Declared source/control commit or tree differs")
    git_read(root, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--exit-code", commit, "--")
    return {"commit": commit, "tree": tree}

def tracked_regular_file(root, commit, relative, expected_sha256=None, expected_git_mode="100644"):
    relative = safe_relative(relative)
    raw_tree = git_read(root, "ls-tree", "-z", commit, "--", relative)
    rows = [row for row in raw_tree.split(b"\0") if row]
    require(len(rows) == 1, "Require one exact tracked source path")
    meta, name = rows[0].split(b"\t", 1)
    mode, kind, blob = meta.decode().split()
    require(expected_git_mode in ("100644", "100755") and name.decode() == relative
                     and mode == expected_git_mode and kind == "blob",
                     "Helper/config/consumer must match its exact regular Git mode")
    full_sha(blob)
    index = git_read(root, "ls-files", "--stage", "-z", "--", relative)
    require(index == (mode + " " + blob + " 0\t" + relative + "\0").encode(),
                     "Source index entry differs from the exact committed helper/input")
    raw, descriptor = regular_bytes(root / relative, root)
    require(bool(descriptor["mode"] & 0o100) == (mode == "100755"),
                     "Tracked helper/input executable bit differs from Git")
    actual_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(actual_blob == blob and raw == git_read(root, "cat-file", "blob", blob),
                     "Tracked source bytes differ, including index-flag-hidden changes")
    if expected_sha256 is not None:
        require(descriptor["sha256"] == expected_sha256, "Original consumer/input bytes changed")
    return raw, {**descriptor, "relative_path": relative, "git_mode": mode, "git_blob": blob}

def validate_host():
    require(__debug__ and sys.implementation.name == "cpython" and sys.platform == "darwin"
                     and platform.machine() == "arm64" and tuple(sys.version_info) == (3, 14, 9, "final", 0)
                     and os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
                     and os.environ.get("RUNNER_OS") == "macOS" and os.getuid() == os.geteuid() and os.getuid() > 0
                     and os.environ.get("DEVELOPER_DIR") == DEVELOPER,
                     "Require the declared completed CPython cache and hosted Darwin arm64 own-UID environment")
    cache = absolute_root(os.environ["RUNNER_TOOL_CACHE"])
    entry = cache / "Python/3.14.9/arm64"
    require(Path(sys.executable).resolve() == (entry / "bin/python3.14").resolve()
                     and Path(str(entry) + ".complete").is_file(), "Interpreter is not the declared completed cache entry")

def validate_current_environment(source, control, mode):
    actual_control = full_sha(os.environ["GITHUB_SHA"])
    require(control["commit"] == actual_control, "Actual control checkout differs from GITHUB_SHA")
    if mode == "canonical":
        require(source == control and source["commit"] == actual_control,
                         "Canonical source must be the actual workflow source; do not relabel a different checkout")
    else:
        require(mode == "candidate", "Unknown identity mode")
    repository, job = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_JOB"]
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                     and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job), "Invalid repository/job identity")
    return {"repository": repository, "run_id": positive_decimal(os.environ["GITHUB_RUN_ID"]),
            "attempt": positive_decimal(os.environ["GITHUB_RUN_ATTEMPT"]), "job": job,
            "helper": control, "runner_os": "macOS"}

def git_ref_commit(root, reference):
    # Exact read-only resolution; the input is an argv element, never shell code.
    value = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "--end-of-options",
                            reference + "^{commit}"], capture_output=True, timeout=META)
    require(value.returncode in (0, 1), "Git could not inspect the explicit checkout input")
    if value.returncode:
        return None
    return full_sha(value.stdout.decode().strip())

def bind_workflow_input_ref(root, supplied, source, resolver=git_ref_commit):
    require(type(supplied) is str and supplied != "" and "\x00" not in supplied,
                     "A nonempty actual workflow input ref is required")
    # Match the pinned actions/checkout11d596 input-helper/ref-helper rules.
    # Preserve the raw input separately. The action's SHA classification uses
    # ASCII trim; branch/tag lookup uses core.getInput's ECMAScript trim.
    ascii_ref = supplied.strip("\t\n\v\f\r ")
    js_whitespace = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
    effective = supplied.strip(js_whitespace)
    if not effective:
        kind, reference, resolved = "action-empty-input-context-default", os.environ["GITHUB_SHA"], full_sha(os.environ["GITHUB_SHA"])
    elif re.fullmatch(r"[0-9a-fA-F]{40}", ascii_ref):
        kind, reference, resolved = "exact-commit", ascii_ref, ascii_ref.lower()
    else:
        upper = effective.upper()
        if upper.startswith("REFS/HEADS/"):
            kind, reference = "qualified-branch", "refs/remotes/origin/" + effective[len("refs/heads/"):]
        elif upper.startswith("REFS/PULL/"):
            kind, reference = "qualified-pull", "refs/remotes/pull/" + effective[len("refs/pull/"):]
        elif upper.startswith("REFS/"):
            kind, reference = "qualified-ref", effective
        else:
            kind, reference = "unqualified-branch", "refs/remotes/origin/" + effective
            resolved = resolver(root, reference)
            if resolved is None:
                kind, reference = "unqualified-tag", "refs/tags/" + effective
            else:
                require(resolved == source["commit"], "Explicit workflow branch does not resolve to actual checkout")
                return {"raw_input_ref": supplied, "action_ascii_trimmed_ref": ascii_ref, "action_effective_ref": effective,
                        "kind": kind, "resolved_local_reference": reference, "resolved_commit": resolved,
                        "actual_source": source, "resolution_scope": "Original checkout already fetched this input; no new fetch or checkout."}
        resolved = resolver(root, reference)
    require(resolved is not None and resolved == source["commit"],
                     "Explicit workflow ref does not resolve to the actual selected source checkout")
    return {"raw_input_ref": supplied, "action_ascii_trimmed_ref": ascii_ref, "action_effective_ref": effective,
            "kind": kind, "resolved_local_reference": reference, "resolved_commit": resolved,
            "actual_source": source, "resolution_scope": "Original checkout already fetched this input; no new fetch or checkout."}

def workflow_input_environment(request, root, source):
    require(request["owner"] == "statistics" and request["mode"] == "workflow-input",
                     "Explicit workflow-input mode is limited to the original Statistics reusable runtime step")
    require(all(request.get(name) is None for name in ("control_root", "control_commit", "control_tree")),
                     "Workflow-input mode must not assert a nonexistent caller control checkout")
    supplied = request.get("workflow_input_ref")
    require(supplied == os.environ.get("RUNTIME_COMMON_SOURCE_REF"),
                     "Declared source ref differs from the actual workflow input environment")
    binding = bind_workflow_input_ref(root, supplied, source)
    repository, job = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_JOB"]
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                     and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job), "Invalid actual caller repository/job context")
    caller = {"github_sha": full_sha(os.environ["GITHUB_SHA"]), "repository": repository,
              "run_id": positive_decimal(os.environ["GITHUB_RUN_ID"]), "attempt": positive_decimal(os.environ["GITHUB_RUN_ATTEMPT"]),
              "job": job, "runner_os": "macOS", "github_workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF"),
              "github_workflow_sha": os.environ.get("GITHUB_WORKFLOW_SHA"),
              "binding_kind": "Actual GitHub caller environment; no caller checkout or caller source-tree equality is claimed."}
    if caller["github_workflow_sha"] is not None:
        full_sha(caller["github_workflow_sha"])
    return caller, binding

def validate_candidate_receipt(value, owner, source, pins, consumer, matrix):
    require(consumer["job"] == "runtime", "Candidate preparation belongs to the unchanged runtime job")
    matches = [row for row in matrix["matrix"] if row["name"] == owner and row["os"] == "xcode-27"]
    require(len(matches) == 1 and matches[0]["sha"] == source["commit"] and matches[0].get("runtime") is True,
                     "Candidate matrix differs from actual source and required runtime coverage")
    require(value.get("status") == "VERIFIED_RUNTIME_INPUT_RESTORED" and value.get("consumer") == consumer,
                     "Original restored consumer context differs from this source/control/run/attempt/job")
    manifest = value["manifest"]
    require(type(manifest["schema"]) is int and manifest["schema"] == 1
                     and manifest["candidate"] == owner and manifest["source"] == source
                     and manifest["native_pins"] == pins and isinstance(manifest["files"], dict) and manifest["files"],
                     "Original restored manifest source/pins/files differ")
    for name, entry in manifest["files"].items():
        safe_relative(name)
        require(type(entry) is dict and set(entry) == {"size", "sha256", "mode"}
                         and type(entry["size"]) is int and entry["size"] >= 0
                         and type(entry["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                         and type(entry["mode"]) is int and entry["mode"] in (0o644, 0o755),
                         "Original restored manifest file identity is malformed")
    producer = manifest["producer"]
    attempt = positive_decimal(producer["attempt"])
    require(int(attempt) <= int(consumer["attempt"])
                     and producer == {**consumer, "attempt": attempt, "job": "build"},
                     "Original producer source/control/run/job or attempt differs")
    job = value["producer_job"]
    positive_decimal(job["id"])
    require(job["name"] == f"build ({owner}, {source['commit']}, xcode-27, true)"
                     and positive_decimal(job["run_id"]) == producer["run_id"]
                     and positive_decimal(job["run_attempt"]) == attempt
                     and job["head_sha"] == consumer["helper"]["commit"]
                     and job["status"] == "completed" and job["conclusion"] == "success",
                     "Original numeric producer job identity/result differs")
    steps = [row for row in job["steps"] if row["name"] == "Execute the exact candidate owner gates"]
    require(len(steps) == 1 and steps[0]["conclusion"] == "success", "Original producer gate step did not succeed")
    positive_decimal(value["input_artifact_id"]); positive_decimal(value["input_artifact_size"])
    require(type(value["input_artifact_digest"]) is str
                     and re.fullmatch(r"sha256:[0-9a-f]{64}", value["input_artifact_digest"])
                     and type(value["archive_sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["archive_sha256"]),
                     "Original restored immutable archive identity is malformed")
    return {"producer": producer, "producer_job_id": job["id"], "input_artifact_id": value["input_artifact_id"],
            "input_artifact_digest": value["input_artifact_digest"], "input_artifact_size": value["input_artifact_size"],
            "archive_sha256": value["archive_sha256"], "matrix_row": matches[0],
            "scope": "Rebind the original successful restorer result; this adapter neither restores nor grants runtime success."}

def context_for(request):
    validate_host()
    owner = request["owner"]
    require(owner in OWNER_PROFILES, "Owner has no reviewed runtime preparation profile")
    profile = OWNER_PROFILES[owner]
    root = absolute_root(request["source_root"])
    require(Path.cwd() == root, "Invoke from the explicitly verified source root, independent of helper depth")
    source = git_root_identity(root, request["source_commit"], request["source_tree"])
    if request["mode"] == "workflow-input":
        control_root = control = None
        consumer, input_binding = workflow_input_environment(request, root, source)
    else:
        require(request.get("workflow_input_ref") is None,
                         "Canonical/candidate modes do not accept an unbound extra workflow source ref")
        control_root = absolute_root(request["control_root"])
        control = source if request["mode"] == "canonical" and control_root == root else git_root_identity(
            control_root, request["control_commit"], request["control_tree"])
        require(control == {"commit": request["control_commit"], "tree": request["control_tree"]},
                         "Declared control tuple differs")
        consumer = validate_current_environment(source, control, request["mode"])
    helpers = {}
    for relative in profile["helper_paths"]:
        raw, info = tracked_regular_file(root, source["commit"], relative)
        helpers[relative] = info
    active = profile["helper_paths"][0]
    require(Path(__file__).resolve() == root / active,
                     "Invoke the actual owner helper path, not a control copy or inherited alternate")
    require(len({(row["sha256"], row["git_blob"], row["git_mode"]) for row in helpers.values()}) == 1,
                     "Integrated owned/inherited helper entries are not the same blob/mode")
    raw_features, features_info = tracked_regular_file(root, source["commit"], "Build/features.json")
    features = decode(raw_features)
    require(features["name"] == profile["feature_name"], "Wrong actual source owner composition")
    pins = features["sources"]
    require(type(pins) is dict and pins, "Native source pins are missing")
    for path, commit in pins.items():
        if path != ".":
            safe_relative(path)
        full_sha(commit)
    consumers = {}
    for relative, expected in profile["original_files"].items():
        _, consumers[relative] = tracked_regular_file(root, source["commit"], relative,
                                                      expected["sha256"], expected["git_mode"])
    result = {"mode": request["mode"], "source_root": str(root), "control_root": str(control_root) if control_root is not None else None,
              "owner": owner, "source": source, "control": control, "consumer": consumer,
              "own_helper_relative_path": active, "own_helper_sha256": helpers[active]["sha256"],
              "helper_files": {name: row["sha256"] for name, row in helpers.items()},
              "helper_git_entries": helpers, "features_file": features_info, "native_pins": pins,
              "original_consumer_files": consumers, "preparation_policy": "installed-runtime-source-v1"}
    if request["mode"] == "workflow-input":
        result["actual_caller_environment"] = consumer
        result["workflow_input_binding"] = input_binding
    if request["mode"] == "candidate":
        raw_matrix, matrix_info = tracked_regular_file(control_root, control["commit"], "Bootstrap/candidates.json")
        _, restorer_info = tracked_regular_file(control_root, control["commit"], "Bootstrap/runtime_handoff.py",
                                                ORIGINAL_RESTORER_SHA256)
        receipt_path = root / "artifacts/runtime-input" / owner / "consumer.json"
        raw_receipt, receipt_info = regular_bytes(receipt_path, root, maximum=64 * 1024 * 1024)
        result["original_restorer_binding"] = {"matrix": matrix_info, "restorer": restorer_info, "receipt": receipt_info,
            "identity": validate_candidate_receipt(decode(raw_receipt), owner, source, pins, consumer, decode(raw_matrix))}
    return result

def recheck_context(request, expected):
    require(context_for(request) == expected, "Actual source/control/evidence identity changed between phases")

def preparation_root(context):
    root = Path(context["source_root"])
    return unlinked_path(root / OWNER_PROFILES[context["owner"]]["preparation_root"], root)

def read_bound_json(path, root, expected=None):
    raw, descriptor = regular_bytes(path, root, maximum=64 * 1024 * 1024)
    if expected is not None:
        require(descriptor == expected, "Saved evidence bytes/mode/path differ from their exact descriptor")
    return decode(raw), descriptor

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def consumer_profile(context, consumer):
    profiles = OWNER_PROFILES[context["owner"]]["consumers"]
    require(consumer in profiles, "Consumer is outside the actual source owner")
    return profiles[consumer]

def write_json(path, value, root, replace=False):
    unlinked_path(path, root)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    require(len(raw) <= 64 * 1024 * 1024, "Preparation receipt exceeded its finite read bound")
    temporary = path.with_name(path.name + ".tmp")
    unlinked_path(temporary, root)
    require(replace or not path.exists(), "Immutable receipt already exists")
    with temporary.open("xb") as stream:
        temporary.chmod(0o600)
        stream.write(raw)
    if path.exists():
        require(replace and path.is_file() and not path.is_symlink(), "Progress receipt target is not regular")
    os.replace(temporary, path)
    return regular_bytes(path, root, maximum=64 * 1024 * 1024)[1]

def failure_record(report, where, error):
    report["errors"].append({"where": where, "type": type(error).__name__, "message": str(error)})

def readback_commands(report, root):
    """Bind saved streams once at the preparation caller boundary; no replay."""
    labels, files = set(), []
    for command in report["commands"]:
        require(command["label"] not in labels and command.get("launches") == 1
                and command.get("reaped") is True, "Preparation command did not finish exactly once")
        labels.add(command["label"])
        for channel in ("stdout", "stderr"):
            path = Path(command[channel])
            require(path.name == command["label"] + "." + channel + ".log",
                    "Preparation stream name differs")
            _, info = regular_bytes(path, root, maximum=command["capture_read_limit_bytes"])
            recorded = command["files"][channel]
            require(recorded["stable_after_reap"] is True and info["bytes"] == recorded["bytes_observed"]
                    and info["sha256"] == recorded["sha256"], "Saved preparation stream changed")
            files.append(info)
    return files

def validate_original_receipt(value, before, profile, consumer):
    runtime = value if profile["runtime_key"] is None else value[profile["runtime_key"]]
    device = before["selection"]["device"] if profile["device_key"] is None else value[profile["device_key"]]
    selection = {"runtime": runtime, "device": device}
    require(canonical(selection_identity(selection)) == canonical(selection_identity(before["selection"])),
            "Actual original receipt selected another runtime/device")
    if profile["device_key"] is not None:
        require(type(value.get("udid")) is str and re.fullmatch(UUID_PATTERN, value["udid"]),
                "Original receipt lacks its actual created-device identity")
    return {"runtime": runtime, "device": None if profile["device_key"] is None else device,
            "scope": "Original selection only; application assertions and success remain the original consumer's responsibility."}

def observer_status(context, consumer, before_info, original_status):
    if consumer == "icon-ui":
        return None, None
    root = Path(context["source_root"])
    path = preparation_root(context) / "consumers" / consumer / "host-observer-after.json"
    value, info = read_bound_json(path, root)
    require(value.get("schema") == "formal-host-observer-caller-binding-v1"
            and value.get("phase") == "after" and value.get("owner") == context["owner"]
            and value.get("consumer") == consumer and value.get("source") == context["source"]
            and value.get("source_root") == str(root) and value.get("common_identity") == context
            and all(value["common_before"][key] == before_info[key] for key in ("path", "bytes", "sha256", "mode"))
            and value.get("original_status_recovered") is True
            and type(value.get("original_shell_status")) is int
            and value["original_shell_status"] == original_status
            and type(value.get("actual_wrapper_status")) is int and 0 <= value["actual_wrapper_status"] <= 255,
            "Original status/observer binding differs from this exact before receipt")
    require(value.get("result") == "BOUND_ACTUAL_ORIGINAL_AND_OBSERVER_EXITS" and "failure" not in value,
            "Observer reader did not complete its secondary evidence binding")
    return value["actual_wrapper_status"], info

# New four-command adapter. Existing source/control and original-consumer
# routines are copied verbatim from the reviewed FA r2 source unless listed.

PREPARE_SCHEMA = "installed-runtime-source-observation-v1"
EXIT_SCHEMA = "installed-runtime-source-caller-exit-v1"
BEFORE_SCHEMA = "installed-runtime-consumer-before-v1"
AFTER_SCHEMA = "installed-runtime-consumer-after-v1"


def capture_for(context, output, report, progress_name):
    root = Path(context["source_root"])
    unlinked_path(output, root)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    return Capture(root, output, report,
                   lambda: write_json(output / progress_name, report, root, replace=True))


def observe_selection(capture, label, consumers):
    observed = {"label": label, "started_utc": utc()}
    observed["logical"] = decode(capture.run(label + "-logical", ["xcrun", "simctl", "list", "runtimes", "-j"]))
    observed["types"] = decode(capture.run(label + "-types", ["xcrun", "simctl", "list", "devicetypes", "-j"]))
    require(type(observed["logical"]) is dict and type(observed["logical"].get("runtimes")) is list
            and type(observed["types"]) is dict and type(observed["types"].get("devicetypes")) is list,
            "Logical runtime/device-type inventory is malformed")
    observed["selections"] = {}
    for consumer in consumers:
        try:
            selection = original_selection(consumer, observed["logical"]["runtimes"], observed["types"]["devicetypes"])
        except StopIteration as error:
            raise ValueError("Original selection found no installed runtime/device: " + consumer) from error
        selection_identity(selection)
        observed["selections"][consumer] = selection
    observed["finished_utc"] = utc()
    capture.report["observations"].append(observed)
    capture.save()
    return observed


def validate_observation(report, context):
    require(report.get("schema") == PREPARE_SCHEMA and report.get("identity") == context
            and report.get("result") == "INSTALLED_SELECTION_OBSERVED_PENDING_ACTUAL_CALLER_EXIT"
            and report.get("errors") == [] and report.get("product_pass") is False
            and report.get("candidate_credit") is False,
            "Installed observation did not complete under this exact source/control identity")
    order = list(OWNER_PROFILES[context["owner"]]["consumers"])
    require(report.get("consumer_order") == order, "Installed observation consumer order differs")
    observed = report["installed_observation"]
    require(report.get("observations") == [observed] and set(observed["selections"]) == set(order),
            "Installed observation lacks its exact selection baseline")
    for consumer in order:
        expected = original_selection(consumer, observed["logical"]["runtimes"], observed["types"]["devicetypes"])
        require(canonical(expected) == canonical(observed["selections"][consumer]),
                "Recorded installed selection differs from the unchanged original predicate")
        selection_identity(expected)
    require([row["label"] for row in report["commands"]] ==
            ["xcode-version", "sdk-version", "simctl-path", "xcodebuild-path", "installed-logical", "installed-types"]
            and all(type(row.get("returncode")) is int and row["returncode"] == 0
                    and row.get("timed_out") is False and row.get("reaped") is True
                    for row in report["commands"]),
            "Installed observation metadata commands did not all finish successfully")
    return observed


def prepare_environment(request, context):
    root, output = Path(context["source_root"]), preparation_root(context)
    require(not output.exists(), "Prepare once; prior evidence is neither reused nor deleted")
    output.mkdir(mode=0o700, parents=True)
    order = list(OWNER_PROFILES[context["owner"]]["consumers"])
    report = {"schema": PREPARE_SCHEMA, "identity": context, "request": request,
              "started_utc": utc(), "commands": [], "observations": [], "errors": [],
              "product_pass": False, "candidate_credit": False, "consumer_order": order,
              "scope": "Read-only toolchain and original selection observation; no managed image preparation or physical-integrity claim."}
    capture = capture_for(context, output / "installed-runtime", report, "progress.json")
    try:
        xcode = capture.run("xcode-version", ["xcodebuild", "-version"]).decode().strip()
        sdk = capture.run("sdk-version", ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"]).decode().strip()
        require(xcode == "Xcode 27.0\nBuild version 27A266a" and sdk == "27.0", "Installed Xcode/SDK differs")
        report["toolchain"] = {"xcode_version": xcode, "simulator_sdk_version": sdk, "tools": {}}
        for tool in ("simctl", "xcodebuild"):
            value = capture.run(tool + "-path", ["xcrun", "--find", tool]).decode().strip()
            require(Path(value).name == tool and Path(value).resolve().is_relative_to(Path(DEVELOPER).resolve()),
                    "Selected tool is outside exact Xcode")
            report["toolchain"]["tools"][tool] = value
        report["installed_observation"] = observe_selection(capture, "installed", order)
        recheck_context(request, context)
        report["result"] = "INSTALLED_SELECTION_OBSERVED_PENDING_ACTUAL_CALLER_EXIT"
    except Exception as error:
        failure_record(report, "prepare", error)
        report["result"] = "INSTALLED_OBSERVATION_FAILED"
    report["finished_utc"] = utc()
    write_json(output / "prepare-result.json", report, root)
    require(not report["errors"], "Installed runtime observation failed; see saved actual evidence")


def record_preparation_exit(context, actual_status):
    require(type(actual_status) is int and 0 <= actual_status <= 255, "Invalid actual preparation shell status")
    root, output = Path(context["source_root"]), preparation_root(context)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    report = {"schema": EXIT_SCHEMA, "identity": context, "actual_shell_status_argument": actual_status,
              "status_provenance": "Caller supplies its immediately captured actual process status.",
              "product_pass": False, "candidate_credit": False, "prepare_result": None}
    if (output / "prepare-result.json").exists():
        observed, info = read_bound_json(output / "prepare-result.json", root)
        require(observed["schema"] == PREPARE_SCHEMA and observed["identity"] == context,
                "Installed observation receipt has a different identity")
        report["prepare_result"] = info
        if actual_status == 0:
            validate_observation(observed, context)
            report["observed_raw_files"] = readback_commands(observed, root)
    else:
        require(actual_status != 0, "A successful preparation process must have its complete receipt")
    write_json(output / "prepare-exit.json", report, root)


def load_preparation(context):
    root, output = Path(context["source_root"]), preparation_root(context)
    actual, actual_info = read_bound_json(output / "prepare-exit.json", root)
    require(actual.get("schema") == EXIT_SCHEMA and actual.get("identity") == context
            and type(actual.get("actual_shell_status_argument")) is int
            and actual["actual_shell_status_argument"] == 0
            and actual.get("product_pass") is False and actual.get("candidate_credit") is False,
            "The same observation process has no bound actual exit zero")
    observed, observed_info = read_bound_json(output / "prepare-result.json", root, actual["prepare_result"])
    baseline = validate_observation(observed, context)
    require(readback_commands(observed, root) == actual["observed_raw_files"],
            "Installed observation command streams changed after the actual caller binding")
    return baseline, {"preparation": observed_info, "actual_exit": actual_info}


def preceding_consumer(context, consumer, binding, initial):
    order = list(OWNER_PROFILES[context["owner"]]["consumers"])
    position = order.index(consumer)
    baseline = decode(canonical(initial["selections"][consumer]))
    if position == 0:
        return baseline, None
    require(order == ["integrated-ui", "integrated-simulator"] and position == 1,
            "Unexpected original consumer sequence")
    root, output = Path(context["source_root"]), preparation_root(context)
    prior, info = read_bound_json(output / "consumers" / order[0] / "after.json", root)
    require(prior.get("schema") == AFTER_SCHEMA and prior.get("identity") == context
            and prior.get("consumer") == order[0] and prior.get("preparation_binding") == binding
            and type(prior.get("original_status")) is int and prior["original_status"] == 0
            and type(prior.get("observer_status")) is int and prior["observer_status"] == 0
            and type(prior.get("effective_status")) is int and prior["effective_status"] == 0
            and prior.get("errors") == [] and prior.get("terminal") is False
            and prior.get("result") == "BOUND_AFTER_ORIGINAL_CONSUMER",
            "Simulator requires the actual successful preceding UI receipt")
    # The simulator's original device value is an identifier, while UI uses the
    # full device-type object. Carry only the UI's observed runtime forward.
    carried = {"runtime": prior["selection_after"]["runtime"], "device": baseline["device"]}
    require(canonical(selection_identity(carried)) == canonical(selection_identity(baseline)),
            "The preceding UI selected another installed runtime")
    return carried, info


def before_consumer(request, context, consumer):
    profile = consumer_profile(context, consumer)
    root, prep = Path(context["source_root"]), preparation_root(context)
    initial, binding = load_preparation(context)
    require(not (prep / "sequence-terminal.json").exists(), "The original-consumer sequence already terminated")
    baseline, prior = preceding_consumer(context, consumer, binding, initial)
    original_receipt = unlinked_path(root / profile["receipt"], root)
    require(not original_receipt.exists(), "Original consumer receipt must be new; the adapter never deletes it")
    output = unlinked_path(prep / "consumers" / consumer, root)
    require(not output.exists(), "This original consumer already has a before binding")
    output.mkdir(mode=0o700, parents=True)
    report = {"schema": BEFORE_SCHEMA, "identity": context, "consumer": consumer,
              "preparation_binding": binding, "preceding_consumer_after_binding": prior,
              "original_receipt_must_be_new": str(original_receipt), "started_utc": utc(),
              "commands": [], "observations": [], "errors": [], "product_pass": False, "candidate_credit": False}
    capture = capture_for(context, output / "before-host", report, "progress.json")
    try:
        observed = observe_selection(capture, "before-original-consumer", [consumer])
        report["selection"] = observed["selections"][consumer]
        report["selection_baseline"] = baseline
        require(canonical(selection_identity(report["selection"])) == canonical(selection_identity(baseline)),
                "Original first-choice identity changed since the installed observation")
        report["raw_files"] = readback_commands(report, root)
        recheck_context(request, context)
        report["result"] = "BOUND_BEFORE_ORIGINAL_CONSUMER"
    except Exception as error:
        failure_record(report, "before", error)
        report["result"] = "BEFORE_BINDING_FAILED"
    report["finished_utc"] = utc()
    write_json(output / "before.json", report, root)
    require(not report["errors"], "Original consumer before binding failed")


def after_consumer(request, context, consumer, original_status):
    require(type(original_status) is int and 0 <= original_status <= 255, "Invalid actual original shell status")
    root, prep = Path(context["source_root"]), preparation_root(context)
    profile = consumer_profile(context, consumer)
    output = unlinked_path(prep / "consumers" / consumer, root)
    require(output.is_dir() and not (output / "after.json").exists(), "A new after binding requires its one original before")
    report = {"schema": AFTER_SCHEMA, "identity": context, "consumer": consumer, "original_status": original_status,
              "observer_status": None, "started_utc": utc(), "commands": [], "observations": [], "errors": [],
              "product_pass": False, "candidate_credit": False}
    # A partial after attempt is never silently repeated. This claim does not
    # assert original success, observer success, or a complete after receipt.
    report["after_claim"] = write_json(output / "after-claim.json",
        {"schema": "installed-runtime-consumer-after-claim-v1", "identity": context, "consumer": consumer,
         "original_status": original_status, "started_utc": report["started_utc"]}, root)
    capture = capture_for(context, output / "after-host", report, "progress.json")
    binding, before, before_info = None, None, None
    try:
        initial, binding = load_preparation(context)
        baseline, prior = preceding_consumer(context, consumer, binding, initial)
        report["preparation_binding"] = binding
        value, info = read_bound_json(output / "before.json", root)
        require(value.get("schema") == BEFORE_SCHEMA and value.get("identity") == context
                and value.get("consumer") == consumer and value.get("result") == "BOUND_BEFORE_ORIGINAL_CONSUMER"
                and value.get("errors") == [] and value.get("preparation_binding") == binding
                and value.get("preceding_consumer_after_binding") == prior
                and value.get("selection_baseline") == baseline,
                "Before binding is missing, failed, reordered or belongs to another observation")
        require(readback_commands(value, root) == value["raw_files"], "Before metadata command streams changed")
        before, before_info = value, info
        report["before_binding"] = before_info
    except Exception as error:
        failure_record(report, "before_binding", error)
    if before is not None:
        try:
            path = unlinked_path(root / profile["receipt"], root)
            if path.exists():
                value, info = read_bound_json(path, root)
                report["original_receipt"] = info
                report["actual_selection"] = validate_original_receipt(value, before, profile, consumer)
            else:
                require(original_status != 0, "A successful original command omitted its selection receipt")
                report["original_receipt"] = {"absent": True, "success_claim": False}
        except Exception as error:
            failure_record(report, "original_receipt", error)
        try:
            report["observer_status"], report["observer_binding"] = observer_status(context, consumer, before_info, original_status)
        except Exception as error:
            failure_record(report, "observer_binding", error)
        try:
            observed = observe_selection(capture, "after-original-consumer", [consumer])
            report["selection_after"] = observed["selections"][consumer]
            require(canonical(selection_identity(report["selection_after"])) == canonical(selection_identity(before["selection"])),
                    "Original first-choice identity changed during the consumer")
            report["raw_files"] = readback_commands(report, root)
        except Exception as error:
            failure_record(report, "selected_after", error)
    try:
        recheck_context(request, context)
    except Exception as error:
        failure_record(report, "source_control_after", error)
    # Only a fully bound successful UI receipt permits Integrated's next
    # consumer. Unknown original/observer evidence never earns a zero here.
    report["terminal"] = not (consumer == "integrated-ui" and original_status == 0
                              and type(report["observer_status"]) is int
                              and report["observer_status"] == 0 and not report["errors"])
    if report["terminal"]:
        try:
            report["terminal_receipt"] = write_json(prep / "sequence-terminal.json",
                {"schema": "installed-runtime-consumer-sequence-terminal-v1", "identity": context,
                 "consumer": consumer, "after_claim": report["after_claim"], "preparation_binding": binding,
                 "original_status": original_status, "observer_status": report["observer_status"],
                 "result": "SEQUENCE_TERMINAL_RECORDED", "product_pass": False, "candidate_credit": False}, root)
        except Exception as error:
            failure_record(report, "terminal_receipt", error)
    report["result"] = "BOUND_AFTER_ORIGINAL_CONSUMER" if not report["errors"] else "AFTER_BINDING_FAILED"
    report["effective_status"] = original_status or report["observer_status"] or (1 if report["errors"] else 0)
    report["finished_utc"] = utc()
    try:
        write_json(output / "after.json", report, root)
    except Exception as error:
        print("After receipt failed; original status retained: " + str(error), file=sys.stderr)
        return original_status or report["observer_status"] or 1
    return report["effective_status"]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "record-prepare-exit", "before", "after"))
    parser.add_argument("--mode", required=True, choices=("canonical", "candidate", "workflow-input"))
    parser.add_argument("--owner", required=True, choices=tuple(OWNER_PROFILES))
    for name in ("source-root", "source-commit", "source-tree"):
        parser.add_argument("--" + name, required=True)
    for name in ("control-root", "control-commit", "control-tree", "workflow-input-ref", "consumer"):
        parser.add_argument("--" + name)
    parser.add_argument("--actual-status", type=int)
    args = parser.parse_args()
    request = {key: getattr(args, key) for key in ("mode", "owner", "source_root", "source_commit", "source_tree",
               "control_root", "control_commit", "control_tree", "workflow_input_ref")}
    try:
        context = context_for(request)
        if args.action == "prepare":
            require(args.consumer is None and args.actual_status is None, "Unexpected prepare arguments")
            prepare_environment(request, context)
        elif args.action == "record-prepare-exit":
            require(args.consumer is None and args.actual_status is not None, "Require actual preparation process status")
            record_preparation_exit(context, args.actual_status)
        elif args.action == "before":
            require(args.consumer is not None and args.actual_status is None, "Require one original consumer")
            before_consumer(request, context, args.consumer)
        else:
            require(args.consumer is not None and args.actual_status is not None, "Require immediately captured actual original status")
            return after_consumer(request, context, args.consumer, args.actual_status)
    except Exception as error:
        print(type(error).__name__ + ": " + str(error), file=sys.stderr)
        if args.action == "after" and type(args.actual_status) is int and 0 < args.actual_status <= 255:
            return args.actual_status
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
