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
from auto_designer.usage import UsageStore
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
        "feedback_counts": {},
        "issue_curve": [],
        "funnel": {"report": 0, "proposal": 0, "ready": 0},  # Spec-0029/T9 三平面漏斗
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
    # issue_curve 现为 backlog 口径（需 Gitea 全状态读能力）；FakeTracker 无 list_issues → 空序列。
    assert body["issue_curve"] == []


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


def test_usage_api_filters_and_empty_data(tmp_path: Path) -> None:
    usage = UsageStore(tmp_path / "usage.jsonl")
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=FakeTracker(), usage_store=usage))
    assert client.get("/api/usage/events").json() == {"events": []}
    usage.append(
        {
            "session_id": "s1",
            "instance_id": "i1",
            "interaction_id": "turn-0",
            "role": "user",
            "round_no": 1,
            "input_tokens": 4,
            "output_tokens": 2,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
            "total_tokens": 6,
            "usage_source": "reported",
        }
    )
    usage.append(
        {
            "session_id": "s2",
            "instance_id": "i2",
            "role": "synthesizer",
            "round_no": 2,
            "input_tokens": 7,
            "output_tokens": 3,
            "reasoning_tokens": 1,
            "cached_input_tokens": 2,
            "total_tokens": 10,
            "usage_source": "reported",
        }
    )
    usage.append(
        {
            "session_id": "s2",
            "instance_id": "i2",
            "role": "synthesizer",
            "round_no": 2,
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
            "total_tokens": None,
            "usage_source": "unavailable",
        }
    )
    assert client.get("/api/usage/summary?role=user").json()["total_tokens"] == 6
    summary = client.get("/api/usage/summary?instance_id=i1").json()
    assert summary["by_instance"]["i1"]["total_tokens"] == 6
    assert summary["by_interaction"]["turn-0"]["total_tokens"] == 6
    events = client.get("/api/usage/events?round_no=2&session_id=s2").json()["events"]
    assert len(events) == 2 and all(event["role"] == "synthesizer" for event in events)
    assert summary["by_instance"]["i1"]["unavailable_count"] == 0
    synthesizer = client.get("/api/usage/summary?role=synthesizer").json()
    assert synthesizer["unavailable_count"] == 1
    assert synthesizer["by_role"]["synthesizer"]["unavailable_count"] == 1
    assert client.get("/api/usage/sessions/s1").json()["event_count"] == 1


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
    assert issue["body"] == "b"  # 正文随列表返回（详情面板完整信息）
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
    client = TestClient(
        create_app(store=store, tracker=_CommitTracker(), repo_url="http://gitea/o/r")
    )
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


_ISSUE_DTO = {
    "number": 7,
    "title": "harness 卡顿",
    "body": "复现步骤……",
    "labels": ["bug"],
    "state": "closed",
    "created_at": "2026-07-01T10:00:00Z",
    "closed_at": "2026-07-02T09:00:00Z",
    "url": "http://gitea/o/r/issues/7",
}


class _ObserveTracker(FakeTracker):
    """FakeTracker + Gitea 观测读能力（全状态 issue/评论/commit 详情），测富端点连通路径。"""

    def list_issues(self, *, state: str = "all", limit: int = 100):
        assert state == "all"
        return [_ISSUE_DTO]

    def get_issue(self, *, number: int):
        if number != 7:
            raise RuntimeError("boom")
        return _ISSUE_DTO

    def list_comments(self, *, number: int):
        return [{"author": "developer", "body": "已推进 main v2", "created_at": "2026-07-02"}]

    def get_commit_detail(self, *, sha: str):
        return {
            "sha": sha,
            "short_sha": sha[:7],
            "message": "fix: issue #7\n\n详细说明",
            "author": "developer",
            "date": "2026-07-02T08:00:00Z",
            "url": f"http://gitea/o/r/commit/{sha}",
            "tags": ["v2"],
            "stats": {"additions": 3, "deletions": 1, "total": 4},
            "files": [{"filename": "agents/main.md", "status": "modified"}],
            "diff": "diff --git a/agents/main.md b/agents/main.md\n+新增",
        }


