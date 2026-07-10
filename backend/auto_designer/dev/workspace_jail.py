# Spec-0007：把 dev/designer 的文件/shell 操作关进 SANDBOX_WORK_DIR，越界即拒——机制隔离 trace。
"""WorkspaceJailMiddleware：dev/designer 只能碰自己的 harness 仓，越界读写一律拒。

动机（同源于提交边界闸的过拟合泄漏）：dev/designer 的 sandbox 工作目录 = harness 仓，但 nexau 的
read 类工具（read_file/list_directory…）**不走权限体系**、只读 bash（cat/grep/find/less）又在只读
白名单里**无条件放行**——agent 顺 `../` 或绝对路径就能读到仓外 data/sessions（体感+会话）、
data/harness_runs（运行副本）里的**任务轨迹**。逐行看某任务轨迹会把该任务专属产物（某库 API、某类
文件、预期输出）带进 harness = 过拟合。这两类角色的合法工作全在自己仓内（git/pytest/改文件），故直接
jail：路径逃出 work_dir 即拒。

拦截点：nexau 的 `wrap_tool_call`（tool_executor 里包住每次工具执行）——本中间件不调 `call_next`、
直接返回一个"拒绝"结果，真工具就不执行。

覆盖：
- 文件类工具（read_file/write_file/replace/list_directory/glob_tool/search_file_content/
  read_many_files/read_visual_file）：把路径参数按 work_dir resolve，逃出 work_dir 一律拒。
- run_shell_command：best-effort 扫命令里的 path-like token，越界即拒；另有 trace 目录名正则兜底。

caveat：bash 若用 `python -c` 之类**动态拼绝对路径**读文件，静态扫描扫不出——要 100% airtight 得上
OS 级沙箱（容器/sandbox-exec），出本层范围。但对非对抗性的 LLM，这已堵住所有现实发现路径。
"""

from __future__ import annotations

import logging
import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nexau.archs.main_sub.execution.hooks import Middleware, ToolCallParams

logger = logging.getLogger(__name__)

# 各文件工具里"路径参数"的键名（值可为 str 或 list[str]）；其余参数（old_string/new_string/pattern
# 等是内容或正则，不是路径）一律不审，避免误伤。
_PATH_PARAMS: dict[str, tuple[str, ...]] = {
    "read_file": ("file_path",),
    "read_visual_file": ("file_path",),
    "write_file": ("file_path",),
    "replace": ("file_path",),
    "multiedit_tool": ("file_path",),
    "list_directory": ("dir_path", "path"),
    "glob_tool": ("dir_path", "path"),
    "search_file_content": ("dir_path", "path"),
    "read_many_files": ("paths",),
}
_SHELL_TOOL = "run_shell_command"

# trace 目录名兜底正则：harness_runs 唯一、绝不该出现在 harness 仓内的命令里；sessions 仅当经 `../`
# 或绝对路径以「路径段」形式出现才算（`grep sessions foo` 这种把 sessions 当搜索词的不误伤）。
_TRACE_REF = re.compile(r"harness_runs|(?:\.\./|/)[^\s'\"]*sessions(?:/|\b)")


def _iter_path_values(tool_name: str, parameters: dict[str, Any]):
    """产出该工具参数里所有 path-like 值（str，展开 list）。"""
    for key in _PATH_PARAMS.get(tool_name, ()):
        val = parameters.get(key)
        if isinstance(val, str):
            yield val
        elif isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, str):
                    yield item


def _escapes(work_dir: Path, raw: str) -> bool:
    """raw 路径按 work_dir resolve 后是否逃出 work_dir（含符号链接、`..` 归一）。解析不了当作越界。"""
    raw = raw.strip()
    if not raw:
        return False
    cand = Path(raw)
    full = cand if cand.is_absolute() else work_dir / cand
    try:
        real = full.resolve()
    except (OSError, RuntimeError, ValueError):
        return True
    return real != work_dir and work_dir not in real.parents


def _shell_offender(work_dir: Path, command: str) -> str | None:
    """返回命令里第一个越界引用（供报错）；无则 None。best-effort：heredoc 正文不当路径扫，仅兜底正则。"""
    if _TRACE_REF.search(command):
        return "trace 目录（sessions / harness_runs）"
    if "<<" in command:  # heredoc：正文是内容不是路径，跳过 token 扫描避免误伤
        return None
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for tok in tokens:
        t = tok.strip()
        if "/" not in t and t != "..":  # 只审 path-like token
            continue
        if _escapes(work_dir, t):
            return t
    return None


class WorkspaceJailMiddleware(Middleware):
    """把 dev/designer 的文件/shell 操作关进 SANDBOX_WORK_DIR，越界读写一律拒（机制隔离 trace）。"""

    def wrap_tool_call(
        self,
        params: ToolCallParams,
        call_next: Callable[[ToolCallParams], Any],
    ) -> Any:
        sandbox = params.sandbox
        work_dir_raw = getattr(sandbox, "work_dir", None) if sandbox is not None else None
        if work_dir_raw is None:  # 无 sandbox/work_dir：无从判定，放行（不改变既有行为）
            return call_next(params)
        try:
            work_dir = Path(str(work_dir_raw)).resolve()
        except (OSError, RuntimeError, ValueError):
            return call_next(params)

        tool = params.tool_name
        if tool in _PATH_PARAMS:
            for raw in _iter_path_values(tool, params.parameters):
                if _escapes(work_dir, raw):
                    return self._deny(f"{tool} 目标路径 {raw!r}")
        elif tool == _SHELL_TOOL:
            command = params.parameters.get("command")
            if isinstance(command, str):
                offender = _shell_offender(work_dir, command)
                if offender is not None:
                    return self._deny(f"命令引用了 {offender}")

        return call_next(params)

    @staticmethod
    def _deny(what: str) -> dict[str, Any]:
        msg = (
            f"[workspace-jail] 拒绝：{what} 在你的工作区（harness 仓）之外。你只能读写自己仓内的文件。"
            "绝不读取任务轨迹/会话录像（data/sessions、data/harness_runs）——逐行看某任务轨迹会把该任务"
            "专属产物带进 harness，造成过拟合。请只在仓内工作；诊断靠 `git log`/读仓内源码，不靠翻轨迹。"
        )
        logger.warning("workspace-jail 拦截越界访问：%s", what)
        return {
            "content": msg,
            "returnDisplay": "Access denied (outside workspace).",
            "error": {"message": msg, "type": "WORKSPACE_JAIL_DENIED"},
        }
