"""Stream each agent's runtime state to the multi-agent activity registry in data/live/.

Decoupled from authoritative SessionStore, is volatile observation projection. Three files:
- agents.json: one slot per agent (by agent_id), running flag + structured process flow log (status changes,
  assistant utterances, tool calls/results, entries like {t, kind, text}).
- run.json: run-wide runtime state (running / current round / total_rounds / each round main SHA).
- history.json: completed work items archived by round (append-only)—agent slots overwritten each round, archiving enables
  "retrospective view of completed state per round".

Atomic write (temp+replace) prevents read process from seeing incomplete artifacts. Fresh run clears; resume preserves history and corrects interrupted slots.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_AGENTS_NAME = "agents.json"
_RUN_NAME = "run.json"
_HISTORY_NAME = "history.json"
# role display order: user → triage → divergent → architect → owner → developer
# (aligned three-plane loop a → first beat (triage∥divergent) → second beat (architect) → owner gate → b, Spec-0029).
_ROLE_ORDER = {
    "user": 0,
    "triager": 1,
    "divergent": 2,
    "architect": 3,
    "owner": 4,
    "developer": 5,
}
# process flow timeline length limit: status changes + assistant utterances + each tool call/result, one agent.run can reach hundreds of entries.
_LOG_CAP = 500

# Spec-0017/T1: module-level single lock wrapping the entire "read-modify-write" sequence of all write functions. mkstemp atomic write only prevents torn writes,
# not two writers based on the same old snapshot overwriting each other (lost updates/lost slots)—after multi-user sessions in segment a,
# multiple session threads simultaneously call update_agent/append_agent_log/archive_agent. Lock granularity = entire single-file operation (pure local file IO,
# no network/subprocess wait while holding, no deadlock surface); read functions unlocked (atomic replace guarantees read always gets complete snapshot).
_WRITE_LOCK = threading.Lock()


def _live_file(*, data_dir: Path, name: str) -> Path:
    return Path(data_dir) / "live" / name


def _read_json(*, path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    # errors="replace": the harness may emit invalid UTF-8 bytes; fault-tolerant reading recovers rather than crashes observations (lossy projection, fallback on corruption).
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError, ValueError):
        return fallback


def _write_atomic(*, path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temporary name (mkstemp) + atomic replace: concurrent writers (dev tracer and status callbacks may write across threads simultaneously) never
    # share the same .tmp or interleave bytes; encode errors="replace" catches invalid characters and prevents writing corrupted bytes.
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8", errors="replace")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        # Atomic replace ensures reading processes never see incomplete files.
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---- agents.json: agent activity slots ----


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
    meta: dict[str, Any] | None = None,
) -> None:
    """Update an agent's activity slot (upsert). turns applies to conversational agents, detail to final reports for dev/architect,
    round_no marks which round this activity belongs to (basis for frontend grouping by round).

    meta (Spec-0026/T1): optional read-only display payload (e.g., user agent persona summary identity/level/domain/goal)—
    for frontend display only, does not participate in any decision; when omitted, carries forward from prior instance (sticky semantics within same round), legacy calls default to None without error."""
    with _WRITE_LOCK:  # Spec-0017/T1: read-modify-write held under lock throughout; concurrent upserts to different slots do not overwrite each other
        path = _live_file(data_dir=data_dir, name=_AGENTS_NAME)
        registry = _read_json(path=path, fallback={})
        prev = registry.get(agent_id, {})
        now = datetime.now().isoformat()
        # started_at = activity start time: resets when transitioning from idle to running (or new agent), otherwise carries forward; used by frontend to compute runtime.
        became_running = running and not prev.get("running", False)
        started_at = now if became_running or not prev.get("started_at") else prev["started_at"]
        # log = process flow timeline: appended when status changes (consecutive duplicates deduplicated), accumulated across tasks, capped at _LOG_CAP.
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
            "meta": meta if meta is not None else prev.get("meta"),
            "turns": turns or [],
            "detail": detail,
            "log": log,
            "started_at": started_at,
            "updated_at": now,
        }
        _write_atomic(path=path, data=registry)


def append_agent_log(*, data_dir: Path, agent_id: str, text: str, kind: str = "step") -> None:
    """Append an entry to an agent's process flow timeline (assistant utterance / tool invocation / tool result, etc.).

    Does not modify status/turns or other fields; updated_at is always refreshed. If agent slot does not exist, no-op (step must occur after
    update_agent creates the slot; do not create partial orphan slots). Consecutive duplicates are deduplicated, capped at _LOG_CAP.
    """
    with _WRITE_LOCK:  # Spec-0017/T1: concurrent appends do not lose entries
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
    """Return all agent activities, sorted by role (users first) then agent_id."""
    registry = _read_json(path=_live_file(data_dir=data_dir, name=_AGENTS_NAME), fallback={})
    return sorted(
        registry.values(),
        key=lambda a: (_ROLE_ORDER.get(a.get("role"), 9), a.get("agent_id", "")),
    )


# ---- run.json: run execution state ----


def update_live_run(
    *,
    data_dir: Path,
    running: bool,
    round_no: int,
    total_rounds: int,
    round_shas: list[str] | None = None,
    phase: str | None = None,
    blocked_issues: list[int] | None = None,
) -> None:
    """Update run execution state. round_shas / phase / blocked_issues retain their existing values if omitted.

    Spec-0050/T4: phase ∈ users/demand/delivery_wait/blocked/done.
    """
    # Spec-0017/T1: prev snapshot and write-back are not interleaved by other writers
    with _WRITE_LOCK:
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
                "phase": phase if phase is not None else prev.get("phase", ""),
                "blocked_issues": (
                    blocked_issues if blocked_issues is not None else prev.get("blocked_issues", [])
                ),
                "started_at": prev.get("started_at") or now,
                "updated_at": now,
            },
        )


def read_live_run(*, data_dir: Path) -> dict[str, Any]:
    """Return run execution state; if never run, return idle defaults."""
    fallback = {
        "running": False,
        "round": 0,
        "total_rounds": 0,
        "round_shas": [],
        "phase": "",
        "blocked_issues": [],
        "started_at": None,
        "updated_at": None,
    }
    return _read_json(path=_live_file(data_dir=data_dir, name=_RUN_NAME), fallback=fallback)


# ---- history.json: completed work items archived by round ----


def archive_agent(
    *,
    data_dir: Path,
    agent_id: str,
    round_no: int,
    extra: dict[str, Any],
) -> None:
    """Archive current slot snapshot of an agent plus extra as a completed work item (append-only).

    The slot is overwritten each round; archival occurs when an agent's activity phase ends (running=False), capturing full snapshot of label/role/status/
    log/turns/detail for frontend "completed · grouped by round" review. extra must contain at least kind
    (user_session/architect_run/dev_run) and role-specific fields (session_id/issue_number/tag…).
    If slot does not exist, no-op (no activity to archive).
    """
    with _WRITE_LOCK:  # Spec-0017/T1: history read-append-write held under lock throughout; concurrent archival does not lose entries
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
        if record.get("kind") == "user_session" and record.get("session_id"):
            history = [
                item
                for item in history
                if not (
                    item.get("kind") == "user_session"
                    and item.get("session_id") == record["session_id"]
                )
            ]
        history.append(record)
        _write_atomic(path=path, data=history)


def read_history(*, data_dir: Path) -> list[dict[str, Any]]:
    """Return all archived work items (naturally ordered by archive time)."""
    history = _read_json(path=_live_file(data_dir=data_dir, name=_HISTORY_NAME), fallback=[])
    return history if isinstance(history, list) else []


# ---- Cleanup ----


def clear_live(*, data_dir: Path) -> None:
    """Clear live observation projections (agents/run/history all). Called at start of each run. Idempotent."""
    with _WRITE_LOCK:  # Spec-0017/T1: mutually exclusive with in-flight writers; clearing does not interleave to produce half-old-half-new state
        for name in (_AGENTS_NAME, _RUN_NAME, _HISTORY_NAME):
            _live_file(data_dir=data_dir, name=name).unlink(missing_ok=True)


def prepare_live_resume(*, data_dir: Path, phase: str) -> None:
    """Preserve live/history while making stale in-process activity explicit."""
    with _WRITE_LOCK:
        now = datetime.now().isoformat()
        agents_path = _live_file(data_dir=data_dir, name=_AGENTS_NAME)
        registry = _read_json(path=agents_path, fallback={})
        if not isinstance(registry, dict):
            registry = {}
        for slot in registry.values():
            if not isinstance(slot, dict) or not slot.get("running"):
                continue
            slot["running"] = False
            slot["status"] = "Previous process interrupted; waiting for recovery reconciliation"
            slot["updated_at"] = now
            log = list(slot.get("log") or [])
            if not log or log[-1].get("text") != slot["status"]:
                log.append({"t": now, "kind": "status", "text": slot["status"]})
            slot["log"] = log[-_LOG_CAP:]
        _write_atomic(path=agents_path, data=registry)

        run_path = _live_file(data_dir=data_dir, name=_RUN_NAME)
        run = _read_json(path=run_path, fallback={})
        if not isinstance(run, dict):
            run = {}
        run.setdefault("round", 0)
        run.setdefault("total_rounds", 0)
        run.setdefault("round_shas", [])
        run.setdefault("blocked_issues", [])
        run.update(running=True, phase=f"recovering:{phase}", updated_at=now)
        run.setdefault("started_at", now)
        _write_atomic(path=run_path, data=run)
