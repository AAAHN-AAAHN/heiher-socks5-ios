#!/usr/bin/env python3
"""Move verified candidate inputs to a fresh macOS runtime job.

The helper workflow and candidate retain separate identities. GitHub's immutable
artifact digest authenticates the ZIP containing both the producer receipt and
the TAR digest; no caller-supplied, unbound TAR hash is accepted. This handoff
does not establish Simulator or UI success.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HELPER = Path(__file__).resolve().parents[1]
NAMES = {"background": "background", "statistics": "traffic-statistics", "integrated": "integrated"}
FRAMEWORK = ".build/core/HevSocks5Server.xcframework"
BACKGROUND = ("SUCCESS.txt", "tested-commit.txt", "built-framework.json",
              "compiled-headers/hev-main.h", "compiled-headers/module.modulemap",
              "compiled-headers/source-commit.txt", "compiled-headers/SHA256SUMS.txt")
AUDIO = ("SUCCESS.txt", "tested-commit.txt", "source-sha256.json", "source.zip",
         "toolchain.txt", "ios-sdk-typecheck.log", "native-inputs.log")
STATISTICS = ("SUCCESS.txt", "tested-commit.txt", "source.zip", "inventory.json",
              "statistics-source-hashes.json", "ios-c-syntax.log",
              "ios-swift-typecheck.log", "project.log", "effective-pins.log",
              "final-identity.log", "reverse.log")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: require(False, "Invalid JSON constant: " + value))


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def positive(value):
    require(type(value) in (str, int) and re.fullmatch(r"[1-9][0-9]*", str(value)),
            "Invalid run, attempt or artifact/job ID")
    return str(value)


def safe_name(name):
    require(type(name) is str, "Non-string path")
    path = PurePosixPath(name)
    require(name not in ("", ".") and not path.is_absolute() and path.as_posix() == name
            and ".." not in path.parts and "\\" not in name
            and not any(ord(c) < 32 or ord(c) == 127 for c in name), "Unsafe path: " + name)
    return name


def unlinked(path, root):
    require(path.is_relative_to(root), "Path outside the candidate checkout")
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "Linked input/output: " + str(parent))
        if parent == root:
            break


def read_file(path):
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    require(stat.S_ISREG(info.st_mode) and mode & ~0o777 == 0 and mode & 0o400,
            "Expected readable regular file: " + str(path))
    return path.read_bytes(), mode


def files_below(folder, root):
    unlinked(folder, root)
    require(folder.is_dir(), "Missing payload directory: " + str(folder))
    result = {}
    for path in sorted(folder.rglob("*")):
        unlinked(path, root)
        if not path.is_dir():
            result[safe_name(path.relative_to(folder).as_posix())] = read_file(path)
    require(result, "Empty payload directory")
    return result


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def identity(root):
    commit = git(root, "rev-parse", "HEAD").decode().strip()
    tree = git(root, "rev-parse", "HEAD^{tree}").decode().strip()
    require(re.fullmatch(r"[0-9a-f]{40}", commit) and re.fullmatch(r"[0-9a-f]{40}", tree),
            "Invalid Git identity")
    git(root, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--exit-code", commit, "--")
    # Compare raw bytes and Git modes, including files masked by Git index flags.
    for record in git(root, "ls-tree", "-rz", commit).split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        require(kind == "blob" and mode in ("100644", "100755"), "Unexpected tracked source type")
        path = root / safe_name(os.fsdecode(name))
        unlinked(path, root)
        raw, actual_mode = read_file(path)
        actual_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(actual_blob == blob and bool(actual_mode & 0o100) == (mode == "100755"),
                "Changed tracked source: " + str(path))
    return {"commit": commit, "tree": tree}


def context():
    require(os.environ["RUNNER_OS"] == "macOS", "A macOS job is required")
    helper = identity(HELPER)
    require(helper["commit"] == os.environ["GITHUB_SHA"], "Helper checkout differs from workflow SHA")
    repository, job = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_JOB"]
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "Invalid repository")
    require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", job), "Invalid workflow job")
    return {"repository": repository, "run_id": positive(os.environ["GITHUB_RUN_ID"]),
            "attempt": positive(os.environ["GITHUB_RUN_ATTEMPT"]), "job": job,
            "helper": helper, "runner_os": "macOS"}


def candidate_identity(candidate, root):
    source = identity(root)
    config = json_bytes(read_file(root / "Build/features.json")[0])
    require(config["name"] == NAMES[candidate], "Wrong candidate composition")
    pins = config["sources"]
    require(pins and all((name == "." or safe_name(name)) and
                        re.fullmatch(r"[0-9a-f]{40}", value) for name, value in pins.items()),
            "Invalid native source pins")
    matrix = json_bytes(read_file(HELPER / "Bootstrap/candidates.json")[0])["matrix"]
    rows = [row for row in matrix if row["name"] == candidate and row["os"] == "xcode-27"]
    require(len(rows) == 1 and rows[0]["sha"] == source["commit"] and rows[0].get("runtime") is True,
            "Candidate differs from this helper's exact runtime matrix")
    return source, pins


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def integrated(root):
    # Reuse validation functions only: its workflow-specific context/identity is
    # intentionally not called, and no GitHub identity environment is overridden.
    sys.modules["release_source"] = load_module("release_source", root / "Build/release_source.py")
    return load_module("candidate_review_handoff", root / "Build/review_handoff.py")


def evidence_paths(candidate):
    if candidate == "background":
        return ["background/" + name for name in BACKGROUND] + ["audio-checks/" + name for name in AUDIO]
    return ["statistics-final-audit/" + name for name in STATISTICS]


def collect(candidate, root, source):
    if candidate == "integrated":
        module = integrated(root)
        module.source.check_product()
        payloads = {"product/" + name: item for name, item in files_below(module.PRODUCT, root).items()}
        for name in module.PHASES:
            unlinked(module.OUT / name, root)
            payloads["phases/" + name] = read_file(module.OUT / name)
        return payloads
    payloads = {}
    if candidate == "background":
        native = load_module("candidate_native_inputs", root / "Tests/Background/native_inputs.py")
        native.verify()
        payloads.update({"framework/" + name: item for name, item in files_below(root / FRAMEWORK, root).items()})
    else:
        # Statistics' successful audit reverses its patches to clean pinned Git
        # inputs. Its UI audit builds its own Simulator library on the fresh host.
        check = load_module("candidate_build_check", root / "Build/check.py")
        check.clean_native(root / ".build/statistics-final-audit/core")
    for name in evidence_paths(candidate):
        unlinked(root / "artifacts" / name, root)
        payloads["evidence/" + name] = read_file(root / "artifacts" / name)
    return payloads


def validate_payloads(candidate, root, source, manifest, payloads):
    require(manifest["source"] == source, "Transferred candidate commit/tree differs")
    if candidate == "integrated":
        integrated(root).check_payloads(manifest, payloads, source)
        return
    evidence = {name[len("evidence/"):]: item for name, item in payloads.items() if name.startswith("evidence/")}
    framework = {name[len("framework/"):]: item for name, item in payloads.items() if name.startswith("framework/")}
    require(set(evidence) == set(evidence_paths(candidate)) and len(evidence) + len(framework) == len(payloads),
            "Missing or extra payload evidence")
    prefix = "audio-checks" if candidate == "background" else "statistics-final-audit"
    require(evidence[prefix + "/SUCCESS.txt"][0].startswith(b"PASS:"), "Missing successful SDK/audit marker")
    require(evidence[prefix + "/tested-commit.txt"][0].decode().strip() == source["commit"],
            "SDK/audit tested another source")
    # The existing raw Git blob/mode archive check is shared by both owners.
    check = load_module("candidate_build_check", root / "Build/check.py")
    with tempfile.TemporaryDirectory(prefix="runtime-source-proof-") as temporary:
        archive = Path(temporary) / "source.zip"
        archive.write_bytes(evidence[prefix + "/source.zip"][0])
        check.archive(archive, source["commit"])
    if candidate == "statistics":
        require(not framework, "Statistics audit did not produce an XCFramework")
        hashes = json_bytes(evidence[prefix + "/statistics-source-hashes.json"][0])
        require(len(hashes) == 17 and all(safe_name(name) and re.fullmatch(r"[0-9a-f]{64}", digest)
                                        for name, digest in hashes.items()), "Invalid audited native hashes")
        require(json_bytes(evidence[prefix + "/inventory.json"][0])["base"] == check.CONFIG["base_commit"],
                "Statistics audit base differs")
        return
    require(framework, "Missing actual built Background framework")
    built = json_bytes(evidence["background/built-framework.json"][0])
    require(built == {"source_commit": source["commit"],
                      "files": {name: sha256(raw) for name, (raw, _) in framework.items()}},
            "Framework differs from native build receipt")
    require(evidence["background/SUCCESS.txt"][0] and
            evidence["background/tested-commit.txt"][0].decode().strip() == source["commit"],
            "Native build did not complete for this source")
    headers = "background/compiled-headers/"
    require(evidence[headers + "source-commit.txt"][0].decode().strip() == source["commit"],
            "Prepared native headers are from another source")
    native = load_module("candidate_native_inputs", root / "Tests/Background/native_inputs.py")
    require(evidence[headers + "module.modulemap"][0] == native.MODULE, "Unexpected native module map")
    expected = "".join(sha256(evidence[headers + name][0]) + "  " + name + "\n"
                       for name in ("hev-main.h", "module.modulemap"))
    require(evidence[headers + "SHA256SUMS.txt"][0] == expected.encode(), "Prepared header checksum differs")
    for name, (raw, _) in framework.items():
        if name.endswith("/Headers/hev-main.h"):
            require(raw == evidence[headers + "hev-main.h"][0], "Built framework/SDK headers differ")
    require({"ios-arm64/Headers/hev-main.h", "ios-arm64_x86_64-simulator/Headers/hev-main.h"} <= set(framework),
            "Missing required native framework slices")
    tracked = git(root, "ls-tree", "-rz", "--name-only", "HEAD").split(b"\0")
    hashes = {os.fsdecode(name): sha256(read_file(root / os.fsdecode(name))[0]) for name in tracked if name}
    require(json_bytes(evidence["audio-checks/source-sha256.json"][0]) == hashes, "SDK source hashes differ")
    require(re.search(rb"(?m)^27\.[^\r\n]*$", evidence["audio-checks/toolchain.txt"][0]),
            "Missing iOS 27 SDK identity")


def validate_inventory(manifest, payloads):
    require(type(manifest.get("schema")) is int and manifest["schema"] == 1, "Unknown handoff schema")
    require(set(payloads) == set(manifest["files"]), "Archive/manifest inventory differs")
    folded = set()
    for name, (raw, mode) in payloads.items():
        safe_name(name)
        require(name.casefold() not in folded, "Duplicate or case-colliding payload")
        folded.add(name.casefold())
        require(type(mode) is int and mode & ~0o777 == 0 and mode & 0o400, "Unsafe file mode")
        entry = manifest["files"][name]
        require(type(entry["size"]) is int and type(entry["mode"]) is int and
                entry == {"size": len(raw), "sha256": sha256(raw), "mode": mode},
                "Archive/manifest bytes or mode differ: " + name)
    for name in folded:
        require(all(parent.as_posix() not in folded for parent in PurePosixPath(name).parents
                    if parent.as_posix() != "."), "Payload file/directory collision")


def write_archive(path, manifest, payloads):
    with tarfile.open(path, "x:gz", format=tarfile.PAX_FORMAT) as archive:
        for name, (raw, mode) in sorted({"MANIFEST.json": (encoded(manifest), 0o644), **payloads}.items()):
            item = tarfile.TarInfo(safe_name(name))
            item.size, item.mode, item.mtime = len(raw), mode, 0
            archive.addfile(item, io.BytesIO(raw))


def read_archive(path, expected_hash, candidate, root):
    raw = read_file(path)[0]
    require(sha256(raw) == expected_hash, "TAR digest differs from immutable producer receipt")
    payloads, folded = {}, set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for item in archive.getmembers():
            name = safe_name(item.name)
            require(item.isfile() and not item.issparse(), "Non-regular TAR input")
            require(name.casefold() not in folded, "Duplicate or case-colliding TAR path")
            folded.add(name.casefold())
            require(item.mode & ~0o777 == 0 and item.mode & 0o400, "Unsafe TAR mode")
            payloads[name] = (archive.extractfile(item).read(), item.mode)
    require("MANIFEST.json" in payloads, "Missing transfer manifest")
    manifest = json_bytes(payloads.pop("MANIFEST.json")[0])
    validate_inventory(manifest, payloads)
    if candidate == "integrated":
        # Exercise the product owner's original archive boundary as well.
        old_manifest, old_payloads = integrated(root).read_archive(path, expected_hash)
        require(old_manifest == manifest and old_payloads == payloads, "Integrated archive interpretation differs")
    return manifest, payloads


def artifact_name(candidate, producer):
    return "UDP-Echo-runtime-" + candidate + "-" + producer["run_id"] + "-" + producer["attempt"]


def pack(args):
    root = args.root.resolve()
    producer = context()
    require(producer["job"] == "build", "Unexpected producer job")
    source, pins = candidate_identity(args.candidate, root)
    payloads = collect(args.candidate, root, source)
    manifest = {"schema": 1, "candidate": args.candidate, "source": source, "native_pins": pins,
                "producer": producer, "files": {name: {"size": len(raw), "sha256": sha256(raw), "mode": mode}
                                                for name, (raw, mode) in sorted(payloads.items())}}
    validate_inventory(manifest, payloads)
    validate_payloads(args.candidate, root, source, manifest, payloads)
    requested_root, output = args.root.absolute(), args.output.absolute()
    require(output.is_relative_to(requested_root), "Output is outside the requested candidate checkout")
    relative_output = safe_name(output.relative_to(requested_root).as_posix())
    output = root / relative_output
    # Keep output inside this candidate's artifact tree, as the workflow expects.
    unlinked(output, root)
    require(output.is_relative_to(root / "artifacts"), "Output must be in candidate artifacts")
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), "Handoff output is not empty")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "runtime-input.tar.gz"
    write_archive(archive, manifest, payloads)
    archive_raw = read_file(archive)[0]
    require(candidate_identity(args.candidate, root) == (source, pins) and context() == producer,
            "Source/helper identity moved while packing")
    receipt = {key: value for key, value in manifest.items() if key != "files"}
    receipt.update({"status": "VERIFIED_RUNTIME_INPUT_EXPORTED", "artifact_name": artifact_name(args.candidate, producer),
                    "archive_sha256": sha256(archive_raw), "archive_size": len(archive_raw)})
    with (output / "producer.json").open("xb") as stream:
        stream.write(encoded(receipt))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write("archive-sha256=" + receipt["archive_sha256"] + "\nartifact-name=" + receipt["artifact_name"]
                     + "\nproducer-attempt=" + producer["attempt"] + "\n")
    print("Exported exact", args.candidate, "inputs:", receipt["archive_sha256"])


def read_artifact(path, metadata):
    raw = read_file(path)[0]
    positive(metadata["id"])
    require(metadata["expired"] is False and type(metadata["size_in_bytes"]) is int
            and metadata["size_in_bytes"] == len(raw)
            and metadata["digest"] == "sha256:" + sha256(raw), "Immutable GitHub artifact bytes differ")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = archive.infolist()
        require(len(items) == 2 and {item.filename for item in items} == {"runtime-input.tar.gz", "producer.json"},
                "Missing, extra or duplicate artifact ZIP entry")
        for item in items:
            mode = item.external_attr >> 16
            require(not item.is_dir() and stat.S_IFMT(mode) in (0, stat.S_IFREG) and mode & 0o7000 == 0,
                    "Linked or unsafe artifact ZIP entry")
        archive_raw = archive.read("runtime-input.tar.gz")
        receipt = json_bytes(archive.read("producer.json"))
    require(type(receipt["archive_size"]) is int and len(archive_raw) == receipt["archive_size"]
            and sha256(archive_raw) == receipt["archive_sha256"], "Archive differs from bound producer receipt")
    return receipt, archive_raw


def check_producer(candidate, source, pins, consumer, receipt, metadata, producer_job):
    require(receipt["schema"] == 1 and type(receipt["schema"]) is int
            and receipt["status"] == "VERIFIED_RUNTIME_INPUT_EXPORTED", "Invalid producer receipt")
    producer = receipt["producer"]
    attempt = positive(producer["attempt"])
    require(int(attempt) <= int(consumer["attempt"]), "Producer attempt is from the future")
    require(producer == {**consumer, "attempt": attempt, "job": producer_job},
            "Producer repository/run/helper/job identity differs")
    require(receipt["candidate"] == candidate and receipt["source"] == source and receipt["native_pins"] == pins,
            "Producer candidate source or native pins differ")
    require(receipt["artifact_name"] == artifact_name(candidate, producer) == metadata["name"],
            "Wrong immutable artifact name")
    run = metadata["workflow_run"]
    require(positive(run["id"]) == producer["run_id"] and run["head_sha"] == producer["helper"]["commit"],
            "Artifact belongs to another workflow run/source")
    job = metadata["verified_producer_job"]
    positive(job["id"])
    expected_name = f"{producer_job} ({candidate}, {source['commit']}, xcode-27, true)"
    require(job["name"] == expected_name and positive(job["run_id"]) == producer["run_id"]
            and positive(job["run_attempt"]) == attempt and job["head_sha"] == producer["helper"]["commit"]
            and job["status"] == "completed" and job["conclusion"] == "success",
            "Verified numeric producer job differs or did not succeed")
    steps = [step for step in job["steps"] if step["name"] == "Execute the exact candidate owner gates"]
    require(len(steps) == 1 and steps[0]["conclusion"] == "success", "Producer execution step did not succeed")


def destinations(candidate, root, payloads):
    result = {}
    for name in payloads:
        if candidate == "integrated":
            prefix = "product/" if name.startswith("product/") else "phases/"
            base = root / (".build/integrated-product-source" if prefix == "product/" else "artifacts/integrated")
        else:
            prefix = "framework/" if name.startswith("framework/") else "evidence/"
            base = root / (FRAMEWORK if prefix == "framework/" else "artifacts")
        path = base / safe_name(name[len(prefix):])
        unlinked(path, root)
        require(not path.exists(), "Refusing to replace existing runtime input: " + str(path))
        result[name] = path
    if candidate in ("background", "integrated"):
        generated = root / (FRAMEWORK if candidate == "background" else ".build/integrated-product-source")
        require(not generated.exists(), "Runtime requires a fresh generated product destination")
    return result


def restore(args):
    root = args.root.resolve()
    consumer = context()
    require(consumer["job"] == "runtime" and args.producer_job == "build", "Unexpected consumer/producer job")
    source, pins = candidate_identity(args.candidate, root)
    metadata = json_bytes(read_file(args.metadata)[0])
    receipt, archive_raw = read_artifact(args.artifact, metadata)
    check_producer(args.candidate, source, pins, consumer, receipt, metadata, args.producer_job)
    with tempfile.TemporaryDirectory(prefix="runtime-input-verify-") as temporary:
        archive = Path(temporary) / "runtime-input.tar.gz"
        archive.write_bytes(archive_raw)
        manifest, payloads = read_archive(archive, receipt["archive_sha256"], args.candidate, root)
    require({key: value for key, value in manifest.items() if key != "files"} ==
            {key: receipt[key] for key in ("schema", "candidate", "source", "native_pins", "producer")},
            "Archive identity differs from bound producer receipt")
    validate_payloads(args.candidate, root, source, manifest, payloads)
    targets = destinations(args.candidate, root, payloads)
    receipt_path = root / "artifacts/runtime-input" / args.candidate / "consumer.json"
    unlinked(receipt_path, root)
    require(not receipt_path.exists(), "Refusing to replace consumer receipt")
    staging_parent = root / ".build"
    unlinked(staging_parent, root)
    staging_parent.mkdir(exist_ok=True)
    # No archive extraction API is used. All identities, bytes and paths have
    # passed before any final destination is populated.
    with tempfile.TemporaryDirectory(prefix="runtime-input-restore-", dir=staging_parent) as temporary:
        staging = Path(temporary)
        for name, (raw, mode) in payloads.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(raw)
            path.chmod(mode)
        for name, destination in targets.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging / name), destination)
    for name, path in targets.items():
        require(read_file(path) == payloads[name], "Restored bytes/mode differ")
    if args.candidate == "integrated":
        integrated(root).source.check_product()
    elif args.candidate == "background":
        load_module("candidate_native_inputs", root / "Tests/Background/native_inputs.py").verify()
    require(candidate_identity(args.candidate, root) == (source, pins) and context() == consumer,
            "Source/helper identity moved while restoring")
    result = {"status": "VERIFIED_RUNTIME_INPUT_RESTORED", "manifest": manifest, "consumer": consumer,
              "input_artifact_id": metadata["id"], "input_artifact_digest": metadata["digest"],
              "input_artifact_size": metadata["size_in_bytes"], "producer_job": metadata["verified_producer_job"],
              "archive_sha256": receipt["archive_sha256"],
              "scope": "Exact producer inputs restored; Simulator and UI remain separate required gates."}
    if args.candidate == "statistics":
        result["native_runtime_input"] = "Fresh clean Git checkout at native_pins; ui_audit.py builds the Simulator library."
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("xb") as stream:
        stream.write(encoded(result))
    print("Restored exact", args.candidate, "inputs from artifact", metadata["id"],
          "producer job", metadata["verified_producer_job"]["id"])


def main():
    require(__debug__, "Assertions must be enabled")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for operation in ("pack", "restore"):
        command = commands.add_parser(operation)
        command.add_argument("--candidate", choices=tuple(NAMES), required=True)
        command.add_argument("--root", type=Path, required=True)
        if operation == "pack":
            command.add_argument("--output", type=Path, required=True)
        else:
            command.add_argument("--artifact", type=Path, required=True)
            command.add_argument("--metadata", type=Path, required=True)
            command.add_argument("--producer-job", required=True)
    args = parser.parse_args()
    {"pack": pack, "restore": restore}[args.operation](args)


if __name__ == "__main__":
    main()
