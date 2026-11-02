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
import uuid
from pathlib import Path

from ahe_beta.models import Session, bound_session_provenance, validate_session_provenance

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
        self._assessment_root: Path | None = None

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
        validate_session_provenance(session, bound_session_provenance())
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

    def reconcile(
        self, session_id: str, *, expected_provenance: dict | None = None
    ) -> Session | None:
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
                validate_session_provenance(session, expected_provenance)
                entries = self.index(include_invalid=True)
                expected = _index_entry(session)
                matching = [row for row in entries if row.get("session_id") == session_id]
                if matching != [expected]:
                    entries = [row for row in entries if row.get("session_id") != session_id]
                    entries.append(expected)
                    _atomic_json(self._root / _INDEX_NAME, entries)
                return session

    def stage_actor(self, session_id: str, *, provenance: dict, payload: dict) -> dict:
        """Keep completed Actor output separate from complete, publishable Sessions."""
        return self._stage_actor_part(
            session_id=session_id, part="actor", provenance=provenance, payload=payload
        )

    def stage_actor_capture(self, session_id: str, *, provenance: dict, payload: dict) -> dict:
        """Commit immutable frozen bytes before cleanup or any terminal reviewer call."""
        if self.load_actor_checkpoint(session_id, expected_provenance=provenance) is None:
            raise SessionConflictError("Actor capture has no completed Actor checkpoint")
        return self._stage_actor_part(
            session_id=session_id, part="capture", provenance=provenance, payload=payload
        )

    def load_actor_checkpoint(
        self, session_id: str, *, expected_provenance: dict | None = None
    ) -> dict | None:
        return self._load_actor_part(
            session_id=session_id, part="actor", expected_provenance=expected_provenance
        )

    def load_actor_capture(
        self, session_id: str, *, expected_provenance: dict | None = None
    ) -> dict | None:
        return self._load_actor_part(
            session_id=session_id, part="capture", expected_provenance=expected_provenance
        )

    def record_actor_capture_failure(
        self, session_id: str, *, provenance: dict, evidence: dict, error: str
    ) -> None:
        """Diagnostic attempts are not complete Sessions and never enter the feedback index."""
        if self.load_actor_checkpoint(session_id, expected_provenance=provenance) is None:
            raise SessionConflictError("Capture failure has no completed Actor")
        directory = self._root / "actor-checkpoints" / f"{session_id}.failures"
        if any(path.is_symlink() for path in (directory, *directory.parents)):
            raise SessionConflictError("Linked Actor capture diagnostics")
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / f"{uuid.uuid4().hex}.json"
        _atomic_json(
            path,
            {
                "session_id": session_id,
                "provenance": provenance,
                "error": error,
                "evidence": {
                    key: evidence[key]
                    for key in (
                        "actor_freeze",
                        "evaluation_artifacts",
                        "prediction_error",
                        "review_snapshot",
                    )
                    if key in evidence
                },
            },
        )
        path.chmod(0o600)

    def _stage_actor_part(self, *, session_id: str, part: str, provenance: dict, payload: dict):
        from ahe_beta.execution_contract import canonical_sha256

        _validate_session_id(session_id)
        packet = {
            "version": 1,
            "session_id": session_id,
            "provenance": dict(provenance),
            "payload": payload,
            "sha256": canonical_sha256(payload),
        }
        with self._lock:
            directory = self._root / "actor-checkpoints"
            if any(path.is_symlink() for path in (directory, *directory.parents)):
                raise SessionConflictError("Linked Actor checkpoint directory")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / f"{session_id}.{part}.json"
            with (directory / ".lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if path.exists():
                    existing = self._load_actor_part(
                        session_id=session_id, part=part, expected_provenance=provenance
                    )
                    if existing != packet:
                        raise SessionConflictError("Completed Actor checkpoint content changed")
                    return existing
                _atomic_json(path, packet)
                path.chmod(0o600)
        return packet

    def _load_actor_part(self, *, session_id: str, part: str, expected_provenance):
        from ahe_beta.execution_contract import canonical_sha256

        _validate_session_id(session_id)
        path = self._root / "actor-checkpoints" / f"{session_id}.{part}.json"
        if any(item.is_symlink() for item in (path, *path.parents)):
            raise SessionConflictError("Linked Actor checkpoint")
        if not path.exists():
            return None
        packet = json.loads(path.read_text())
        if (
            packet.get("version") != 1
            or packet.get("session_id") != session_id
            or packet.get("sha256") != canonical_sha256(packet.get("payload"))
            or expected_provenance is not None
            and packet.get("provenance") != expected_provenance
        ):
            raise SessionConflictError("Actor checkpoint identity or digest mismatch")
        return packet

    def find_session_id_by_issue(self, issue_number: int) -> str | None:
        """Resolve an issue to its session, repairing a stale/missing index.

        The full session file is the authoritative record.  A crash or a
        resume restore can leave that file present while the derived
        ``index.json`` is empty or stale; callers must not turn that recoverable
        state into an evidence gap.
        """
        number = int(issue_number)
        for entry in reversed(self.index(include_invalid=True)):
            if number in [int(value) for value in entry.get("issue_numbers", [])]:
                sid = str(entry.get("session_id") or "")
                if sid:
                    try:
                        self.load(sid)
                    except (FileNotFoundError, ValueError, json.JSONDecodeError):
                        continue
                    return sid

        # Index miss: scan authoritative session files and repair the derived
        # projection before returning the match.  This is intentionally a
        # bounded local read with no model/tool activity.
        for path in sorted(self._root.glob("*.json")):
            if path.name == _INDEX_NAME:
                continue
            try:
                session = self.load(path.stem)
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
            if any(ref.number == number for ref in session.issue_refs):
                self.reconcile(session.session_id)
                return session.session_id
        return None

    def rebuild_index(self) -> list[dict]:
        """Rebuild ``index.json`` from authoritative session files.

        Resume and replay entry points call this before role stages.  Invalid
        or partial files are skipped and remain available for separate audit;
        they must not prevent valid sessions from becoming trace-addressable.
        """
        with self._lock:
            self._root.mkdir(parents=True, exist_ok=True)
            with (self._root / ".sessions.lock").open("a+b") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX)
                entries: list[dict] = []
                for path in sorted(self._root.glob("*.json")):
                    if path.name == _INDEX_NAME:
                        continue
                    try:
                        session = self.load(path.stem)
                    except (FileNotFoundError, ValueError, json.JSONDecodeError):
                        continue
                    entries.append(_index_entry(session))
                _atomic_json(self._root / _INDEX_NAME, entries)
                return entries

    def load_user_feedback_envelope(self, session_id: str) -> dict:
        """Return the persisted 0055 handoff, reconstructing legacy sessions once.

        The fallback is deterministic and deliberately does not mutate the old
        file, so replaying historical sessions remains read-only.
        """
        session = self.load(session_id)
        if session.user_feedback_envelope:
            from ahe_beta.demand.evidence_contract import EvidenceEnvelope

            restored = EvidenceEnvelope.from_dict(session.user_feedback_envelope)
            if restored.evidence_categories:
                return restored.to_dict()
            # Early 0055 snapshots did not carry the category index; rebuild
            # from the same persisted session rather than widening visibility.
            from ahe_beta.demand.evidence_contract import build_evidence_envelope

            return build_evidence_envelope(session).to_dict()
        from ahe_beta.demand.evidence_contract import build_evidence_envelope

        return build_evidence_envelope(session).to_dict()

    def bind_assessment_root(self, root: Path) -> None:
        """Spec-0084/T5: controller supplies its trusted measurement projection root."""
        self._assessment_root = Path(root)

    def load_assessment_summaries(self, session_id: str) -> list[dict]:
        """Read only frozen safe feedback, never live worker state or private reports."""
        if self._assessment_root is None:
            return []
        return read_assessment_summaries(self._assessment_root, self.load(session_id))

    def index(self, *, include_invalid: bool = False) -> list[dict]:
        index_path = self._root / _INDEX_NAME
        if not index_path.exists():
            return []  # 首次运行无索引为合法初始态
        rows = json.loads(index_path.read_text(encoding="utf-8"))
        if include_invalid:
            return rows
        # 旧索引没有该字段，按 valid 兼容；正式体感/通过率消费者不接收 evaluator-invalid。
        return [row for row in rows if row.get("evaluation_status", "valid") == "valid"]


