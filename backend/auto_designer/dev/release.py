"""release 发版（spec-0003/T5）：体感门禁通过的候选合入 release 分支并打 tag。

tag = 现有最大版本 +1（无则 v1），即用户侧下一轮 pin 的版本。否决则不动 release，可在 issue 留否决 comment。
合并默认 merge commit；冲突不自动解，显式抛错并保持 release 原状。issue 联动经可选 tracker。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from auto_designer.dev.test_agent import Verdict
from auto_designer.tracker.base import IssueTracker

_TAG_RE = re.compile(r"^v(\d+)$")


@dataclass
class ReleaseResult:
    released: bool
    tag: str | None = None
    ref: str | None = None


def release(
    harness_repo: str,
    candidate_branch: str,
    verdict: Verdict,
    tracker: IssueTracker | None,
    issue_number: int | None,
) -> ReleaseResult:
    """通过则合并候选到 release + 打 tag（+ 关 issue）；否决则不动 release（+ 留否决 comment）。"""
    if not verdict.passed:
        if tracker is not None and issue_number is not None:
            tracker.add_comment(
                issue_number,
                f"体感门禁未过：mean={verdict.mean:.3f} baseline={verdict.baseline}",
            )
        return ReleaseResult(released=False)

    if not _branch_exists(harness_repo, candidate_branch):
        raise RuntimeError(f"候选分支不存在：{candidate_branch}")

    _git(harness_repo, ["checkout", "release"])
    # 候选已是 release 祖先 → 已合入，无实际差异 → 不打空版本。
    if _is_ancestor(harness_repo, candidate_branch, "release"):
        return ReleaseResult(released=False, ref=_git(harness_repo, ["rev-parse", "HEAD"]).strip())

    merge = subprocess.run(
        [
            "git",
            "-C",
            harness_repo,
            "-c",
            "user.email=rel@auto-designer",
            "-c",
            "user.name=release",
            "merge",
            "--no-ff",
            candidate_branch,
            "-m",
            f"release: merge {candidate_branch}",
        ],
        capture_output=True,
        text=True,
    )
    if merge.returncode != 0:  # 冲突等 → abort 保持 release 原状后抛错
        subprocess.run(["git", "-C", harness_repo, "merge", "--abort"], capture_output=True)
        raise RuntimeError(f"合并 {candidate_branch} 失败：{merge.stdout}{merge.stderr}"[:300])

    tag = f"v{_next_version(harness_repo)}"
    _git(harness_repo, ["tag", tag])
    _push_origin(harness_repo, "release")  # 有 origin(Gitea)则把发版后的 release 分支+tag 推上去
    _push_origin(harness_repo, tag)
    if tracker is not None and issue_number is not None:
        tracker.set_state(issue_number, "closed", f"发版 {tag}")
    return ReleaseResult(released=True, tag=tag, ref=tag)


def _push_origin(repo: str, ref: str) -> None:
    """有 origin 远程则 push 该 ref（分支/tag）；无 origin（离线单测）则 no-op。"""
    remotes = subprocess.run(
        ["git", "-C", repo, "remote"], capture_output=True, text=True
    ).stdout.split()
    if "origin" in remotes:
        subprocess.run(["git", "-C", repo, "push", "origin", ref], capture_output=True)


def _branch_exists(repo: str, branch: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", repo, "rev-parse", "--verify", branch], capture_output=True
        ).returncode
        == 0
    )


def _is_ancestor(repo: str, maybe_ancestor: str, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", repo, "merge-base", "--is-ancestor", maybe_ancestor, ref],
            capture_output=True,
        ).returncode
        == 0
    )


def _next_version(repo: str) -> int:
    tags = _git(repo, ["tag", "--list", "v*"]).split()
    versions = [int(m.group(1)) for t in tags if (m := _TAG_RE.match(t))]
    return (max(versions) + 1) if versions else 1


def _git(repo: str, args: list[str]) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args], check=True, capture_output=True, text=True
    ).stdout
