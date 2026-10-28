"""Compare the declared timer flag; never describe this as a final source gate."""
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
baseline = len(sys.argv) == 3 and sys.argv[2] == "--baseline"
service = "Socks5/BackgroundKeepAlive/PeriodicUDPEchoService.swift"
tests = {
    "Tests/Background/UDPEchoSchedulerProbe.swift",
    "Tests/Background/UDPEchoSchedulerTests.py",
}
if set(manifest["files"]) != tests | {service}:
    raise SystemExit("Unexpected diagnostic files")
expected = tests if baseline else tests | {service}

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
    if digest(overlay / path) != record["overlay_sha256"]:
        raise SystemExit("Unexpected diagnostic test bytes: " + path)
for path, sha in manifest["unchanged_production_sources"].items():
    if digest(source / path) != sha:
        raise SystemExit("Unexpected production bytes: " + path)
for path in expected:
    shutil.copyfile(overlay / path, source / path)

output = source / "artifacts/background-scheduler-diagnostic"
output.mkdir(parents=True, exist_ok=True)
command = [sys.executable, "Tests/Background/UDPEchoSchedulerTests.py",
           "--output", str(output)]
receipt = {
    "scope": manifest["scope"],
    "variant": "baseline" if baseline else "strict",
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
    receipt["production_matches_declared_variant"] = all(
        digest(source / path) == sha
        for path, sha in manifest["unchanged_production_sources"].items())
    key = "before_sha256" if baseline else "overlay_sha256"
    receipt["production_matches_declared_variant"] &= (
        digest(source / service) == manifest["files"][service][key])
    receipt["changed_files"] = git("diff", "--name-only", "HEAD").splitlines()
    if not receipt["production_matches_declared_variant"] or set(receipt["changed_files"]) != expected:
        code = 1
    receipt["result"] = "PASS" if code == 0 else "FAIL"
    (output / "diagnostic-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
raise SystemExit(code)
