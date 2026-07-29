# Spec-0007：把 dev/designer 的文件/shell 操作关进 SANDBOX_WORK_DIR，越界即拒——机制隔离 trace。
"""WorkspaceJailMiddleware：dev/designer 以 harness 仓为可写工作区；NexAU 源码与运行时产物只读放行。

动机：堵住读 `data/sessions` / `data/harness_runs` 任务轨迹导致的过拟合；同时允许：
- 只读查阅钉死的 NexAU 库（多 agent / session / 锁等）；
- 只读 NexAU 本地 bash/tool 临时输出（`nexau_bash_tool_results` / `nexau_tool_outputs`）——
  这是框架自己落盘的 stdout/stderr，不是任务轨迹；拒读会误伤正常工具环。

覆盖：
- 写类工具（write_file/replace/…）：目标必须在 harness work_dir 内。
- 读类工具：work_dir **或** NexAU 仓根 **或** NexAU 运行时临时目录内放行。
- run_shell_command：path-like token 同读规则；trace 目录名仍一律拒。

caveat：bash `python -c` 动态拼路径静态扫不出——要 100% airtight 需 OS 级沙箱。
"""

from __future__ import annotations

import logging
import re
import shlex
import tempfile
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
# 写工具：只允许 harness 仓；读工具额外放行 NexAU 源码 + 运行时临时目录。
_WRITE_TOOLS: frozenset[str] = frozenset({"write_file", "replace", "multiedit_tool"})
_SHELL_TOOL = "run_shell_command"

# trace 目录名兜底正则：harness_runs 唯一、绝不该出现在 harness 仓内的命令里；sessions 仅当经 `../`
# 或绝对路径以「路径段」形式出现才算（`grep sessions foo` 这种把 sessions 当搜索词的不误伤）。
_TRACE_REF = re.compile(r"harness_runs|(?:\.\./|/)[^\s'\"]*sessions(?:/|\b)")

# heredoc 起始：`<<EOF` / `<<-EOF` / `<< 'PY'` / `<<"END"`（marker 为标识符）。用于剥掉正文行——
# 正文是数据不是路径（扫它误伤），但含 `<<` 那一行的**重定向目标**（`cat > OUT <<EOF`）是真路径，须留。
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# NexAU 本地临时目录名（与 nexau.archs.platform.path_helpers 对齐；import 失败时作兜底）。
_BASH_TOOL_RESULTS_DIR = "nexau_bash_tool_results"
_TOOL_OUTPUTS_DIR = "nexau_tool_outputs"


def _nexau_repo_root() -> Path | None:
    """当前环境 `import nexau` 所在的源码仓根（包目录的上一级）；解析失败则无只读放行根。"""
    try:
        import nexau

        return Path(nexau.__file__).resolve().parents[1]
    except Exception:  # noqa: BLE001  无 nexau 时退化为纯 work_dir jail
        return None


def _nexau_runtime_read_roots() -> list[Path]:
    """NexAU 框架落盘的本地临时目录（bash stdout/stderr、长工具输出）——只读放行。

    不是任务轨迹；agent 用 read_file 回看 shell 结果时必须能读，否则 jail 误伤工具环。
    """
    roots: list[Path] = []
    try:
        from nexau.archs.platform.path_helpers import (
            get_local_bash_tool_results_dir,
            get_local_tool_output_dir,
        )

        roots.extend([get_local_bash_tool_results_dir(), get_local_tool_output_dir()])
    except Exception:  # noqa: BLE001  旧 nexau / 无 path_helpers → 按 tempfile 惯例兜底
        tmp = Path(tempfile.gettempdir())
        roots.extend([tmp / _BASH_TOOL_RESULTS_DIR, tmp / _TOOL_OUTPUTS_DIR])
    out: list[Path] = []
    for r in roots:
        try:
            out.append(r.resolve())
        except (OSError, RuntimeError, ValueError):
            continue
    return out


def _read_roots_for(work_dir: Path) -> list[Path]:
    """读放行根：harness 仓 + NexAU 源码 + NexAU 运行时临时目录。"""
    roots = [work_dir]
    nexau_root = _nexau_repo_root()
    if nexau_root is not None:
        roots.append(nexau_root)
    roots.extend(_nexau_runtime_read_roots())
    return roots


