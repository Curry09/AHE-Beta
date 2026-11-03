"""Inner-layer user agent's atomic tools + D1 capability gating (spec-0008/T2).

Atomic tools (indivisible, composable):
- read_file(sandbox, path)         read file
- run_shell(sandbox, cmd, timeout) run command in sandbox cwd
- write_file(sandbox, path, content) write file (high capability tier only: can write test scripts)
- report_issue(sandbox, body)      mid-session record one issue (does not end conversation; actual write intercepted by agentic client)
- web_search(query)                placeholder, not implemented this round

"Running tests / constructing edge cases" are emergent composite behaviors from "atomic tools + LLM reasoning", not standalone tools.
Tool set gated by persona D1 mechanical control (tool_stack): gating occurs at "expose which tools to LLM" layer,
not prompt self-discipline. Mapping aligns with spec-0005 cap_mask (read_code/run_once/run_tests/review_diff) origin.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dimensions import D1Eval, Persona

if TYPE_CHECKING:
    from .sandbox import Sandbox


# --------------------------------------------------------------------------
# Atomic tools (unified return format {ok, ...})
# --------------------------------------------------------------------------
def read_file(sandbox: Sandbox, path: str) -> dict:
    try:
        return {"ok": True, "content": sandbox.read_text(path)}
    except Exception as e:  # noqa: BLE001 — tool layer converts any failure to structured result, never crashes inner loop
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
    """Placeholder: real note-taking is intercepted by AgenticPersonaClient._dispatch; direct calls will fail."""
    return {"ok": False, "error": "report_issue requires agentic client dispatch"}


def web_search(query: str) -> dict:
    """Placeholder: not implemented this cycle; always returns unimplemented."""
    return {"ok": False, "error": "not_implemented"}


# --------------------------------------------------------------------------
# Tool spec + D1 gating
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolSpec:
    """For T3 to render into prompt (name/description/args); for T4 to dispatch by name (fn)."""

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

# Gating mapping (same origin as cap_mask):
#   blind                 -> []                 (text only, no verification)
#   shallow               -> read_file,run_shell + report_issue
#   competent / expert    -> + write_file
# report_issue not tied to verification capability: anyone with tool stack can record mid-session; allows idling, not prompt-driven.
_STACK: dict[D1Eval, list[ToolSpec]] = {
    D1Eval.BLIND: [],
    D1Eval.SHALLOW: [READ_FILE, RUN_SHELL, REPORT_ISSUE],
    D1Eval.COMPETENT: [READ_FILE, RUN_SHELL, WRITE_FILE, REPORT_ISSUE],
    D1Eval.EXPERT: [READ_FILE, RUN_SHELL, WRITE_FILE, REPORT_ISSUE],
}


def tool_stack(persona: Persona) -> list[ToolSpec]:
    """Provide available tool subset by persona's D1 (web_search excluded from stack: placeholder, never truly enabled)."""
    return list(_STACK[persona.d1])


def review_tool_stack(persona: Persona) -> list[ToolSpec]:
    """Spec-0084/T2: reviewer capabilities are independent of authoring tools."""
    return [] if persona.d1 is D1Eval.BLIND else [READ_FILE, LIST_FILES, READ_DIFF]
