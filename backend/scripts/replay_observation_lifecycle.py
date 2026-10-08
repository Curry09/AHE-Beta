#!/usr/bin/env python3
"""Spec-0061 controlled integration: real Docker/Gitea/merge, scripted role decisions.

Creates a private, isolated test repository and keeps evidence for audit. Does not
run a model, touch an existing experiment, or use any benchmark data.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gitea-url", default="http://localhost:3000")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--openagents-source", type=Path, required=True)
    parser.add_argument("--image", default="python:3.12-slim")
    parser.add_argument(
        "--delivery-image",
        help="Optional pinned OpenAgents image: verify private attachment reads inside it",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Keep test evidence under a persistent experiment directory",
    )
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(args.openagents_source))
    from dotenv import dotenv_values
    from openagents.agents import reviewer
    from openagents.backends.base import AgentResult
    from openagents.runtime import engine
    from openagents.utils import forge

    from auto_designer.demand.owner import Owner
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.observations.delivery_gaps import ingest_delivery_gaps
    from auto_designer.observations.gaps import GapService
    from auto_designer.observations.grants import grant
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.runtime import DockerWorkspaceRuntime

    token = dotenv_values(args.env_file).get("TOKEN")
    if not token:
        raise ValueError("TOKEN is required in the chosen environment file")
    os.environ["GITEA_TOKEN"] = token
    env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: token {token}",
        "GIT_TERMINAL_PROMPT": "0",
    }
    tracker = GiteaTracker(args.gitea_url, "unused", "unused", token)
    actor = tracker.authenticated_login()
    name = f"observation-lifecycle-{time.strftime('%Y%m%d-%H%M%S')}"
    tracker._request("POST", "/user/repos", {"name": name, "private": True, "auto_init": False})
    tracker = GiteaTracker(args.gitea_url, actor, name, token)
    tracker.preflight_observations()
    forge.configure(
        name="gitea", settings={"base_url": args.gitea_url, "owner": actor, "repo": name}
    )
    if args.output_root is not None:
        args.output_root.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="spec0061-lifecycle-", dir=args.output_root))
    repo = root / "harness"
    repo.mkdir()
    store = SessionStore(root / "sessions")
    os.environ["AUTO_DESIGNER_OBSERVATION_ROOT"] = str(root / "observations")
    fixtures = Path(__file__).resolve().parents[1] / "tests/observations/fixtures"

    def run(argv, cwd=None):
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=40)
        if result.returncode:
            raise RuntimeError(
                f"{argv[0]} failed: {result.stderr[:500].replace(token, '[redacted]')}"
            )
        return result.stdout.strip()

    def git(*parts):
        return run(["git", *parts], cwd=repo)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Observation lifecycle test")
    git("config", "user.email", "observation-test@local.invalid")
    git("remote", "add", "origin", f"{args.gitea_url}/{actor}/{name}.git")
    (repo / "params.yaml").write_text(
        "entry: [python3, entry.py]\nprotocol: stdio-jsonl-v1\nobservations: artifact-observations-v1\n"
    )
    (repo / ".gitignore").write_text(".openagents/\n")
    shutil.copyfile(fixtures / "alternate_v1.py", repo / "entry.py")
    git("add", "entry.py", "params.yaml", ".gitignore")
    git("commit", "-qm", "feat: initial non-NexAU harness")
    git("push", "-u", "origin", "main")
    v1 = git("rev-parse", "HEAD")
    launcher = HarnessLauncher(str(repo), root / "runs")
    images = json.loads(run(["docker", "image", "inspect", args.image]))
    image_digest = images[0]["Id"]
    report = {
        "kind": "controlled integration, scripted decisions (not a live-model evolution)",
        "repository": f"{args.gitea_url}/{actor}/{name}",
        "root": str(root),
        "v1": v1,
        "image_digest": image_digest,
        "sessions": [],
    }

    def session(sha, sid):
        cid = run(["docker", "run", "-d", "--network", "none", args.image, "sleep", "300"])
        ws = DockerWorkspaceRuntime(
            container_id=cid,
            container_name=cid,
            image=args.image,
            image_digest=image_digest,
            cwd="/tmp",
        )
        handle = None
        try:
            handle = launcher.launch(sha, workspace_dir=ws)
            replies = [
                handle.send(message) for message in ["start A", "cancel", "start B", "inspect"]
            ]
            assert replies == ["active=A", "active=none", "active=B", "active=B"], replies
            handle.close()
            receipt = handle.observation_source.collect(root=root / "observations", session_id=sid)
            ws.evidence["observation"] = receipt
            assert receipt["status"] == "complete", receipt
            report["sessions"].append(
                {"session_id": sid, "sha": sha, "replies": replies, "receipt": receipt}
            )
            return root / "observations" / sid / "runs" / receipt["run_id"]
        finally:
            if handle is not None:
                handle.close()
            ws.close()

    old = session(v1, "s1")
    assert (old / "transitions.log").read_text() == "transition\n" * 4
    old_bytes = (old / "transitions.log").read_bytes()
    request = {
        "request_id": "distinguish-cancel-owner",
        "scope": "harness",
        "session_ids": ["s1"],
        "related_issues": [],
        "question": "Which request owns work after cancellation?",
        "checked": "v1 READING.md and all transition records",
        "unknowns": "old or new owner",
        "impact": "Cannot verify request ownership from diagnostics",
        "desired_capability": "Distinguish cancelled and current owner",
        "verification": "Start A; cancel A; start B; inspect. Verify behavior and ownership separately.",
    }
    svc = GapService(
        store=store,
        tracker=tracker,
        role="triager",
        subject="controlled-v1",
        sessions={"s1"},
        issues=set(),
    )
    issue = svc.submit(request)["issue"]
    owner = Owner(tracker, store, str(repo), "unused", review=False)
    assert owner.admit_once().admitted == [issue]

    class ControlledReview:
        name = "scripted-integration"

        def run(self, *, work_dir, task, context):
            entries = list((work_dir / ".openagents/observation-evidence").glob(f"issue-{issue}-*"))
            path = max(entries, key=lambda p: p.stat().st_mtime_ns)
            assert list((path / "s1").rglob("transitions.log"))
            # The backend explicitly requests a gap; the runner binds role and scope.
            (path / "requests.json").write_text(
                json.dumps(
                    [{**request, "request_id": "developer-ownership", "related_issues": [issue]}]
                )
            )
            return AgentResult(
                changed=False,
                summary='{"verdict":"REWORK","reason":"Current diagnostics cannot distinguish ownership."}',
            )

    engine.run_agent(
        reviewer,
        backend=ControlledReview(),
        work_dir=repo,
        issue_number=issue,
        pr_number=0,
        context="Controlled review of v1 diagnostics; no model is called.",
    )
    outcomes = ingest_delivery_gaps(store=store, tracker=tracker)
    assert len(outcomes) == 1 and outcomes[0]["status"] == "submitted", outcomes
    second = outcomes[0]["issue"]
    assert owner.admit_once().admitted == [second]
    git("checkout", "-qb", "observation-ownership")
    shutil.copyfile(fixtures / "alternate_v2.py", repo / "entry.py")
    git("add", "entry.py")
    git("commit", "-qm", "feat: distinguish cancelled and current request ownership")
    git("push", "-u", "origin", "observation-ownership")
    pr = forge.create_pr(
        branch="observation-ownership",
        title="Observation ownership refinement",
        body=f"Closes #{issue}\nCloses #{second}\nControlled fixture delivery, no benchmark.",
        base="main",
    )
    # This is a transport/lifecycle integration, not an invocation of vigil's engineering gates.
    for attempt in range(10):
        try:
            forge.merge_pr(pr_number=pr.number)
            break
        except forge.GithubError:
            if attempt == 9:
                raise
            time.sleep(0.5)
    git("fetch", "origin", "main")
    v2 = git("rev-parse", "origin/main")
    assert v1 != v2
    assert tracker.get_issue(number=issue)["state"] == "closed"
    assert tracker.get_issue(number=second)["state"] == "closed"
    current = session(v2, "s2")
    assert (current / "ownership.tsv").read_text().splitlines() == [
        "start\tA",
        "cancel\tA",
        "start\tB",
        "inspect\tB",
    ]
    assert (old / "transitions.log").read_bytes() == old_bytes
    from openagents.observations.evidence import prepare

    from auto_designer.models import IssueDraft

    verified = tracker.create_issue(
        IssueDraft(
            title="Controlled v2 evidence read", body="Verify v2 ownership", labels=["proposal"]
        )
    )
    grant(store=store, issue=verified.number, sessions={"s2"})
    owner.admit_once()
    scope = prepare(work_dir=repo, issue=verified.number, role="acceptance")
    assert scope["sessions"] == ["s2"]
    fresh = list(Path(scope["request_path"]).parent.rglob("ownership.tsv"))
    assert len(fresh) == 1 and fresh[0].read_bytes() == (current / "ownership.tsv").read_bytes()
    if args.delivery_image:
        env.update(
            OBSERVATION_REPO=name, OBSERVATION_OWNER=actor, OBSERVATION_ISSUE=str(verified.number)
        )
        probe = """import json, os, pathlib, subprocess, tempfile
