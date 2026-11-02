"""内层用户 agent 的原子工具 + D1 能力门控（spec-0008/T2）。

原子工具（不可再分、可组合）：
- read_file(sandbox, path)         读文件
- run_shell(sandbox, cmd, timeout) 在 sandbox cwd 跑命令
- write_file(sandbox, path, content) 写文件（高能力档专属：能写测试脚本）
- report_issue(sandbox, body)      中途记一条 issue（不结束对话；真实写入由 agentic client 拦截）
- web_search(query)                占位，本轮不实现

「跑测试 / 构造边界用例」这类是「原子工具 + LLM 推理」涌现出的复合行为，不做成工具。
工具集按 persona D1 机械门控（tool_stack）：门控发生在「暴露哪些工具给 LLM」这一层，
不依赖 prompt 自律。映射与 0005 cap_mask（read_code/run_once/run_tests/review_diff）同源。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dimensions import D1Eval, Persona

if TYPE_CHECKING:
    from .sandbox import Sandbox


# --------------------------------------------------------------------------
# 原子工具（统一返回 {ok, ...}）
# --------------------------------------------------------------------------
def read_file(sandbox: Sandbox, path: str) -> dict:
    try:
        return {"ok": True, "content": sandbox.read_text(path)}
    except Exception as e:  # noqa: BLE001 — 工具层把任何失败转成结构化结果，绝不崩内层循环
        return {"ok": False, "error": str(e)}


def write_file(sandbox: Sandbox, path: str, content: str) -> dict:
    try:
        target = sandbox.write_text(path, content)
        return {"ok": True, "path": target}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def run_shell(sandbox: Sandbox, cmd: str, timeout: float = 10.0) -> dict:
    return sandbox.run(cmd, timeout=timeout)


def list_files(sandbox: Sandbox, path: str = ".") -> dict:
    """Spec-0084/T2: list only already captured review files."""
    try:
        return {"ok": True, "files": sandbox.list_files(path)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def read_diff(sandbox: Sandbox) -> dict:
    try:
        return {"ok": True, "content": sandbox.read_diff()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def report_issue(sandbox: Sandbox, body: str) -> dict:  # noqa: ARG001
    """占位：真实记笔记由 AgenticPersonaClient._dispatch 拦截；直接调则失败。"""
    return {"ok": False, "error": "report_issue requires agentic client dispatch"}


def web_search(query: str) -> dict:
    """占位：本轮不实现，永远返回未实现。"""
    return {"ok": False, "error": "not_implemented"}


# --------------------------------------------------------------------------
# 工具规格 + D1 门控
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolSpec:
    """供 T3 渲染进 prompt（name/description/args）、供 T4 按 name 派发（fn）。"""

    name: str
    description: str
    args: tuple[str, ...]
    fn: Callable[..., dict]


READ_FILE = ToolSpec("read_file", "Read a file in your workspace.", ("path",), read_file)
LIST_FILES = ToolSpec(
    "list_files", "List files captured in this read-only snapshot.", ("path",), list_files
)
READ_DIFF = ToolSpec("read_diff", "Read the captured patch; never runs a command.", (), read_diff)
RUN_SHELL = ToolSpec(
    "run_shell", "Run a shell command in your workspace and see its output.", ("cmd",), run_shell
)
WRITE_FILE = ToolSpec(
    "write_file", "Write/overwrite a file in your workspace.", ("path", "content"), write_file
)
REPORT_ISSUE = ToolSpec(
    "report_issue",
    "Optionally file an issue note for the team behind the tool. Does NOT end this "
    "conversation — you can keep talking after. Skip if you have nothing worth reporting; "
    "there is no obligation to use this. (Distinct from ending the session with action "
    "file_issue.)",
    ("body",),
    report_issue,
)

# 门控映射（与 cap_mask 同源）：
#   blind                 -> []                 （只凭文本，不核实）
#   shallow               -> read_file,run_shell + report_issue
#   competent / expert    -> + write_file
# report_issue 不绑核实能力：有工具栈的人即可中途记一笔；允许闲置，不靠 prompt 硬推。
_STACK: dict[D1Eval, list[ToolSpec]] = {
    D1Eval.BLIND: [],
    D1Eval.SHALLOW: [READ_FILE, RUN_SHELL, REPORT_ISSUE],
    D1Eval.COMPETENT: [READ_FILE, RUN_SHELL, WRITE_FILE, REPORT_ISSUE],
    D1Eval.EXPERT: [READ_FILE, RUN_SHELL, WRITE_FILE, REPORT_ISSUE],
}


def tool_stack(persona: Persona) -> list[ToolSpec]:
    """按 persona 的 D1 给出可用工具子集（web_search 不入栈：占位、永不真实启用）。"""
    return list(_STACK[persona.d1])


def review_tool_stack(persona: Persona) -> list[ToolSpec]:
    """Spec-0084/T2: reviewer capabilities are independent of authoring tools."""
    return [] if persona.d1 is D1Eval.BLIND else [READ_FILE, LIST_FILES, READ_DIFF]
