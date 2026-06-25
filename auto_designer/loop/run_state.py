"""run_state（spec-0004/T1）：编排游标 + 三侧中间态标记，作为「无法从产物观测」之外的兜底。

能从产物（session 文件、分支 head、tag 存在）推断的进度优先推断；run_state 只记不可观测的游标与分派。
JSON、原子写。空 STATE_DIR 读 → 初始 RunState(round=0)。
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
    """轮次/阶段/当前 release_ref + 用户侧已完成 session、开发者侧 issue 分派、编排瞬态。"""

    round: int = 0
    phase: str = "a"
    current_release_ref: str = ""
    done_session_keys: list[str] = field(default_factory=list)
    issue_assignments: dict[str, str] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
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
    """读 STATE_DIR/run_state.json；缺失 → 初始 RunState(round=0)，不抛错。"""
    path = run_state_path(state_dir)
    if not path.is_file():
        return RunState()
    return RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))


def write_run_state(state_dir: Path, run_state: RunState) -> None:
    """原子写 run_state.json（tmp + os.replace），避免中途死留半截。"""
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    path = run_state_path(state_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(run_state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
