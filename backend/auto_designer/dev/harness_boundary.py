# Spec-0007：dev 侧硬提交边界，堵「任务代码焊进 harness 仓」的过拟合泄漏。
"""harness 提交边界闸：harness 是**通用编码助手**，仓里只该有它自身的制品——
`entry.py`（启动器）、`agents/`（角色定义）、`tools/`（工具声明）、`MANUAL.md`（用户手册）、
`params.yaml`/`agent.yaml`（配置），外加仓基建 `.gitignore`。

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

# harness 本体允许出现在仓根的顶层路径（目录或文件）。其余一律视为越界（任务代码/被测项目脚手架）。
ALLOWED_TOP: frozenset[str] = frozenset(
    {"MANUAL.md", "agent.yaml", "params.yaml", "entry.py", "agents", "tools", ".gitignore"}
)


def _is_ignorable(path: str) -> bool:
    """构建噪声（字节码缓存），不算越界也不该进版本库——钩子跳过，别为它拒绝整次提交。"""
    top = path.split("/", 1)[0]
    return top == "__pycache__" or path.endswith(".pyc") or "/__pycache__/" in path


def violations(staged_paths: Iterable[str]) -> list[str]:
    """给定暂存文件相对路径集，返回其中越界（顶层不在白名单）的路径；空列表 = 全合法。"""
    bad: list[str] = []
    for raw in staged_paths:
        path = raw.strip()
        if not path or _is_ignorable(path):
            continue
        if path.split("/", 1)[0] not in ALLOWED_TOP:
            bad.append(path)
    return bad


# pre-commit 钩子脚本：自包含（只依赖 python3 stdlib + git），不 import 本包——harness 仓是独立仓，
# 钩子在其内跑，PYTHONPATH 未必含 auto_designer。白名单从 ALLOWED_TOP 注入，逻辑与 violations() 同源。
_HOOK_TEMPLATE = '''#!/usr/bin/env python3
# auto-designer harness boundary gate（由 auto_designer.dev.harness_boundary 生成，勿手改）。
# 拒绝把 harness 本体之外的文件（某个具体任务的项目代码）提交进 harness 仓——保通用工具不被过拟合。
import subprocess
import sys

ALLOWED = {allowed}


def _ignorable(path):
    top = path.split("/", 1)[0]
    return top == "__pycache__" or path.endswith(".pyc") or "/__pycache__/" in path


staged = subprocess.run(
    ["git", "diff", "--cached", "--name-only"], capture_output=True, text=True
).stdout.split("\\n")
bad = [p.strip() for p in staged if p.strip() and not _ignorable(p.strip())
       and p.strip().split("/", 1)[0] not in ALLOWED]
if bad:
    sys.stderr.write(
        "\\n[harness-boundary] 提交被拒。harness 是通用编码助手，仓里只允许它自身的制品："
        "entry.py / agents/ / tools/ / MANUAL.md / params.yaml / agent.yaml。\\n"
        "严禁把某个具体任务的项目代码（被测项目本体、pyproject.toml、新建包、任务 tests/ 等）"
        "焊进来——那是过拟合，且白耗迭代。请删除下列越界文件，只提交对 harness *能力* 的改动：\\n  "
        + "\\n  ".join(bad)
        + "\\n"
    )
    sys.exit(1)
'''


def render_hook() -> str:
    """渲染 pre-commit 钩子脚本文本（白名单内联为 python set 字面量，与 ALLOWED_TOP 同步）。"""
    return _HOOK_TEMPLATE.format(allowed=set(ALLOWED_TOP))


def install_pre_commit(repo: Path) -> None:
    """把边界钩子写入 `<repo>/.git/hooks/pre-commit` 并置可执行（覆盖旧钩子）。repo 须已 git init。"""
    hook = Path(repo) / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(render_hook(), encoding="utf-8")
    hook.chmod(0o755)
