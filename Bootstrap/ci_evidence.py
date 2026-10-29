#!/usr/bin/env python3
"""Bind fresh runtime inputs and final gates to this exact candidate workflow."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "AAAHN-AAAHN/heiher-socks5-ios"
API = "https://api.github.com/repos/" + REPOSITORY


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def api(path):
    request = urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return urllib.request.build_opener(NoRedirect).open(request, timeout=30)


def api_json(path):
    with api(path) as response:
        return json.load(response)


def pages(path, key):
    result = []
    for page in range(1, 101):
        separator = "&" if "?" in path else "?"
        values = api_json(path + separator + f"per_page=100&page={page}")[key]
        result.extend(values)
        if len(values) < 100:
            return result
    raise RuntimeError("GitHub pagination exceeded the bounded inventory")


def context(candidate, platform):
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY, "Unexpected repository")
    helper = os.environ["GITHUB_SHA"]
    require(re.fullmatch("[0-9a-f]{40}", helper), "Invalid helper identity")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])
    run = api_json(f"/actions/runs/{run_id}")
    require(run["head_sha"] == helper and run["run_attempt"] == attempt,
            "Workflow identity or attempt moved")
    manifest = json.loads((Path(__file__).parent / "candidates.json").read_bytes())
    rows = [row for row in manifest["matrix"]
            if row["name"] == candidate and row["os"] == platform]
    require(len(rows) == 1, "Candidate matrix row is missing or duplicated")
    return run_id, attempt, helper, rows[0]


def name(stage, row):
    runtime = str(row.get("runtime", False)).lower()
    return f"{stage} ({row['name']}, {row['sha']}, {row['os']}, {runtime})"


def completed_job(jobs, expected_name, required_step):
    found = [job for job in jobs if job["name"] == expected_name]
    require(len(found) == 1, "Expected one job: " + expected_name)
    job = found[0]
    require(job["status"] == "completed" and job["conclusion"] == "success",
            "Required job did not succeed: " + expected_name)
    steps = [step for step in job["steps"] if step["name"] == required_step]
    require(len(steps) == 1 and steps[0]["conclusion"] == "success",
            "Required execution step did not succeed: " + required_step)
    return {key: job[key] for key in
            ("id", "name", "head_sha", "run_id", "run_attempt", "status",
             "conclusion", "html_url", "started_at", "completed_at", "steps")}


def download(candidate, output):
    run_id, attempt, helper, row = context(candidate, "xcode-27")
    require(row.get("runtime") is True, "Runtime was not requested")
    jobs = pages(f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    producer = completed_job(jobs, name("build", row),
                             "Execute the exact candidate owner gates")
    expected = f"UDP-Echo-runtime-{candidate}-{run_id}-{attempt}"
    artifacts = pages(f"/actions/runs/{run_id}/artifacts", "artifacts")
    matches = [item for item in artifacts if item["name"] == expected]
    require(len(matches) == 1, "Runtime artifact is missing or duplicated")
    metadata = matches[0]
    require(not metadata["expired"], "Runtime artifact expired")
    require(metadata["workflow_run"]["id"] == run_id and
            metadata["workflow_run"]["head_sha"] == helper, "Artifact source differs")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", metadata.get("digest", "")),
            "GitHub artifact digest is absent")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "runtime-input.zip"
    try:
        response = api(f"/actions/artifacts/{metadata['id']}/zip")
    except urllib.error.HTTPError as error:
        require(error.code in (301, 302, 303, 307, 308), "Artifact download failed")
        location = error.headers["Location"]
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == "https" and parsed.hostname and
                any(parsed.hostname.endswith(suffix) for suffix in
                    (".blob.core.windows.net", ".githubusercontent.com")),
                "Unexpected artifact download host")
        # The signed storage request must not receive the GitHub credential.
        response = urllib.request.urlopen(location, timeout=60)
    digest = hashlib.sha256()
    size = 0
    with response, destination.open("wb") as stream:
        while block := response.read(1024 * 1024):
            stream.write(block)
            digest.update(block)
            size += len(block)
    require(size == metadata["size_in_bytes"] and
            "sha256:" + digest.hexdigest() == metadata["digest"],
            "Downloaded artifact differs from its immutable GitHub identity")
    metadata["verified_producer_job"] = producer
    (output / "artifact.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"artifact_id": metadata["id"], "bytes": size,
                      "sha256": digest.hexdigest(), "producer_job_id": producer["id"]}))


def gate(candidate, platform, output):
    run_id, attempt, helper, row = context(candidate, platform)
    jobs = pages(f"/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    build = completed_job(jobs, name("build", row),
                          "Execute the exact candidate owner gates")
    runtime = None
    if row.get("runtime"):
        runtime = completed_job(jobs, name("runtime", row),
                                "Execute requested macOS runtime coverage")
    for job in [build] + ([runtime] if runtime else []):
        require(job["head_sha"] == helper and job["run_id"] == run_id and
                job["run_attempt"] == attempt, "Executed job identity differs")
    output.mkdir(parents=True, exist_ok=True)
    record = {"result": "PASS", "candidate": row, "helper_sha": helper,
              "run_id": run_id, "run_attempt": attempt,
              "build_job": build, "runtime_job": runtime}
    (output / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"result": "PASS", "candidate": row,
                      "build_job_id": build["id"],
                      "runtime_job_id": runtime["id"] if runtime else None}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("download", "gate"))
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--platform", default="xcode-27")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "download":
        download(args.candidate, args.output)
    else:
        gate(args.candidate, args.platform, args.output)


if __name__ == "__main__":
    main()