def _strip_heredoc_bodies(command: str) -> str:
    """去掉 heredoc 正文（`<<MARKER` 之后到闭合 `MARKER` 行之间的内容），保留命令/重定向行本身。

    旧实现「命令一含 `<<` 即整条跳过 token 扫描」把重定向目标（`cat > /仓外/x <<EOF`）也放行了，
    成了绕过 jail 往仓外写文件的口子（实测被 dev 用来把 harness 内容写进仓外文件）。
    这里只剥正文、保留含 `<<MARKER` 的首行，让后续 token 扫描照样能抓到那个越界重定向目标。
    """
    lines = command.splitlines()
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)  # 保留含 `<<MARKER` 的这行（重定向目标在此）
        m = _HEREDOC_RE.search(line)
        if m:
            marker = m.group(2)
            i += 1
            while i < len(lines) and lines[i].strip() != marker:
                i += 1  # 丢弃正文行
            # 跳过闭合 marker 行（若存在；不存在则 i 已到末尾）
        i += 1
    return "\n".join(kept)


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


def _resolve_against(work_dir: Path, raw: str) -> Path | None:
    """相对路径相对 work_dir；解析失败返回 None（视为越界）。"""
    raw = raw.strip()
    if not raw:
        return None
    cand = Path(raw)
    full = cand if cand.is_absolute() else work_dir / cand
    try:
        return full.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _inside_any(roots: list[Path], real: Path) -> bool:
    for root in roots:
        if real == root or root in real.parents:
            return True
    return False


def _escapes(work_dir: Path, raw: str) -> bool:
    """raw 路径按 work_dir resolve 后是否逃出 work_dir（含符号链接、`..` 归一）。解析不了当作越界。

    保留给单测/旧语义：只审 work_dir，不含 NexAU 只读根。
    """
    real = _resolve_against(work_dir, raw)
    if real is None:
        return bool(raw.strip())
    return not _inside_any([work_dir], real)


def _escapes_roots(work_dir: Path, roots: list[Path], raw: str) -> bool:
    """相对 work_dir resolve 后是否不在任一允许根内。"""
    real = _resolve_against(work_dir, raw)
    if real is None:
        return bool(raw.strip())
    return not _inside_any(roots, real)


def _shell_offender(work_dir: Path, command: str, read_roots: list[Path]) -> str | None:
    """返回命令里第一个越界引用（供报错）；无则 None。

    read_roots：读放行根（含 work_dir 与可选 NexAU）。写重定向到 NexAU 仍可能被 path token 放行
    （静态分不清读写）——靠 prompt「NexAU 只读」约束；轨迹路径仍由 _TRACE_REF 硬拒。
    """
    if _TRACE_REF.search(command):
        return "trace 目录（sessions / harness_runs）"
    scanned = _strip_heredoc_bodies(command)  # 剥正文、留重定向行——堵住 `> /仓外 <<EOF` 绕过口
    try:
        tokens = shlex.split(scanned, posix=True)
    except ValueError:
        tokens = scanned.split()
    for tok in tokens:
        t = tok.strip().lstrip("<>")  # 去掉重定向操作符前缀（>path / >>path / <path / <<MARKER）
        if "/" not in t and t != "..":  # 只审 path-like token
            continue
        if _escapes_roots(work_dir, read_roots, t):
            return t
    return None


class WorkspaceJailMiddleware(Middleware):
    """harness 仓可读写；NexAU 源码 + 运行时临时目录只读放行；轨迹与其它路径一律拒。"""

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

        read_roots = _read_roots_for(work_dir)

        tool = params.tool_name
        if tool in _PATH_PARAMS:
            roots = [work_dir] if tool in _WRITE_TOOLS else read_roots
            for raw in _iter_path_values(tool, params.parameters):
                if _escapes_roots(work_dir, roots, raw):
                    return self._deny(f"{tool} 目标路径 {raw!r}")
        elif tool == _SHELL_TOOL:
            command = params.parameters.get("command")
            if isinstance(command, str):
                offender = _shell_offender(work_dir, command, read_roots)
                if offender is not None:
                    return self._deny(f"命令引用了 {offender}")

        return call_next(params)

    @staticmethod
    def _deny(what: str) -> dict[str, Any]:
        msg = (
            f"[workspace-jail] 拒绝：{what} 越界。"
            "可写范围 = harness 仓；可读范围 = harness 仓 + NexAU 源码（只读）"
            " + NexAU 运行时临时目录（bash/tool 输出，只读）。"
            "绝不读取任务轨迹/会话录像（data/sessions、data/harness_runs）——会过拟合。"
            "框架细节读 NexAU；改动只落 harness 仓。"
        )
        logger.warning("workspace-jail 拦截越界访问：%s", what)
        return {
            "content": msg,
            "returnDisplay": "Access denied (outside workspace).",
            "error": {"message": msg, "type": "WORKSPACE_JAIL_DENIED"},
        }
