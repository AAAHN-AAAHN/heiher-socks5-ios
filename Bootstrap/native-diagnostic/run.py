"""Observe native listener failure with exact production and declared test logs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

overlay = Path(__file__).resolve().parent
source = Path(sys.argv[1]).resolve()
manifest = json.loads((overlay / "manifest.json").read_bytes())
test_path = "Tests/Background/check_udp_echo_native.py"
if set(manifest["overlay_files"]) != {test_path, "socket_probe.py"}:
    raise SystemExit("Unexpected diagnostic files")


def git(*args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if git("rev-parse", "HEAD") != manifest["candidate_commit"]:
    raise SystemExit("Wrong native candidate")
git("diff", "--exit-code", "HEAD", "--")
git("diff", "--cached", "--exit-code", "HEAD", "--")
for path, sha in manifest["unchanged_candidate_files"].items():
    if digest(source / path) != sha:
        raise SystemExit("Unexpected candidate input: " + path)
for path, row in manifest["overlay_files"].items():
    if digest(overlay / path) != row["after_sha256"]:
        raise SystemExit("Unexpected diagnostic overlay: " + path)
    if "before_sha256" in row and digest(source / path) != row["before_sha256"]:
        raise SystemExit("Unexpected original test input: " + path)

output = source / "artifacts/native-listener-focused"
output.mkdir(parents=True, exist_ok=True)
core = source / ".build/core"
core.parent.mkdir(parents=True, exist_ok=True)
receipt = {
    "scope": manifest["purpose"],
    "helper_commit": os.environ.get("GITHUB_SHA"),
    "run_id": os.environ.get("GITHUB_RUN_ID"),
    "candidate": manifest["candidate_commit"],
    "manifest": manifest,
    "swift": subprocess.check_output(["swiftc", "--version"], text=True),
    "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True),
}
code = 1
try:
    subprocess.run([sys.executable, str(overlay / "socket_probe.py"),
                    "--output", str(output / "socket-probe.json")], check=True, timeout=30)
    commands = [
        ["git", "clone", "--no-checkout", "https://github.com/heiher/hev-socks5-server.git", str(core)],
        ["git", "-C", str(core), "checkout", "--detach", manifest["native_sources"]["."]],
        ["git", "-C", str(core), "submodule", "update", "--init", "--recursive"],
        [sys.executable, "Build/check.py", "checkout", str(core)],
        [sys.executable, "Build/check.py", "apply", str(core)],
    ]
    with (output / "prepare.log").open("w") as stream:
        for command in commands:
            stream.write(json.dumps(command) + "\n")
            stream.flush()
            subprocess.run(command, cwd=source, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=240)
    shutil.copyfile(overlay / test_path, source / test_path)
    command = [sys.executable, test_path, "--native", str(core),
               "--output", str(output / "native")]
    receipt["command"] = command
    with (output / "native.log").open("w") as stream:
        code = subprocess.run(command, cwd=source, stdout=stream,
                              stderr=subprocess.STDOUT, timeout=300).returncode
    receipt["returncode"] = code
except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
    receipt["error"] = str(error)
finally:
    receipt["production_unchanged"] = all(
        digest(source / path) == sha
        for path, sha in manifest["unchanged_candidate_files"].items())
    receipt["changed_files"] = git("diff", "--name-only", "HEAD").splitlines()
    if not receipt["production_unchanged"] or set(receipt["changed_files"]) != {test_path}:
        code = 1
    receipt["result"] = "PASS" if code == 0 else "FAIL"
    (output / "diagnostic-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
raise SystemExit(code)
