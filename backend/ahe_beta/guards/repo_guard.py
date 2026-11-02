# Spec-0021/T1：编排仓完整性绊线——run 期间编排仓（ahe-beta 检出）应全程冻结，被 dev 触碰即暴露。
"""repo_guard：编排仓完整性快照与校验。

实测 dev agent 用 python heredoc 隧道绕过 workspace-jail 的路径扫描，`os.chdir` 到编排仓
（ahe-beta 检出本身）改文件并提交/推送。路径级 jail 关不住能调解释器的 agent。本模块提供
一道**独立信道**兜底：run 前对编排仓拍一张 (HEAD, porcelain) 快照，每轮 b 段（dev 直推）后校验
未变——被改一个字都会使 HEAD 或 porcelain 变化，立即抛错中止，不再靠人翻远端才发现。

绊线是**检测+fail-closed 中止**，不是阻止（阻止由 run.py 的凭证隔离掐推送做，二者纵深互补）。
"""

from __future__ import annotations

import subprocess

# Python imports in the frozen harness checkout may create bytecode caches while a
# role is running.  They are runtime by-products, not edits to the orchestration
# source.  Keep the guard fail-closed for every other untracked path.
_GENERATED_CACHE_SUFFIXES = ("/__pycache__", ".pyc", ".pyo")


def _meaningful_porcelain(value: str) -> str:
    """Remove interpreter-generated cache entries from a git status snapshot."""
    lines = []
    for line in value.splitlines():
        path = line[3:] if len(line) >= 4 else line
        if any(path.endswith(suffix) or suffix in path for suffix in _GENERATED_CACHE_SUFFIXES):
            continue
        lines.append(line)
    return "\n".join(lines)


class RepoIntegrityError(RuntimeError):
    """编排仓在 run 期间被改动（HEAD 或工作树相对开跑前快照发生变化）。"""


def _git(repo: str, *args: str) -> str:
    """跑一条 git 子命令，返回 stdout（strip）；非 0/异常一律抛 RepoIntegrityError（宁紧勿松）。"""
    try:
        result = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RepoIntegrityError(f"编排仓 git 读取失败（{repo}）：{exc}") from exc
    if result.returncode != 0:
        raise RepoIntegrityError(
            f"编排仓 git {args!r} 非零退出（{repo}）：{result.stderr.strip()[:200]}"
        )
    return result.stdout.strip()


def snapshot_repo(*, repo: str) -> tuple[str, str]:
    """拍一张编排仓快照 = (HEAD commit SHA, `git status --porcelain` 全文)。

    dev 提交 → HEAD 变；dev 改 tracked 文件 → porcelain 出现 ` M …`；dev 新建文件 → porcelain
    出现 `?? …`。既有 untracked（本地 docs / .idea 等）在前后快照里都在，全等即未被触碰。
    """
    head = _git(repo, "rev-parse", "HEAD")
    porcelain = _meaningful_porcelain(_git(repo, "status", "--porcelain"))
    return (head, porcelain)


def verify_unchanged(*, repo: str, before: tuple[str, str]) -> None:
    """校验编排仓相对 before 快照未变；变了即抛 RepoIntegrityError（附差异摘要）。"""
    after = snapshot_repo(repo=repo)
    if after == before:
        return
    head_before, porc_before = before
    head_after, porc_after = after
    parts: list[str] = []
    if head_after != head_before:
        parts.append(f"HEAD {head_before[:12]} → {head_after[:12]}（出现新提交）")
    if porc_after != porc_before:
        # 只报新增的 porcelain 行（既有 untracked 不算），让告警直指被动的文件。
        added = [ln for ln in porc_after.splitlines() if ln not in porc_before.splitlines()]
        detail = "；".join(added[:10]) if added else "工作树状态变化"
        parts.append(f"工作树新增改动：{detail}")
    raise RepoIntegrityError(
        f"编排仓 {repo} 在 run 期间被改动（疑似 dev agent 逃逸出沙箱）——{'；'.join(parts)}"
    )
