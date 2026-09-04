"""本地 SessionStore（spec-0001/T6）：一局 Session 全量落盘 + 单一总索引。

全量文件 root/<session_id>.json 为唯一权威；索引 root/index.json 是其派生投影（可由全量重建），
承载体感曲线/回归基线所需最小信息及 evaluation_status。invalid 条目保留供审计，但默认 index()
过滤，避免进入正常体感/通过率。先写全量后追加索引。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from auto_designer.models import Session

_INDEX_NAME = "index.json"


class SessionStore:
    """把 Session 持久化到本地 root/。

    Spec-0017/T1：save 全程持实例锁——index.json 是读-改-写追加，a 段多用户会话并行后
    并发 save 会基于同一旧快照互相覆盖（丢条目）；锁粒度=单次 save 全程（纯本地文件 IO，
    持锁期内无网络/子进程等待，无死锁面）。跨进程并发仍不支持（单进程内多线程即本仓形态）。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        """会话落盘根目录；live 通道据此定位同级 data/live。"""
        return self._root

    def save(self, session: Session) -> None:
        with self._lock:
            self._save_locked(session=session)

    def _save_locked(self, *, session: Session) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        # 先写全量文件（唯一权威），后追加索引：中途失败至多「有全量缺索引」，可重建。
        full_path = self._root / f"{session.session_id}.json"
        full_path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        entries = self.index(include_invalid=True)
        evaluation_status = (
            session.sim_trace.evaluation_status if session.sim_trace is not None else "valid"
        )
        entries.append(
            {
                "session_id": session.session_id,
                "score": session.feeling.score,
                # 体感的「为什么」（用户末态那句话）：设计师据此判根因，不再只看分数。
                # 见 designer._feeling_trend——延迟/等待本身这类痛点只能从 reason 里看出来。
                "reason": session.feeling.reason,
                "created_at": session.created_at.isoformat(),
                "n_issues": len(session.issue_refs),
                # 供设计师 get_session_timeline(issue_number=…) 快查；旧 index 无此键则扫盘回落。
                "issue_numbers": [r.number for r in session.issue_refs],
                # Spec-0048：invalid 仍落全量与索引供审计，但默认趋势读取会排除。
                "evaluation_status": evaluation_status,
                # 轻量协议分轨：兼容旧 evaluation_status，同时标明是否为 persona 契约问题。
                "interaction_status": (
                    getattr(session.sim_trace, "interaction_status", "completed")
                    if session.sim_trace is not None
                    else "completed"
                ),
                "user_outcome": (session.user_outcome or {}).get("end_reason"),
                "accept_validity": session.accept_validity,
                "objective_passed": (session.objective_evaluation or {}).get("passed"),
                # Compact goal index fields let design-side trend views discover
                # revisions/audit warnings without loading every session JSON.
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
        )
        (self._root / _INDEX_NAME).write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> Session:
        full_path = self._root / f"{session_id}.json"
        data = json.loads(full_path.read_text(encoding="utf-8"))  # 不存在则 FileNotFoundError
        return Session.from_dict(data)

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
