"""Observation access through ordinary tools and the real role handoff boundaries."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from nexau.archs.main_sub.execution.hooks import ToolCallParams

from ahe_beta.demand.architect import Architect
from ahe_beta.demand.divergent import Divergent
from ahe_beta.demand.observation_provider import (
    ObservationProvider,
    bind_observation_provider,
    bind_observation_scope,
    current_observation_provider,
)
from ahe_beta.demand.proposal_view import evidence_session_ids, format_proposal_view
from ahe_beta.demand.session_timeline import bind_session_store, get_session_timeline
from ahe_beta.guards.workspace_jail import WorkspaceJailMiddleware
from ahe_beta.models import (
    FeelingScore,
    IssueDraft,
    OpenIssue,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.session_store import SessionStore


def bundle(root: Path, sid: str, filename: str = "engine.log") -> Path:
    path = root / sid
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": sid,
                "artifact": {"commit": "fixture-v2"},
                "files": [{"path": filename}, {"path": "READING.md"}],
            }
        )
    )
    (path / filename).write_text(
        f"request={sid} attempt=1 parser failed\nretry retained context\nreply completed\n"
    )
    (path / "READING.md").write_text("Internal engine diagnostics; not displayed to the user.")
    (path / "unexported.env").write_text("private data")
    return path


def session(sid: str) -> Session:
    return Session(
        session_id=sid,
        persona=Persona("tester", "experienced", "coding", "complete work", "direct"),
        scenario=SeedScenario("fix the problem"),
        transcript=Transcript(),
        feeling=FeelingScore(2, "I had to wait without understanding progress"),
    )


def call_file(workdir: Path, tool: str, **parameters):
    args = ToolCallParams(
        agent_state=None,
        sandbox=SimpleNamespace(work_dir=str(workdir)),
        tool_name=tool,
        parameters=parameters,
        tool_call_id="fixture",
        execution_params={},
    )
    return WorkspaceJailMiddleware().wrap_tool_call(args, lambda _: {"ordinary_source_tool": True})


def test_read_search_list_use_manifest_without_fixed_log_schema(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions")
    path = bundle(tmp_path / "observations", "s1", "renamed-v9.txt")
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path / "role-runs"))
    monkeypatch.setenv("DEMAND_LLM_API_KEY", "secret-value")
    (path / "renamed-v9.txt").write_text(
        "new-engine-key=secret-value\nretry now uses a different format\nfinished\n"
    )
    with (
        bind_usage_context(role="divergent"),
        bind_observation_provider(store, allowed_session_ids={"s1"}) as provider,
    ):
        assert str(path / "manifest.json") in provider.prompt_index()
        assert "retry now" not in provider.prompt_index()
        listing = call_file(tmp_path, "list_directory", dir_path=str(path))
        read = call_file(
            tmp_path, "read_file", file_path=str(path / "renamed-v9.txt"), offset=0, limit=2
        )
        search = call_file(tmp_path, "search_file_content", dir_path=str(path), pattern="retry")
    assert "renamed-v9.txt" in listing["content"]
    assert "unexported.env" not in listing["content"]
    assert "secret-value" not in read["content"]
    assert "2| retry now uses a different format" in read["content"]
    assert "renamed-v9.txt:2:" in search["content"]
    events = [
        json.loads(line)
        for line in (tmp_path / "role-runs/evidence_access.jsonl").read_text().splitlines()
    ]
    assert len(events) == 3 and all(row["allowed"] for row in events)
    assert {row["role"] for row in events} == {"divergent"}
    assert "pattern=retry" in events[-1]["reason"]


def test_undeclared_cross_session_and_write_access_are_denied(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    first = bundle(tmp_path / "observations", "s1")
    second = bundle(tmp_path / "observations", "s2")
    workdir = tmp_path / "harness"
    workdir.mkdir()
    with bind_observation_provider(store, allowed_session_ids={"s1"}):
        for target in [first / "unexported.env", second / "engine.log"]:
            result = call_file(workdir, "read_file", file_path=str(target))
            assert "error" in result
        assert "error" in call_file(workdir, "list_directory", dir_path=str(first.parent))
        assert "error" in call_file(
            workdir, "write_file", file_path=str(first / "engine.log"), content="overwrite"
        )
        assert call_file(workdir, "read_file", file_path="entry.py")["ordinary_source_tool"]


@pytest.mark.parametrize("bad_path", ["../s2/engine.log", "/etc/passwd", "linked.log"])
def test_bad_manifest_or_symlink_is_unavailable(tmp_path, bad_path):
    root = tmp_path / "observations"
    path = bundle(root, "s1")
    other = bundle(root, "s2")
    (path / "linked.log").symlink_to(other / "engine.log")
    (path / "manifest.json").write_text(
        json.dumps({"session_id": "s1", "files": [{"path": bad_path}]})
    )
    provider = ObservationProvider(
        SessionStore(tmp_path / "sessions"), allowed_session_ids=frozenset({"s1"})
    )
    assert not provider.files and "s1" in provider.unavailable


def test_missing_logs_do_not_invent_success_and_session_schema_is_not_required(tmp_path):
    store = SessionStore(tmp_path / "sessions")  # No Session JSON is necessary for a native bundle.
    bundle(tmp_path / "observations", "s1")
    provider = ObservationProvider(store, allowed_session_ids=frozenset({"s1", "old-session"}))
    assert "s1" in provider.files and "old-session" in provider.unavailable
    assert "原生日志不可用" in provider.prompt_index()


def test_broad_source_search_and_alias_cannot_bypass_file_scope(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = bundle(tmp_path / "observations", "s1")
    alias = tmp_path / "alias.log"
    alias.symlink_to(path / "unexported.env")
    with bind_observation_provider(store, allowed_session_ids={"s1"}):
        assert "error" in call_file(tmp_path, "search_file_content", pattern="private")
        assert "error" in call_file(tmp_path, "read_file", file_path=str(alias))


def test_parallel_invocations_keep_independent_scopes(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    for sid in ("s1", "s2"):
        bundle(tmp_path / "observations", sid)

    def read_own(sid):
        with bind_observation_provider(store, allowed_session_ids={sid}):
            provider = current_observation_provider()
            return sorted(provider.files)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(read_own, ["s1", "s2"])) == [["s1"], ["s2"]]
    assert current_observation_provider() is None


def test_successive_round_formats_and_historical_evidence_coexist(tmp_path):
    """Reader compatibility, not a claim that the production exporter exists."""
    store = SessionStore(tmp_path / "sessions")
    first = bundle(tmp_path / "observations", "round1-session", "runtime.jsonl")
    second = bundle(tmp_path / "observations", "round2-session", "scheduler-v2.txt")
    (first / "runtime.jsonl").write_text('{"event":"span_finished","has_error":true}\n')
    (second / "scheduler-v2.txt").write_text("job abc entered WAITING_FOR_REMOTE\n")
    (second / "READING.md").write_text(
        "v2 has no spans; WAITING_FOR_REMOTE means blocked on provider."
    )
    manifest = json.loads((second / "manifest.json").read_text())
    manifest["artifact"]["commit"] = "fixture-v3"
    (second / "manifest.json").write_text(json.dumps(manifest))
    for sid, filename, expected in (
        ("round1-session", "runtime.jsonl", "span_finished"),
        ("round2-session", "scheduler-v2.txt", "WAITING_FOR_REMOTE"),
    ):
        with bind_observation_provider(store, allowed_session_ids={sid}) as provider:
            assert set(provider.files) == {sid}
            result = call_file(tmp_path, "read_file", file_path=str(provider.root / sid / filename))
            assert expected in result["content"]
    # A later synthesis can still cite both versions; neither is interpreted using
    # the other's format. Reading instructions remain bundle-local.
    with bind_observation_provider(store, allowed_session_ids={"round1-session", "round2-session"}):
        for path in (first, second):
            assert "error" not in call_file(
                tmp_path, "read_file", file_path=str(path / "manifest.json")
            )
        assert (
            "v2 has no spans"
            in call_file(tmp_path, "read_file", file_path=str(second / "READING.md"))["content"]
        )


def test_new_round_missing_bundle_does_not_reuse_previous_round(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    bundle(tmp_path / "observations", "previous-session")
    with bind_observation_provider(store, allowed_session_ids={"new-session"}) as provider:
        assert not provider.files
        assert provider.unavailable == ["new-session"]
        result = call_file(
            tmp_path, "read_file", file_path=str(provider.root / "previous-session" / "engine.log")
        )
        assert "error" in result


def test_reference_chain_survives_body_clipping_and_legacy_raw_is_excluded():
    issue = OpenIssue(
        1,
        "normalized problem",
        "x" * 4000 + "\n会话：s1, s2\n## 原始用户报告（案例证据，非实现对象）\nsession_id: private",
    )
    assert evidence_session_ids([issue]) == {"s1", "s2"}
    assert "evidence_sessions=s1,s2" in format_proposal_view(issue)
    assert "private" not in format_proposal_view(issue)


def test_architect_tools_are_available_only_for_cited_sessions(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.save(session("s1"))
    store.save(session("s2"))
    with bind_session_store(store), bind_usage_context(role="architect"):
        assert not get_session_timeline(session_id="s1")["ok"]
        with bind_observation_scope(allowed_session_ids={"s1"}):
            assert get_session_timeline(session_id="s1", reason="compare two reports")["ok"]
            assert not get_session_timeline(session_id="s2")["ok"]


@pytest.mark.parametrize("needs_recovery", [False, True])
def test_drivers_scope_pm_independently_and_inherit_synthesis_references(
    tmp_path, monkeypatch, needs_recovery
):
    store = SessionStore(tmp_path / "sessions")
    store.save(session("s1"))
    store.save(session("s2"))
    store.save(session("s3"))
    tracker = FakeTracker()
    a = tracker.create_issue(IssueDraft("one", "session_id: s1", ["proposal"]))
    b = tracker.create_issue(IssueDraft("two", "会话：s2", ["proposal"]))
    from ahe_beta.observations.grants import grant

    grant(store=store, issue=a.number, sessions={"s1"})
    grant(store=store, issue=b.number, sessions={"s2"})
    pm = tracker.create_issue(
        IssueDraft(
            "PM_TITLE_SENTINEL", "PM_BODY_SENTINEL\n会话：s3", ["proposal", "from-divergent"]
        )
    )
    tracker.create_issue(IssueDraft("PM_READY_SENTINEL", "会话：s3", ["ready", "from-divergent"]))
    seen = []

    def pm_run(*args, **kwargs):
        seen.append(kwargs["allowed_session_ids"])
        return '{"proposals": []}'

    monkeypatch.setattr("ahe_beta.demand.divergent.run_agent_def", pm_run)
    Divergent(tracker, store, str(tmp_path), str(tmp_path)).propose_once()
    assert seen == [{"s1", "s2", "s3"}]
    product = {
        "title": "shared direction",
        "source_proposals": [a.number, b.number],
        "relationship": "shared",
        "common_tension": "uncertain state",
        "structural_direction": "coherent execution",
        "expected_leverage": "preserved user control",
        "solution_level": "structural_mechanism",
        "abstraction_rationale": "shared behavior",
        "covers": [a.number, b.number, pm.number],
    }

    architect_calls = []

    def architect_run(*args, **kwargs):
        architect_calls.append(args[1])
        assert kwargs["allowed_session_ids"] == {"s1", "s2"}
        assert kwargs["evidence"]["source_proposals"] == [a.number, b.number]
        assert all(
            marker not in args[1]
            for marker in ("PM_TITLE_SENTINEL", "PM_BODY_SENTINEL", "PM_READY_SENTINEL")
        )
        assert "运行时行为聚合" not in args[1]
        if needs_recovery and len(architect_calls) == 1:
            return "unfinished investigation without submit"
        return json.dumps({"proposals": [product]})

    monkeypatch.setattr("ahe_beta.demand.architect.run_agent_def", architect_run)
    outcome = Architect(tracker, store, str(tmp_path), str(tmp_path)).propose_once()
    assert len(outcome.proposal_numbers) == 1
    assert sorted(outcome.merged_numbers) == [a.number, b.number]
    assert tracker.issue(pm.number)["state"] == "open"
    structures = [i for i in tracker.list_open_issues() if i.number in outcome.proposal_numbers]
    assert evidence_session_ids(structures) == {"s1", "s2"}
    assert len(architect_calls) == (2 if needs_recovery else 1)
