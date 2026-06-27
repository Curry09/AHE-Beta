"""多 agent 活动注册表（流式观测）：各 agent（用户/开发者/测试）的实时状态写到 data/live/agents.json。

与权威 SessionStore 解耦，是易失观测投影。每个 agent 一个槽（按 agent_id），互不覆盖；看板按 role
分组、折叠展示，running 标志表示是否正在跑。原子写（temp+replace）避免读进程读到半成品。
一轮 run 开始时 clear_agents 清空。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_AGENTS_NAME = "agents.json"
# role 展示顺序：用户在前、开发者在后。
_ROLE_ORDER = {"user": 0, "developer": 1}


def _agents_file(*, data_dir: Path) -> Path:
    return Path(data_dir) / "live" / _AGENTS_NAME


def _read_raw(*, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def update_agent(
    *,
    data_dir: Path,
    agent_id: str,
    role: str,
    label: str,
    running: bool,
    status: str,
    turns: list[dict[str, Any]] | None = None,
    detail: str | None = None,
) -> None:
    """更新某 agent 的活动槽（upsert）。turns 给会话型 agent，detail 给开发者展开内容。"""
    path = _agents_file(data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry = _read_raw(path=path)
    prev = registry.get(agent_id, {})
    now = datetime.now().isoformat()
    # started_at = 本段活动起始：刚由空闲转为 running（或新 agent）时重置，否则沿用，供前端算运行时长。
    became_running = running and not prev.get("running", False)
    started_at = now if became_running or not prev.get("started_at") else prev["started_at"]
    registry[agent_id] = {
        "agent_id": agent_id,
        "role": role,
        "label": label,
        "running": running,
        "status": status,
        "turns": turns or [],
        "detail": detail,
        "started_at": started_at,
        "updated_at": now,
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # 原子替换，读进程不会看到半成品


def read_agents(*, data_dir: Path) -> list[dict[str, Any]]:
    """返回所有 agent 活动，按 role（用户在前）再 agent_id 排序。"""
    registry = _read_raw(path=_agents_file(data_dir=data_dir))
    return sorted(
        registry.values(),
        key=lambda a: (_ROLE_ORDER.get(a.get("role"), 9), a.get("agent_id", "")),
    )


def clear_agents(*, data_dir: Path) -> None:
    """清空注册表（一轮 run 开始时调用）。幂等。"""
    _agents_file(data_dir=data_dir).unlink(missing_ok=True)
