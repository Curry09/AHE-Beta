"""本地 SessionStore（spec-0001/T6）：一局 Session 全量落盘 + 单一总索引。

全量文件 root/<session_id>.json 为唯一权威；索引 root/index.json 是其派生投影（可由全量重建），
承载体感曲线/回归基线所需最小信息及 evaluation_status。invalid 条目保留供审计，但默认 index()
过滤，避免进入正常体感/通过率。先写全量后追加索引。
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import threading
from pathlib import Path

from auto_designer.models import Session

_INDEX_NAME = "index.json"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class SessionConflictError(RuntimeError):
    """A stable session id already points to different immutable content."""


class SessionStore:
    """把 Session 持久化到本地 root/。

    Spec-0017/T1：save 全程持实例锁——index.json 是读-改-写追加，a 段多用户会话并行后
    并发 save 会基于同一旧快照互相覆盖（丢条目）；锁粒度=单次 save 全程（纯本地文件 IO，
    持锁期内无网络/子进程等待，无死锁面）。跨进程并发仍不支持（单进程内多线程即本仓形态）。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        """会话落盘根目录；live 通道据此定位同级 data/live。"""
        return self._root

    def save(self, session: Session) -> None:
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            with (self._root / ".sessions.lock").open("a+b") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX)
                self._save_locked(session=session)

    def _save_locked(self, *, session: Session) -> None:
        _validate_session_id(session.session_id)
        # 先写全量文件（唯一权威），后追加索引：中途失败至多「有全量缺索引」，可重建。
        full_path = self._root / f"{session.session_id}.json"
        body = session.to_dict()
        if full_path.exists():
            try:
                existing = json.loads(full_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SessionConflictError(
                    f"session file is invalid: {session.session_id}"
                ) from exc
            if existing != body:
                if _is_issue_handoff_enrichment(existing=existing, current=body):
                    _atomic_json(full_path, body)
                else:
                    raise SessionConflictError(
                        f"stable session id has different content: {session.session_id}"
                    )
        else:
            _atomic_json(full_path, body)
        entries = self.index(include_invalid=True)
        # Spec-0064/T3: index is an upsert projection.  A crash after the full
        # file and before index publication is repaired without a duplicate row.
        entries = [row for row in entries if row.get("session_id") != session.session_id]
        entries.append(_index_entry(session))
        _atomic_json(self._root / _INDEX_NAME, entries)

    def load(self, session_id: str) -> Session:
        _validate_session_id(session_id)
        full_path = self._root / f"{session_id}.json"
        data = json.loads(full_path.read_text(encoding="utf-8"))  # 不存在则 FileNotFoundError
        return Session.from_dict(data)

    def reconcile(self, session_id: str) -> Session | None:
        """Return a complete session and repair its derived index, or return None."""
        _validate_session_id(session_id)
        full_path = self._root / f"{session_id}.json"
        if not full_path.is_file():
            return None
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            with (self._root / ".sessions.lock").open("a+b") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX)
                session = self.load(session_id)
                if session.session_id != session_id:
                    raise SessionConflictError(f"session identity mismatch: {session_id}")
                entries = self.index(include_invalid=True)
                expected = _index_entry(session)
                matching = [row for row in entries if row.get("session_id") == session_id]
                if matching != [expected]:
                    entries = [row for row in entries if row.get("session_id") != session_id]
                    entries.append(expected)
                    _atomic_json(self._root / _INDEX_NAME, entries)
                return session

    def load_user_feedback_envelope(self, session_id: str) -> dict:
        """Return the persisted 0055 handoff, reconstructing legacy sessions once.

        The fallback is deterministic and deliberately does not mutate the old
        file, so replaying historical sessions remains read-only.
        """
        session = self.load(session_id)
        if session.user_feedback_envelope:
            from auto_designer.designer.evidence_contract import EvidenceEnvelope

            restored = EvidenceEnvelope.from_dict(session.user_feedback_envelope)
            if restored.evidence_categories:
                return restored.to_dict()
            # Early 0055 snapshots did not carry the category index; rebuild
            # from the same persisted session rather than widening visibility.
            from auto_designer.designer.evidence_contract import build_evidence_envelope

            return build_evidence_envelope(session).to_dict()
        from auto_designer.designer.evidence_contract import build_evidence_envelope

        return build_evidence_envelope(session).to_dict()

    def index(self, *, include_invalid: bool = False) -> list[dict]:
        index_path = self._root / _INDEX_NAME
        if not index_path.exists():
            return []  # 首次运行无索引为合法初始态
        rows = json.loads(index_path.read_text(encoding="utf-8"))
        if include_invalid:
            return rows
        # 旧索引没有该字段，按 valid 兼容；正式体感/通过率消费者不接收 evaluator-invalid。
        return [row for row in rows if row.get("evaluation_status", "valid") == "valid"]


def _validate_session_id(session_id: str) -> None:
    if not session_id or not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(f"invalid session id: {session_id!r}")


def _is_issue_handoff_enrichment(*, existing: dict, current: dict) -> bool:
    """Allow the legacy two-step save that only attaches the final issue handoff."""
    old_refs = existing.get("issue_refs") or []
    new_refs = current.get("issue_refs") or []
    if old_refs or not new_refs:
        return False
    old_base = dict(existing)
    new_base = dict(current)
    for key in ("issue_refs", "user_feedback_envelope"):
        old_base.pop(key, None)
        new_base.pop(key, None)
    return old_base == new_base


def _atomic_json(path: Path, value: object) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def _index_entry(session: Session) -> dict:
    evaluation_status = (
        session.sim_trace.evaluation_status if session.sim_trace is not None else "valid"
    )
    return {
        "session_id": session.session_id,
        "score": session.feeling.score,
        "reason": session.feeling.reason,
        "created_at": session.created_at.isoformat(),
        "n_issues": len(session.issue_refs),
        "issue_numbers": [ref.number for ref in session.issue_refs],
        "evaluation_status": evaluation_status,
        "interaction_status": (
            getattr(session.sim_trace, "interaction_status", "completed")
            if session.sim_trace is not None
            else "completed"
        ),
        "user_outcome": (session.user_outcome or {}).get("end_reason"),
        "accept_validity": session.accept_validity,
        "objective_passed": (session.objective_evaluation or {}).get("passed"),
        "goal_audit_status": (
            (session.sim_trace.goal_audit or {}).get("status")
            if session.sim_trace is not None
            else None
        ),
        "baseline_revision_count": (
            (session.sim_trace.goal_ledger or {}).get("baseline_revision_count", 0)
            if session.sim_trace is not None
            else 0
        ),
        "unresolved_goal_ids": (
            list((session.sim_trace.goal_ledger or {}).get("unresolved") or [])
            if session.sim_trace is not None
            else []
        ),
    }
