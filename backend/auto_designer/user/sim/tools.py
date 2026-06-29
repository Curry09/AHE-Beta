"""内层用户 agent 的原子工具 + D1 能力门控（spec-0008/T2）。

原子工具（不可再分、可组合）：
- read_file(sandbox, path)         读文件
- run_shell(sandbox, cmd, timeout) 在 sandbox cwd 跑命令
- write_file(sandbox, path, content) 写文件（高能力档专属：能写测试脚本）
- web_search(query)                占位，本轮不实现

「跑测试 / 构造边界用例」这类是「原子工具 + LLM 推理」涌现出的复合行为，不做成工具。
工具集按 persona D1 机械门控（tool_stack）：门控发生在「暴露哪些工具给 LLM」这一层，
不依赖 prompt 自律。映射与 0005 cap_mask（read_code/run_once/run_tests/review_diff）同源。
"""

from __future__ import annotations

import os
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
        with open(sandbox.resolve(path), encoding="utf-8") as f:
            return {"ok": True, "content": f.read()}
    except Exception as e:  # noqa: BLE001 — 工具层把任何失败转成结构化结果，绝不崩内层循环
        return {"ok": False, "error": str(e)}


def write_file(sandbox: Sandbox, path: str, content: str) -> dict:
    try:
        target = sandbox.resolve(path)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": target}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def run_shell(sandbox: Sandbox, cmd: str, timeout: float = 10.0) -> dict:
    return sandbox.run(cmd, timeout=timeout)


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
RUN_SHELL = ToolSpec(
    "run_shell", "Run a shell command in your workspace and see its output.", ("cmd",), run_shell
)
WRITE_FILE = ToolSpec(
    "write_file", "Write/overwrite a file in your workspace.", ("path", "content"), write_file
)

# 门控映射（与 cap_mask 同源）：
#   blind                 -> []                 （只凭文本，不核实）
#   shallow               -> read_file,run_shell（能读能跑一次，但写不出测试套件）
#   competent / expert    -> + write_file       （能自写测试脚本）
_STACK: dict[D1Eval, list[ToolSpec]] = {
    D1Eval.BLIND: [],
    D1Eval.SHALLOW: [READ_FILE, RUN_SHELL],
    D1Eval.COMPETENT: [READ_FILE, RUN_SHELL, WRITE_FILE],
    D1Eval.EXPERT: [READ_FILE, RUN_SHELL, WRITE_FILE],
}


def tool_stack(persona: Persona) -> list[ToolSpec]:
    """按 persona 的 D1 给出可用工具子集（web_search 不入栈：占位、永不真实启用）。"""
    return list(_STACK[persona.d1])
