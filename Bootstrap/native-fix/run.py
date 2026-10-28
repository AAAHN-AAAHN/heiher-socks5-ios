"""Verify the declared native listener correction against its original cases."""
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
expected = {test_path, "Patches/hev-socks5-listener-info.patch",
            "Tests/Background/listener_info.c"}
if set(manifest["overlay_files"]) != expected | {"socket_probe.py"}:
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

output = source / "artifacts/native-listener-fix"
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
    for path in expected:
        shutil.copyfile(overlay / path, source / path)
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
    command = [sys.executable, test_path, "--native", str(core),
               "--output", str(output / "native")]
    receipt["command"] = command
    with (output / "native.log").open("w") as stream:
        code = subprocess.run(command, cwd=source, stdout=stream,
                              stderr=subprocess.STDOUT, timeout=300).returncode
    receipt["native_returncode"] = code
    libraries = [core / path for path in (
        "bin/libhev-socks5-server.a",
        "third-part/hev-task-system/bin/libhev-task-system.a",
        "third-part/yaml/bin/libyaml.a")]
    binary = output / "listener-info"
    listener_compile = ["cc", "-Wall", "-Wextra", "-Werror", "-pthread",
                        "-I" + str(core / "src"), "Tests/Background/listener_info.c",
                        *map(str, libraries), "-o", str(binary)]
    receipt["listener_compile"] = listener_compile
    with (output / "listener-info.log").open("w") as stream:
        subprocess.run(listener_compile, cwd=source, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=60)
        listener_code = subprocess.run([str(binary)], cwd=source, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=35).returncode
    receipt["listener_returncode"] = listener_code
    code = code or listener_code
except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
    code = 1
    receipt["error"] = str(error)
finally:
    receipt["unchanged_inputs_match"] = all(
        digest(source / path) == sha
        for path, sha in manifest["unchanged_candidate_files"].items())
    receipt["changed_files"] = git("diff", "--name-only", "HEAD").splitlines()
    receipt["overlay_inputs_match"] = all(
        digest(source / path) == manifest["overlay_files"][path]["after_sha256"]
        for path in expected)
    if (not receipt["unchanged_inputs_match"] or not receipt["overlay_inputs_match"]
            or set(receipt["changed_files"]) != expected):
        code = 1
    receipt["result"] = "PASS" if code == 0 else "FAIL"
    (output / "diagnostic-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
raise SystemExit(code)
