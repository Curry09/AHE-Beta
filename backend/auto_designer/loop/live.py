"""多 agent 活动注册表（流式观测）：各 agent（用户/创新者/开发者）的实时状态写到 data/live/。

与权威 SessionStore 解耦，是易失观测投影。三个文件：
- agents.json：每个 agent 一个槽（按 agent_id），running 标志 + 结构化过程流 log（status 变化、
  assistant 发言、工具调用/结果，条目形如 {t, kind, text}）。
- run.json：整条 run 的运行态（running / 当前轮 round / total_rounds / 各轮 main SHA）。
- history.json：按轮归档的已完成工作项（append-only）——agent 槽位每轮被覆盖，归档让
  「已完成状态按轮回看」成为可能。

原子写（temp+replace）避免读进程读到半成品。一轮 run 开始时 clear_live 全部清空。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

_AGENTS_NAME = "agents.json"
_RUN_NAME = "run.json"
_HISTORY_NAME = "history.json"
# role 展示顺序：用户 → 创新者 → 开发者（对齐闭环 a → d → b 的次序）。
_ROLE_ORDER = {"user": 0, "designer": 1, "developer": 2}
# 过程流时间线长度上限：status 变化 + assistant 发言 + 逐工具调用/结果，一次 agent.run 可达数百条。
_LOG_CAP = 500


def _live_file(*, data_dir: Path, name: str) -> Path:
    return Path(data_dir) / "live" / name


def _read_json(*, path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    # errors="replace"：harness 可能吐非法 UTF-8 字节，容错读回而非炸掉观测（易失投影，坏了就回落）。
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError, ValueError):
        return fallback


def _write_atomic(*, path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 唯一临时名（mkstemp）+ 原子 replace：并发写者（dev tracer 与 status 回调可能跨线程同时写）绝不
    # 共用同一 .tmp 而相互串字节；encode errors="replace" 兜底非法字符，杜绝写出坏字节。
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8", errors="replace")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp_name, path)  # 原子替换，读进程不会看到半成品
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---- agents.json：agent 活动槽 ----


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
    round_no: int | None = None,
) -> None:
    """更新某 agent 的活动槽（upsert）。turns 给会话型 agent，detail 给 dev/designer 最终报告，
    round_no 标注该活动属于第几轮（前端按轮分组的依据）。"""
    path = _live_file(data_dir=data_dir, name=_AGENTS_NAME)
    registry = _read_json(path=path, fallback={})
    prev = registry.get(agent_id, {})
    now = datetime.now().isoformat()
    # started_at = 本段活动起始：刚由空闲转为 running（或新 agent）时重置，否则沿用，供前端算运行时长。
    became_running = running and not prev.get("running", False)
    started_at = now if became_running or not prev.get("started_at") else prev["started_at"]
    # log = 过程流时间线：status 变化即追加（连续重复去重），跨任务累计、封顶 _LOG_CAP。
    log = list(prev.get("log", []))
    if not log or log[-1].get("text") != status:
        log.append({"t": now, "kind": "status", "text": status})
    log = log[-_LOG_CAP:]
    registry[agent_id] = {
        "agent_id": agent_id,
        "role": role,
        "label": label,
        "running": running,
        "status": status,
        "round": round_no if round_no is not None else prev.get("round"),
        "turns": turns or [],
        "detail": detail,
        "log": log,
        "started_at": started_at,
        "updated_at": now,
    }
    _write_atomic(path=path, data=registry)


def append_agent_log(*, data_dir: Path, agent_id: str, text: str, kind: str = "step") -> None:
    """往某 agent 的过程流时间线追加一条（assistant 发言 / 工具调用 / 工具结果等）。

    不动 status/turns 等其余字段，updated_at 照刷。agent 槽不存在则 no-op（步骤必然发生在
    update_agent 建槽之后；不为孤儿步骤造半空槽）。连续重复去重，同 _LOG_CAP 封顶。
    """
    path = _live_file(data_dir=data_dir, name=_AGENTS_NAME)
    registry = _read_json(path=path, fallback={})
    slot = registry.get(agent_id)
    if slot is None:
        return
    log = list(slot.get("log", []))
    if log and log[-1].get("text") == text:
        return
    now = datetime.now().isoformat()
    log.append({"t": now, "kind": kind, "text": text})
    slot["log"] = log[-_LOG_CAP:]
    slot["updated_at"] = now
    _write_atomic(path=path, data=registry)


def read_agents(*, data_dir: Path) -> list[dict[str, Any]]:
    """返回所有 agent 活动，按 role（用户在前）再 agent_id 排序。"""
    registry = _read_json(path=_live_file(data_dir=data_dir, name=_AGENTS_NAME), fallback={})
    return sorted(
        registry.values(),
        key=lambda a: (_ROLE_ORDER.get(a.get("role"), 9), a.get("agent_id", "")),
    )


# ---- run.json：整条 run 的运行态 ----


def update_live_run(
    *,
    data_dir: Path,
    running: bool,
    round_no: int,
    total_rounds: int,
    round_shas: list[str] | None = None,
) -> None:
    """更新 run 运行态。round_shas 不传则沿用已有值（各轮结束时才追加 SHA）。"""
    path = _live_file(data_dir=data_dir, name=_RUN_NAME)
    prev = _read_json(path=path, fallback={})
    now = datetime.now().isoformat()
    _write_atomic(
        path=path,
        data={
            "running": running,
            "round": round_no,
            "total_rounds": total_rounds,
            "round_shas": round_shas if round_shas is not None else prev.get("round_shas", []),
            "started_at": prev.get("started_at") or now,
            "updated_at": now,
        },
    )


def read_live_run(*, data_dir: Path) -> dict[str, Any]:
    """返回 run 运行态；从未跑过则给静止缺省。"""
    fallback = {
        "running": False,
        "round": 0,
        "total_rounds": 0,
        "round_shas": [],
        "started_at": None,
        "updated_at": None,
    }
    return _read_json(path=_live_file(data_dir=data_dir, name=_RUN_NAME), fallback=fallback)


# ---- history.json：按轮归档的已完成工作项 ----


def archive_agent(
    *,
    data_dir: Path,
    agent_id: str,
    round_no: int,
    extra: dict[str, Any],
) -> None:
    """把某 agent 当前槽位快照 + extra 归档为一条已完成工作项（append-only）。

    槽位每轮被覆盖，归档发生在该 agent 一段活动收尾（running=False）时，把 label/role/status/
    log/turns/detail 全量快照下来，供前端「已完成 · 按轮分组」回看。extra 至少含 kind
    （user_session/designer_run/dev_run）与各角色专属字段（session_id/issue_number/tag…）。
    槽不存在则 no-op（无活动可归档）。
    """
    registry = _read_json(path=_live_file(data_dir=data_dir, name=_AGENTS_NAME), fallback={})
    slot = registry.get(agent_id)
    if slot is None:
        return
    record: dict[str, Any] = {
        "round": round_no,
        "agent_id": agent_id,
        "role": slot.get("role"),
        "label": slot.get("label"),
        "status": slot.get("status"),
        "turns": slot.get("turns", []),
        "detail": slot.get("detail"),
        "log": slot.get("log", []),
        "started_at": slot.get("started_at"),
        "archived_at": datetime.now().isoformat(),
        **extra,
    }
    path = _live_file(data_dir=data_dir, name=_HISTORY_NAME)
    history = _read_json(path=path, fallback=[])
    if not isinstance(history, list):
        history = []
    history.append(record)
    _write_atomic(path=path, data=history)


def read_history(*, data_dir: Path) -> list[dict[str, Any]]:
    """返回全部已归档工作项（按归档先后自然有序）。"""
    history = _read_json(path=_live_file(data_dir=data_dir, name=_HISTORY_NAME), fallback=[])
    return history if isinstance(history, list) else []


# ---- 清理 ----


def clear_live(*, data_dir: Path) -> None:
    """清空 live 观测投影（agents/run/history 全部）。一轮 run 开始时调用。幂等。"""
    for name in (_AGENTS_NAME, _RUN_NAME, _HISTORY_NAME):
        _live_file(data_dir=data_dir, name=name).unlink(missing_ok=True)
