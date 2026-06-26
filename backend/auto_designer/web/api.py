"""前端观测看板的只读 HTTP 层（FastAPI）。

复用既有 Metrics/SessionStore/IssueTracker 的只读路径，序列化为 JSON 供前端 SPA 消费。
不新增存储、不写任何状态、不引入 benchmark。端点为同步 def（读本地文件，避免阻塞 event loop 的
ASYNC 告警）。create_app 注入依赖（测试传 Fake，运行时传真），便于无网络单测。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from auto_designer.loop.metrics import Metrics
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore


def _open_issue_count(*, tracker: IssueTracker | None) -> int | None:
    """当前 open issue 数；无 tracker 或读取失败时降级为 None（不抛 500）。"""
    if tracker is None:
        return None
    try:
        return len(tracker.list_open_issues())
    except Exception:
        return None


def _summarize(*, store: SessionStore, row: dict) -> dict[str, object]:
    """index 行 + 从全量补 persona_identity 与截断后的 scenario，组装列表摘要 DTO。"""
    session = store.load(row["session_id"])
    scenario = session.scenario.description
    return {
        "session_id": row["session_id"],
        "created_at": row["created_at"],
        "score": row["score"],
        "n_issues": row["n_issues"],
        "persona_identity": session.persona.identity,
        "scenario": scenario[:80],
    }


def _list_issues(*, tracker: IssueTracker | None, board_url: str | None) -> dict[str, object]:
    """Gitea 看板整合：列 open issue + 看板链接；无 tracker 或读取失败时 connected=False。"""
    if tracker is None:
        return {"connected": False, "board_url": board_url, "issues": []}
    try:
        open_issues = tracker.list_open_issues()
    except Exception:
        return {"connected": False, "board_url": board_url, "issues": []}
    return {
        "connected": True,
        "board_url": board_url,
        "issues": [
            {
                "number": i.number,
                "title": i.title,
                "labels": list(i.labels),
                "state": i.state,
                "url": f"{board_url}/{i.number}" if board_url else "",
            }
            for i in open_issues
        ],
    }


def create_app(
    *, store: SessionStore, tracker: IssueTracker | None, board_url: str | None = None
) -> FastAPI:
    app = FastAPI(title="auto-designer observation dashboard", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/overview")
    def overview() -> dict[str, object]:
        metrics = Metrics(tracker, store)  # tracker 仅 open_issue_count 用，trend/curve 不触
        return {
            "open_issue_count": _open_issue_count(tracker=tracker),
            "session_count": len(store.index()),
            "feeling_trend": metrics.feeling_trend(),
            "issue_curve": metrics.issue_curve(),
        }

    @app.get("/api/issues")
    def issues() -> dict[str, object]:
        return _list_issues(tracker=tracker, board_url=board_url)

    @app.get("/api/sessions")
    def sessions() -> list[dict[str, object]]:
        rows = sorted(store.index(), key=lambda e: e["created_at"], reverse=True)
        return [_summarize(store=store, row=row) for row in rows]

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: str) -> dict[str, object]:
        try:
            return store.load(session_id).to_dict()
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"session not found: {session_id}"
            ) from None

    # 构建过前端则由 FastAPI 直接托管 SPA（开发期 dist 不存在，跳过）。
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")

    return app


def _default_store() -> SessionStore:
    data = Path(__file__).resolve().parents[2] / "data" / "sessions"
    return SessionStore(data)


def _default_tracker() -> IssueTracker | None:
    """有 Gitea 环境变量则接真 tracker，否则 None（open 数显示 —）。"""
    base_url = os.environ.get("GITEA_URL")
    owner = os.environ.get("OWNER")
    repo = os.environ.get("REPO")
    token = os.environ.get("TOKEN")
    if not (base_url and owner and repo and token):
        return None
    from auto_designer.tracker.gitea import GiteaTracker

    return GiteaTracker(base_url=base_url, owner=owner, repo=repo, token=token)


def _default_board_url() -> str | None:
    """Gitea 看板地址：{GITEA_URL}/{OWNER}/{REPO}/issues，环境不全则 None。"""
    base_url = os.environ.get("GITEA_URL")
    owner = os.environ.get("OWNER")
    repo = os.environ.get("REPO")
    if not (base_url and owner and repo):
        return None
    return f"{base_url.rstrip('/')}/{owner}/{repo}/issues"


app = create_app(store=_default_store(), tracker=_default_tracker(), board_url=_default_board_url())
