"""Local regression checks for the destructive release boundaries; no network access."""
import base64
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch

import ref_maintenance as release


def sha(number):
    return f"{number:040x}"


def step(name):
    return {"name": name, "status": "completed", "conclusion": "success"}


def job(job_id, run_id, name, steps=()):
    return {"id": job_id, "run_id": run_id, "name": name, "status": "completed",
            "run_attempt": 1, "head_sha": sha(900),
            "conclusion": "success", "steps": list(steps)}


def fixture():
    final = {branch: sha(index + 1) for index, branch in enumerate(release.OWNERS.values())}
    helper, run_id = sha(900), 501
    rows, jobs, matrix = [], [], []
    for index, (owner, branch) in enumerate(release.OWNERS.items()):
        for platform_index, platform in enumerate(release.PLATFORMS):
            runtime = platform == "xcode-27" and owner not in ("main", "udp")
            job_id = 1000 + index * 2 + platform_index
            name = f"verify ({owner}, {final[branch]}, {platform}, {str(runtime).lower()})"
            steps = [step("Verify candidate objects and create a detached local worktree"),
                     step("Execute the exact candidate owner gates")]
            if runtime:
                steps.append(step("Execute requested macOS runtime coverage"))
            jobs.append(job(job_id, run_id, name, steps))
            rows.append(dict(owner=owner, source_sha=final[branch], platform=platform,
                             run_id=run_id, run_attempt=1, job_id=job_id, helper_sha=helper))
            matrix.append(dict(name=owner, sha=final[branch], os=platform, runtime=runtime))
    manifest = {"candidates": [dict(name=owner, sha=final[branch])
                               for owner, branch in release.OWNERS.items()], "matrix": matrix}
    run = dict(id=run_id, run_attempt=1, head_sha=helper, status="completed",
               path=".github/workflows/udp-echo-candidate.yml")
    plan = {"final_heads": final, "verified_jobs": rows,
            "requirement_closure": {"result": "PASS", "final_heads": dict(final),
                                    "unresolved": [], "evidence": "Reviewed socket and owner runtime receipts"}}
    return plan, manifest, run, jobs


def evidence_api(manifest, run, jobs):
    def read(path, body=None):
        if body is not None:
            raise AssertionError("Gate validation attempted a remote mutation")
        prefix = f"actions/runs/{run['id']}/attempts/{run['run_attempt']}"
        if path == prefix:
            return deepcopy(run)
        if path == prefix + "/jobs?per_page=100":
            return dict(total_count=len(jobs), jobs=deepcopy(jobs))
        if path.startswith("contents/Bootstrap/candidates.json?ref="):
            return dict(encoding="base64", content=base64.b64encode(json.dumps(manifest).encode()).decode())
        return None
    return read