def test_issues_full_states_via_observe_tracker(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=_ObserveTracker())
    body = client.get("/api/issues").json()
    assert body["connected"] is True
    # 全状态 + 正文 + 时间戳原样透传；Spec-0025/T7 附加 kind/round/triage_status/priority/
    # reject_reason 与 covers/covered_by（labels=[bug] 的普通闭票：kind=bug、其余无标签 → None/空）
    assert body["issues"] == [
        {
            **_ISSUE_DTO,
            "kind": "bug",
            "round": None,
            "triage_status": None,
            "priority": None,
            "reject_reason": None,
            "covers": [],
            "covered_by": None,
        }
    ]


# ---- Spec-0025/T7：/api/issues 平台层派生字段（kind/round/triage_status/priority/驳回原因）----


class _TriageStateTracker(FakeTracker):
    """FakeTracker + 全状态读能力，返回带 triage 标签/时间戳/reason 的 issue，测 T7 派生字段。"""

    def __init__(self, issues: list[dict]) -> None:
        super().__init__()
        self._all = issues

    def list_issues(self, *, state: str = "all", limit: int = 100):
        return list(self._all)


def _dto(number: int, *, labels: list[str], state: str = "open", body: str = "", reason: str = ""):
    return {
        "number": number,
        "title": f"issue {number}",
        "body": body,
        "labels": labels,
        "state": state,
        "created_at": "2026-06-01T00:00:00Z",
        "closed_at": "2026-06-02T00:00:00Z" if state == "closed" else None,
        "url": f"http://gitea/o/r/issues/{number}",
        "reason": reason,
    }


def test_issues_triage_fields(tmp_path: Path) -> None:
    tracker = _TriageStateTracker(
        [
            _dto(1, labels=["bug", "triaged", "P1", "round-2"]),
            _dto(2, labels=["RFC", "P0"], body="综合\n\ncovers: #3"),
            _dto(3, labels=["bug", "triaged", "superseded"], state="closed"),
            _dto(
                4,
                labels=["feature", "rejected", "round-1"],
                state="closed",
                reason="超出 harness 范围",
            ),
            _dto(5, labels=["bug", "needs-triage", "round-3"]),
        ]
    )
    client = _client(tmp_path, tracker=tracker)
    issues = {i["number"]: i for i in client.get("/api/issues").json()["issues"]}

    # 1：已 triaged 的 bug，带优先级与轮号
    assert (issues[1]["kind"], issues[1]["triage_status"]) == ("bug", "triaged")
    assert (issues[1]["priority"], issues[1]["round"]) == ("P1", 2)
    assert issues[1]["covered_by"] is None
    # 2：RFC 凌驾 type（kind=rfc）、covers 声明、triage_status 不落在 triage 枚举里 → None
    assert issues[2]["kind"] == "rfc"
    assert issues[2]["covers"] == [3]
    assert issues[2]["triage_status"] is None
    # 3：被 RFC 取代——superseded 胜过 triaged；被 open RFC #2 覆盖
    assert issues[3]["triage_status"] == "superseded"
    assert issues[3]["covered_by"] == 2
    # 4：驳回——带原因（reason 透出）
    assert issues[4]["triage_status"] == "rejected"
    assert issues[4]["reject_reason"] == "超出 harness 范围"
    assert issues[4]["round"] == 1
    # 5：未 triage
    assert issues[5]["triage_status"] == "needs-triage"
    assert issues[5]["priority"] is None


# ---- Spec-0020/T4：/api/issues 覆盖关系字段 covers / covered_by ----