def read_assessment_summaries(
    root: Path, session: Session, *, archive_sha256: str | None = None
) -> list[dict]:
    """Read a frozen projection, optionally bound to a verified parent archive inventory."""
    import hashlib

    from ahe_beta.execution_contract import canonical_sha256, validate_assessment_summary

    round_no = session.session_provenance.get("round_no")
    if type(round_no) is not int:
        return []
    path = root / "feedback" / f"round-{round_no}.json"
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise SessionConflictError("Unsafe frozen assessment projection")
    if not path.exists():
        if archive_sha256 is not None:
            raise SessionConflictError("Archived assessment projection is missing")
        return []
    raw = path.read_bytes()
    if archive_sha256 is not None and hashlib.sha256(raw).hexdigest() != archive_sha256:
        raise SessionConflictError("Archived assessment projection content changed")
    frozen = json.loads(raw)
    if (
        frozen.get("sha256") != canonical_sha256(frozen.get("summaries"))
        or frozen.get("round_no") != round_no
        or frozen.get("user_sha") != session.session_provenance.get("harness_sha")
    ):
        raise SessionConflictError("Frozen assessment projection identity mismatch")
    result = []
    for item in frozen["summaries"]:
        if item.get("session_id") == session.session_id:
            row = validate_assessment_summary(item)
            if row["contract_id"] != session.execution_contract.get("contract_id"):
                raise SessionConflictError("Assessment is bound to another execution contract")
            result.append(row)
    return result


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
    validate_session_provenance(session)
    evaluation_status = (
        session.sim_trace.evaluation_status if session.sim_trace is not None else "valid"
    )
    return {
        "session_id": session.session_id,
        **(
            {
                "session_provenance": dict(session.session_provenance),
                **{
                    key: session.session_provenance[key]
                    for key in (
                        "persona_id",
                        "task_id",
                        "task_digest",
                        "task_kind",
                        "round_no",
                        "slot",
                        "interaction",
                        "harness_sha",
                    )
                },
            }
            if session.session_provenance
            else {}
        ),
        "score": session.feeling.score if session.feeling is not None else None,
        "reason": session.feeling.reason if session.feeling is not None else "",
        # Spec-0084/T1: missingness is a measurement, not a synthetic low score.
        "experience_status": (session.feedback.get("experience") or {}).get(
            "status", "rated" if session.feeling is not None else "missing"
        ),
        "experience_source": (session.feedback.get("experience") or {}).get("source", "legacy"),
        "task_assessment": (session.feedback.get("task_assessment") or {}).get("status", "unknown"),
        "followup_input": session.execution_contract.get("followup_input", "unknown"),
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
