"""Request one fresh full Integrated run only after the UI state diagnostic is reviewed."""
import json
import os

import ref_maintenance as maintenance


def main():
    maintenance.require(os.environ["GITHUB_REPOSITORY"] == maintenance.REPOSITORY,
                        "Unexpected repository")
    maintenance.require(os.environ["GITHUB_RUN_ATTEMPT"] == "1",
                        "This fixed dispatch must not be rerun")
    maintenance.require(maintenance.git("rev-parse", "HEAD") == os.environ["GITHUB_SHA"],
                        "Checkout must be the exact retry helper")
    maintenance.git("diff", "--exit-code", "HEAD", "--")
    maintenance.git("diff", "--cached", "--exit-code", "HEAD", "--")
    plan = json.loads((maintenance.ROOT / "Bootstrap/ref-operations.json").read_bytes())
    result = {"operation": "retry_canonical", "result": "FAIL",
              "run_id": os.environ["GITHUB_RUN_ID"],
              "helper_commit": os.environ["GITHUB_SHA"],
              "canonical_ci_complete": False, "remote_ref_mutations": 0,
              "historical_failure_cause_resolved": False, "dispatches": []}
    try:
        maintenance.require(plan["operation"] == "dispatch", "Unexpected retry plan")
        retries = plan["canonical_retries"]
        maintenance.require([row["branch"] for row in retries] ==
                            ["release/integrated"],
                            "Exactly one full Integrated run is permitted")
        preflight = {}
        maintenance.execute(plan, preflight, check_only=True)
        result["original_preflight_result"] = preflight["result"]

        diagnostic = plan["ui_state_diagnostic"]
        run, jobs = maintenance.run_jobs(diagnostic["run_id"], diagnostic["run_attempt"])
        maintenance.require(run["head_sha"] == diagnostic["helper_sha"]
                            and run["head_branch"] == "work/udp-echo-udp-20261028"
                            and run["path"] == ".github/workflows/udp-echo-ui-diagnostic.yml"
                            and run["event"] == "push" and run["conclusion"] == "success",
                            "Fixed diagnostic identity or result differs")
        maintenance.require(set(jobs) == {diagnostic["job_id"]},
                            "Fixed diagnostic job inventory differs")
        job = maintenance.successful_job(jobs, diagnostic["job_id"], diagnostic["run_id"])
        for step in ("Run one original UI4 invocation with only temporary-app state logging",
                     "Preserve every actual outcome and exact diagnostic recipe"):
            maintenance.successful_step(job, step)
        artifact = maintenance.api("actions/artifacts/" + str(diagnostic["artifact_id"]))
        maintenance.require(artifact["id"] == diagnostic["artifact_id"]
                            and artifact["workflow_run"]["id"] == diagnostic["run_id"]
                            and artifact["workflow_run"]["head_sha"] == diagnostic["helper_sha"]
                            and artifact["size_in_bytes"] == diagnostic["artifact_bytes"]
                            and artifact["digest"] == "sha256:" + diagnostic["artifact_sha256"]
                            and artifact["expired"] is False,
                            "Actual diagnostic artifact identity differs")
        result["diagnostic"] = diagnostic

        previous = []
        for retry in retries:
            branch = retry["branch"]
            source = plan["final_heads"][branch]
            run, jobs = maintenance.run_jobs(retry["failed_run_id"], retry["failed_run_attempt"])
            maintenance.require(run["head_branch"] == branch and run["head_sha"] == source
                                and run["path"] == ".github/workflows/verify-build.yml"
                                and run["conclusion"] == "failure", "Failed run identity differs")
            failed = jobs[retry["failed_job_id"]]
            maintenance.require(failed["status"] == "completed" and failed["conclusion"] == "failure"
                                and any(step["name"] == retry["failed_step"]
                                        and step["conclusion"] == "failure"
                                        for step in failed["steps"]), "Recorded failure differs")
            previous.append(retry)
        result["previous_failures"] = previous
        heads = maintenance.refs("heads")
        maintenance.verify_heads(plan["final_heads"], heads)
        tags = maintenance.refs("tags")
        for retry in retries:
            branch = retry["branch"]
            source = plan["final_heads"][branch]
            maintenance.require(maintenance.refs("heads") == heads,
                                "A head changed before the fixed dispatch")
            maintenance.require(maintenance.refs("tags") == tags,
                                "A tag changed before the fixed dispatch")
            result["pending_dispatch"] = {"branch": branch, "source_sha": source}
            maintenance.api("actions/workflows/verify-build.yml/dispatches", {"ref": branch})
            result["dispatches"].append({"branch": branch, "source_sha": source,
                                         "workflow": "verify-build.yml", "status": "REQUESTED"})
            result.pop("pending_dispatch")
        maintenance.require(maintenance.refs("heads") == heads,
                            "A head changed during the fixed dispatch")
        maintenance.require(maintenance.refs("tags") == tags, "Tags changed during retry")
        result["result"] = "PASS_REQUESTED_ONE_NEW_RUN_NOT_CANONICAL_ACCEPTANCE"
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        output = maintenance.ROOT / "artifacts/ref-maintenance"
        output.mkdir(parents=True, exist_ok=True)
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
