"""git SeedSource（spec-0009/T4）。

Spec-0009/T4: git 源（clone repo@commit 成快照工作区）

provision 时把 `params.repo` clone 到隔离目录并 `git checkout <params.commit>`，得到
「某仓库停在某 commit」的干净快照并返回该目录——真实 repo 任务（SWE-bench 的 base_commit
未修复态、funcy@某版本等）的起点。repo/commit（及可选 ref/depth）全落 `WorkspaceSpec.params`，
不扩 schema、kind="git"；每局 fresh（每 round 重 clone/checkout 一份，隔离避免跨局串状态）。

可插拔证明：接入它只新增本模块——靠 spec-0009/T1 的 sources/ 自动发现注册，seed_source /
models / workspace 与消费侧（orchestrator / sim_user / Sandbox）一律不改。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import register


@register("git")
class GitSource:
    kind = "git"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        """Clone a repo into an isolated dir and checkout the target commit.

        Spec-0009/T4: 从 spec.params 读 repo（必填）、commit（必填）、可选 ref/depth；
        在隔离目录 clone + checkout，返回该目录绝对路径（该 repo 在该 commit 的工作树）。
        """
        # 1. 读并自校验 params（不扩 WorkspaceSpec，字段完整性由本源保证）。
        repo = spec.params.get("repo")
        commit = spec.params.get("commit")
        if not repo:
            raise ValueError("git 源需要非空 params.repo（可 clone 的 URL 或本地路径）")
        if not commit:
            raise ValueError("git 源需要非空 params.commit（要恢复的快照 sha/ref）")
        ref = spec.params.get("ref")
        depth = spec.params.get("depth")

        # 2. 每局 fresh：在隔离目录里新开一份工作树，跨局互不污染、可清理。
        base = dest_root or tempfile.mkdtemp(prefix="sim_ws_git_")
        dest = Path(base) / "repo"

        # 3. clone；depth/ref 仅用于加速定向拉取，最终仍以 commit 为准 checkout。
        clone_cmd = ["git", "clone"]
        if depth:
            clone_cmd += ["--depth", str(depth)]
        if ref:
            clone_cmd += ["--branch", str(ref)]
        clone_cmd += [str(repo), str(dest)]
        _run_git(cmd=clone_cmd, cwd=None)

        # 4. checkout 到目标 commit；浅克隆可能取不到任意历史 commit，
        #    回退为 fetch --unshallow 全量拉取后重试（浅克隆 + 任意 commit 的兼容）。
        try:
            _run_git(cmd=["git", "checkout", str(commit)], cwd=str(dest))
        except RuntimeError:
            if not depth:
                raise
            _run_git(cmd=["git", "fetch", "--unshallow"], cwd=str(dest))
            _run_git(cmd=["git", "checkout", str(commit)], cwd=str(dest))

        return str(dest.resolve())


def _run_git(*, cmd: list[str], cwd: str | None) -> subprocess.CompletedProcess[str]:
    """Run a git subprocess, raising with diagnostics on failure.

    Spec-0009/T4: clone/checkout 失败时抛 RuntimeError 并携带失败命令 + returncode +
    截断 stderr 的诊断（对齐 T3 deps.py 报错风格）。
    """
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if len(stderr) > 2000:
            stderr = stderr[:2000] + "…(stderr 截断)"
        raise RuntimeError(
            f"git 命令失败：{' '.join(cmd)}（returncode={proc.returncode}）\nstderr: {stderr}"
        )
    return proc