def test_issues_covers_and_covered_by(tmp_path: Path) -> None:
    tracker = FakeTracker()
    bug = tracker.create_issue(IssueDraft(title="被覆盖bug", body="x", labels=["bug"])).number
    plain = tracker.create_issue(IssueDraft(title="无关bug", body="y", labels=["bug"])).number
    design = tracker.create_issue(
        IssueDraft(title="整合", body=f"根因\n\ncovers: #{bug}", labels=["design"])
    ).number

    client = _client(tmp_path, tracker=tracker)
    issues = {i["number"]: i for i in client.get("/api/issues").json()["issues"]}

    assert issues[design]["covers"] == [bug]
    assert issues[bug]["covered_by"] == design
    assert issues[plain] == {**issues[plain], "covers": [], "covered_by": None}


def test_issues_covered_by_gone_when_design_closed(tmp_path: Path) -> None:
    """design 票 closed 后其覆盖关系消失（covered_by 只认 open design 票）。"""
    tracker = FakeTracker()
    bug = tracker.create_issue(IssueDraft(title="bug", body="x", labels=["bug"])).number
    design = tracker.create_issue(
        IssueDraft(title="整合", body=f"covers: #{bug}", labels=["design"])
    ).number
    tracker.set_state(design, "closed", "已落地")

    client = _client(tmp_path, tracker=tracker)
    issues = {i["number"]: i for i in client.get("/api/issues").json()["issues"]}
    assert issues[bug]["covered_by"] is None


def test_issues_covered_by_prefers_smallest_design_number(tmp_path: Path) -> None:
    tracker = FakeTracker()
    bug = tracker.create_issue(IssueDraft(title="bug", body="x", labels=["bug"])).number
    d1 = tracker.create_issue(
        IssueDraft(title="早提案", body=f"covers: #{bug}", labels=["design"])
    ).number
    tracker.create_issue(IssueDraft(title="晚提案", body=f"covers: #{bug}", labels=["design"]))

    client = _client(tmp_path, tracker=tracker)
    issues = {i["number"]: i for i in client.get("/api/issues").json()["issues"]}
    assert issues[bug]["covered_by"] == d1


def test_issue_detail_with_comments(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=_ObserveTracker())
    body = client.get("/api/issues/7").json()
    assert body["connected"] is True
    assert body["issue"]["title"] == "harness 卡顿"
    assert body["comments"][0]["author"] == "developer"
    assert body["timeline"]["available"] is False


def test_issue_detail_no_capability_degrades(tmp_path: Path) -> None:
    # FakeTracker 无 get_issue/list_comments → connected=False（不抛 500）。
    client = _client(tmp_path, tracker=FakeTracker())
    body = client.get("/api/issues/1").json()
    assert body["connected"] is False
    assert body["issue"] is None and body["comments"] == []
    assert body["timeline"]["available"] is False


def test_issue_detail_timeline_connected_and_failure_isolated(tmp_path: Path) -> None:
    class _TimelineTracker(_ObserveTracker):
        def list_timeline(self, *, number: int):
            return [
                {
                    "id": 1,
                    "type": "label",
                    "body": "1",
                    "label": "ready",
                    "operation": "add",
                    "actor": "synthesizer",
                    "created_at": "2026-06-01T00:00:00Z",
                }
            ]

        def get_issue(self, *, number: int):
            issue = super().get_issue(number=number)
            issue["labels"] = ["ready"]
            issue["created_at"] = "2026-06-01T00:00:00Z"
            return issue

    connected = _client(tmp_path, tracker=_TimelineTracker()).get("/api/issues/7").json()
    assert connected["timeline"]["available"] is True
    assert connected["timeline"]["current"]["plane"] == "ready"

    class _BrokenTimeline(_TimelineTracker):
        def list_timeline(self, *, number: int):
            raise RuntimeError("timeline down")

    degraded = _client(tmp_path, tracker=_BrokenTimeline()).get("/api/issues/7").json()
    assert degraded["connected"] is True
    assert degraded["issue"]["title"] == "harness 卡顿"
    assert degraded["timeline"]["available"] is False


