#!/usr/bin/env python3
"""Replay saved user sessions through the design plane, stopping before OpenAgents.

The source conversations are never rerun. Their report issues are copied from a source
Gitea repository into a fresh target repository, session issue references are remapped,
then triage + divergent PM -> synthesize -> Owner admission execute once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests
from tools.dev import add_inputs, role_environment, run_inputs
from tools.dev.delivery import git_remote_url, run_git

ROOT = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(ROOT))

from auto_designer.experiment.controllers import ordinary as run_mod  # noqa: E402


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", help="Explicit demand model override; otherwise use profile/run")
    add_inputs(parser, run=True)
    return parser.parse_args()


def _no_proxy_value(*urls: str) -> str:
    bypass = ["localhost", "127.0.0.1"]
    for url in urls:
        host = urlparse(url).hostname
        if host and host not in bypass:
            bypass.append(host)
    return ",".join(bypass)


def _ensure_fresh_repo(*, gitea: dict[str, str], repo: str) -> None:
    base = gitea["GITEA_URL"].rstrip("/")
    headers = {"Authorization": f"token {gitea['TOKEN']}", "Content-Type": "application/json"}
    check = requests.get(
        f"{base}/api/v1/repos/{gitea['OWNER']}/{repo}", headers=headers, timeout=30
    )
    if check.status_code == 200:
        raise SystemExit(f"target repo already exists; refusing to overwrite: {repo}")
    if check.status_code != 404:
        raise SystemExit(
            f"failed to inspect target repo: HTTP {check.status_code} {check.text[:200]}"
        )
    created = requests.post(
        f"{base}/api/v1/user/repos",
        headers=headers,
        json={"name": repo, "private": False, "auto_init": False, "default_branch": "main"},
        timeout=30,
    )
    if created.status_code not in (201, 202):
        raise SystemExit(
            f"failed to create target repo: HTTP {created.status_code} {created.text[:300]}"
        )


def _seed_repo(*, output: Path, gitea: dict[str, str]) -> Path:
    repo = output / "harness_repo"
    shutil.copytree(
        ROOT / "harness_template",
        repo,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=replay-seed",
            "-c",
            "user.email=replay@local",
            "commit",
            "-m",
            "seed: replay harness v0",
        ],
        check=True,
    )
    run_git(
        ["git", "-C", str(repo), "remote", "add", "origin", git_remote_url(gitea, gitea["REPO"])],
        gitea=gitea,
    )
    run_git(["git", "-C", str(repo), "push", "-u", "origin", "main"], gitea=gitea)
    return repo


def _copy_sessions(*, source: Path, target: Path) -> None:
    if not (source / "index.json").is_file():
        raise SystemExit(f"missing session index: {source}")
    target.mkdir(parents=True)
    for path in source.glob("*.json"):
        shutil.copy2(path, target / path.name)


def _source_issue_numbers(*, sessions: Path) -> list[int]:
    index = json.loads((sessions / "index.json").read_text(encoding="utf-8"))
    return list(
        dict.fromkeys(int(number) for entry in index for number in entry.get("issue_numbers", []))
    )


def _validate_source_reports(*, source_tracker, sessions: Path) -> list[dict]:
    from auto_designer.demand.issue_schema import REPORT, plane

    snapshots = [
        source_tracker.get_issue(number=number)
        for number in _source_issue_numbers(sessions=sessions)
    ]
    invalid = [item["number"] for item in snapshots if plane(item["labels"]) != REPORT]
    if invalid:
        raise SystemExit(f"source issues are not raw reports: {invalid}")
    return snapshots


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prompt_hashes() -> dict[str, str]:
    paths = sorted((ROOT / "agent_defs").glob("*/systemprompt.md"))
    paths.append(ROOT / "agent_defs" / "user_agent" / "prompt.md")
    return {str(path.relative_to(ROOT)): _sha256(path) for path in paths if path.is_file()}


def _copy_reports_and_remap(
    *, source_tracker, target_tracker, sessions: Path, target_repo: str, gitea: dict[str, str]
) -> dict[int, int]:
    from auto_designer.models import IssueDraft

    index_path = sessions / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    old_numbers: list[int] = []
    for entry in index:
        for number in entry.get("issue_numbers", []):
            number = int(number)
            if number not in old_numbers:
                old_numbers.append(number)

    mapping: dict[int, int] = {}
    target_tracker.ensure_labels(["bug", "feature", "question", "document", "report", "round-1"])
    for old in old_numbers:
        item = source_tracker.get_issue(number=old)
        kinds = [
            name for name in item["labels"] if name in {"bug", "feature", "question", "document"}
        ]
        labels = [*(kinds[:1] or ["bug"]), "report", "round-1"]
        ref = target_tracker.create_issue(
            IssueDraft(title=item["title"], body=item["body"], labels=labels)
        )
        mapping[old] = ref.number

    for entry in index:
        session_path = sessions / f"{entry['session_id']}.json"
        doc = json.loads(session_path.read_text(encoding="utf-8"))
        refs = []
        for ref in doc.get("issue_refs", []):
            old = int(ref["number"])
            if old not in mapping:
                continue
            new = mapping[old]
            refs.append(
                {
                    "number": new,
                    "url": f"{gitea['GITEA_URL'].rstrip('/')}/{gitea['OWNER']}/{target_repo}/issues/{new}",
                    "state": "open",
                }
            )
        doc["issue_refs"] = refs
        session_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        entry["issue_numbers"] = [ref["number"] for ref in refs]
        entry["n_issues"] = len(refs)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return mapping


def main() -> int:
    args = _args()
    args.output = args.output.resolve()
    if args.output.exists():
        raise SystemExit(f"output already exists; refusing to overwrite: {args.output}")
    sessions_source = args.sessions.resolve()
    if not (sessions_source / "index.json").is_file():
        raise SystemExit(f"missing session index: {sessions_source}")

    _, _, gitea_base = run_inputs(args.run_dir, args.secrets_file)
    role_environment("DEMAND", model=args.model)
    args.model = os.environ["DEMAND_LLM_MODEL"]
    source_gitea = {**gitea_base, "REPO": args.source_repo}
    target_gitea = {**gitea_base, "REPO": args.target_repo}
    os.environ["DEMAND_LLM_MODEL"] = args.model

    os.environ["NO_PROXY"] = _no_proxy_value(
        os.environ["DEMAND_LLM_BASE_URL"], gitea_base.get("GITEA_URL", "")
    )
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    run_mod._isolate_git_credentials()

    from auto_designer.demand.divergent import Divergent
    from auto_designer.demand.issue_schema import plane
    from auto_designer.demand.owner import Owner
    from auto_designer.demand.synthesizer import Synthesizer
    from auto_designer.demand.triage import Triager
    from auto_designer.tracker.gitea import GiteaTracker
    from auto_designer.usage import bind_usage_context, default_usage_store
    from auto_designer.user.session_store import SessionStore

    source_tracker = GiteaTracker(
        base_url=source_gitea["GITEA_URL"],
        owner=source_gitea["OWNER"],
        repo=source_gitea["REPO"],
        token=source_gitea["TOKEN"],
    )
    source_snapshots = _validate_source_reports(
        source_tracker=source_tracker, sessions=sessions_source
    )
    _ensure_fresh_repo(gitea=target_gitea, repo=args.target_repo)
    args.output.mkdir(parents=True)
    harness_repo = _seed_repo(output=args.output, gitea=target_gitea)
    sessions = args.output / "sessions"
    _copy_sessions(source=sessions_source, target=sessions)
    tracker = GiteaTracker(
        base_url=target_gitea["GITEA_URL"],
        owner=target_gitea["OWNER"],
        repo=target_gitea["REPO"],
        token=target_gitea["TOKEN"],
    )
    mapping = _copy_reports_and_remap(
        source_tracker=source_tracker,
        target_tracker=tracker,
        sessions=sessions,
        target_repo=args.target_repo,
        gitea=target_gitea,
    )
    store = SessionStore(sessions)
    events = args.output / "agent-events.jsonl"
    event_lock = threading.Lock()
    run_id = f"spec-0042-replay-{uuid.uuid4().hex}"

    def event(role: str):
        def write(kind: str, text: str) -> None:
            with event_lock, events.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"role": role, "kind": kind, "text": text}, ensure_ascii=False)
                    + "\n"
                )

        return write

    triager = Triager(
        tracker,
        store,
        str(harness_repo),
        str(ROOT / "agent_defs" / "triage_agent"),
        on_event=event("triager"),
    )
    divergent = Divergent(
        tracker,
        store,
        str(harness_repo),
        str(ROOT / "agent_defs" / "divergent_pm"),
        on_event=event("divergent"),
        round_provider=lambda: 1,
    )
    synthesizer = Synthesizer(
        tracker,
        store,
        str(harness_repo),
        str(ROOT / "agent_defs" / "synthesizer"),
        on_event=event("synthesizer"),
        round_provider=lambda: 1,
    )
    owner = Owner(
        tracker,
        store,
        str(harness_repo),
        str(ROOT / "agent_defs" / "owner"),
        on_event=event("owner"),
        review=True,
    )

    def invoke(role: str, operation) -> object:
        with bind_usage_context(run_id=run_id, role=role):
            return operation()

    with ThreadPoolExecutor(max_workers=2) as pool:
        triage_future = pool.submit(invoke, "triager", triager.triage_once)
        divergent_future = pool.submit(invoke, "divergent", divergent.propose_once)
        triage_out = triage_future.result()
        divergent_out = divergent_future.result()
    design_out = invoke("synthesizer", synthesizer.propose_once)
    owner_out = invoke("owner", owner.admit_once)

    issues = tracker.list_issues(state="all", limit=100)
    summary = {
        "code_revision": subprocess.run(
            ["git", "-C", str(ROOT.parent), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "prompt_sha256": _prompt_hashes(),
        "model": args.model,
        "model_endpoint": os.environ["DEMAND_LLM_BASE_URL"],
        "usage": default_usage_store().summary(run_id=run_id),
        "source_sessions": len(store.index()),
        "source_issue_snapshot": source_snapshots,
        "source_report_mapping": mapping,
        "triage": triage_out.__dict__,
        "divergent": divergent_out.__dict__,
        "synthesizer": design_out.__dict__,
        "owner": owner_out.__dict__,
        "issues": [
            {
                "number": item["number"],
                "state": item["state"],
                "title": item["title"],
                "labels": item["labels"],
                "plane": plane(item["labels"]),
                "body": item["body"],
            }
            for item in issues
        ],
        "openagents_started": False,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("STOPPED BEFORE OPENAGENTS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
