# Spec-0007: confine dev/architect file/shell operations to SANDBOX_WORK_DIR, reject out-of-bounds—mechanism isolates trace.
"""WorkspaceJailMiddleware: dev/architect use harness repo as writable workspace; NexAU source and runtime artifacts are read-only.

Motivation: prevent overfitting from reading `data/sessions` / `data/harness_runs` task traces; meanwhile allow:
- read-only access to pinned NexAU library (multiple agents / sessions / locks, etc.);
- read-only NexAU local bash/tool ephemeral outputs (`nexau_bash_tool_results` / `nexau_tool_outputs`)—
  these are stdout/stderr persisted by the framework itself, not task traces; blocking reads would harm normal tool environments.

Covers:
- write-class tools (write_file/replace/…): target must be within harness work_dir.
- read-class tools: allowed within work_dir **or** NexAU repo root **or** NexAU runtime ephemeral directories.
- role-bound artifact observation packages: plain file tools read-only their declared files, access separately logged; raw sessions library not exposed.
- run_shell_command: path-like tokens follow read rules; trace directory names still universally rejected.

caveat: bash `python -c` with dynamically composed paths can evade static scanning—full airtightness requires OS-level sandbox.
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

from ahe_beta.usage import current_usage_context

logger = logging.getLogger(__name__)

# key names for "path parameters" in file tools (values may be str or list[str]); all other parameters (old_string/new_string/pattern,
# etc. are content or regex, not paths) are never audited, avoiding false positives.
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
# write tools: allow only harness repo; read tools additionally permit NexAU source + runtime ephemeral directories.
_WRITE_TOOLS: frozenset[str] = frozenset({"write_file", "replace", "multiedit_tool"})
_SHELL_TOOL = "run_shell_command"
_TRIAGE_RUNTIME_DIRS = frozenset({".openagents", ".ruff_cache", ".pytest_cache", ".mypy_cache"})

# Fallback regex for trace directory names: harness_runs is unique and must never appear in harness repo commands; sessions only when reached through `../`
# via `../` or absolute path (e.g., `grep sessions foo` treating sessions as a search term does not trigger).
_TRACE_REF = re.compile(r"harness_runs|role_runs|(?:\.\./|/)[^\s'\"]*sessions(?:/|\b)")

# heredoc start: `<<EOF` / `<<-EOF` / `<< 'PY'` / `<<"END"` (marker is an identifier). Used to strip the body—
# body is data not paths (scanning it causes false positives), but the **redirection target** on the line with `<<` (e.g., `cat > OUT <<EOF`) is a real path, must be kept.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# NexAU local ephemeral directory names (aligned with nexau.archs.platform.path_helpers; used as fallback on import failure).
_BASH_TOOL_RESULTS_DIR = "nexau_bash_tool_results"
_TOOL_OUTPUTS_DIR = "nexau_tool_outputs"


def _nexau_repo_root() -> Path | None:
    """Source repo root where `import nexau` resolves in the current environment (parent of package directory); None on parse failure."""
    try:
        import nexau

        return Path(nexau.__file__).resolve().parents[1]
    except Exception:  # noqa: BLE001  without nexau, restrict access to work_dir only
        return None


def _nexau_runtime_read_roots() -> list[Path]:
    """NexAU framework local ephemeral directory (bash stdout/stderr, verbose tool output)—read-only access allowed.

    Not task trace; agents reading shell results via read_file must be able to read, else jail harms tool environment.
    """
    roots: list[Path] = []
    try:
        from nexau.archs.platform.path_helpers import (
            get_local_bash_tool_results_dir,
            get_local_tool_output_dir,
        )

        roots.extend([get_local_bash_tool_results_dir(), get_local_tool_output_dir()])
    except Exception:  # noqa: BLE001  old nexau / no path_helpers → fallback to tempfile convention
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
    """Read allowlist roots: harness repo + NexAU source + NexAU runtime ephemeral directory."""
    roots = [work_dir]
    nexau_root = _nexau_repo_root()
    if nexau_root is not None:
        roots.append(nexau_root)
    roots.extend(_nexau_runtime_read_roots())
    return roots


def _strip_heredoc_bodies(command: str) -> str:
    """Strip heredoc body (`<<MARKER` through closing `MARKER` line), preserve command/redirection lines.

    Old implementation "if line contains `<<`, skip token scan entirely" also allowed redirection targets (e.g., `cat > /outside/x <<EOF`),
    creating a jail bypass for dev to write harness content to out-of-repo files (observed in practice).
    This only strips the body, keeps the line with `<<MARKER`, so subsequent token scan can catch out-of-bounds redirection targets.
    """
    lines = command.splitlines()
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)  # preserve this line with `<<MARKER` (redirection target is here)
        m = _HEREDOC_RE.search(line)
        if m:
            marker = m.group(2)
            i += 1
            while i < len(lines) and lines[i].strip() != marker:
                i += 1  # discard body lines
            # Skip closing marker line (if present; if absent, i has reached the end)
        i += 1
    return "\n".join(kept)


def _iter_path_values(tool_name: str, parameters: dict[str, Any]):
    """Yield all path-like values in this tool's parameters (str, expanding lists)."""
    for key in _PATH_PARAMS.get(tool_name, ()):
        val = parameters.get(key)
        if isinstance(val, str):
            yield val
        elif isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, str):
                    yield item