def test_issue_detail_404(tmp_path: Path) -> None:
    class _NotFound(_ObserveTracker):
        def get_issue(self, *, number: int):
            exc = RuntimeError("not found")
            exc.status = 404
            raise exc

    client = _client(tmp_path, tracker=_NotFound())
    assert client.get("/api/issues/99").status_code == 404


def test_commit_detail_full(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=_ObserveTracker())
    body = client.get("/api/commits/" + "a" * 40).json()
    assert body["connected"] is True
    commit = body["commit"]
    assert commit["message"] == "fix: issue #7\n\n详细说明"  # 全文非首行
    assert commit["stats"]["additions"] == 3
    assert "+新增" in commit["diff"]


def test_commit_detail_no_capability_degrades(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=FakeTracker())
    assert client.get("/api/commits/abc").json() == {"connected": False, "commit": None}


def test_state_defaults_then_running(tmp_path: Path) -> None:
    from auto_designer.loop.live import update_live_run

    client = _client(tmp_path, tracker=FakeTracker())
    body = client.get("/api/state").json()
    assert body["running"] is False and body["round"] == 0

    update_live_run(data_dir=tmp_path, running=True, round_no=2, total_rounds=5)
    body = client.get("/api/state").json()
    assert body["running"] is True and body["round"] == 2 and body["total_rounds"] == 5


def test_history_grouped_source(tmp_path: Path) -> None:
    from auto_designer.loop.live import archive_agent, update_agent

    client = _client(tmp_path, tracker=FakeTracker())
    assert client.get("/api/history").json() == {"items": []}

    update_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        role="developer",
        label="dev#1",
        running=False,
        status="已推进 main v1",
        detail="完整报告",
        round_no=1,
    )
    archive_agent(
        data_dir=tmp_path,
        agent_id="dev-0",
        round_no=1,
        extra={"kind": "dev_run", "issue_number": 3, "tag": "v1", "committed": True},
    )
    items = client.get("/api/history").json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "dev_run" and items[0]["round"] == 1
    assert items[0]["detail"] == "完整报告" and items[0]["log"]


def test_issues_plane_and_provenance_fields(tmp_path: Path) -> None:
    """Spec-0029/T9：每条 issue 附 plane（三平面投影，旧标签映射）与 provenance。"""
    from auto_designer.demand import issue_schema as sc

    tracker = FakeTracker()
    r = tracker.create_issue(IssueDraft(title="报告", body="x", labels=["bug", sc.REPORT])).number
    p = tracker.create_issue(
        IssueDraft(title="提案", body="x", labels=["bug", sc.PROPOSAL, sc.FROM_TRIAGE, "P1"])
    ).number
    s = tracker.create_issue(
        IssueDraft(
            title="结构案", body=f"x\n\ncovers: #{p}", labels=[sc.PROPOSAL, sc.FROM_SYNTHESIZE]
        )
    ).number
    w = tracker.create_issue(
        IssueDraft(title="旧triaged", body="x", labels=["bug", sc.TRIAGED])
    ).number

    client = _client(tmp_path, tracker=tracker)
    issues = {i["number"]: i for i in client.get("/api/issues").json()["issues"]}

    assert issues[r]["plane"] == sc.REPORT and issues[r]["provenance"] is None
    assert issues[p]["plane"] == sc.PROPOSAL and issues[p]["provenance"] == sc.FROM_TRIAGE
    assert issues[s]["provenance"] == sc.FROM_SYNTHESIZE and issues[s]["covers"] == [p]
    assert issues[p]["covered_by"] == s  # 被 open 结构案覆盖
    assert issues[w]["plane"] == sc.READY  # 旧标签读侧映射


def test_issues_tracker_error(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=_BrokenTracker()))
    body = client.get("/api/issues").json()
    assert body["connected"] is False
    assert body["issues"] == []


# Spec-0032/T7：交付面观测端点 /api/delivery——open PR + needs-human 积压（PR 与 issue 双源）。


