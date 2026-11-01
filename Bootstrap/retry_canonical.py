"""Request one fresh canonical run after a recorded Simulator setup failure."""
import json
import os

import ref_maintenance as maintenance


def main():
    maintenance.require(os.environ["GITHUB_REPOSITORY"] == maintenance.REPOSITORY,
                        "Unexpected repository")
    maintenance.require(maintenance.git("rev-parse", "HEAD") == os.environ["GITHUB_SHA"],
                        "Checkout must be the exact retry helper")
    maintenance.git("diff", "--exit-code", "HEAD", "--")
    maintenance.git("diff", "--cached", "--exit-code", "HEAD", "--")
    plan = json.loads((maintenance.ROOT / "Bootstrap/ref-operations.json").read_bytes())
    retry = plan["canonical_retry"]
    result = {"operation": "retry_canonical", "result": "FAIL",
              "run_id": os.environ["GITHUB_RUN_ID"],
              "helper_commit": os.environ["GITHUB_SHA"],
              "canonical_ci_complete": False, "remote_ref_mutations": 0}
    try:
        maintenance.require(plan["operation"] == "dispatch", "Unexpected retry plan")
        preflight = {}
        maintenance.execute(plan, preflight, check_only=True)
        result["original_preflight_result"] = preflight["result"]
        branch = retry["branch"]
        source = plan["final_heads"][branch]
        run, jobs = maintenance.run_jobs(retry["failed_run_id"], retry["failed_run_attempt"])
        maintenance.require(run["head_branch"] == branch and run["head_sha"] == source
                            and run["path"] == ".github/workflows/verify-build.yml"
                            and run["conclusion"] == "failure", "Failed run identity differs")
        failed = jobs[retry["failed_job_id"]]
        maintenance.require(failed["conclusion"] == "failure"
                            and any(step["name"] == retry["failed_step"]
                                    and step["conclusion"] == "failure"
                                    for step in failed["steps"]), "Recorded failure differs")
        maintenance.verify_heads(plan["final_heads"], maintenance.refs("heads"))
        tags = maintenance.refs("tags")
        result["previous_failure"] = retry
        result["pending_dispatch"] = {"branch": branch, "source_sha": source}
        maintenance.api("actions/workflows/verify-build.yml/dispatches", {"ref": branch})
        result["dispatches"] = [{"branch": branch, "source_sha": source,
                                  "workflow": "verify-build.yml", "status": "REQUESTED"}]
        result.pop("pending_dispatch")
        maintenance.verify_heads(plan["final_heads"], maintenance.refs("heads"))
        maintenance.require(maintenance.refs("tags") == tags, "Tags changed during retry")
        result["result"] = "PASS_REQUESTED_NEW_RUN_NOT_CANONICAL_ACCEPTANCE"
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
