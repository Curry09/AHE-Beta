"""seed_adapter.py（spec-0010/T2）：把种子卡注入 0009 的 SeedSource 供给。

card_to_seed 是「采集（种子卡，0010/T1）」与「0009 SeedSource 引擎」之间的**唯一桥接层**：按字段
把一张卡翻成 spec-0001 models.SeedScenario——`task.prompt` → description，`source.repo`+`env.repo_at`
→ git 工作区（0009/T4 kind="git" + params{repo, commit}），`env.setup` → venv 前缀化的 setup
（0009/T3）。无 repo 的纯文本卡退化为 workspace=None。与 0006/T2 card_to_persona 对称镜像。

**held-out 红线**：客观判分制品 oracle / env.test_cmd / gates 是 benchmark 侧证据，经 extract_sidecar
剥到旁路、**绝不进** SeedScenario（及其 to_dict / {version, seeds} 信封 JSON）、不进训练环。依据
CLAUDE.md「benchmark 全程 held-out：不参与训练，不参与发版门禁」——训练信号只取体感，oracle 归
harbor 侧平行评测，二者物理隔离于注入边界。卡形状契约见 tools/seed-distill/seed-card-schema.md。

缺字段 / 非法值（git 型缺 repo_at、repo_at 仍是未解析占位、domain 越表）显式报错（不静默兜底），
把采集质量问题暴露在注入边界；与 0006/T2 报错而非安全缺省同策。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ahe_beta.distill.seed_library import validate_card
from ahe_beta.models import SeedScenario, WorkspaceSpec

if TYPE_CHECKING:
    from ahe_beta.distill.seed_library import SeedLibrary

# {version, seeds} 信封版本：card_to_seeds 的可持久化产物形状（信封 JSON schema 版本号）。
SEED_ENVELOPE_VERSION = 1

# held-out 客观判分制品：注入时剥离到 sidecar，绝不进 SeedScenario。
_SIDECAR_KEYS = ("oracle", "gates", "provenance")

# 裸解释器命令 → per-workspace venv 内命令（对齐 0009/T3 约定）。
_VENV_BIN = {
    "pip": ".venv/bin/pip",
    "pip3": ".venv/bin/pip3",
    "python": ".venv/bin/python",
    "python3": ".venv/bin/python3",
}


def extract_sidecar(record: dict) -> dict:
    """剥离出一张卡的 held-out 判分制品（oracle / test_cmd / gates + provenance）。

    Spec-0010/T2: 供 harbor 侧平行评测消费；**绝不**进 SeedScenario / 训练环。只收录卡中实际存在
    的键（前向兼容）。test_cmd 藏在 env 里，单独提到顶层便于 sidecar 消费。
    """
    sidecar: dict = {key: record[key] for key in _SIDECAR_KEYS if key in record}
    env = record.get("env")
    if isinstance(env, dict) and "test_cmd" in env:
        sidecar["test_cmd"] = env["test_cmd"]
    return sidecar


def card_to_seed(record: dict) -> SeedScenario:
    """把一张种子卡映射为 models.SeedScenario；held-out 字段（oracle/test_cmd/gates）被剥离。

    Spec-0010/T2: task.prompt → description（原文直传，禁带 oracle/test_cmd）；有 source.repo 的卡
    → WorkspaceSpec(kind="git", params={repo(URL), commit(已解析 SHA)}, setup=venv 前缀化)；无 repo 的
    纯文本卡 → workspace=None。缺 repo_at / 占位未解析 / domain 越表显式报错。
    """
    # 1. 契约级校验前移到注入边界（domain/capability 受控、非 benchmark、白名单）。
    validate_card(record)

    # 2. task.prompt → description（held-out 红线：只带真实诉求原文）。
    task = record.get("task")
    if not isinstance(task, dict) or not task.get("prompt"):
        raise ValueError("卡缺 task.prompt（注入 SeedScenario.description 的原文）")
    description = str(task["prompt"])

    # 3. 有真实 repo → git 工作区；否则纯文本（workspace=None）。
    source = record.get("source") or {}
    repo = source.get("repo")
    if not repo or repo == "n/a":
        return SeedScenario(description=description, workspace=None)

    env = record.get("env") or {}
    repo_at = env.get("repo_at")
    if not repo_at:
        raise ValueError("git 型卡缺 env.repo_at（要恢复的父 commit 真实 SHA）")
    commit = _resolved_sha(repo_at=str(repo_at))
    workspace = WorkspaceSpec(
        kind="git",
        params={"repo": _repo_url(repo=str(repo)), "commit": commit},
        setup=_prefix_venv(setup=list(env.get("setup") or [])),
    )
    return SeedScenario(description=description, workspace=workspace)


def card_to_seeds(library: SeedLibrary) -> dict:
    """把库内每条卡注入为 {version, seeds:[SeedScenario.to_dict()...]} 信封。

    Spec-0010/T2: 可持久化的 {version, seeds} 信封（供旁路落盘 / 离线检视）。held-out 字段已在
    card_to_seed 剥离，故信封 JSON 不含 oracle/test_cmd/gates。run.py 走 card_to_seed 直接注入
    SeedScenario、不经此信封。
    """
    return {
        "version": SEED_ENVELOPE_VERSION,
        "seeds": [card_to_seed(record).to_dict() for record in library.load()],
    }


def _repo_url(repo: str) -> str:
    """owner/repo → https clone URL；已是 URL / git@ 形式则原样透传。"""
    if "://" in repo or repo.startswith("git@"):
        return repo
    return f"https://github.com/{repo}.git"


def _resolved_sha(repo_at: str) -> str:
    """校验 repo_at 已解析为真实 SHA；未解析占位（如 `<parent-...>`）显式拒收。

    Spec-0010/T2: 0009/T4 git 源按 commit checkout，占位会在物化时才炸——在注入边界前移校验。
    """
    val = repo_at.strip()
    if not val:
        raise ValueError("env.repo_at 为空（须为已解析的真实 commit SHA）")
    if "<" in val or ">" in val or any(ch.isspace() for ch in val):
        raise ValueError(
            f"env.repo_at={repo_at!r} 仍是未解析占位（须为已解析的真实 commit SHA，"
            "harvest 时用 git 求父 commit）"
        )
    return val


def _prefix_venv(setup: list[str]) -> list[str]:
    """venv 前缀化 env.setup（对齐 0009/T3）：首插 `python -m venv .venv`，裸 pip/python 改写为 .venv/bin/…。

    Spec-0010/T2: 使 0009/T3 ensure_deps 建 per-workspace venv、Sandbox 探测 `.venv` 生效。
    空 setup（无依赖）不建 venv（返回 []，与既有无依赖场景零改动）。
    """
    if not setup:
        return []
    steps = ["python -m venv .venv"]
    steps.extend(_venv_bin(command=cmd) for cmd in setup)
    return steps


def _venv_bin(command: str) -> str:
    """把一条 setup 命令的裸解释器前缀（pip/python）改写为 .venv/bin/…；其余原样。"""
    parts = command.split()
    if parts and parts[0] in _VENV_BIN:
        parts[0] = _VENV_BIN[parts[0]]
        return " ".join(parts)
    return command
