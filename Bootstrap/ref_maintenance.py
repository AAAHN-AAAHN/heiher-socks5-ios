"""Preserve old heads or remove only explicitly leased, obsolete refs."""
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
BRANCHES = {
    "main", "feature/udp-compat", "feature/traffic-statistics", "feature/background",
    "feature/server-control", "feature/settings-persistence", "feature/app-icon",
    "release/integrated",
}
TEMPORARY = {
    "work/udp-echo-build-20261028", "work/udp-echo-main-20261028",
    "work/udp-echo-udp-20261028", "work/udp-echo-publish-20261028",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


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
            return json.load(response)
    except HTTPError as error:
        if error.code == 404 and body is None:
            return None
        raise


def refs(prefix):
    return {item["ref"]: item["object"]["sha"]
            for item in api("git/matching-refs/" + prefix + "/")}


def verify_heads(expected, actual):
    require(set(expected) == BRANCHES, "Expected the exact eight active branches")
    for branch, sha in expected.items():
        require(re.fullmatch(r"[0-9a-f]{40}", sha), "Invalid expected commit")
        require(actual.get("refs/heads/" + branch) == sha, "Concurrent branch change: " + branch)


def main():
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY, "Unexpected repository")
    plan = json.loads((ROOT / "Bootstrap/ref-operations.json").read_bytes())
    operation = plan["operation"]
    heads = refs("heads")
    tags = refs("tags")
    for name, sha in plan["preserved_tags"].items():
        require(tags.get(name) == sha, "Historical tag changed: " + name)
    result = {"operation": operation, "run_id": os.environ["GITHUB_RUN_ID"],
              "helper_commit": os.environ["GITHUB_SHA"]}
    if operation == "archive":
        old = plan["old_heads"]
        require(set(old) == BRANCHES | {"feature/icmp-relay"}, "Expected nine original heads")
        verify_heads({name: sha for name, sha in old.items() if name in BRANCHES}, heads)
        require(heads.get("refs/heads/feature/icmp-relay") == old["feature/icmp-relay"],
                "Concurrent ICMP branch change")
        archived = {}
        missing = {}
        for branch, sha in sorted(old.items()):
            require(re.fullmatch(r"[0-9a-f]{40}", sha), "Invalid archive commit")
            name = "refs/tags/archive/before-udp-echo-20261028/" + branch + "-" + sha[:12]
            existing = api("git/ref/" + name.removeprefix("refs/"))
            if existing is None:
                missing[name] = sha
            else:
                require(existing["object"]["sha"] == sha, "Archive tag differs: " + name)
            archived[name] = sha
        # Validate every destination before the first create. POST creates only:
        # a tag arriving after this preflight makes the API reject, never replace.
        for name, sha in missing.items():
            existing = api("git/refs", {"ref": name, "sha": sha})
            require(existing["object"]["sha"] == sha, "Archive tag differs: " + name)
        result["archive_tags"] = archived
        result["operating_refs_changed"] = False
    elif operation == "cleanup":
        verify_heads(plan["final_heads"], heads)
        obsolete = dict(plan["obsolete_heads"])
        own = "work/udp-echo-publish-20261028"
        require(own not in obsolete, "Helper lease must use this actual workflow commit")
        obsolete[own] = os.environ["GITHUB_SHA"]
        require(set(obsolete) == TEMPORARY | {"feature/icmp-relay"}, "Unexpected deletion scope")
        for branch, sha in obsolete.items():
            require(re.fullmatch(r"[0-9a-f]{40}", sha), "Invalid deletion lease")
            require(heads.get("refs/heads/" + branch) == sha, "Deletion lease changed: " + branch)
        token = base64.b64encode(("x-access-token:" + os.environ["GH_TOKEN"]).encode()).decode()
        print("::add-mask::" + token, flush=True)
        env = dict(os.environ, GIT_CONFIG_COUNT="1",
                   GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + token,
                   GIT_TERMINAL_PROMPT="0")
        command = ["git", "push", "--atomic"]
        command += ["--force-with-lease=refs/heads/" + branch + ":" + sha
                    for branch, sha in obsolete.items()]
        command += ["https://github.com/" + REPOSITORY + ".git"]
        command += [":refs/heads/" + branch for branch in obsolete]
        subprocess.run(command, env=env, check=True, timeout=120)
        after = refs("heads")
        verify_heads(plan["final_heads"], after)
        require(all("refs/heads/" + name not in after for name in obsolete), "Obsolete ref remains")
        require(refs("tags") == tags, "Cleanup changed tags")
        result["deleted_heads"] = obsolete
        result["final_heads"] = after
        result["tags_preserved"] = tags
    else:
        raise RuntimeError("Unknown maintenance operation")
    result["result"] = "PASS"
    output = ROOT / "artifacts/ref-maintenance"
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
