"""git SeedSource（spec-0009/T4）。

Spec-0009/T4: git 源（repo@commit 快照工作区）

provision 返回「某仓库停在某 commit」的干净快照目录——真实 repo 任务（SWE-bench 的
base_commit 未修复态、funcy@某版本等）的起点。repo/commit（及可选 ref/depth）全落
`WorkspaceSpec.params`，不扩 schema、kind="git"。

网络策略（大仓 + 慢代理下的生存性）：同一 (repo, commit) 只联网取一次——优先
`git fetch --depth 1 <repo> <commit>` 按 SHA 浅拉取（只拿目标快照，pandas 级大仓从
全量 GB 降到百 MB）；服务端不支持按 SHA 取时回退全量 clone。取到的快照缓存在
backend/data/repo_cache/<slug>@<sha>/，之后每局 provision 直接本地 copytree，
每局仍是独立目录、互不串状态（隔离语义与「每局 fresh clone」等价）。

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

# (repo, commit) 快照缓存根：backend/data/repo_cache（运行产物，随 data/ 整体 .gitignore）。
_CACHE_ROOT = Path(__file__).resolve().parents[4] / "data" / "repo_cache"


@register("git")
class GitSource:
    kind = "git"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        """Provision an isolated working tree of repo@commit（缓存命中则纯本地复制）。

        Spec-0009/T4: 从 spec.params 读 repo（必填）、commit（必填）、可选 ref/depth；
        确保 (repo, commit) 快照进本地缓存后 copytree 到隔离目录，返回该目录绝对路径。
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

        cache = _ensure_cached_snapshot(
            repo=str(repo), commit=str(commit), ref=ref, depth=depth
        )

        # 每局 fresh：从缓存复制一份独立工作树，跨局互不污染、可清理。
        base = dest_root or tempfile.mkdtemp(prefix="sim_ws_git_")
        dest = Path(base) / "repo"
        shutil.copytree(cache, dest, symlinks=True)
        return str(dest.resolve())


def _ensure_cached_snapshot(
    *, repo: str, commit: str, ref: str | None, depth: int | None
) -> Path:
    """确保 (repo, commit) 的快照在本地缓存并返回其路径；只有 miss 时才碰网络。

    取法优先级：① fetch --depth 1 按 SHA 定向浅取（GitHub 等支持 allowAnySHA1InWant 的
    服务端，只下载该 commit 的树）；② 回退 clone（可带 depth/ref 加速）+ checkout，
    浅克隆取不到目标 commit 时再 fetch --unshallow（与旧行为一致）。
    半成品防护：构建全程在 cache 目录内进行，成功后落 .ready 标记；无标记视为脏缓存重建。
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", repo).strip("-")[-60:]
    entry = _CACHE_ROOT / f"{slug}@{commit[:12]}"
    cache = entry / "repo"
    marker = entry / ".ready"
    if marker.is_file() and cache.is_dir():
        return cache
    if entry.exists():  # 上次构建被中断的残骸
        shutil.rmtree(entry)
    entry.mkdir(parents=True)

    try:
        _run_git(cmd=["git", "init", "-q", str(cache)], cwd=None)
        _run_git(cmd=["git", "fetch", "--depth", "1", repo, commit], cwd=str(cache))
        _run_git(cmd=["git", "checkout", "-q", commit], cwd=str(cache))
    except RuntimeError:
        shutil.rmtree(cache, ignore_errors=True)
        clone_cmd = ["git", "clone"]
        if depth:
            clone_cmd += ["--depth", str(depth)]
        if ref:
            clone_cmd += ["--branch", str(ref)]
        clone_cmd += [repo, str(cache)]
        _run_git(cmd=clone_cmd, cwd=None)
        try:
            _run_git(cmd=["git", "checkout", str(commit)], cwd=str(cache))
        except RuntimeError:
            if not depth:
                raise
            _run_git(cmd=["git", "fetch", "--unshallow"], cwd=str(cache))
            _run_git(cmd=["git", "checkout", str(commit)], cwd=str(cache))

    marker.touch()
    return cache


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