class _PullTracker(FakeTracker):
    """带 list_pulls 观测能力的 Fake（形状对齐 GiteaTracker.list_pulls 的 DTO）。"""

    def __init__(self, pulls: list[dict]) -> None:
        super().__init__()
        self._pulls = pulls

    def list_pulls(self, *, state: str = "open", limit: int = 20) -> list[dict]:
        return [p for p in self._pulls if state in ("all", p.get("state"))][:limit]


def _pull(number: int, *, labels: list[str] | None = None, state: str = "open") -> dict:
    return {
        "number": number,
        "title": f"pr {number}",
        "state": state,
        "head_branch": f"openagents/issue-{number}",
        "mergeable": True,
        "labels": labels or [],
        "closes_issues": [number],
        "url": "",
        "created_at": "",
        "updated_at": "",
    }


def test_delivery_lists_pulls_and_counts_needs_human(tmp_path: Path) -> None:
    tracker = _PullTracker([_pull(5), _pull(6, labels=["needs-human"])])
    tracker.create_issue(IssueDraft(title="卡人的票", body="x", labels=["needs-human"]))
    store = SessionStore(tmp_path / "sessions")
    client = TestClient(create_app(store=store, tracker=tracker))

    body = client.get("/api/delivery").json()
    assert body["connected"] is True
    assert [p["number"] for p in body["pulls"]] == [5, 6]
    assert body["needs_human"] == 2  # PR#6 + 那张 issue（双源计数）


def test_delivery_degrades_without_capability(tmp_path: Path) -> None:
    # FakeTracker 无 list_pulls 观测能力 → connected=False（前端降级占位，不抛 500）。
    client = _client(tmp_path, tracker=FakeTracker())
    body = client.get("/api/delivery").json()
    assert body == {"connected": False, "pulls": [], "needs_human": 0}


def test_delivery_no_tracker(tmp_path: Path) -> None:
    client = _client(tmp_path, tracker=None)
    assert client.get("/api/delivery").json()["connected"] is False


def test_config_exposes_synthesizer_roster(monkeypatch, tmp_path):
    monkeypatch.setenv("N_SYNTHESIZERS", "3")
    data = _client(tmp_path, tracker=None).get("/api/config").json()
    assert data["roster"]["synthesizer"] == 3


# Spec-0073/T5: summaries and detail expose the same authoritative frozen identity.
def test_multitask_api_keeps_persona_task_session_and_harness_attribution(tmp_path):
    from auto_designer.models import WorkspaceSpec

    store = SessionStore(tmp_path / "sessions")
    expected = {}
    for slot, task_id in enumerate(("orders", "pvlib")):
        session = _session(score=3, n_issues=0)
        session.session_id = f"bound-session-{slot}"
        session.persona.identity = f"persona-{slot}"
        origin = {
            "contract_version": 1,
            "run_id": "selected-run",
            "round_no": 2,
            "slot": slot,
            "persona_id": session.persona.identity,
            "task_id": task_id,
            "task_digest": f"digest-{task_id}",
            "task_kind": "ordinary",
            "interaction": "direct",
            "harness_sha": "round-two-harness",
        }
        session.scenario.workspace = WorkspaceSpec(
            params={
                key: origin[key] for key in ("task_id", "task_digest", "task_kind", "interaction")
            }
        )
        session.session_provenance = origin
        store.save(session)
        expected[session.session_id] = origin
    client = TestClient(create_app(store=store, tracker=FakeTracker()))
    rows = client.get("/api/sessions").json()
    assert {row["session_id"]: row["session_provenance"] for row in rows} == expected
    for session_id, origin in expected.items():
        body = client.get(f"/api/sessions/{session_id}").json()
        assert body["session_id"] == session_id
        assert body["session_provenance"] == origin
        assert body["persona"]["identity"] == origin["persona_id"]
        assert body["scenario"]["workspace"]["params"]["task_id"] == origin["task_id"]
