#!/usr/bin/env python3
"""One diagnostic preparation change; no candidate or publication acceptance.

Run the original preparation, delete its one frozen old-iOS duplicate, and
observe the frozen watch UUIDs without deleting them. Invoke the original
Integrated consumers only after the bounded helper actually exits zero. Their
arguments, source, assertions and deadlines remain unchanged. The historical
adapter validates saved preparation and distinct live consumer boundaries; it
does not establish a binding for this added retirement/settlement phase. This
diagnostic omits its before/after calls and grants no formal candidate credit.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


SOURCE = "3a6ba06abcbffc48bb5c7290a5e53709e3809fbc"
TREE = "6e745ac08beb1ab9eeb9e367cdaa28148d2f3600"
CONSUMERS = {
    "Build/ui_review.py": "3a155a9c78b5acdd5f40b3057d3077c309c4a5ff8545a509e8da1d591e50ad30",
    "Build/simulator_review.py": "e1897dd4aba4702ad6ee28332fa6d614606260e05c98c310ba6a4464c9e4590f",
}


class PhaseFailed(RuntimeError):
    def __init__(self, label, returncode):
        super().__init__(label + " returned " + str(returncode))
        self.returncode = returncode


def now():
    return datetime.now(timezone.utc).isoformat()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def diagnostic(message):
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10)
    require(result.returncode == 0 and not result.stderr, "Git identity check failed: " + " ".join(args))
    return result.stdout


def bind_source(source):
    require(git(source, "rev-parse", "HEAD").decode().strip() == SOURCE, "Wrong diagnostic source")
    require(git(source, "rev-parse", "HEAD^{tree}").decode().strip() == TREE, "Wrong diagnostic source tree")
    git(source, "diff", "--no-ext-diff", "--no-textconv", "--exit-code", "HEAD", "--")
    git(source, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--exit-code", "HEAD", "--")
    for relative, expected in CONSUMERS.items():
        path = source / relative
        require(path.resolve(strict=True) == path and path.is_file(), "Linked or missing consumer")
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, "Original consumer bytes changed")
        require(raw == git(source, "show", "HEAD:" + relative), "Consumer differs from the exact Git source")


def main():
    expected = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "AAAHN-AAAHN/heiher-socks5-ios",
        "GITHUB_REF": "refs/heads/work/udp-echo-build-20261028", "GITHUB_JOB": "runtime",
        "RUNNER_OS": "macOS", "RUNNER_ARCH": "ARM64", "CANDIDATE": "integrated",
        "DEVELOPER_DIR": "/Applications/Xcode_27.app/Contents/Developer",
    }
    require(__debug__ and all(os.environ.get(key) == value for key, value in expected.items()),
            "Require the declared diagnostic workflow context")
    require(sys.platform == "darwin" and platform.machine() == "arm64" and os.getuid() == os.geteuid() > 0,
            "Require the ordinary-user Darwin arm64 host")
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
    source = temporary / "udp-source"
    control = Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    require(Path.cwd() == source and source.resolve(strict=True) == source, "Wrong source working directory")
    require(Path(__file__).resolve(strict=True) == control / "Bootstrap/run_runtime_recovery_probe.py",
            "Require the tracked diagnostic orchestrator")
    require(git(control, "rev-parse", "HEAD").decode().strip() == os.environ["GITHUB_SHA"],
            "Control checkout differs from the actual workflow")
    git(control, "diff", "--exit-code", "HEAD", "--")
    git(control, "diff", "--cached", "--exit-code", "HEAD", "--")
    bind_source(source)
    output = temporary / "runtime-recovery-probe"
    output.mkdir(exist_ok=False)
    python = Path(os.environ["RUNNER_TOOL_CACHE"]) / "Python/3.14.9/arm64/bin/python3.14"
    require(python.is_file() and os.access(python, os.X_OK), "Original preparation interpreter is absent")
    report = {
        "schema": "single-old-ios-delete-watch-settlement-probe-v2", "started_utc": now(),
        "result": "IN_PROGRESS", "formal_candidate_credit": False, "publication_credit": False,
        "source": {"commit": SOURCE, "tree": TREE}, "original_consumer_sha256": CONSUMERS,
        "context": {key: os.environ.get(key) for key in (*expected, "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")},
        "scope": "One original preparation; at most one exact old-iOS keep-asset delete; zero watch deletes; one bounded read-only watch settlement; at most one invocation of each original UI/Simulator consumer. Original saved preparation validation is preserved. No formal binding or original consumer before/after adapter receipt is asserted for the added phase.",
        "phases": [], "errors": [],
    }

    def save():
        pending = output / "result.pending.json"
        pending.write_text(json.dumps(report, indent=2) + "\n")
        pending.replace(output / "result.json")

    def run(label, argv, log):
        row = {"phase": label, "argv": [str(value) for value in argv], "started_utc": now(),
               "stdout_stderr": str(log), "invocations": 0, "added_timeout": None}
        report["phases"].append(row)
        save()
        started = time.monotonic()
        phase_failure = None
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("xb") as stream:
                row["invocations"] = 1
                # No shell, retry, added deadline, altered environment or signal.
                completed = subprocess.run(row["argv"], stdout=stream, stderr=subprocess.STDOUT)
            row["returncode"] = completed.returncode
            row["shell_exit_status"] = completed.returncode if completed.returncode >= 0 else 128 - completed.returncode
            if completed.returncode != 0:
                raise PhaseFailed(label, completed.returncode)
        except Exception as error:
            phase_failure = error
        finally:
            row.update(finished_utc=now(), elapsed_seconds=time.monotonic() - started)
            try:
                if log.is_file():
                    with log.open("rb") as stream:
                        row["log_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                    row["log_bytes"] = log.stat().st_size
            except Exception as error:
                phase_failure = phase_failure or error
                report["errors"].append({"stage": label + "-log-recording", "type": type(error).__name__, "message": str(error)})
            try:
                save()
            except Exception as error:
                phase_failure = phase_failure or error
                report["errors"].append({"stage": label + "-result-recording", "type": type(error).__name__, "message": str(error)})
        if phase_failure is not None:
            raise phase_failure

    failure = None
    try:
        save()
        run("original-preparation", ["bash", control / "Bootstrap/run_candidate_runtime.sh", "prepare"],
            output / "original-preparation.log")
        run("exact-duplicate-retirement", [python, "-B", control / "Bootstrap/retire_duplicate_registrations.py",
            "--source-root", source, "--output", temporary / "runtime-duplicate-retirement"],
            output / "duplicate-retirement.log")
        bind_source(source)
        run("original-ui", ["python3", "Build/ui_review.py"], source / "artifacts/integrated/ui-review.log")
        run("original-simulator", ["python3", "Build/simulator_review.py"],
            source / "artifacts/integrated/simulator-review.log")
        report["result"] = "DIAGNOSTIC_SEQUENCE_COMPLETED_WITHOUT_FORMAL_CREDIT"
    except Exception as error:
        failure = error
        report["errors"].append({"stage": "sequence", "type": type(error).__name__, "message": str(error)})
    finally:
        try:
            bind_source(source)
            report["original_source_preserved_after"] = True
        except Exception as error:
            failure = failure or error
            report["errors"].append({"stage": "final-source", "type": type(error).__name__, "message": str(error)})
        if failure is not None:
            report["result"] = "DIAGNOSTIC_FAILED_WITHOUT_FORMAL_CREDIT"
        report["exit_status"] = (failure.returncode if failure.returncode >= 0 else 128 - failure.returncode
                                 ) if isinstance(failure, PhaseFailed) else (1 if failure is not None else 0)
        report["finished_utc"] = now()
        try:
            save()
        except Exception as error:
            failure = failure or error
            report["result"] = "DIAGNOSTIC_RECORDING_FAILED_WITHOUT_FORMAL_CREDIT"
            report["exit_status"] = (failure.returncode if failure.returncode >= 0 else 128 - failure.returncode
                                     ) if isinstance(failure, PhaseFailed) else 1
            diagnostic("Final diagnostic recording failed: " + str(error))
    if isinstance(failure, PhaseFailed):
        diagnostic(str(failure))
        return report["exit_status"]
    elif failure is not None:
        raise failure
    return 0


if __name__ == "__main__":
    sys.exit(main())