class CandidateProofTests(unittest.TestCase):
    def test_inline_legacy_and_split_runtime_proof(self):
        plan, manifest, run, jobs = fixture()
        # The already completed main producer predates the optional runtime matrix field.
        run["head_sha"] = release.LEGACY_MAIN_HELPER
        for row in plan["verified_jobs"]:
            row["helper_sha"] = release.LEGACY_MAIN_HELPER
        for item in jobs:
            item["head_sha"] = release.LEGACY_MAIN_HELPER
        for index in (0, 1):
            manifest["matrix"][index].pop("runtime")
            jobs[index]["name"] = jobs[index]["name"].replace(", false)", ")")
            jobs[index]["steps"][0]["name"] = "Run actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
        # A new macOS run uses separate producer and runtime jobs, then a final verify gate.
        row, gate = plan["verified_jobs"][7], jobs[7]
        gate["steps"] = []
        identity = gate["name"].removeprefix("verify ")
        jobs.append(job(2000, run["id"], "build " + identity,
                        [step("Verify candidate objects and create a detached local worktree"),
                         step("Execute the exact candidate owner gates")]))
        jobs.append(job(2001, run["id"], "runtime " + identity,
                        [step("Verify candidate objects and create a detached local worktree"),
                         step("Execute requested macOS runtime coverage")]))
        for item in jobs[-2:]:
            item["head_sha"] = release.LEGACY_MAIN_HELPER
        row.update(build_job_id=2000, runtime_job_id=2001)
        with patch.object(release, "api", side_effect=evidence_api(manifest, run, jobs)):
            release.verify_candidate_jobs(plan)

    def test_bad_source_runtime_or_provenance_is_rejected(self):
        def stale_source(plan, manifest, run, jobs):
            plan["verified_jobs"][0]["source_sha"] = sha(999)
        def stale_helper(plan, manifest, run, jobs):
            run["head_sha"] = sha(999)
        def wrong_workflow(plan, manifest, run, jobs):
            run["path"] = ".github/workflows/diagnostic.yml"
        def wrong_attempt(plan, manifest, run, jobs):
            run["run_attempt"] = 2
        def duplicate_platform(plan, manifest, run, jobs):
            plan["verified_jobs"][1] = dict(plan["verified_jobs"][0], job_id=7777)
        def untested_candidate(plan, manifest, run, jobs):
            manifest["candidates"][0]["sha"] = sha(999)
        def disabled_runtime(plan, manifest, run, jobs):
            manifest["matrix"][7]["runtime"] = False
        def diagnostic_job(plan, manifest, run, jobs):
            jobs[7]["name"] = "fixture diagnostics"
        def unknown_legacy_helper(plan, manifest, run, jobs):
            manifest["matrix"][0].pop("runtime")
            jobs[0]["name"] = jobs[0]["name"].replace(", false)", ")")
        def skipped_runtime(plan, manifest, run, jobs):
            jobs[7]["steps"][-1]["conclusion"] = "skipped"
        def skipped_build(plan, manifest, run, jobs):
            jobs[0]["steps"][1]["conclusion"] = "skipped"
        def skipped_source_preparation(plan, manifest, run, jobs):
            jobs[0]["steps"][0]["conclusion"] = "skipped"
        def wrong_job_attempt(plan, manifest, run, jobs):
            jobs[0]["run_attempt"] = 2
        def unrelated_runtime_job(plan, manifest, run, jobs):
            plan["verified_jobs"][7]["runtime_job_id"] = jobs[5]["id"]
        def unresolved_defect(plan, manifest, run, jobs):
            plan["requirement_closure"]["unresolved"] = ["fixed relay association"]
        def stale_closure(plan, manifest, run, jobs):
            plan["requirement_closure"]["final_heads"]["main"] = sha(999)
        for change in (stale_source, stale_helper, wrong_workflow, wrong_attempt,
                       duplicate_platform, untested_candidate, disabled_runtime,
                       diagnostic_job, unknown_legacy_helper, skipped_runtime, skipped_build,
                       skipped_source_preparation, wrong_job_attempt,
                       unrelated_runtime_job, unresolved_defect, stale_closure):
            with self.subTest(change=change.__name__):
                plan, manifest, run, jobs = fixture()
                change(plan, manifest, run, jobs)
                with patch.object(release, "api", side_effect=evidence_api(manifest, run, jobs)):
                    with self.assertRaises(RuntimeError):
                        release.verify_candidate_jobs(plan)

    def test_incomplete_job_inventory_is_rejected(self):
        plan, manifest, run, jobs = fixture()
        original = evidence_api(manifest, run, jobs)
        def read(path, body=None):
            value = original(path, body)
            if path.endswith("jobs?per_page=100"):
                value["total_count"] += 1
            return value
        with patch.object(release, "api", side_effect=read):
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                release.verify_candidate_jobs(plan)


