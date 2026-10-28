"""Run a declared test-only overlay; never describe it as a final source gate."""
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
expected = {
    "Tests/Background/UDPEchoSchedulerProbe.swift",
    "Tests/Background/UDPEchoSchedulerTests.py",
}
if set(manifest["files"]) != expected:
    raise SystemExit("Unexpected diagnostic files")

def git(*args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

if git("rev-parse", "HEAD") != manifest["candidate"]:
    raise SystemExit("Wrong production candidate")
git("diff", "--exit-code", "HEAD", "--")
git("diff", "--cached", "--exit-code", "HEAD", "--")
for path, record in manifest["files"].items():
    if digest(source / path) != record["before_sha256"]:
        raise SystemExit("Unexpected original test bytes: " + path)
    if digest(overlay / path) != record["diagnostic_sha256"]:
        raise SystemExit("Unexpected diagnostic test bytes: " + path)
for path, sha in manifest["production_sources"].items():
    if digest(source / path) != sha:
        raise SystemExit("Unexpected production bytes: " + path)
for path in expected:
    shutil.copyfile(overlay / path, source / path)

output = source / "artifacts/background-scheduler-diagnostic"
output.mkdir(parents=True, exist_ok=True)
command = [sys.executable, "Tests/Background/UDPEchoSchedulerTests.py",
           "--output", str(output)]
receipt = {
    "scope": "Diagnostic test overlay, not a clean final candidate gate",
    "helper_commit": os.environ.get("GITHUB_SHA"),
    "run_id": os.environ.get("GITHUB_RUN_ID"),
    "candidate": manifest["candidate"],
    "manifest": manifest,
    "command": command,
    "swift": subprocess.check_output(["swiftc", "--version"], text=True),
    "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True),
}
code = 1
try:
    with (output / "scheduler.log").open("w") as stream:
        code = subprocess.run(command, cwd=source, stdout=stream,
                              stderr=subprocess.STDOUT, timeout=180).returncode
    receipt["returncode"] = code
except subprocess.TimeoutExpired as error:
    receipt["error"] = str(error)
finally:
    receipt["production_unchanged"] = all(
        digest(source / path) == sha
        for path, sha in manifest["production_sources"].items())
    receipt["changed_files"] = git("diff", "--name-only", "HEAD").splitlines()
    if not receipt["production_unchanged"] or set(receipt["changed_files"]) != expected:
        code = 1
    receipt["result"] = "PASS" if code == 0 else "FAIL"
    (output / "diagnostic-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
raise SystemExit(code)
