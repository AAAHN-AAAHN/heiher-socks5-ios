"""Verify the declared test-only Off ordering fix against unchanged production."""
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
expected = {"Tests/Background/UDPEchoTransportProbe.swift",
            "Tests/Background/UDPEchoTransportTests.py"}
if {row["path"] for row in manifest["files"]} != expected:
    raise SystemExit("Unexpected diagnostic files")


def git(*args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if git("rev-parse", "HEAD") != manifest["base_commit"]:
    raise SystemExit("Wrong production candidate")
git("diff", "--exit-code", "HEAD", "--")
git("diff", "--cached", "--exit-code", "HEAD", "--")
for row in manifest["files"]:
    if digest(source / row["path"]) != row["before_sha256"]:
        raise SystemExit("Unexpected original test bytes: " + row["path"])
    if digest(overlay / row["path"]) != row["after_sha256"]:
        raise SystemExit("Unexpected diagnostic test bytes: " + row["path"])
client = manifest["production_client"]
if digest(source / client["path"]) != client["sha256"]:
    raise SystemExit("Unexpected production client bytes")
for row in manifest["files"]:
    shutil.copyfile(overlay / row["path"], source / row["path"])

output = source / "artifacts/background-transport-focused"
output.mkdir(parents=True, exist_ok=True)
command = [sys.executable, "Tests/Background/UDPEchoTransportTests.py",
           "--output", str(output)]
receipt = {
    "scope": manifest["scope"],
    "helper_commit": os.environ.get("GITHUB_SHA"),
    "run_id": os.environ.get("GITHUB_RUN_ID"),
    "candidate": manifest["base_commit"],
    "manifest": manifest,
    "command": command,
    "swift": subprocess.check_output(["swiftc", "--version"], text=True),
    "xcode": subprocess.check_output(["xcodebuild", "-version"], text=True),
}
code = 1
try:
    with (output / "transport.log").open("w") as stream:
        code = subprocess.run(command, cwd=source, stdout=stream,
                              stderr=subprocess.STDOUT, timeout=180).returncode
    receipt["returncode"] = code
except subprocess.TimeoutExpired as error:
    receipt["error"] = str(error)
finally:
    receipt["production_client_unchanged"] = digest(source / client["path"]) == client["sha256"]
    receipt["changed_files"] = git("diff", "--name-only", "HEAD").splitlines()
    if not receipt["production_client_unchanged"] or set(receipt["changed_files"]) != expected:
        code = 1
    receipt["result"] = "PASS" if code == 0 else "FAIL"
    (output / "diagnostic-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
raise SystemExit(code)