class RefMutationTests(unittest.TestCase):
    def setUp(self):
        self.plan, _, _, _ = fixture()
        self.old = {name: sha(index + 100) for index, name in enumerate(sorted(release.BRANCHES | {release.ICMP}))}
        self.plan.update(operation="publish", old_heads=self.old)
        self.tags = {"refs/tags/historical": sha(800), **release.archive_tags(self.old)}
        self.plan["preserved_tags"] = dict(self.tags)
        self.heads = {"refs/heads/" + name: value for name, value in self.old.items()}
        self.helpers = {name: sha(index + 700) for index, name in enumerate(sorted(release.TEMPORARY))}
        self.heads.update({"refs/heads/" + name: value for name, value in self.helpers.items()})
        self.heads["refs/heads/user/new-work"] = sha(890)
        self.requests, self.pushes = [], []
        self.result = {"result": "FAIL"}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(release, "refs", side_effect=lambda kind: dict(self.heads if kind == "heads" else self.tags)))
        self.stack.enter_context(patch.object(release, "verify_sources"))
        self.stack.enter_context(patch.object(release, "verify_candidate_jobs"))
        self.stack.enter_context(patch.object(release, "verify_canonical_runs"))
        self.stack.enter_context(patch.object(release, "atomic_push", side_effect=self.push))
        self.stack.enter_context(patch.object(release, "api", side_effect=self.api))
        self.stack.enter_context(patch.dict(os.environ, {"GITHUB_SHA": self.helpers[release.SELF]}))

    def push(self, updates, removals, old):
        self.assertEqual(set(old), set(updates) | set(removals))
        for name, expected in old.items():
            self.assertEqual(self.heads["refs/heads/" + name], expected)
        self.pushes.append((dict(updates), set(removals), dict(old)))
        for name, value in updates.items():
            self.heads["refs/heads/" + name] = value
        for name in removals:
            del self.heads["refs/heads/" + name]

    def api(self, path, body=None):
        self.requests.append((path, body))
        if path == "git/refs":
            self.tags[body["ref"]] = body["sha"]
            return {"object": {"sha": body["sha"]}}
        self.assertEqual(path, "actions/workflows/verify-build.yml/dispatches")
        self.assertIn(body["ref"], release.BRANCHES)
        return None

    def published(self):
        self.heads.update({"refs/heads/" + name: value for name, value in self.plan["final_heads"].items()})
        self.heads.pop("refs/heads/" + release.ICMP)

    def cleanup_plan(self):
        self.published()
        self.plan.update(operation="cleanup", obsolete_heads={name: value for name, value in self.helpers.items() if name != release.SELF})

    def test_atomic_publication_preserves_unrelated_refs_and_requests_eight_runs(self):
        before_tags = dict(self.tags)
        release.execute(self.plan, self.result)
        self.assertEqual(self.result["result"], "PASS")
        self.assertTrue(self.result["publication_completed"])
        self.assertFalse(self.result["canonical_ci_complete"])
        self.assertEqual(self.pushes, [(self.plan["final_heads"], {release.ICMP}, self.old)])
        self.assertEqual(len(self.requests), 8)
        self.assertEqual({row["branch"] for row in self.result["dispatches"]}, release.BRANCHES)
        self.assertEqual(self.tags, before_tags)
        self.assertEqual(self.heads["refs/heads/user/new-work"], sha(890))

    def test_prepublication_failures_do_not_mutate(self):
        for issue in ("lease", "archive", "closure"):
            with self.subTest(issue=issue):
                heads, tags = dict(self.heads), dict(self.tags)
                if issue == "lease":
                    self.heads["refs/heads/main"] = sha(999)
                elif issue == "archive":
                    self.tags.pop(next(iter(release.archive_tags(self.old))))
                else:
                    release.verify_candidate_jobs.side_effect = RuntimeError("Unresolved defect")
                with self.assertRaises(RuntimeError):
                    release.execute(self.plan, self.result)
                self.assertEqual(self.pushes, [])
                self.assertEqual(self.requests, [])
                self.heads, self.tags = heads, tags
                release.verify_candidate_jobs.side_effect = None

    def test_check_only_never_mutates(self):
        release.execute(self.plan, self.result, check_only=True)
        self.assertEqual(self.result["result"], "PASS")
        self.assertEqual(self.pushes, [])
        self.assertEqual(self.requests, [])
        self.assertNotIn("publication_completed", self.result)

    def test_failure_after_push_records_publication_and_partial_dispatch(self):
        count = 0
        def dispatch(path, body=None):
            nonlocal count
            count += 1
            if count == 3:
                raise RuntimeError("Dispatch unavailable")
            return self.api(path, body)
        release.api.side_effect = dispatch
        with self.assertRaisesRegex(RuntimeError, "Dispatch unavailable"):
            release.execute(self.plan, self.result)
        self.assertTrue(self.result["publication_completed"])
        self.assertEqual(len(self.result["dispatches"]), 2)
        self.assertIn("pending_dispatch", self.result)
        self.assertFalse(self.result["canonical_ci_complete"])
        self.assertEqual(self.result["result"], "FAIL")
        self.assertNotIn("refs/heads/" + release.ICMP, self.heads)

    def test_dispatch_recovery_does_not_move_refs(self):
        self.published()
        self.plan["operation"] = "dispatch"
        release.execute(self.plan, self.result)
        self.assertEqual(self.pushes, [])
        self.assertEqual(len(self.requests), 8)

    def test_cleanup_only_removes_four_helpers_after_icmp_is_absent(self):
        self.cleanup_plan()
        release.execute(self.plan, self.result)
        self.assertEqual(self.pushes, [({}, release.TEMPORARY, self.helpers)])
        self.assertTrue(self.result["canonical_ci_complete"])
        self.assertEqual(set(self.heads), {"refs/heads/" + name for name in release.BRANCHES} | {"refs/heads/user/new-work"})
        self.assertEqual(self.requests, [])

    def test_cleanup_rejects_changed_helper_or_remaining_icmp(self):
        self.cleanup_plan()
        self.heads["refs/heads/" + release.SELF] = sha(999)
        with self.assertRaisesRegex(RuntimeError, "Deletion lease"):
            release.execute(self.plan, self.result)
        self.heads["refs/heads/" + release.SELF] = self.helpers[release.SELF]
        self.heads["refs/heads/" + release.ICMP] = self.old[release.ICMP]
        with self.assertRaisesRegex(RuntimeError, "ICMP remains"):
            release.execute(self.plan, self.result)
        self.assertEqual(self.pushes, [])

    def test_archive_is_idempotent_and_never_moves_heads(self):
        self.plan["operation"] = "archive"
        before = dict(self.heads)
        release.execute(self.plan, self.result)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.pushes, [])
        self.assertEqual(self.heads, before)


