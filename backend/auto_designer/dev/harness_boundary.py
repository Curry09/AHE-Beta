# Spec-0007 / 0033 / 0040/T2：dev 侧提交边界。围堵已升到容器后，本闸从白名单改为拒绝清单。
"""harness 提交边界闸：拦住密钥和 vigil 运行态，不再用顶层白名单锁死产品形状。

Spec-0040/T2: 拒绝清单只拦密钥与 vigil 运行态。

原先白名单（只许 entry.py / agents / tests …）是防「把某个 benchmark 任务焊进 harness」。
spec-0033 之后交付面默认关在容器里、零宿主挂载，过拟合信道（编排仓 / data/sessions）已经看不见；
RFC（docs/specs/）和结构性演进（新目录、pyproject、README）反而是交付面该做的事。白名单会把
这些合法改动在 CI 上打死（实证：rfc:agent 写下 docs/ 后 smoke 3 秒红、合并不了）。

仍拒绝：真实密钥（``.env`` / ``.env.*``，``.env.example`` 除外）和 ``.openagents/``（vigil 运行态，
随容器重建，不应入库）。其余顶层路径放行。不靠 prompt 自觉；``--no-verify`` 仍可能绕过钩子，
服务端兜底见 harness_template/.gitea/workflows/smoke.yml（拒绝清单须与本模块同步）。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

# Spec-0040/T2：顶层目录/文件拒绝清单（精确匹配第一段）。``.env`` 另走文件名规则，不进本集合。
DENIED_TOP: frozenset[str] = frozenset({".openagents"})


def _is_ignorable(*, path: str) -> bool:
    """构建噪声（字节码缓存），不算越界也不该进版本库——钩子跳过，别为它拒绝整次提交。"""
    top = path.split("/", 1)[0]
    return top == "__pycache__" or path.endswith(".pyc") or "/__pycache__/" in path


def _is_denied(*, path: str) -> bool:
    """Return whether a relative path is on the denylist.

    Spec-0040/T2：运行态目录，或除 .env.example 外的 .env / .env.* 密钥文件。
    """
    top = path.split("/", 1)[0]
    if top in DENIED_TOP:
        return True
    for part in path.split("/"):
        if part == ".env.example":
            continue
        if part == ".env" or part.startswith(".env."):
            return True
    return False


def violations(staged_paths: Iterable[str]) -> list[str]:
    """给定暂存文件相对路径集，返回其中越界（密钥 / vigil 运行态）的路径。"""
    bad: list[str] = []
    for raw in staged_paths:
        path = raw.strip()
        if not path or _is_ignorable(path=path):
            continue
        if _is_denied(path=path):
            bad.append(path)
    return bad


# pre-commit 钩子脚本：自包含（只依赖 python3 stdlib + git），不 import 本包——harness 仓是独立仓，
# 钩子在其内跑，PYTHONPATH 未必含 auto_designer。拒绝清单从本模块注入，逻辑与 violations() 同源。
_HOOK_TEMPLATE = """#!/usr/bin/env python3
# auto-designer harness boundary gate（由 auto_designer.dev.harness_boundary 生成，勿手改）。
# 只拒密钥与 vigil 运行态；其余顶层路径放行（docs/specs、结构性演进）。容器围堵后不再用白名单。
import subprocess
import sys

DENIED_TOP = {denied_top}


def _ignorable(path):
    top = path.split("/", 1)[0]
    return top == "__pycache__" or path.endswith(".pyc") or "/__pycache__/" in path


def _denied(path):
    top = path.split("/", 1)[0]
    if top in DENIED_TOP:
        return True
    for part in path.split("/"):
        if part == ".env.example":
            continue
        if part == ".env" or part.startswith(".env."):
            return True
    return False


staged = subprocess.run(
    ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
).stdout.split("\\n")
bad = []
for p in staged:
    path = p.strip()
    if not path or _ignorable(path) or not _denied(path):
        continue
    bad.append(path)
if bad:
    sys.stderr.write(
        "\\n[harness-boundary] 提交被拒。只拦真实密钥（.env / .env.*，.env.example 除外）"
        "和 .openagents/（vigil 运行态）。docs/、新目录、产品文件都允许。"
        "请删掉下列文件后再提交：\\n  "
        + "\\n  ".join(bad)
        + "\\n"
    )
    sys.exit(1)
"""


def render_hook() -> str:
    """渲染 pre-commit 钩子脚本文本（拒绝清单内联为 python set 字面量）。"""
    return _HOOK_TEMPLATE.format(denied_top=set(DENIED_TOP))


def install_pre_commit(repo: Path) -> None:
    """把边界钩子写入 `<repo>/.git/hooks/pre-commit` 并置可执行（覆盖旧钩子）。repo 须已 git init。"""
    hook = Path(repo) / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(render_hook(), encoding="utf-8")
    hook.chmod(0o755)
