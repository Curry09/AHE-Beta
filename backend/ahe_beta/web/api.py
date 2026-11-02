"""前端观测看板的只读 HTTP 层（FastAPI）。

复用既有 Metrics/SessionStore/IssueTracker 的只读路径，序列化为 JSON 供前端 SPA 消费。
不新增存储、不写任何状态、不引入 benchmark。端点为同步 def（读本地文件，避免阻塞 event loop 的
ASYNC 告警）。create_app 注入依赖（测试传 Fake，运行时传真），便于无网络单测。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.types import Scope

from ahe_beta.demand.issue_schema import (
    DECLINED,
    NEEDS_INFO,
    REJECTED,
    issue_kind,
    parse_covers_line,
    plane,
    priority_of,
    provenance_of,
    round_of,
    triage_status,
)
from ahe_beta.loop.live import read_agents, read_history, read_live_run
from ahe_beta.loop.metrics import Metrics
from ahe_beta.loop.roster import load_roster
from ahe_beta.tracker.base import IssueTracker
from ahe_beta.usage import UsageStore, default_usage_store
from ahe_beta.user.session_store import SessionStore
from ahe_beta.web.issue_timeline import build_issue_timeline, unavailable_timeline


class _SPAStaticFiles(StaticFiles):
    """托管 SPA：真实文件（index.html / assets/*）照常返回；其余路径（前端路由如 /agentboard、
    /sessions/:id 的深链/刷新）回退到 index.html，交给 BrowserRouter 客户端路由。/api/* 由更早注册的
    路由优先匹配，不会落到这里。"""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


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
    # Spec-0073/T5: project provenance from the full authoritative session.
    session = store.load(row["session_id"])
    scenario = session.scenario.description
    return {
        "session_id": row["session_id"],
        "created_at": row["created_at"],
        "score": row["score"],
        "n_issues": row["n_issues"],
        "persona_identity": session.persona.identity,
        **(
            {"session_provenance": dict(session.session_provenance)}
            if session.session_provenance
            else {}
        ),
        "scenario": scenario[:80],
    }


def _annotate_issues(*, issues: list[dict]) -> None:
    """就地给每条 issue 附平台层派生字段（Spec-0029/T9，纯标签/正文解析、无新存储）：

    - `plane`——report/proposal/ready（三平面投影，旧标签经映射；终态/无平面为 None）；
    - `provenance`——from-triage/from-architect/from-divergent（提案来源，无则 None）；
    - `kind` / `round` / `priority`——同 0025/T7 投影；
    - `triage_status`——旧口径单值投影（旧数据前端展示兼容；新数据以 plane 为准）；
    - `reject_reason`——declined（及旧 rejected/needs-info）关闭原因；DTO 带 `reason` 时透出，
      权威原因见详情端点的评论；
    - `covers: list[int]`——body covers 机器行声明的票号（issue_schema 单一真源解析，任何票都解）；
    - `covered_by: int | None`——被哪张 **open** 带 covers 的票（提案/工作项）覆盖，多票取号最小。
    """
    covered_by: dict[int, int] = {}
    for it in issues:
        labels = it.get("labels") or []
        covers = parse_covers_line(str(it.get("body") or ""))
        status = triage_status(labels)
        it["plane"] = plane(labels)
        it["provenance"] = provenance_of(labels)
        it["kind"] = issue_kind(labels)
        it["round"] = round_of(labels)
        it["triage_status"] = status
        it["priority"] = priority_of(labels)
        declined = DECLINED in labels or status in (REJECTED, NEEDS_INFO)
        it["reject_reason"] = (it.get("reason") or None) if declined else None
        it["covers"] = covers
        if covers and it.get("state") == "open":
            for n in covers:
                if n not in covered_by or int(it["number"]) < covered_by[n]:
                    covered_by[n] = int(it["number"])
    for it in issues:
        it["covered_by"] = covered_by.get(int(it["number"]))


def _list_issues(*, tracker: IssueTracker | None, board_url: str | None) -> dict[str, object]:
    """Gitea 看板整合：列全状态 issue（含正文/时间戳）+ 看板链接；无 tracker 或读取失败时
    connected=False。tracker 无 list_issues 观测能力（Fake）时回落 open issue 列表。"""
    if tracker is None:
        return {"connected": False, "board_url": board_url, "issues": []}
    fetch_all = getattr(tracker, "list_issues", None)
    try:
        if callable(fetch_all):
            issues = fetch_all(state="all")
        else:  # Fake 等仅协议实现：回落 open 集（正文仍有，时间戳缺省）
            issues = [
                {
                    "number": i.number,
                    "title": i.title,
                    "body": i.body,
                    "labels": list(i.labels),
                    "state": i.state,
                    "created_at": "",
                    "closed_at": None,
                    "url": f"{board_url}/{i.number}" if board_url else "",
                }
                for i in tracker.list_open_issues()
            ]
    except Exception:
        return {"connected": False, "board_url": board_url, "issues": []}
    _annotate_issues(issues=issues)
    return {"connected": True, "board_url": board_url, "issues": issues}


def _issue_detail(*, tracker: IssueTracker | None, number: int) -> dict[str, object]:
    """单条 issue 全量 + 评论 + 标签演进。timeline 单独失败不拖断 issue/comments。"""
    get_issue = getattr(tracker, "get_issue", None)
    list_comments = getattr(tracker, "list_comments", None)
    if tracker is None or not callable(get_issue) or not callable(list_comments):
        return {
            "connected": False,
            "issue": None,
            "comments": [],
            "timeline": unavailable_timeline(reason="issue detail capability unavailable"),
        }
    try:
        issue = get_issue(number=number)
        comments = list_comments(number=number)
    except Exception as exc:
        if getattr(exc, "status", None) == 404:
            raise HTTPException(status_code=404, detail=f"issue not found: #{number}") from None
        return {
            "connected": False,
            "issue": None,
            "comments": [],
            "timeline": unavailable_timeline(reason="issue detail read failed"),
        }

    list_timeline = getattr(tracker, "list_timeline", None)
    if not callable(list_timeline):
        timeline = unavailable_timeline()
    else:
        try:
            timeline = build_issue_timeline(issue=issue, events=list_timeline(number=number))
        except Exception as exc:
            timeline = unavailable_timeline(reason=f"timeline read failed: {type(exc).__name__}")
    return {"connected": True, "issue": issue, "comments": comments, "timeline": timeline}


def _commit_detail(*, tracker: IssueTracker | None, sha: str) -> dict[str, object]:
    """单个 commit 全量（message 全文/stats/files/diff）。不存在抛 404；无能力/读失败 connected=False。"""
    fetch = getattr(tracker, "get_commit_detail", None)
    if tracker is None or not callable(fetch):
        return {"connected": False, "commit": None}
    try:
        commit = fetch(sha=sha)
    except Exception as exc:
        if getattr(exc, "status", None) == 404:
            raise HTTPException(status_code=404, detail=f"commit not found: {sha}") from None
        return {"connected": False, "commit": None}
    return {"connected": True, "commit": commit}


# Spec-0032/T7：交付面「卡人」标签（OpenAgents 的 needs-human 终态）——无人值守环里唯一要人清的死票。
_NEEDS_HUMAN = "needs-human"


def _delivery(*, tracker: IssueTracker | None) -> dict[str, object]:
    """交付面观测（Spec-0032/T7）：open PR 列表 + needs-human 积压计数（PR 与 issue 双源）。

    tracker 无 list_pulls 观测能力（Fake）或读失败时 connected=False（前端降级为占位，不抛 500）。
    """
    fetch = getattr(tracker, "list_pulls", None)
    if tracker is None or not callable(fetch):
        return {"connected": False, "pulls": [], "needs_human": 0}
    try:
        pulls = fetch(state="open")
        open_issues = tracker.list_open_issues()
    except Exception:
        return {"connected": False, "pulls": [], "needs_human": 0}
    needs_human = sum(1 for p in pulls if _NEEDS_HUMAN in (p.get("labels") or [])) + sum(
        1 for i in open_issues if _NEEDS_HUMAN in (i.labels or [])
    )
    return {"connected": True, "pulls": pulls, "needs_human": needs_human}


def _list_commits(*, tracker: IssueTracker | None, commits_url: str | None) -> dict[str, object]:
    """main 分支更新：列 harness 仓最近 commit + vK tag。tracker 无该读能力（Fake）或读取失败时
    connected=False（前端降级为占位，不抛 500）。"""
    fetch = getattr(tracker, "list_recent_commits", None)
    if tracker is None or not callable(fetch):
        return {"connected": False, "commits_url": commits_url, "commits": []}
    try:
        commits = fetch(limit=15)
    except Exception:
        return {"connected": False, "commits_url": commits_url, "commits": []}
    return {"connected": True, "commits_url": commits_url, "commits": commits}


def create_app(
    *,
    store: SessionStore,
    tracker: IssueTracker | None,
    board_url: str | None = None,
    repo_url: str | None = None,
    usage_store: UsageStore | None = None,
    data_dir: Path | None = None,
    roster: dict[str, int] | None = None,
    runmeta: dict[str, object] | None = None,
    observation_guard: Callable[[], tuple[dict[str, object], object]] | None = None,
) -> FastAPI:
    app = FastAPI(title="ahe-beta observation dashboard", version="0.1.0")
    commits_url = f"{repo_url.rstrip('/')}/commits/branch/main" if repo_url else None
    usage_store = usage_store or default_usage_store()
    # Spec-0072/T4: a selected v2 run supplies its data root independently of sessions.
    live_root = data_dir if data_dir is not None else store.root.parent
    app.state.runmeta = dict(runmeta or {})

    if observation_guard is not None:

        @app.middleware("http")
        async def guard_observations(request: Request, call_next):
            if not request.url.path.startswith("/api/"):
                return await call_next(request)

            def unavailable():
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Observation snapshot is changing or unavailable; retry after collect completes"
                    },
                )

            try:
                metadata, generation = observation_guard()
                app.state.runmeta.update(metadata)
            except (OSError, ValueError):
                return unavailable()
            response = await call_next(request)
            try:
                metadata, after = observation_guard()
                app.state.runmeta.update(metadata)
                if generation != after:
                    raise ValueError("Snapshot changed during request")
                return response
            except (OSError, ValueError):
                return unavailable()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/runmeta")
    def run_metadata() -> dict[str, object]:
        return dict(app.state.runmeta)

    @app.get("/api/overview")
    def overview() -> dict[str, object]:
        metrics = Metrics(tracker, store)  # tracker 仅 open_issue_count 用，trend/curve 不触
        return {
            "open_issue_count": _open_issue_count(tracker=tracker),
            "session_count": len(store.index()),
            "feeling_trend": metrics.feeling_trend(),
            "feedback_counts": metrics.feedback_counts(),
            "issue_curve": metrics.issue_curve(),
            "funnel": metrics.funnel(),  # Spec-0029/T9：三平面漏斗当前量（report/proposal/ready）
        }

    @app.get("/api/issues")
    def issues() -> dict[str, object]:
        return _list_issues(tracker=tracker, board_url=board_url)

    @app.get("/api/delivery")
    def delivery() -> dict[str, object]:
        # Spec-0032/T7：交付面观测——open PR + needs-human 积压（vigil 的工作切面，只读）。
        return _delivery(tracker=tracker)

    @app.get("/api/issues/{number}")
    def issue_detail(number: int) -> dict[str, object]:
        return _issue_detail(tracker=tracker, number=number)

    @app.get("/api/commits")
    def commits() -> dict[str, object]:
        return _list_commits(tracker=tracker, commits_url=commits_url)

    @app.get("/api/commits/{sha}")
    def commit_detail(sha: str) -> dict[str, object]:
        return _commit_detail(tracker=tracker, sha=sha)

    @app.get("/api/state")
    def state() -> dict[str, object]:
        # 整条 run 的运行态（data/live/run.json）：running/当前轮/总轮数/各轮 main SHA。
        return read_live_run(data_dir=live_root)

    @app.get("/api/history")
    def history() -> dict[str, object]:
        # 按轮归档的已完成工作项（data/live/history.json），前端按 round 分组回看。
        return {"items": read_history(data_dir=live_root)}

    @app.get("/api/config")
    def config() -> dict[str, object]:
        # 编制（单一真源，与后端 run.py 同一份 roster）：前端据此定三个房间的容量。
        return {"roster": roster if roster is not None else load_roster()}

    @app.get("/api/agents")
    def agents() -> dict[str, object]:
        # 多 agent 活动注册表（data/live/agents.json，与 data/sessions 同级），跑闭环时各 agent 实时更新。
        return {"agents": read_agents(data_dir=live_root)}

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

    def _usage_filters(
        run_id: str | None,
        round_no: int | None,
        session_id: str | None,
        instance_id: str | None,
        interaction_id: str | None,
        turn_no: int | None,
        role: str | None,
        agent_id: str | None,
        model: str | None,
    ) -> dict[str, object]:
        return {
            "run_id": run_id,
            "round_no": round_no,
            "session_id": session_id,
            "instance_id": instance_id,
            "interaction_id": interaction_id,
            "turn_no": turn_no,
            "role": role,
            "agent_id": agent_id,
            "model": model,
        }

    @app.get("/api/usage/events")
    def usage_events(
        run_id: str | None = None,
        round_no: int | None = None,
        session_id: str | None = None,
        instance_id: str | None = None,
        interaction_id: str | None = None,
        turn_no: int | None = None,
        role: str | None = None,
        agent_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, object]:
        filters = _usage_filters(
            run_id,
            round_no,
            session_id,
            instance_id,
            interaction_id,
            turn_no,
            role,
            agent_id,
            model,
        )
        return {"events": usage_store.events(**filters)}

    @app.get("/api/usage/summary")
    def usage_summary(
        run_id: str | None = None,
        round_no: int | None = None,
        session_id: str | None = None,
        instance_id: str | None = None,
        interaction_id: str | None = None,
        turn_no: int | None = None,
        role: str | None = None,
        agent_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, object]:
        return usage_store.summary(
            **_usage_filters(
                run_id,
                round_no,
                session_id,
                instance_id,
                interaction_id,
                turn_no,
                role,
                agent_id,
                model,
            )
        )

    @app.get("/api/usage/sessions/{session_id}")
    def session_usage(session_id: str) -> dict[str, object]:
        return usage_store.summary(session_id=session_id)

    # 构建过前端则由 FastAPI 直接托管 SPA（开发期 dist 不存在，跳过）。
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", _SPAStaticFiles(directory=str(dist), html=True), name="static")

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
    from ahe_beta.tracker.gitea import GiteaTracker

    return GiteaTracker(base_url=base_url, owner=owner, repo=repo, token=token)


def _default_board_url() -> str | None:
    """Gitea 看板地址：{GITEA_URL}/{OWNER}/{REPO}/issues，环境不全则 None。"""
    base_url = os.environ.get("GITEA_URL")
    owner = os.environ.get("OWNER")
    repo = os.environ.get("REPO")
    if not (base_url and owner and repo):
        return None
    return f"{base_url.rstrip('/')}/{owner}/{repo}/issues"


def _default_repo_url() -> str | None:
    """Gitea 仓地址：{GITEA_URL}/{OWNER}/{REPO}，环境不全则 None（commit 列表降级为空）。"""
    base_url = os.environ.get("GITEA_URL")
    owner = os.environ.get("OWNER")
    repo = os.environ.get("REPO")
    if not (base_url and owner and repo):
        return None
    return f"{base_url.rstrip('/')}/{owner}/{repo}"


app = create_app(
    store=_default_store(),
    tracker=_default_tracker(),
    board_url=_default_board_url(),
    repo_url=_default_repo_url(),
)
