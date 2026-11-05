"""Archive, publish or clean only explicitly leased UDP Echo repository refs."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "AAAHN-AAAHN/heiher-socks5-ios"
OWNERS = {
    "main": "main", "udp": "feature/udp-compat",
    "statistics": "feature/traffic-statistics", "background": "feature/background",
    "server": "feature/server-control", "settings": "feature/settings-persistence",
    "icon": "feature/app-icon", "integrated": "release/integrated",
}
BRANCHES = set(OWNERS.values())
ICMP = "feature/icmp-relay"
SELF = "work/udp-echo-publish-20261028"
TEMPORARY = {SELF, "work/udp-echo-build-20261028", "work/udp-echo-main-20261028",
             "work/udp-echo-udp-20261028"}
BASES = dict(zip(OWNERS, (
    "94cc35ba5b50bab177f7aa678aa5af8fd3b8481d", "9baac92fb4508d9e1b96f00744a91ff1cae77003",
    "91a6e736a9b9e007caa49d9aac44f8e4d9697c00", "c6935dbfbc6fecb7d7f573db0d5149bb0afc61b9",
    "7e40f951441cb226bc5e22a95d9c0658aba76939", "c1722e48f99e140b98cc436979b8ffc49ca0fa63",
    "7d224414d29e7aa243e9542b3144584fe8f0fdf2", "e9d8e75f96f4cc96cb53604edd30e5077c87032c")))
FORBIDDEN = ("e5980901a6c0b7a8b12ddc37461e22405f7dbe0e",
             "0a62910f5e444edbf176fe3ccd52363e5b8f869e")
PARENTS = {"udp": ("main",), "statistics": ("udp",), "background": ("udp",),
           "server": ("main",), "settings": ("server",), "icon": ("main",),
           "integrated": ("udp", "statistics", "background", "server", "settings", "icon")}
PLATFORMS = ("ubuntu-24.04", "xcode-27")
WORKFLOW = "verify-build.yml"
LEGACY_MAIN_HELPER = "0303b7708027c060e536ea5f0f705d15270fe26e"
CURRENT_EIGHT_SCHEMA = "current-eight-v1"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def full_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def api(path, body=None):
    request = Request(
        "https://api.github.com/repos/" + REPOSITORY + "/" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return None if response.status == 204 else json.load(response)
    except HTTPError as error:
        if error.code == 404 and body is None:
            return None
        raise


def refs(prefix):
    value = api("git/matching-refs/" + prefix + "/")
    require(isinstance(value, list), "Missing remote ref inventory")
    return {item["ref"]: item["object"]["sha"] for item in value}


def check_map(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names), label + " scope differs")
    require(all(full_sha(sha) for sha in value.values()), label + " has an invalid commit")


def verify_heads(expected, actual):
    check_map(expected, BRANCHES, "Final heads")
    for branch, sha in expected.items():
        require(actual.get("refs/heads/" + branch) == sha, "Concurrent branch change: " + branch)


def verify_old_heads(old, actual):
    check_map(old, BRANCHES | {ICMP}, "Old heads")
    verify_heads({name: sha for name, sha in old.items() if name in BRANCHES}, actual)
    require(actual.get("refs/heads/" + ICMP) == old[ICMP], "Concurrent ICMP branch change")


def current_eight_plan(plan):
    schema = plan.get("ref_schema")
    require(schema in (None, CURRENT_EIGHT_SCHEMA), "Unknown ref plan schema")
    if schema is None:
        return False
    require(plan["operation"] in ("archive", "publish", "dispatch", "cleanup"),
            "Current-eight schema only supports archive, publication, dispatch or cleanup")
    return True


def verify_current_heads(expected, actual):
    verify_heads(expected, actual)
    require("refs/heads/" + ICMP not in actual, "ICMP must be absent in current-eight topology")


def verify_tags(expected, actual):
    require(isinstance(expected, dict), "Missing preserved tags")
    for name, sha in expected.items():
        require(name.startswith("refs/tags/") and full_sha(sha), "Invalid preserved tag")
        require(actual.get(name) == sha, "Historical tag changed: " + name)


def archive_tags(old):
    return {"refs/tags/archive/before-udp-echo-20261028/" + branch + "-" + sha[:12]: sha
            for branch, sha in old.items()}


def current_archive_tags(old):
    return {"refs/tags/archive/before-current8-publication/" + branch + "-" + sha[:12]: sha
            for branch, sha in old.items()}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def verify_sources(final):
    check_map(final, BRANCHES, "Final heads")
    manifest = json.loads((ROOT / "Bootstrap/candidates.json").read_bytes())
    entries = manifest["candidates"] + manifest.get("support", [])
    declared = {entry["name"]: entry["sha"] for entry in entries}
    require(len(declared) == len(entries), "Duplicate final bundle owner")
    if "main" not in declared:
        # The generator deliberately excludes the already published Main work ref
        # from the seven-owner bundle. It remains an exact remote prerequisite.
        require(refs("heads").get("refs/heads/work/udp-echo-main-20261028") == final["main"],
                "Verified Main remote prerequisite changed")
        declared["main"] = final["main"]
    require(declared == {owner: final[branch] for owner, branch in OWNERS.items()},
            "Final heads differ from the verified candidate bundle")
    for owner, branch in OWNERS.items():
        sha = final[branch]
        require(git("cat-file", "-t", sha) == "commit", "Final source must be a commit")
        for ancestor, expected in [(BASES[owner], 0), *((value, 1) for value in FORBIDDEN)]:
            result = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", ancestor, sha])
            require(result.returncode == expected, "Missing or forbidden ancestry: " + branch)
        document = json.loads(git("show", sha + ":docs/documentation.json"))
        require(document["branch"] == branch, "Source branch identity differs: " + branch)
        if owner in PARENTS:
            parents = {OWNERS[parent]: final[OWNERS[parent]] for parent in PARENTS[owner]}
            require(document["parents"] == parents, "Final parent manifest differs: " + branch)
        else:
            parents = {"upstream": "180012e8b9dbaa2002a68ebd2c75bccebcfb789c"}
            require(document["parents"] == parents, "Main upstream parent differs")
        for parent in parents.values():
            result = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", parent, sha])
            require(result.returncode == 0, "Final declared parent is not an ancestor: " + branch)
        if owner == "integrated":
            membership = json.loads(git("show", sha + ":docs/feature-membership.json"))
            require(membership["branches"] == document["parents"], "Final owner membership differs")


def positive_id(value):
    return type(value) is int and value > 0


def run_jobs(run_id, attempt):
    require(positive_id(run_id) and positive_id(attempt), "Invalid run or attempt")
    prefix = f"actions/runs/{run_id}/attempts/{attempt}"
    run = api(prefix)
    require(isinstance(run, dict) and run.get("id") == run_id and run.get("run_attempt") == attempt,
            "Workflow run/attempt differs")
    require(run.get("status") == "completed", "Workflow attempt is still active")
    value = api(prefix + "/jobs?per_page=100")
    require(isinstance(value, dict) and isinstance(value.get("jobs"), list), "Missing workflow jobs")
    jobs = {job["id"]: job for job in value["jobs"]}
    require(len(jobs) == value.get("total_count"), "Incomplete or duplicate workflow job inventory")
    require(all(job.get("run_id") == run_id and job.get("run_attempt") == attempt
                and job.get("head_sha") == run.get("head_sha") for job in jobs.values()),
            "Workflow job run/attempt/helper identity differs")
    return run, jobs


def successful_job(jobs, job_id, run_id):
    require(positive_id(job_id) and job_id in jobs, "Job is not in the expected workflow attempt")
    job = jobs[job_id]
    require(job.get("run_id") == run_id and job.get("status") == "completed"
            and job.get("conclusion") == "success", "Required job did not succeed")
    return job


def successful_step(job, name):
    steps = [step for step in job.get("steps", []) if step.get("name") == name]
    require(len(steps) == 1 and steps[0].get("status") == "completed"
            and steps[0].get("conclusion") == "success", "Required step did not execute successfully: " + name)


def verify_candidate_job(row, final, runs, manifests):
    owner, sha, platform = row["owner"], row["source_sha"], row["platform"]
    require(owner in OWNERS and platform in PLATFORMS and sha == final[OWNERS[owner]],
            "Candidate gate source/platform differs from final heads")
    run_id, attempt, job_id, helper = row["run_id"], row["run_attempt"], row["job_id"], row["helper_sha"]
    require(full_sha(helper) and positive_id(job_id),
            "Invalid helper or final gate job")
    key = (run_id, attempt)
    if key not in runs:
        runs[key] = run_jobs(run_id, attempt)
    run, jobs = runs[key]
    require(run.get("head_sha") == helper
            and run.get("path") == ".github/workflows/udp-echo-candidate.yml",
            "Candidate helper SHA or workflow differs")
    if helper not in manifests:
        value = api("contents/Bootstrap/candidates.json?ref=" + helper)
        require(isinstance(value, dict) and value.get("encoding") == "base64", "Missing frozen candidate declaration")
        manifests[helper] = json.loads(base64.b64decode(value["content"], validate=False))
    manifest = manifests[helper]
    require(any(entry.get("name") == owner and entry.get("sha") == sha
                for entry in manifest["candidates"]), "Source is not a tested candidate of this helper")
    matrix = [entry for entry in manifest["matrix"] if entry.get("name") == owner and entry.get("os") == platform]
    runtime = platform == "xcode-27" and owner not in ("main", "udp")
    require(len(matrix) == 1 and matrix[0].get("sha") == sha
            and type(matrix[0].get("runtime", False)) is bool
            and matrix[0].get("runtime", False) == runtime, "Required runtime/source matrix differs")
    job = successful_job(jobs, job_id, run_id)
    label = f"({owner}, {sha}, {platform}"
    expected = "verify " + label + ", " + str(runtime).lower() + ")"
    legacy = (owner == "main" and helper == LEGACY_MAIN_HELPER and "runtime" not in matrix[0]
              and not runtime and job.get("name") == "verify " + label + ")")
    require(job.get("name") == expected or legacy, "Candidate job identity differs")
    build = successful_job(jobs, row.get("build_job_id", job_id), run_id)
    require(label in build.get("name", ""), "Producer source identity differs")
    source_step = ("Run actions/checkout@11d5960a326750d5838078e36cf38b85af677262" if legacy
                   else "Verify candidate objects and create a detached local worktree")
    successful_step(build, source_step)
    successful_step(build, "Execute the exact candidate owner gates")
    if runtime:
        review = successful_job(jobs, row.get("runtime_job_id", job_id), run_id)
        require(label in review.get("name", ""), "Runtime source identity differs")
        successful_step(review, "Verify candidate objects and create a detached local worktree")
        successful_step(review, "Execute requested macOS runtime coverage")
    else:
        require("runtime_job_id" not in row, "Unexpected runtime proof for this platform")
    return (owner, platform), job_id


def verify_candidate_jobs(plan):
    final, rows = plan["final_heads"], plan["verified_jobs"]
    require(isinstance(rows, list) and len(rows) == 16, "Exactly sixteen candidate platform gates are required")
    seen, identities, runs, manifests = set(), set(), {}, {}
    for row in rows:
        pair, job_id = verify_candidate_job(row, final, runs, manifests)
        require(pair not in seen and job_id not in identities, "Duplicate candidate platform gate or job")
        seen.add(pair)
        identities.add(job_id)
    require(seen == {(owner, platform) for owner in OWNERS for platform in PLATFORMS}, "Incomplete platform gates")
    closure = plan["requirement_closure"]
    require(closure.get("result") == "PASS" and closure.get("final_heads") == final
            and closure.get("unresolved") == [] and isinstance(closure.get("evidence"), str)
            and closure["evidence"].strip(), "Requirement closure is missing, unresolved or belongs to different sources")


def canonical_required_steps(branch):
    checkout = "Run actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    standard = "Validate source, test native code, and archive iOS on macOS"
    owner_step = {
        "main": standard, "feature/background": standard, "feature/app-icon": standard,
        "feature/udp-compat": "Audit exact sources, native UDP behavior and address memory safety",
        "feature/traffic-statistics": "Verify statistics-only sources, native accounting and Swift types",
        "feature/server-control": "Native, lifecycle and persistence checks without IPA",
        "feature/settings-persistence": "Native, lifecycle and persistence checks without IPA",
        "release/integrated": "Exact latest composition, native and model checks",
    }[branch]
    linux, macos = [checkout, owner_step], [checkout, owner_step]
    if branch == "feature/udp-compat":
        macos += ["Record the actual iOS 27 toolchain",
                  "Type check the unchanged app sources with the actual iOS 27 SDK"]
    elif branch == "feature/traffic-statistics":
        macos += ["Record the actual iOS 27 toolchain",
                  "Exercise actual Server controls and tabs on iOS 27 Simulator"]
    elif branch in ("feature/server-control", "feature/settings-persistence"):
        macos += ["Actual iOS 27 API type checks",
                  ("Actual server-control UI and native listener on iOS 27 Simulator"
                   if branch == "feature/server-control"
                   else "Actual persistence, restart and JSON on iOS 27 Simulator")]
    elif branch == "release/integrated":
        macos = [checkout,
                 "Exact latest composition, native and model checks; ARM64 archive on macOS",
                 "Record the actual Apple build environment",
                 "Actual iOS 27 type check and archived IPA validation",
                 "Preserve verified product bytes and modes for the independent review job"]
    required = {"verify (ubuntu-24.04)": linux, "verify (xcode-27)": macos}
    if branch == "release/integrated":
        required["Simulator and integrated UI (xcode-27)"] = [
            checkout,
            "Record the independent Apple review environment",
            "Require the specific producer ID and digest before downloading",
            "Verify and restore the exact producer source, framework and phase evidence",
            "Actual integrated UI, saved intent and native response",
            "Original and remapped Simulator installs, saved tabs and real TCP"]
    return required


def verify_canonical_runs(plan):
    rows, final = plan["canonical_runs"], plan["final_heads"]
    require(isinstance(rows, list) and len(rows) == 8, "Eight canonical branch runs are required")
    seen = set()
    for row in rows:
        branch = row["branch"]
        require(branch in BRANCHES and branch not in seen and row["source_sha"] == final[branch],
                "Canonical branch/source scope differs")
        seen.add(branch)
        run, jobs = run_jobs(row["run_id"], row["run_attempt"])
        require(run.get("head_branch") == branch and run.get("head_sha") == final[branch]
                and run.get("path") == ".github/workflows/" + WORKFLOW
                and run.get("event") in ("push", "workflow_dispatch")
                and run.get("conclusion") == "success", "Canonical workflow identity or result differs")
        for name, steps in canonical_required_steps(branch).items():
            matching = [job for job in jobs.values() if job.get("name") == name]
            require(len(matching) == 1, "Canonical required job is missing: " + name)
            job = successful_job(jobs, matching[0]["id"], row["run_id"])
            for step in steps:
                successful_step(job, step)


def atomic_push(updates, removals, old):
    require(set(old) == set(updates) | set(removals), "Every ref mutation requires an explicit lease")
    require(not set(updates) & set(removals), "A ref cannot be updated and removed together")
    require(all(full_sha(sha) for sha in [*old.values(), *updates.values()]), "Invalid mutation SHA")
    token = base64.b64encode(("x-access-token:" + os.environ["GH_TOKEN"]).encode()).decode()
    print("::add-mask::" + token, flush=True)
    env = dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
               GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + token, GIT_TERMINAL_PROMPT="0")
    command = ["git", "-C", str(ROOT), "push", "--atomic", "--porcelain"]
    command += ["--force-with-lease=refs/heads/" + branch + ":" + old[branch] for branch in sorted(old)]
    command += ["https://github.com/" + REPOSITORY + ".git"]
    command += [sha + ":refs/heads/" + branch for branch, sha in sorted(updates.items())]
    command += [":refs/heads/" + branch for branch in sorted(removals)]
    subprocess.run(command, env=env, check=True, timeout=120)


def dispatch(final, result):
    result["dispatches"] = []
    result["canonical_ci_complete"] = False
    # Start the longest owner suites before shorter jobs occupy macOS runners.
    first = ("release/integrated", "feature/background")
    order = [*first, *sorted(set(final) - set(first))]
    for branch in order:
        sha = final[branch]
        verify_heads(final, refs("heads"))
        result["pending_dispatch"] = {"branch": branch, "source_sha": sha, "workflow": WORKFLOW}
        api("actions/workflows/" + WORKFLOW + "/dispatches", {"ref": branch})
        result["dispatches"].append({"branch": branch, "source_sha": sha,
                                     "workflow": WORKFLOW, "status": "REQUESTED"})
        result.pop("pending_dispatch")
    verify_heads(final, refs("heads"))


def execute(plan, result, check_only=False):
    operation = plan["operation"]
    current_eight = current_eight_plan(plan)
    if current_eight:
        result["ref_schema"] = CURRENT_EIGHT_SCHEMA
    publication_heads = verify_current_heads if current_eight else verify_old_heads
    preservation_tags = current_archive_tags if current_eight else archive_tags
    heads, tags = refs("heads"), refs("tags")
    verify_tags(plan["preserved_tags"], tags)
    if operation == "archive":
        old = plan["old_heads"]
        publication_heads(old, heads)
        archived, missing = preservation_tags(old), {}
        for name, sha in sorted(archived.items()):
            existing = tags.get(name)
            require(existing is None or existing == sha, "Archive tag differs: " + name)
            if existing is None:
                missing[name] = sha
        if not check_only:
            for name, sha in missing.items():
                require(api("git/refs", {"ref": name, "sha": sha})["object"]["sha"] == sha,
                        "Archive tag differs: " + name)
            require(refs("tags") == {**tags, **archived}, "Archive changed an unexpected tag")
            require(refs("heads") == heads, "Operating heads changed during archive")
        result["archive_tags"] = archived
        result["operating_refs_changed"] = False
    elif operation in ("publish", "dispatch"):
        final = plan["final_heads"]
        if operation == "publish":
            publication_heads(plan["old_heads"], heads)
            verify_tags(preservation_tags(plan["old_heads"]), tags)
        else:
            verify_heads(final, heads)
            require("refs/heads/" + ICMP not in heads, "ICMP was not removed by atomic publication")
        verify_sources(final)
        verify_candidate_jobs(plan)
        if not check_only:
            if operation == "publish":
                # Proof checks can take time. Refresh leases just before the atomic mutation.
                publication_heads(plan["old_heads"], refs("heads"))
                require(refs("tags") == tags, "Tag inventory changed before publication")
                result["publication_attempted"] = True
                atomic_push(final, set() if current_eight else {ICMP}, plan["old_heads"])
                result["publication_completed"] = True
                result["published_heads"] = final
                if not current_eight:
                    result["deleted_icmp_sha"] = plan["old_heads"][ICMP]
                after = refs("heads")
                expected = {**heads, **{"refs/heads/" + branch: sha for branch, sha in final.items()}}
                if not current_eight:
                    expected.pop("refs/heads/" + ICMP)
                require(after == expected, "Publication changed an unexpected head")
                require(refs("tags") == tags, "Publication changed tags")
            dispatch(final, result)
    elif operation == "cleanup":
        verify_heads(plan["final_heads"], heads)
        require("refs/heads/" + ICMP not in heads, "ICMP remains after publication")
        verify_canonical_runs(plan)
        obsolete = dict(plan["obsolete_heads"])
        check_map(obsolete, TEMPORARY - {SELF}, "Cleanup helpers")
        obsolete[SELF] = os.environ["GITHUB_SHA"]
        check_map(obsolete, TEMPORARY, "Cleanup leases")
        current = refs("heads")
        verify_heads(plan["final_heads"], current)
        require("refs/heads/" + ICMP not in current, "ICMP reappeared before cleanup")
        for branch, sha in obsolete.items():
            require(current.get("refs/heads/" + branch) == sha, "Deletion lease changed: " + branch)
        if not check_only:
            require(refs("tags") == tags, "Tag inventory changed before cleanup")
            result["cleanup_attempted"] = True
            atomic_push({}, set(obsolete), obsolete)
            result["cleanup_completed"] = True
            result["deleted_heads"] = obsolete
            after = refs("heads")
            expected = {name: sha for name, sha in current.items() if name.removeprefix("refs/heads/") not in obsolete}
            require(after == expected, "Cleanup changed an unexpected head")
            require(refs("tags") == tags, "Cleanup changed tags")
            result["final_heads"] = after
        result["canonical_ci_complete"] = True
    else:
        raise RuntimeError("Unknown maintenance operation")
    result["tags_preserved"] = tags
    result["result"] = "PASS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Validate inputs and remote evidence without mutations")
    options = parser.parse_args()
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY, "Unexpected repository")
    require(git("rev-parse", "HEAD") == os.environ["GITHUB_SHA"], "Checkout must be this exact helper commit")
    git("diff", "--exit-code", "HEAD", "--")
    git("diff", "--cached", "--exit-code", "HEAD", "--")
    plan = json.loads((ROOT / "Bootstrap/ref-operations.json").read_bytes())
    result = {"operation": plan["operation"], "run_id": os.environ["GITHUB_RUN_ID"],
              "helper_commit": os.environ["GITHUB_SHA"], "check_only": options.check_only, "result": "FAIL"}
    try:
        execute(plan, result, options.check_only)
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        output = ROOT / "artifacts/ref-maintenance"
        output.mkdir(parents=True, exist_ok=True)
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
