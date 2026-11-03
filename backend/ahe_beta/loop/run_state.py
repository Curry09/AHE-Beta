"""run_state (spec-0004/T1): orchestration cursor + three-side intermediate state markers, as fallback beyond "unobservable from artifacts".

Progress observable from artifacts (session files, main HEAD, tag existence) takes priority; run_state only records unobservable cursors and dispatch.
JSON, atomic write. Empty STATE_DIR read → initial RunState(round=0).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_RUN_STATE_FILE = "run_state.json"


@dataclass
class RunState:
    """Round/phase/current main SHA + user-side completed sessions, developer-side issue dispatch, orchestration transient state.

    Spec-0007/T2: after pure trunk, `current_release_ref` field name retained, semantics changed to "current main HEAD SHA"—
    pure observation cursor (main latest SHA parsed by orchestrator at round end), no longer a release version number, does not participate in parsing.
    """

    schema_version: int = 1
    recovery_revision: int = 0
    round: int = 0
    phase: str = "a"
    # Spec-0007/T2: semantics = current main HEAD SHA (observation cursor)
    current_release_ref: str = ""
    done_session_keys: list[str] = field(default_factory=list)
    issue_assignments: dict[str, str] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "recovery_revision": self.recovery_revision,
            "round": self.round,
            "phase": self.phase,
            "current_release_ref": self.current_release_ref,
            "done_session_keys": list(self.done_session_keys),
            "issue_assignments": dict(self.issue_assignments),
            "pending": list(self.pending),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            recovery_revision=int(data.get("recovery_revision", 0)),
            round=data.get("round", 0),
            phase=data.get("phase", "a"),
            current_release_ref=data.get("current_release_ref", ""),
            done_session_keys=list(data.get("done_session_keys", [])),
            issue_assignments=dict(data.get("issue_assignments", {})),
            pending=list(data.get("pending", [])),
        )


def run_state_path(state_dir: Path) -> Path:
    return Path(state_dir) / _RUN_STATE_FILE


def read_run_state(state_dir: Path) -> RunState:
    """Read STATE_DIR/run_state.json; if missing → initial RunState(round=0), do not raise."""
    path = run_state_path(state_dir)
    if not path.is_file():
        return RunState()
    return RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_run_state(state_dir: Path, run_state: RunState) -> None:
    """Atomic write run_state.json (tmp + os.replace) to avoid leaving half-written on interruption."""
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    path = run_state_path(state_dir)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(run_state.to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
