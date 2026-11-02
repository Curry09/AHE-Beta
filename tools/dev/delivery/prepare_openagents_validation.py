#!/usr/bin/env python3
"""Clone a frozen Gitea experiment into a fresh OpenAgents validation repository."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import requests
from tools.dev import add_inputs, run_inputs
from tools.dev.delivery import git_remote_url, require_execution_config, run_git


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--deliver", type=int, nargs="+", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    add_inputs(parser, run=True)
    return parser.parse_args()


def validate_delivery_selection(
    *, source_repo: str, target_repo: str, snapshots: list[dict], selected: set[int]
) -> None:
    """Reject invalid local/read-only plans before creating the target repository."""
    if source_repo == target_repo:
        raise SystemExit("source and target repositories must differ")
    numbers = [item.get("number") for item in snapshots]
    if any(not isinstance(number, int) or isinstance(number, bool) for number in numbers):
        raise SystemExit("source issue snapshots need integer numbers")
    if len(numbers) != len(set(numbers)):
        raise SystemExit("source issue snapshots contain duplicate numbers")
    missing = selected - set(numbers)
    if missing:
        raise SystemExit(f"selected source issues do not exist: {sorted(missing)}")


def _create_repo(*, gitea: dict[str, str], repo: str) -> None:
    base = gitea["GITEA_URL"].rstrip("/")
    headers = {"Authorization": f"token {gitea['TOKEN']}"}
    check = requests.get(
        f"{base}/api/v1/repos/{gitea['OWNER']}/{repo}", headers=headers, timeout=30
    )
    if check.status_code != 404:
        raise SystemExit(f"target repository must not exist: HTTP {check.status_code}")
    response = requests.post(
        f"{base}/api/v1/user/repos",
        headers=headers,
        json={"name": repo, "private": False, "auto_init": False, "default_branch": "main"},
        timeout=30,
    )
    response.raise_for_status()


def _copy_git(*, gitea: dict[str, str], source: str, target: str) -> str:
    with tempfile.TemporaryDirectory(prefix="openagents-validation-") as temp:
        checkout = Path(temp) / "repo"
        source_url = git_remote_url(gitea, source)
        target_url = git_remote_url(gitea, target)
        run_git(["git", "clone", "--branch", "main", source_url, str(checkout)], gitea=gitea)
        require_execution_config(checkout)
        tracked = run_git(
            ["git", "-C", str(checkout), "ls-files", "-z"],
            gitea=gitea,
        ).stdout.split(b"\0")
        generated = [
            Path(value.decode())
            for value in tracked
            if value
            and (value.decode().endswith(".pyc") or "__pycache__" in Path(value.decode()).parts)
        ]
        for relative in generated:
            (checkout / relative).unlink(missing_ok=True)
        ignore = checkout / ".gitignore"
        ignore_text = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        additions = [
            pattern
            for pattern in ("__pycache__/", "*.pyc")
            if pattern not in ignore_text.splitlines()
        ]
        if additions:
            separator = "" if not ignore_text or ignore_text.endswith("\n") else "\n"
            addition_text = "\n".join(additions)
            ignore.write_text(f"{ignore_text}{separator}{addition_text}\n", encoding="utf-8")
        if generated or additions or (checkout / ".openagents/openagents.yml").exists():
            run_git(["git", "-C", str(checkout), "add", "-A"], gitea=gitea)
            run_git(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=validation-seed",
                    "-c",
                    "user.email=validation-seed@local",
                    "commit",
                    "-m",
                    "chore: prepare execution contract validation seed",
                ],
                gitea=gitea,
            )
        run_git(
            ["git", "-C", str(checkout), "remote", "set-url", "origin", target_url], gitea=gitea
        )
        run_git(["git", "-C", str(checkout), "push", "-u", "origin", "main"], gitea=gitea)
        return run_git(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            gitea=gitea,
            text=True,
        ).stdout.strip()


def main() -> int:
    args = _args()
    if args.manifest.exists():
        raise SystemExit(f"manifest already exists: {args.manifest}")
    selected = set(args.deliver)
    _, _, gitea = run_inputs(args.run_dir, args.secrets_file)

    from ahe_beta.demand.issue_schema import OPENAGENTS  # noqa: PLC0415
    from ahe_beta.models import IssueDraft  # noqa: PLC0415
    from ahe_beta.tracker.gitea import GiteaTracker  # noqa: PLC0415

    def tracker(repo: str) -> GiteaTracker:
        return GiteaTracker(
            base_url=gitea["GITEA_URL"],
            owner=gitea["OWNER"],
            repo=repo,
            token=gitea["TOKEN"],
        )

    source = tracker(args.source_repo)
    snapshots = sorted(source.list_issues(state="all", limit=100), key=lambda item: item["number"])
    validate_delivery_selection(
        source_repo=args.source_repo,
        target_repo=args.target_repo,
        snapshots=snapshots,
        selected=selected,
    )
    _create_repo(gitea=gitea, repo=args.target_repo)
    main_sha = _copy_git(gitea=gitea, source=args.source_repo, target=args.target_repo)
    target = tracker(args.target_repo)
    copied: list[dict] = []
    for item in snapshots:
        labels = list(item["labels"])
        if item["number"] not in selected:
            labels = [label for label in labels if label != OPENAGENTS]
        ref = target.create_issue(IssueDraft(title=item["title"], body=item["body"], labels=labels))
        if ref.number != item["number"]:
            raise RuntimeError(f"issue number drift: {item['number']} -> {ref.number}")
        for comment in source.list_comments(number=item["number"]):
            target.add_comment(ref.number, comment["body"])
        if item["state"] == "closed":
            target.set_state(ref.number, "closed", "")
        copied.append(
            {
                "number": ref.number,
                "state": item["state"],
                "labels": labels,
                "deliver": ref.number in selected,
            }
        )

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(
            {
                "source_repo": args.source_repo,
                "target_repo": args.target_repo,
                "main_sha": main_sha,
                "delivery_issues": sorted(selected),
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
