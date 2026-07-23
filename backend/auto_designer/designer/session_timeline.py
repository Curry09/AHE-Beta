"""设计师按需取用 session 上帝视角时间线。

暂时原样投影落盘的 sim_trace（不做脱敏/抽象）；权威仍是 Session JSON（按需取用，非整包注入）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from auto_designer.models import Session
from auto_designer.user.session_store import SessionStore

_STORE: ContextVar[SessionStore | None] = ContextVar("designer_session_store", default=None)


@contextmanager
def bind_session_store(store: SessionStore) -> Iterator[None]:
    """在 Designer._run_agent 期间注入 SessionStore，供 tool 读取。"""
    token = _STORE.set(store)
    try:
        yield
    finally:
        _STORE.reset(token)


def _require_store() -> SessionStore:
    store = _STORE.get()
    if store is None:
        raise RuntimeError("session store not bound; call within Designer.run")
    return store


def format_session_timeline(session: Session) -> str:
    """Session → 落盘 god-view 原样 JSON 文本（feeling / issue_refs / sim_trace）。"""
    payload: dict[str, Any] = {
        "session_id": session.session_id,
        "created_at": session.created_at.isoformat(),
        "feeling": session.feeling.to_dict(),
        "issue_refs": [r.to_dict() for r in session.issue_refs],
        "sim_trace": session.sim_trace.to_dict() if session.sim_trace is not None else None,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def find_session_by_id(store: SessionStore, session_id: str) -> Session | None:
    sid = session_id.strip()
    if not sid:
        return None
    try:
        return store.load(sid)
    except FileNotFoundError:
        return None


def find_session_by_issue(store: SessionStore, issue_number: int) -> Session | None:
    """按 issue 号反查：先看 index.issue_numbers，再扫全量（兼容旧 index）。"""
    n = int(issue_number)
    for entry in reversed(store.index()):
        nums = entry.get("issue_numbers") or []
        if n in nums:
            found = find_session_by_id(store, str(entry.get("session_id", "")))
            if found is not None:
                return found
    for entry in reversed(store.index()):
        sid = str(entry.get("session_id", ""))
        sess = find_session_by_id(store, sid)
        if sess is None:
            continue
        if any(r.number == n for r in sess.issue_refs):
            return sess
    return None


def get_session_timeline(
    issue_number: int | None = None,
    session_id: str | None = None,
    agent_state: Any = None,  # noqa: ARG001 — nexau 注入，未用
) -> dict[str, Any]:
    """设计师 tool：按 issue 或 session_id 取落盘 god-view（暂不脱敏）。

    须在 bind_session_store(...) 内调用。两个参数至少提供一个；都给时以 session_id 为准。
    """
    del agent_state
    try:
        store = _require_store()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    sid = (session_id or "").strip() or None
    session: Session | None = None
    if sid is not None:
        session = find_session_by_id(store, sid)
        if session is None:
            return {"ok": False, "error": f"session not found: {sid}"}
    elif issue_number is not None:
        session = find_session_by_issue(store, int(issue_number))
        if session is None:
            return {
                "ok": False,
                "error": f"no session linked to issue #{int(issue_number)}",
            }
    else:
        return {
            "ok": False,
            "error": "provide issue_number or session_id",
        }

    text = format_session_timeline(session)
    return {
        "ok": True,
        "session_id": session.session_id,
        "timeline": text,
    }
