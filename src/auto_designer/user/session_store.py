"""本地 SessionStore（spec-0001/T6）：一局 Session 全量落盘 + 单一总索引。

全量文件 root/<session_id>.json 为唯一权威；索引 root/index.json 是其派生投影（可由全量重建），
承载体感曲线/回归基线所需最小信息 {session_id, score, created_at, n_issues}。先写全量后追加索引。
"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.models import Session

_INDEX_NAME = "index.json"


class SessionStore:
    """把 Session 持久化到本地 root/。单进程 MVP，不处理并发写竞态。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def save(self, session: Session) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        # 先写全量文件（唯一权威），后追加索引：中途失败至多「有全量缺索引」，可重建。
        full_path = self._root / f"{session.session_id}.json"
        full_path.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        entries = self.index()
        entries.append(
            {
                "session_id": session.session_id,
                "score": session.feeling.score,
                "created_at": session.created_at.isoformat(),
                "n_issues": len(session.issue_refs),
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

    def index(self) -> list[dict]:
        index_path = self._root / _INDEX_NAME
        if not index_path.exists():
            return []  # 首次运行无索引为合法初始态
        return json.loads(index_path.read_text(encoding="utf-8"))
