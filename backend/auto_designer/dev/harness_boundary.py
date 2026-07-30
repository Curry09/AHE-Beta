# Spec-0007：dev 侧硬提交边界，堵「任务代码焊进 harness 仓」的过拟合泄漏。
"""harness 提交边界闸：harness 是**通用编码助手**，仓里只该有它自身的制品。

允许的是 harness 产品区域：入口、agent/tool 配置、HELP/RUNTIME、运行脚本、自测与配置模板。
拒绝的是用户任务项目、真实密钥、项目脚手架和未知顶层目录。

真实闭环里观测到：用户 agent 把「跑不动某个 benchmark 任务（如 unidecode）」当 bug 提 issue，
dev agent 领到后照字面 `mkdir -p unicode_ascii/tables; cat > pyproject.toml …` 把**被测项目本体**
一行行写进 harness 仓并提交——通用工具被焊死成某个具体任务，正是要极力避免的过拟合；同时 dev 把整轮
迭代耗在建/装/测这个包上（实测 issue #69 用掉 23 次 shell 调用），直接爆迭代次数。

对策是仓层面的**硬门**：装一个 git `pre-commit` 钩子，暂存区里出现 harness 本体之外的路径就拒绝提交、
打印原因，逼 dev 删掉任务代码、只提交对 harness 能力的改动。不靠 prompt 自觉、agent 绕不过
（除非显式 `--no-verify`，dev 指令不会那么做）。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

# harness 本体允许出现在仓根的顶层文件。
ALLOWED_ROOT_FILES: frozenset[str] = frozenset(
    {
        "HELP.md",
        "RUNTIME.md",
        ".env.example",
        "requirements.txt",
        "agent.yaml",
        "params.yaml",
        "entry.py",
        ".gitignore",
    }
)

# harness 本体允许出现在仓根的顶层目录。
# 注（Spec-0032 实证修复#1）：`.gitea/`（CI workflow 定义）**故意不在白名单**——它是随 seed 下发的
# 平台制品，dev/交付面 agent 不得改写自己的质量闸。seed 提交在装钩子之前完成（run.py._seed_harness_repo
# 的顺序保证），故种子自身不受此拦；服务端兜底见 harness_template/.gitea/workflows/smoke.yml 的边界检查步。
ALLOWED_ROOT_DIRS: frozenset[str] = frozenset(
    {
        "agents",
        "tools",
        "scripts",
        "tests",
    }
)

# 明确拒绝的顶层文件/目录：真实密钥、任务项目脚手架、已退场文档名。
DENIED_TOP: frozenset[str] = frozenset(
    {
        ".env",
        "pyproject.toml",
        "package.json",
        "setup.py",
        "setup.cfg",
        "src",
        "README.md",
        "USER.md",
        "MANUAL.md",
        "INTERFACE.md",
    }
)

# 向后兼容导出：部分测试/调用方只关心“可作为顶层的集合”。
ALLOWED_TOP: frozenset[str] = ALLOWED_ROOT_FILES | ALLOWED_ROOT_DIRS


def _is_ignorable(path: str) -> bool:
    """构建噪声（字节码缓存），不算越界也不该进版本库——钩子跳过，别为它拒绝整次提交。"""
    top = path.split("/", 1)[0]
    return top == "__pycache__" or path.endswith(".pyc") or "/__pycache__/" in path


def violations(staged_paths: Iterable[str]) -> list[str]:
    """给定暂存文件相对路径集，返回其中越界（不属于 harness 产品区域）的路径。"""
    bad: list[str] = []
    for raw in staged_paths:
        path = raw.strip()
        if not path or _is_ignorable(path):
            continue
        top = path.split("/", 1)[0]
        if top in DENIED_TOP:
            bad.append(path)
            continue
        if top in ALLOWED_ROOT_FILES or top in ALLOWED_ROOT_DIRS:
            continue
        bad.append(path)
    return bad


# pre-commit 钩子脚本：自包含（只依赖 python3 stdlib + git），不 import 本包——harness 仓是独立仓，
# 钩子在其内跑，PYTHONPATH 未必含 auto_designer。白名单从本模块注入，逻辑与 violations() 同源。
_HOOK_TEMPLATE = """#!/usr/bin/env python3
# auto-designer harness boundary gate（由 auto_designer.dev.harness_boundary 生成，勿手改）。
# 拒绝把 harness 本体之外的文件（某个具体任务的项目代码）提交进 harness 仓——保通用工具不被过拟合。
import subprocess
import sys

ALLOWED_FILES = {allowed_files}
ALLOWED_DIRS = {allowed_dirs}
DENIED = {denied}


def _ignorable(path):
    top = path.split("/", 1)[0]
    return top == "__pycache__" or path.endswith(".pyc") or "/__pycache__/" in path


staged = subprocess.run(
    ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
).stdout.split("\\n")
bad = []
for p in staged:
    path = p.strip()
    if not path or _ignorable(path):
        continue
    top = path.split("/", 1)[0]
    if top in DENIED or (top not in ALLOWED_FILES and top not in ALLOWED_DIRS):
        bad.append(path)
if bad:
    sys.stderr.write(
        "\\n[harness-boundary] 提交被拒。harness 是通用编码助手，仓里只允许它自身的产品制品："
        "entry.py / agent.yaml / params.yaml / HELP.md / RUNTIME.md / requirements.txt / "
        ".env.example / agents/ / tools/ / scripts/ / tests/。\\n"
        "严禁把某个具体任务的项目代码、项目脚手架、真实密钥或已退场文档名（README/USER/MANUAL/INTERFACE）"
        "提交进 harness 仓。请删除下列越界文件，只提交对 harness *能力* 的改动：\\n  "
        + "\\n  ".join(bad)
        + "\\n"
    )
    sys.exit(1)
"""


def render_hook() -> str:
    """渲染 pre-commit 钩子脚本文本（边界集合内联为 python set 字面量）。"""
    return _HOOK_TEMPLATE.format(
        allowed_files=set(ALLOWED_ROOT_FILES),
        allowed_dirs=set(ALLOWED_ROOT_DIRS),
        denied=set(DENIED_TOP),
    )


def install_pre_commit(repo: Path) -> None:
    """把边界钩子写入 `<repo>/.git/hooks/pre-commit` 并置可执行（覆盖旧钩子）。repo 须已 git init。"""
    hook = Path(repo) / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(render_hook(), encoding="utf-8")
    hook.chmod(0o755)
