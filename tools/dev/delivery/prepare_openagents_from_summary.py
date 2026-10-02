#!/usr/bin/env python3
"""Materialize a frozen offline design summary as a fresh Gitea delivery repository."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import requests
from tools.dev import add_inputs, run_inputs
from tools.dev.delivery import git_remote_url, run_git


def validate_summary(source: object, harness_repo: Path) -> list[dict]:
    """Validate all local inputs before creating a remote repository."""
    if not harness_repo.is_dir():
        raise SystemExit(f"harness repository does not exist: {harness_repo}")
    if not isinstance(source, dict) or not isinstance(source.get("issues"), list):
        raise SystemExit("summary must contain an issues list")
    issues = source["issues"]
    numbers: list[int] = []
    for item in issues:
        if not isinstance(item, dict):
            raise SystemExit("each summary issue must be an object")
        if not isinstance(item.get("number"), int) or isinstance(item.get("number"), bool):
            raise SystemExit("each summary issue needs an integer number")
        if not isinstance(item.get("title"), str) or not isinstance(item.get("body"), str):
            raise SystemExit(f"summary issue #{item['number']} needs string title/body")
        if not isinstance(item.get("labels"), list) or any(
            not isinstance(label, str) for label in item["labels"]
        ):
            raise SystemExit(f"summary issue #{item['number']} needs string labels")
        if item.get("state", "open") not in {"open", "closed"}:
            raise SystemExit(f"summary issue #{item['number']} has invalid state")
        numbers.append(item["number"])
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        raise SystemExit("summary issue numbers must be unique and contiguous from 1")
    return sorted(issues, key=lambda row: row["number"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--harness-repo", type=Path, required=True)
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    add_inputs(parser, run=True)
    args = parser.parse_args()
    if args.manifest.exists():
        raise SystemExit(f"manifest already exists: {args.manifest}")

    source = json.loads(args.summary.read_text(encoding="utf-8"))
    issues = validate_summary(source, args.harness_repo)
    _, _, gitea = run_inputs(args.run_dir, args.secrets_file)
    base = gitea["GITEA_URL"].rstrip("/")
    headers = {"Authorization": f"token {gitea['TOKEN']}"}
    check = requests.get(
        f"{base}/api/v1/repos/{gitea['OWNER']}/{args.target_repo}",
        headers=headers,
        timeout=30,
    )
    if check.status_code != 404:
        raise SystemExit(f"target repository must not exist: HTTP {check.status_code}")
    made = requests.post(
        f"{base}/api/v1/user/repos",
        headers=headers,
        json={"name": args.target_repo, "private": False, "auto_init": False},
        timeout=30,
    )
    made.raise_for_status()

    remote = git_remote_url(gitea, args.target_repo)
    with tempfile.TemporaryDirectory(prefix="openagents-summary-") as temp:
        checkout = Path(temp) / "repo"
        shutil.copytree(
            args.harness_repo,
            checkout,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
        )
        commands = (
            ["git", "init", "-b", "main"],
            ["git", "add", "-A"],
            [
                "git",
                "-c",
                "user.name=validation-seed",
                "-c",
                "user.email=validation-seed@local",
                "commit",
                "-m",
                "seed: frozen harness for OpenAgents validation",
            ],
            ["git", "remote", "add", "origin", remote],
            ["git", "push", "-u", "origin", "main"],
        )
        for command in commands:
            run_git(command, cwd=checkout, gitea=gitea)
        main_sha = run_git(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            gitea=gitea,
            text=True,
        ).stdout.strip()

    from auto_designer.models import IssueDraft  # noqa: PLC0415
    from auto_designer.tracker.gitea import GiteaTracker  # noqa: PLC0415

    tracker = GiteaTracker(
        base_url=base,
        owner=gitea["OWNER"],
        repo=args.target_repo,
        token=gitea["TOKEN"],
    )
    copied: list[dict] = []
    for item in issues:
        ref = tracker.create_issue(
            IssueDraft(title=item["title"], body=item["body"], labels=list(item["labels"]))
        )
        if ref.number != item["number"]:
            raise RuntimeError(f"issue number drift: {item['number']} -> {ref.number}")
        if item.get("state") == "closed":
            tracker.set_state(ref.number, "closed", "")
        copied.append(
            {
                "number": ref.number,
                "state": item.get("state", "open"),
                "labels": list(item["labels"]),
                "deliver": "openagents" in item["labels"] and item.get("state") == "open",
            }
        )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(
            {
                "source_summary": str(args.summary.resolve()),
                "target_repo": args.target_repo,
                "main_sha": main_sha,
                "issues": copied,
                "openagents_started": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
