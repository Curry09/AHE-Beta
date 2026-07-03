"""git SeedSource（spec-0009/T4）。

Spec-0009/T4: git 源（repo@commit 快照工作区）

provision 返回「某仓库停在某 commit」的干净快照目录——真实 repo 任务（SWE-bench 的
base_commit 未修复态、funcy@某版本等）的起点。repo/commit（及可选 ref/depth）全落
`WorkspaceSpec.params`，不扩 schema、kind="git"。

网络策略（大仓 + 慢网下的生存性）：缓存按**仓库**共享（backend/data/repo_cache/<slug>/repo），
每个目标 commit 只联网取一次——`git fetch --depth 1 <repo> <sha>:refs/seeds/<sha>` 按 SHA
定向浅取（GitHub 支持 reachable SHA fetch；同仓第二个 commit 起走增量 delta，只有几 MB）；
服务端不支持按 SHA 取时回退全量 clone 重建缓存（兼容本地裸路径仓）。之后每局 provision
copytree 该缓存 + 在副本里 checkout 目标 commit，每局仍是独立目录、互不串状态
（隔离语义与「每局 fresh clone」等价）。

可插拔证明：接入它只新增本模块——靠 spec-0009/T1 的 sources/ 自动发现注册，seed_source /
models / workspace 与消费侧（orchestrator / sim_user / Sandbox）一律不改。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import register

# 仓库缓存根：backend/data/repo_cache（运行产物，随 data/ 整体 .gitignore）。
_CACHE_ROOT = Path(__file__).resolve().parents[4] / "data" / "repo_cache"


@register("git")
class GitSource:
    kind = "git"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        """Provision an isolated working tree of repo@commit（缓存命中则纯本地复制）。

        Spec-0009/T4: 从 spec.params 读 repo（必填）、commit（必填）、可选 ref/depth；
        确保 commit 对象进本仓缓存后 copytree 到隔离目录并 checkout，返回该目录绝对路径。
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

        cache = _ensure_commit_cached(
            repo=str(repo), commit=str(commit), ref=ref, depth=depth
        )

        # 2. 每局 fresh：从缓存复制一份独立目录再 checkout，跨局互不污染、可清理。
        base = dest_root or tempfile.mkdtemp(prefix="sim_ws_git_")
        dest = Path(base) / "repo"
        shutil.copytree(cache, dest, symlinks=True)

        # 3. checkout 到目标 commit；浅克隆可能取不到任意历史 commit，
        #    回退为 fetch --unshallow 全量拉取后重试（浅克隆 + 任意 commit 的兼容）。
        try:
            _run_git(cmd=["git", "checkout", "-q", str(commit)], cwd=str(dest))
        except RuntimeError:
            if not depth:
                raise
            _run_git(cmd=["git", "fetch", "--unshallow"], cwd=str(dest))
            _run_git(cmd=["git", "checkout", str(commit)], cwd=str(dest))

        return str(dest.resolve())


def _ensure_commit_cached(
    *, repo: str, commit: str, ref: str | None, depth: int | None
) -> Path:
    """确保 commit 对象在 repo 的共享缓存里并返回缓存路径；只有 miss 时才碰网络。

    取法优先级：① `fetch --depth 1 <repo> <sha>:refs/seeds/<sha>` 按 SHA 定向浅取并落 ref
    锚住对象（防 gc），同仓多 commit 增量复用已有对象；② 首个 commit 且服务端拒绝按 SHA 取
    （本地裸路径仓/老服务端）时回退全量 clone 重建缓存。每个 commit 成功后落 shas/<sha> 标记，
    命中即跳过网络；缓存本体不 checkout（copytree 只搬 .git，工作树由 provision 副本里生成）。
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", repo).strip("-")[-60:] or "repo"
    entry = _CACHE_ROOT / slug
    cache = entry / "repo"
    markers = entry / "shas"
    marker = markers / commit
    if marker.is_file() and (cache / ".git").is_dir():
        return cache
    markers.mkdir(parents=True, exist_ok=True)
    if not (cache / ".git").is_dir():  # 首建或上次构建的残骸
        shutil.rmtree(cache, ignore_errors=True)
        _run_git(cmd=["git", "init", "-q", str(cache)], cwd=None)

    if _has_commit(cache=cache, commit=commit):  # 既有对象（如全量回退已带回）→ 零网络
        marker.touch()
        return cache

    try:
        _run_git(
            cmd=["git", "fetch", "--depth", "1", repo, f"{commit}:refs/seeds/{commit[:12]}"],
            cwd=str(cache),
        )
    except RuntimeError:
        if any(markers.iterdir()):
            # 缓存已有既往内容、仅新 commit 按 SHA 取失败 → 全量 fetch 更新；
            # 可及性最终由 provision 副本里的 checkout 诊断。
            _run_git(
                cmd=["git", "fetch", repo, "+refs/heads/*:refs/seeds/heads/*"],
                cwd=str(cache),
            )
        else:
            # 回退：全量 clone（老路径），可选 depth/ref 加速（兼容本地路径仓/老服务端）。
            shutil.rmtree(cache)
            clone_cmd = ["git", "clone"]
            if depth:
                clone_cmd += ["--depth", str(depth)]
            if ref:
                clone_cmd += ["--branch", str(ref)]
            clone_cmd += [repo, str(cache)]
            _run_git(cmd=clone_cmd, cwd=None)

    marker.touch()
    return cache


def _has_commit(*, cache: Path, commit: str) -> bool:
    """cache 仓里是否已有该 commit 对象（cat-file -e；任何失败视为无）。"""
    try:
        _run_git(cmd=["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=str(cache))
        return True
    except RuntimeError:
        return False


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