class CommandAndCanonicalTests(unittest.TestCase):
    def test_seven_owner_bundle_requires_exact_remote_main_and_complete_scope(self):
        plan, manifest, _, _ = fixture()
        final = plan["final_heads"]
        entries = [entry for entry in manifest["candidates"] if entry["name"] != "main"]
        reverse = {value: owner for owner, branch in release.OWNERS.items() for value in [final[branch]]}
        def git(*args):
            if args[0] == "cat-file":
                return "commit"
            source, path = args[1].split(":", 1)
            owner = reverse[source]
            parents = ({release.OWNERS[parent]: final[release.OWNERS[parent]] for parent in release.PARENTS[owner]}
                       if owner != "main" else {"upstream": "180012e8b9dbaa2002a68ebd2c75bccebcfb789c"})
            return json.dumps({"branch": release.OWNERS[owner], "parents": parents}
                              if path == "docs/documentation.json" else {"branches": parents})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Bootstrap").mkdir()
            path = root / "Bootstrap/candidates.json"
            path.write_text(json.dumps({"candidates": entries}))
            with patch.object(release, "ROOT", root), patch.object(release, "git", side_effect=git), \
                 patch.object(release.subprocess, "run", side_effect=lambda command: unittest.mock.Mock(returncode=1 if command[-2] in release.FORBIDDEN else 0)), \
                 patch.object(release, "refs", return_value={"refs/heads/work/udp-echo-main-20261028": final["main"]}) as refs:
                release.verify_sources(final)
                refs.return_value = {"refs/heads/work/udp-echo-main-20261028": sha(999)}
                with self.assertRaisesRegex(RuntimeError, "Main remote prerequisite changed"):
                    release.verify_sources(final)
                refs.return_value = {"refs/heads/work/udp-echo-main-20261028": final["main"]}
                path.write_text(json.dumps({"candidates": entries[:-1]}))
                with self.assertRaisesRegex(RuntimeError, "Final heads differ"):
                    release.verify_sources(final)

    def test_atomic_command_has_nine_explicit_leases_and_no_unscoped_force(self):
        plan, _, _, _ = fixture()
        old = {name: sha(index + 100) for index, name in enumerate(sorted(release.BRANCHES | {release.ICMP}))}
        with patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}), patch.object(release.subprocess, "run") as run, redirect_stdout(io.StringIO()):
            release.atomic_push(plan["final_heads"], {release.ICMP}, old)
        command = run.call_args.args[0]
        self.assertIn("--atomic", command)
        self.assertNotIn("--force", command)
        self.assertEqual({part for part in command if part.startswith("--force-with-lease=")},
                         {"--force-with-lease=refs/heads/" + name + ":" + value for name, value in old.items()})
        targets = {part for part in command if ":refs/heads/" in part}
        self.assertEqual(targets, {value + ":refs/heads/" + name for name, value in plan["final_heads"].items()} | {":refs/heads/" + release.ICMP})
        self.assertNotIn("fixture-token", " ".join(command))
        with patch.object(release.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "explicit lease"):
                release.atomic_push(plan["final_heads"], {release.ICMP}, {})
            run.assert_not_called()

    def test_canonical_source_and_required_jobs(self):
        plan, _, _, _ = fixture()
        rows, runs = [], {}
        for index, (branch, source) in enumerate(plan["final_heads"].items()):
            run_id = index + 600
            rows.append(dict(branch=branch, source_sha=source, run_id=run_id, run_attempt=1))
            run = dict(id=run_id, run_attempt=1, head_branch=branch, head_sha=source,
                       status="completed", conclusion="success", event="workflow_dispatch",
                       path=".github/workflows/verify-build.yml")
            required = release.canonical_required_steps(branch)
            jobs = {run_id * 10 + position: job(run_id * 10 + position, run_id, name,
                                               [step(title) for title in steps])
                    for position, (name, steps) in enumerate(required.items())}
            runs[run_id] = (run, jobs)
        plan["canonical_runs"] = rows
        with patch.object(release, "run_jobs", side_effect=lambda run_id, attempt: runs[run_id]):
            release.verify_canonical_runs(plan)
            # A green job is insufficient if any actual owner/SDK/runtime stage was skipped.
            for branch_row in rows:
                for value in runs[branch_row["run_id"]][1].values():
                    for execution in value["steps"]:
                        with self.subTest(branch=branch_row["branch"], job=value["name"], step=execution["name"]):
                            execution["conclusion"] = "skipped"
                            with self.assertRaisesRegex(RuntimeError, "Required step did not execute"):
                                release.verify_canonical_runs(plan)
                            execution["conclusion"] = "success"
            runs[600][0]["head_sha"] = sha(999)
            with self.assertRaisesRegex(RuntimeError, "Canonical workflow identity"):
                release.verify_canonical_runs(plan)
            runs[600][0]["head_sha"] = plan["final_heads"]["main"]
            runs[607][1].pop(6072)
            with self.assertRaisesRegex(RuntimeError, "Canonical required job is missing"):
                release.verify_canonical_runs(plan)

    def test_dispatch_http_204_is_not_json_decoded(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.status = 204
        with patch.dict(os.environ, {"GH_TOKEN": "fixture-token"}), patch.object(release, "urlopen", return_value=response), patch.object(release.json, "load") as decode:
            self.assertIsNone(release.api("actions/workflows/verify-build.yml/dispatches", {"ref": "main"}))
            decode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