def _resolve_against(work_dir: Path, raw: str) -> Path | None:
    """Relative paths are relative to work_dir; return None on parse failure (treated as out-of-bounds)."""
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
    """Whether a raw path, after resolve relative to work_dir, escapes work_dir (including symlinks and `..' normalization). Treat parse failures as out-of-bounds.

    Reserved for unit tests/legacy semantics: only audits work_dir, excluding NexAU read-only root.
    """
    real = _resolve_against(work_dir, raw)
    if real is None:
        return bool(raw.strip())
    return not _inside_any([work_dir], real)


def _escapes_roots(work_dir: Path, roots: list[Path], raw: str) -> bool:
    """Whether, after resolve relative to work_dir, the path is not within any allowed root."""
    real = _resolve_against(work_dir, raw)
    if real is None:
        return bool(raw.strip())
    return not _inside_any(roots, real)


def _shell_offender(work_dir: Path, command: str, read_roots: list[Path]) -> str | None:
    """Return the first out-of-bounds reference in the command (for error reporting); None if absent.

    read_roots: read allowlist roots (including work_dir and optional NexAU). Write redirects to NexAU may still be approved by path tokens
    (static analysis cannot disambiguate read vs. write)—constrained by prompt directive "NexAU read-only"; trace paths are still hard-rejected by _TRACE_REF.
    """
    if _TRACE_REF.search(command):
        return "trace directories (sessions / harness_runs / role_runs)"
    # Strip the body but keep redirection lines to block the `> /outside <<EOF` bypass.
    scanned = _strip_heredoc_bodies(command)
    try:
        tokens = shlex.split(scanned, posix=True)
    except ValueError:
        tokens = scanned.split()
    for tok in tokens:
        # Remove redirect operator prefix (>path / >>path / <path / <<MARKER)
        t = tok.strip().lstrip("<>")
        if "/" not in t and t != "..":  # Audit only path-like tokens
            continue
        if _escapes_roots(work_dir, read_roots, t):
            return t
    return None


class WorkspaceJailMiddleware(Middleware):
    """Harness repo is readable/writable; NexAU source code + runtime temp directory are read-only approved; trace and other paths are all rejected."""

    def wrap_tool_call(
        self,
        params: ToolCallParams,
        call_next: Callable[[ToolCallParams], Any],
    ) -> Any:
        sandbox = params.sandbox
        work_dir_raw = getattr(sandbox, "work_dir", None) if sandbox is not None else None
        # No sandbox/work_dir: cannot determine; allow (preserves existing behavior)
        if work_dir_raw is None:
            return call_next(params)
        try:
            work_dir = Path(str(work_dir_raw)).resolve()
        except (OSError, RuntimeError, ValueError):
            return call_next(params)

        # Artifact-owned exports use the same file tools. The provider restricts
        # reads/searches to the invocation's declared files and audits accesses;
        # source/workspace access continues through the existing jail below.
        from ahe_beta.demand.observation_provider import current_observation_provider

        observations = current_observation_provider()
        if observations is not None:
            result = observations.handle_file_tool(
                tool=params.tool_name, parameters=params.parameters, work_dir=work_dir
            )
            if result is not None:
                return result

        read_roots = _read_roots_for(work_dir)

        tool = params.tool_name
        if tool in _PATH_PARAMS:
            if current_usage_context().role == "triager":
                for raw in _iter_path_values(tool, params.parameters):
                    path = _resolve_against(work_dir, raw)
                    if path is not None and path.is_relative_to(work_dir):
                        parts = path.relative_to(work_dir).parts
                        if any(part in _TRIAGE_RUNTIME_DIRS for part in parts):
                            return self._deny(f"triage runtime directory {raw!r}")
            roots = [work_dir] if tool in _WRITE_TOOLS else read_roots
            for raw in _iter_path_values(tool, params.parameters):
                if _escapes_roots(work_dir, roots, raw):
                    return self._deny(f"{tool} target path {raw!r}")
        elif tool == _SHELL_TOOL:
            command = params.parameters.get("command")
            if isinstance(command, str):
                offender = _shell_offender(work_dir, command, read_roots)
                if offender is not None:
                    return self._deny(f"command references {offender}")

        return call_next(params)

    @staticmethod
    def _deny(what: str) -> dict[str, Any]:
        msg = (
            f"[workspace-jail] Denied: {what} is outside the allowed scope. "
            "Writable scope = harness repository; readable scope = harness repository + NexAU "
            "source (read-only) + NexAU runtime temporary directories (bash/tool output, read-only). "
            "Never read task traces or session recordings (data/sessions, data/harness_runs, "
            "data/role_runs): doing so risks overfitting. Read NexAU for framework details; "
            "apply changes only in the harness repository."
        )
        logger.warning("workspace-jail blocked out-of-bounds access: %s", what)
        return {
            "content": msg,
            "returnDisplay": "Access denied (outside workspace).",
            "error": {"message": msg, "type": "WORKSPACE_JAIL_DENIED"},
        }
