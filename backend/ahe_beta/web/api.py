"""Read-only HTTP layer for frontend observation dashboard (FastAPI).

Reuses existing read paths from Metrics/SessionStore/IssueTracker, serialized as JSON for frontend SPA consumption.
No new storage, no state writes, no benchmark introduction. Endpoints are synchronous def (read local files,
avoiding ASYNC blocking warnings on event loop). create_app injects dependencies (Fake for testing, real on runtime),
enabling offline unit tests.
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
    """Host SPA: real files (index.html / assets/*) returned as-is; other paths (frontend routes like /agentboard,
    deep links/refreshes for /sessions/:id) fall back to index.html, delegated to BrowserRouter client routing.
    /api/* matched by earlier-registered routes takes priority and does not reach here."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _open_issue_count(*, tracker: IssueTracker | None) -> int | None:
    """Current open issue count; degrades to None if no tracker or read fails (no 500 raised)."""
    if tracker is None:
        return None
    try:
        return len(tracker.list_open_issues())
    except Exception:
        return None


def _summarize(*, store: SessionStore, row: dict) -> dict[str, object]:
    """Index row + supplement persona_identity and truncated scenario from full data, assemble list summary DTO."""
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
    """In-place attach platform-layer derived fields to each issue (Spec-0029/T9, pure label/body parsing, no new storage):

    - `plane`—report/proposal/ready (three-plane projection, old labels mapped; end state/no plane is None);
    - `provenance`—from-triage/from-architect/from-divergent (proposal origin, None if absent);
    - `kind` / `round` / `priority`—same projection as 0025/T7;
    - `triage_status`—old-convention single-value projection (for legacy data frontend compatibility; new data uses plane);
    - `reject_reason`—declined (and legacy rejected/needs-info) closure reason; DTO includes `reason` when present,
      authoritative reason in detail endpoint comments;
    - `covers: list[int]`—issue numbers declared in body covers machine line (issue_schema single source of truth,
      parsed for any issue);
    - `covered_by: int | None`—which **open** issue with covers (proposal/work item) covers this one, smallest number if multiple.
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
    """Gitea dashboard integration: list all-state issues (including body/timestamps) + dashboard link; connected=False
    if no tracker or read fails. Tracker without list_issues observation capability (Fake) falls back to open issue list."""
    if tracker is None:
        return {"connected": False, "board_url": board_url, "issues": []}
    fetch_all = getattr(tracker, "list_issues", None)
    try:
        if callable(fetch_all):
            issues = fetch_all(state="all")
        else:  # Fake protocol-only implementation: fall back to open set (body present, timestamp defaults)
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
    """Single issue in full + comments + label evolution. Timeline failure alone does not break issue/comments."""
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
    """Single commit in full (complete message/stats/files/diff). Raises 404 if not found; connected=False if capability absent or read fails."""
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


# Spec-0032/T7: delivery-layer "blocking" label (OpenAgents' needs-human end state)—the only dead ticket requiring manual clearing in unattended loops.
_NEEDS_HUMAN = "needs-human"


def _delivery(*, tracker: IssueTracker | None) -> dict[str, object]:
    """Delivery-layer observation (Spec-0032/T7): open PR list + needs-human backlog count (dual-sourced from PR and issue).

    connected=False if tracker lacks list_pulls observation capability (Fake) or read fails (frontend degrades to placeholder, no 500).
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
    """Main branch updates: list recent commits on harness repo + vK tags. connected=False if tracker lacks this read capability (Fake)
    or read fails (frontend degrades to placeholder, no 500)."""
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
        # tracker only used for open_issue_count, trend/curve not triggered
        metrics = Metrics(tracker, store)
        return {
            "open_issue_count": _open_issue_count(tracker=tracker),
            "session_count": len(store.index()),
            "feeling_trend": metrics.feeling_trend(),
            "feedback_counts": metrics.feedback_counts(),
            "issue_curve": metrics.issue_curve(),
            "funnel": metrics.funnel(),  # Spec-0029/T9: current three-plane funnel quantities (report/proposal/ready)
        }

    @app.get("/api/issues")
    def issues() -> dict[str, object]:
        return _list_issues(tracker=tracker, board_url=board_url)

    @app.get("/api/delivery")
    def delivery() -> dict[str, object]:
        # Spec-0032/T7: delivery-layer observation—open PR + needs-human backlog (vigil work cross-section, read-only).
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
        # Running state for entire run (data/live/run.json): running/current round/total rounds/each round main SHA.
        return read_live_run(data_dir=live_root)

    @app.get("/api/history")
    def history() -> dict[str, object]:
        # Completed work items archived by round (data/live/history.json), frontend groups by round for historical review.
        return {"items": read_history(data_dir=live_root)}

    @app.get("/api/config")
    def config() -> dict[str, object]:
        # Roster (single source of truth, same file as backend run.py): frontend uses this to configure the capacity of three rooms.
        return {"roster": roster if roster is not None else load_roster()}

    @app.get("/api/agents")
    def agents() -> dict[str, object]:
        # Multi-agent activity registry (data/live/agents.json, at same level as data/sessions); each agent updates in real time during closed-loop runs.
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

    # If frontend has been built, FastAPI serves the SPA directly (during development dist does not exist, skip).
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", _SPAStaticFiles(directory=str(dist), html=True), name="static")

    return app


def _default_store() -> SessionStore:
    data = Path(__file__).resolve().parents[2] / "data" / "sessions"
    return SessionStore(data)


def _default_tracker() -> IssueTracker | None:
    """If Gitea environment variables are set, use real tracker; otherwise None (open count displays —)."""
    base_url = os.environ.get("GITEA_URL")
    owner = os.environ.get("OWNER")
    repo = os.environ.get("REPO")
    token = os.environ.get("TOKEN")
    if not (base_url and owner and repo and token):
        return None
    from ahe_beta.tracker.gitea import GiteaTracker

    return GiteaTracker(base_url=base_url, owner=owner, repo=repo, token=token)


def _default_board_url() -> str | None:
    """Gitea board address: {GITEA_URL}/{OWNER}/{REPO}/issues; None if environment is incomplete."""
    base_url = os.environ.get("GITEA_URL")
    owner = os.environ.get("OWNER")
    repo = os.environ.get("REPO")
    if not (base_url and owner and repo):
        return None
    return f"{base_url.rstrip('/')}/{owner}/{repo}/issues"


def _default_repo_url() -> str | None:
    """Gitea repository address: {GITEA_URL}/{OWNER}/{REPO}; None if environment is incomplete (commit list degrades to empty)."""
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