from openagents.observations import evidence
from openagents.utils import forge
root = pathlib.Path(tempfile.mkdtemp(prefix="delivery-observation-probe-"))
subprocess.run(["git", "init", "-q", str(root)], check=True)
forge.configure(name="gitea", settings={"base_url":"http://gitea:3000", "owner":os.environ["OBSERVATION_OWNER"], "repo":os.environ["OBSERVATION_REPO"]})
scope = evidence.prepare(work_dir=root, issue=int(os.environ["OBSERVATION_ISSUE"]), role="developer")
assert scope["sessions"] == ["s2"], scope["context"]
files = list(pathlib.Path(scope["request_path"]).parent.rglob("ownership.tsv"))
assert len(files) == 1
assert files[0].read_text().splitlines() == ["start\\tA", "cancel\\tA", "start\\tB", "inspect\\tB"]
print(json.dumps({"installed_module": evidence.__file__, "sessions":scope["sessions"], "verified_ownership":True}))
"""
        cid = run(
            [
                "docker",
                "create",
                "--network",
                "auto-designer-vigil-net",
                "-e",
                "GITEA_TOKEN",
                "-e",
                "OBSERVATION_REPO",
                "-e",
                "OBSERVATION_OWNER",
                "-e",
                "OBSERVATION_ISSUE",
                args.delivery_image,
                "python3",
                "-c",
                probe,
            ]
        )
        try:
            config = json.loads(run(["docker", "inspect", cid]))[0]
            assert not any(m["Type"] == "bind" for m in config["Mounts"])
            result = json.loads(run(["docker", "start", "-a", cid]))
            report["delivery_container"] = {
                **result,
                "image_id": config["Image"],
                "host_bind_mounts": False,
            }
        finally:
            run(["docker", "rm", "-f", cid])
    tracker.transition_issue(verified.number, state="closed", labels=["controlled-test"])
    report.update(
        v2=v2,
        demand_gap=issue,
        delivery_gap=second,
        pull_request=pr.number,
        old_evidence_preserved=True,
        alternate_format_read_by_delivery=True,
        behavior_passed=True,
        observation_question_answerable=True,
        temporary_containers="removed after successful publication",
    )
    (root / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
