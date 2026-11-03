#!/usr/bin/env python3
"""Check whether spec group numbers conflict locally or across other open PRs.

Spec-0014/T5: number validation script (the spec version of check-rfc)

Repo convention: spec source data is a single markdown file docs/specs/NNNN-slug.md (frontmatter + rust-RFC body).
The same number NNNN must not be reused by a different slug (locally); new group numbers must not collide with other open PRs.
Matches the docs/specs/(NNNN)-slug.md single-file form; the next number is taken from the union of local + open PRs (decision D11).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Match the docs/specs/NNNN-slug.md single-file form and extract the group number and slug.
# Slugs start with a letter; exclude dated design docs (YYYY-MM-DD-*.md) and OVERVIEW/ARCHITECTURE/README.
SPEC_PATH_RE = re.compile(r"^docs/specs/(?P<number>\d{4})-(?P<slug>[A-Za-z][^/]*)\.md$")
NEW_SPEC_CHANGE_TYPES = {"ADDED", "RENAMED"}


def _run_gh(args: list[str]) -> Any:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout or "[]")


def _extract_spec_identity(path: str) -> tuple[str, str] | None:
    match = SPEC_PATH_RE.match(path)
    if not match:
        return None
    return match.group("number"), match.group("slug")


def _iter_repo_spec_groups(repo_root: Path) -> list[tuple[str, str]]:
    """List of (number, slug) group files under the local docs/specs/."""
    specs_dir = repo_root / "docs" / "specs"
    if not specs_dir.is_dir():
        return []
    groups: list[tuple[str, str]] = []
    for child in sorted(specs_dir.glob("*.md")):
        # Only the NNNN-slug.md single-file form counts as a spec group.
        identity = _extract_spec_identity(f"docs/specs/{child.name}")
        if identity:
            groups.append(identity)
    return groups


def _find_local_conflicts(repo_root: Path) -> list[str]:
    by_number: dict[str, set[str]] = {}
    for number, slug in _iter_repo_spec_groups(repo_root):
        by_number.setdefault(number, set()).add(slug)

    conflicts: list[str] = []
    for number, slugs in sorted(by_number.items()):
        if len(slugs) > 1:
            joined = ", ".join(sorted(slugs))
            conflicts.append(f"spec-{number} is reused by multiple slugs: {joined}")
    return conflicts


def _pr_new_spec_numbers(pr: dict[str, Any]) -> dict[str, list[str]]:
    """Spec files newly added in the PR (ADDED/RENAMED) → number -> [paths]."""
    files = pr.get("files", [])
    if not isinstance(files, list):
        return {}

    numbers: dict[str, list[str]] = {}
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        path = file_info.get("path")
        change_type = file_info.get("changeType")
        if not (isinstance(path, str) and change_type in NEW_SPEC_CHANGE_TYPES):
            continue
        identity = _extract_spec_identity(path)
        if identity:
            number, _slug = identity
            numbers.setdefault(number, []).append(path)
    return numbers


def _find_open_pr_conflicts(current_pr: int) -> list[str]:
    current = _pr_new_spec_numbers(_run_gh(["pr", "view", str(current_pr), "--json", "files"]))
    if not current:
        print("This PR adds no spec files; skipping the open-PR conflict scan.")
        return []

    open_prs = _run_gh(
        ["pr", "list", "--state", "open", "--json", "number,files", "--limit", "100"]
    )
    conflicts: list[str] = []
    for pr in open_prs:
        if not isinstance(pr, dict):
            continue
        pr_number = pr.get("number")
        if pr_number == current_pr:
            continue
        for number in _pr_new_spec_numbers(pr):
            if number in current:
                current_paths = ", ".join(sorted(current[number]))
                conflicts.append(
                    f"spec-{number} (this PR: {current_paths}) is already used by open PR #{pr_number}"
                )
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root; defaults to the current working directory.",
    )
    parser.add_argument(
        "--open-prs",
        action="store_true",
        help="Also use gh to compare spec numbers with other open PRs.",
    )
    parser.add_argument(
        "--current-pr",
        type=int,
        help="Current PR number; use with --open-prs.",
    )
    parser.add_argument(
        "--require-open-pr-scan",
        action="store_true",
        help="Fail if the open-PR scan cannot be completed.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    conflicts = _find_local_conflicts(repo_root)

    if args.open_prs:
        if args.current_pr is None:
            print("--current-pr is required with --open-prs", file=sys.stderr)
            return 2
        try:
            conflicts.extend(_find_open_pr_conflicts(args.current_pr))
        except (
            FileNotFoundError,
            json.JSONDecodeError,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as exc:
            message = f"Open-PR spec conflict scan failed: {exc}"
            if args.require_open_pr_scan:
                print(f"::error::{message}")
                return 1
            print(f"::warning::{message}")

    if conflicts:
        for conflict in conflicts:
            print(f"::error::{conflict}")
        return 1

    print("✓ Spec number conflict check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
