"""进行中会话的实时通道（流式观测）：把当前正在跑的一局逐轮写到 data/live/current.json。

与权威 SessionStore 解耦：live 是易失的观测投影（一局跑完即清），不参与「失败局不留半成品」的
权威落盘语义。看板单独轮询 read_live 渲染流式对话；末轮为 user 即表示 harness 尚在回复中。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

_LIVE_NAME = "current.json"


def _live_file(*, data_dir: Path) -> Path:
    return Path(data_dir) / "live" / _LIVE_NAME


def write_live(
    *, data_dir: Path, persona_identity: str, scenario: str, turns: list[dict[str, Any]]
) -> None:
    """覆盖写当前进行中会话快照（含已产出的逐轮 turns）。"""
    path = _live_file(data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "active": True,
                "persona_identity": persona_identity,
                "scenario": scenario,
                "turns": turns,
                "updated_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def read_live(*, data_dir: Path) -> dict[str, Any]:
    """读当前进行中会话；无/损坏则返回 {"active": False}。"""
    path = _live_file(data_dir=data_dir)
    if not path.exists():
        return {"active": False}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active": False}


def clear_live(*, data_dir: Path) -> None:
    """一局结束后清除 live 快照（幂等）。"""
    path = _live_file(data_dir=data_dir)
    path.unlink(missing_ok=True)
