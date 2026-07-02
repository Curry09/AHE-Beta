"""前端观测看板只读 API 单测：TestClient + 临时 SessionStore + FakeTracker，不触网。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    Turn,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.web.api import create_app


def _persona() -> Persona:
    return Persona(
        identity="独立开发者",
        level="中级",
        domain="Python 后端",
        goal="让慢查询快起来",
        speaking_style="口语",
    )


def _session(*, score: int, n_issues: int) -> Session:
    refs = [
        IssueRef(number=i + 1, url=f"fake://issues/{i + 1}", state="open") for i in range(n_issues)
    ]
    return Session(
        persona=_persona(),
        scenario=SeedScenario(description="我有个 Django 接口很慢，帮我排查优化。" * 4),
        transcript=Transcript(
            turns=[Turn(role="user", content="hi"), Turn(role="harness", content="yo")]
        ),
        feeling=FeelingScore(score=score, reason="还行"),
        issue_refs=refs,
    )


def _client(tmp_path: Path, *, tracker: object | None) -> TestClient:
    store = SessionStore(tmp_path / "sessions")
    return TestClient(create_app(store=store, tracker=tracker))


def test_health(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=FakeTracker())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_overview_empty(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=FakeTracker())
    body = client.get("/api/overview").json()
    assert body == {
        "open_issue_count": 0,
        "session_count": 0,
        "feeling_trend": [],
        "issue_curve": [],
    }


def test_overview_with_sessions(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.save(_session(score=3, n_issues=1))
    store.save(_session(score=2, n_issues=2))
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="t", body="b", labels=["bug"]))
    client = TestClient(create_app(store=store, tracker=tracker))

    body = client.get("/api/overview").json()
    assert body["session_count"] == 2
    assert body["open_issue_count"] == 1
    assert len(body["feeling_trend"]) == 2
    # issue_curve net_open 累计：第一局 opened=1 net=1，第二局 opened=2 net=3
    nets = [row[2] for row in body["issue_curve"]]
    assert nets == [1, 3]


class _BrokenTracker:
    def list_open_issues(self):
        raise RuntimeError("gitea down")


def test_overview_tracker_degrades_to_null(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=_BrokenTracker()))
    assert client.get("/api/overview").json()["open_issue_count"] is None


def test_overview_no_tracker_null(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=None)
    assert client.get("/api/overview").json()["open_issue_count"] is None


def test_sessions_list(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    store.save(_session(score=4, n_issues=0))
    client = TestClient(create_app(store=store, tracker=FakeTracker()))

    rows = client.get("/api/sessions").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["score"] == 4
    assert row["n_issues"] == 0
    assert row["persona_identity"] == "独立开发者"
    assert len(row["scenario"]) <= 80
    assert set(row) == {
        "session_id",
        "created_at",
        "score",
        "n_issues",
        "persona_identity",
        "scenario",
    }


def test_session_detail_ok(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    sess = _session(score=3, n_issues=1)
    store.save(sess)
    client = TestClient(create_app(store=store, tracker=FakeTracker()))

    body = client.get(f"/api/sessions/{sess.session_id}").json()
    assert body["session_id"] == sess.session_id
    assert body["feeling"]["score"] == 3
    assert body["transcript"]["turns"][0]["role"] == "user"
    assert body["issue_refs"][0]["number"] == 1


def test_session_detail_404(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=FakeTracker())
    assert client.get("/api/sessions/nope").status_code == 404


def test_issues_connected(tmp_path: Path) -> None:
    tracker = FakeTracker()
    tracker.create_issue(IssueDraft(title="慢查询排查", body="b", labels=["bug"]))
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(
        create_app(store=store, tracker=tracker, board_url="http://gitea/o/r/issues")
    )

    body = client.get("/api/issues").json()
    assert body["connected"] is True
    assert body["board_url"] == "http://gitea/o/r/issues"
    assert len(body["issues"]) == 1
    issue = body["issues"][0]
    assert issue["title"] == "慢查询排查"
    assert issue["url"] == "http://gitea/o/r/issues/1"
    assert "bug" in issue["labels"]
    assert issue["state"] == "open"


def test_agents_empty_then_populated(tmp_path: Path) -> None:
    from auto_designer.loop.live import update_agent

    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=FakeTracker()))

    assert client.get("/api/agents").json() == {"agents": []}

    update_agent(  # store.root.parent == tmp_path
        data_dir=tmp_path,
        agent_id="user-A",
        role="user",
        label="独立开发者",
        running=True,
        status="harness 回复中…",
        turns=[{"role": "user", "content": "在吗"}],
    )
    update_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        role="developer",
        label="dev#1",
        running=False,
        status="已提交 fix/issue-1",
    )
    agents = client.get("/api/agents").json()["agents"]
    assert [a["role"] for a in agents] == ["user", "developer"]  # 用户在前
    assert agents[0]["turns"][0]["content"] == "在吗"


class _CommitTracker(FakeTracker):
    """FakeTracker + 观测 commit 读能力，用来测 /api/commits 的 connected 路径。"""

    def list_recent_commits(self, *, limit: int = 15):
        return [
            {
                "sha": "abc1234def",
                "short_sha": "abc1234",
                "message": "feat(main): 收窄超时",
                "author": "dev#1",
                "date": "2026-07-02T10:00:00Z",
                "url": "http://gitea/o/r/commit/abc1234def",
                "tags": ["v7"],
            }
        ][:limit]


def test_commits_connected(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=_CommitTracker(), repo_url="http://gitea/o/r"))
    body = client.get("/api/commits").json()
    assert body["connected"] is True
    assert body["commits_url"] == "http://gitea/o/r/commits/branch/main"
    assert len(body["commits"]) == 1
    commit = body["commits"][0]
    assert commit["short_sha"] == "abc1234"
    assert commit["tags"] == ["v7"]
    assert commit["url"] == "http://gitea/o/r/commit/abc1234def"


def test_commits_no_tracker(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=None)
    body = client.get("/api/commits").json()
    assert body["connected"] is False
    assert body["commits"] == []


def test_commits_fake_tracker_no_capability(tmp_path: Path) -> None:
    # FakeTracker 无 list_recent_commits → 降级 connected=False（不抛 500）。
    client = _client(tmp_path, tracker=FakeTracker())
    body = client.get("/api/commits").json()
    assert body["connected"] is False
    assert body["commits"] == []


def test_issues_no_tracker(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=None)
    body = client.get("/api/issues").json()
    assert body["connected"] is False
    assert body["issues"] == []


def test_issues_tracker_error(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=_BrokenTracker()))
    body = client.get("/api/issues").json()
    assert body["connected"] is False
    assert body["issues"] == []
