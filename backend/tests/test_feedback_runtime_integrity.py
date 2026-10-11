"""Spec-0082: real source snapshots, subprocess deadlines and direct evidence handoff."""

import contextvars
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from auto_designer.demand import triage
from auto_designer.demand.evidence_contract import build_evidence_envelope
from auto_designer.demand.session_timeline import (
    bind_session_store,
    format_harness_beat,
    format_harness_step,
    format_session_timeline,
    get_harness_step,
)
from auto_designer.demand.source import bind_harness_source, current_harness_source
from auto_designer.harness.budget import request_limits
from auto_designer.harness.launcher import _HarnessHandle
from auto_designer.loop.feedback_pipeline import FeedbackPipeline
from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore
from auto_designer.loop.sim_user import (
    make_direct_run_session_fn,
    result_to_sim_trace,
    result_to_turns,
)
from auto_designer.models import FeelingScore, Persona, SeedScenario, Session, Transcript, Turn
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context, current_usage_context
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.loop import SessionResult, TurnLog


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _source_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "entry.py").write_text("version = 'seed'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")
    seed = _git(repo, "rev-parse", "HEAD")
    (repo / "entry.py").write_text("version = 'tested'\n")
    _git(repo, "commit", "-qam", "tested")
    tested = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", seed)
    return repo, seed, tested


def test_feedback_roles_share_tested_snapshot_without_changing_checkout(tmp_path):
    repo, seed, tested = _source_repo(tmp_path)
    ledger = RecoveryStore.initialize(
        root=tmp_path / "ledger", identity=RecoveryIdentity("exp", "run", "cfg", "src", "plan")
    )
    ledger.freeze_round(round_no=1, user_sha=tested, plan=[])
    observations = []

    class Role:
        def inspect(self):
            source = current_harness_source()
            path = source.snapshot()
            observations.append((source.sha, (path / "entry.py").read_text(), path))
            assert not (path / ".git").exists()

        def triage_once(self, **kwargs):
            self.inspect()

        propose_once = inspect

        def admit_once(self):
            self.inspect()
            return SimpleNamespace(admitted=[])

    role = Role()
    pipeline = FeedbackPipeline(
        recovery=ledger,
        grounding_repo=str(repo),
        resolve_head=lambda: tested,
        assert_descendant=lambda **kwargs: None,
        triagers=[role],
        divergents=[role],
        synthesizers=[role],
        owner=role,
    )
    pipeline.mark_stage(round_no=1, stage="users", input_value={"done": True})
    assert pipeline.run(round_no=1, user_sha=tested) == tested
    assert len(observations) == 4
    assert all(sha == tested and "tested" in text for sha, text, _ in observations)
    assert len({path for _, _, path in observations}) == 1
    assert not observations[0][2].exists()
    assert _git(repo, "rev-parse", "HEAD") == seed


def test_missing_snapshot_cannot_fall_back_to_seed(tmp_path):
    repo, _, _ = _source_repo(tmp_path)
    with bind_harness_source(repo, "a" * 40), pytest.raises(subprocess.CalledProcessError):
        current_harness_source().snapshot()


def test_source_binding_propagates_to_parallel_role_and_is_restored(tmp_path):
    repo, seed, tested = _source_repo(tmp_path)
    with bind_harness_source(repo, seed):
        parent = current_harness_source()
        with bind_harness_source(repo, tested), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    contextvars.copy_context().run, lambda: current_harness_source().snapshot()
                )
                for _ in range(2)
            ]
            assert len({future.result() for future in futures}) == 1
        assert current_harness_source() is parent
    assert current_harness_source() is None


@pytest.mark.parametrize("budget", ["0", "-1", "nan", "inf", "invalid"])
def test_invalid_request_budget_is_rejected(budget):
    with pytest.raises(ValueError):
        request_limits({"AUTO_DESIGNER_HARNESS_REQUEST_BUDGET_SECONDS": budget}, fallback=1800)


def test_legacy_internal_limit_has_termination_margin():
    limits = request_limits({"HARNESS_CALL_TIMEOUT": "1800"}, fallback=1800)
    assert limits.request_seconds is None
    assert limits.outer_seconds == 1860


def test_invalid_legacy_knobs_preserve_launcher_fallback():
    limits = request_limits({"HARNESS_CALL_TIMEOUT": "unknown"}, fallback=1800)
    assert limits.outer_seconds == 1860


def test_source_config_is_bound_per_invocation_without_shared_env(tmp_path, monkeypatch):
    import nexau

    from auto_designer.demand.agent_runtime import run_agent_def

    repo, seed, tested = _source_repo(tmp_path)
    monkeypatch.setenv("SANDBOX_WORK_DIR", "/unrelated-host-directory")
    monkeypatch.setenv("DEMAND_LLM_MODEL", "unused-model")
    monkeypatch.setenv("DEMAND_LLM_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("DEMAND_LLM_API_KEY", "test-secret")
    observed = []

    class Agent:
        def __init__(self, *, config):
            self.config = config

        def run(self, *, message):
            from pathlib import Path

            path = Path(self.config.sandbox_config.work_dir)
            observed.append((path / "entry.py").read_text())
            assert tested in message
            return {"dispositions": []}

    monkeypatch.setattr(nexau, "Agent", Agent)
    from pathlib import Path

    agent_def = Path(__file__).resolve().parents[1] / "agent_defs/triage_agent"
    with bind_harness_source(repo, tested):
        run_agent_def(
            agent_def,
            "inspect source",
            store=SessionStore(tmp_path / "sessions"),
            repo=repo,
            role="triager",
            timeout=5,
        )
    assert observed == ["version = 'tested'\n"]
    assert _git(repo, "rev-parse", "HEAD") == seed
    import os

    assert os.environ["SANDBOX_WORK_DIR"] == "/unrelated-host-directory"


def test_triage_backlog_uses_report_sha_and_restores_round_context(tmp_path, monkeypatch):
    repo, seed, tested = _source_repo(tmp_path)
    role = triage.Triager(FakeTracker(), SessionStore(tmp_path / "sessions"), str(repo), str(repo))
    monkeypatch.setattr(
        role, "_evidence_for_issue", lambda issue: {"harness_source": {"ref": seed}}
    )
    observed = []

    def run(*args, **kwargs):
        source = current_harness_source()
        observed.append((source.sha, current_usage_context().harness_sha))
        assert "seed" in (source.snapshot() / "entry.py").read_text()
        return json.dumps({"dispositions": []})

    monkeypatch.setattr(triage, "run_agent_def", run)
    issue = SimpleNamespace(number=25, title="Old report", body="", labels=["report"])
    with bind_harness_source(repo, tested), bind_usage_context(harness_sha=tested):
        parent = current_harness_source()
        role._run_agent(pending=[issue])
        assert current_harness_source() is parent
        assert current_usage_context().harness_sha == tested
    assert observed == [(seed, seed)]


@pytest.mark.parametrize("source", ["reply_steps", "stdout_progress", "nested_progress"])
@pytest.mark.parametrize("text_size", [5000, 9000])
def test_direct_and_simulated_storage_and_query_limits_match(tmp_path, source, text_size):
    steps = [
        {"kind": "tool_result", "text": str(i) + ":" + "x" * text_size, "metadata": {"index": i}}
        for i in range(300)
    ]
    events = [
        {
            "type": "progress",
            "text": step["text"],
            "raw": {"type": "progress", **step},
            "source": "harness_stdout",
        }
        for step in steps
    ]
    if source == "nested_progress":
        for event, step in zip(events, steps, strict=True):
            event["raw"] = {"progress": step}
    expected_steps = steps
    handle = SimpleNamespace(
        visible_events=events,
        last_steps=steps if source == "reply_steps" else [],
        reset=lambda: None,
        send=lambda message: "completed",
        close=lambda: None,
    )
    review = SimpleNamespace(respond=lambda *args: {"score": 3, "reason": "done"})
    store = SessionStore(tmp_path / "sessions")
    persona = Persona("p", "senior", "python", "task", "brief")
    scenario = SeedScenario("do task")
    direct = make_direct_run_session_fn(
        client_factory=lambda: review, tracker=FakeTracker(), store=store, sim_personas={}
    )(persona, scenario, handle)
    direct = store.load(direct.session_id)
    record = direct.user_outcome["execution_record"]
    assert record["events"] == events  # Includes raw frames and complete text.
    assert record["events_total"] == len(events) == 300
    assert record["steps_total"] == len(expected_steps) == 300
    assert record["events_omitted"] == record["steps_omitted"] == 0
    assert direct.transcript.turns[1].steps == expected_steps

    turn = TurnLog(
        turn=1,
        phase="active",
        action_space=[],
        perceive="",
        verdict="unsure",
        action="send_message",
        message="do task",
        executor="user",
        channel="emit",
        patience=3,
        trust="ok",
        harness_output="completed",
        harness_steps=expected_steps,
        harness_events=events,
    )
    result = SessionResult(persona_id="p", end_reason="completed", turns=[turn])
    simulated = Session(
        persona,
        scenario,
        Transcript(result_to_turns(result)),
        FeelingScore(3, "done"),
        sim_trace=result_to_sim_trace(result),
    )
    store.save(simulated)
    simulated = store.load(simulated.session_id)
    assert simulated.transcript.turns[0].steps == direct.transcript.turns[1].steps
    assert simulated.sim_trace.turns[0].harness_events == record["events"]

    # Both query paths keep the same 80-item peek and 6000-character expansion.
    for session in (direct, simulated):
        beat = format_harness_beat(session=session, turn=1, occurrence=0)
        assert beat["n_steps_raw"] == 300
        assert beat["n_steps_returned"] == 80
        assert any(step["kind"] == "omitted" for step in beat["steps"])
        # An original middle index survives; direct previously removed these steps.
        step = format_harness_step(session=session, turn=1, occurrence=0, step_i=150)
        assert step["n_chars_raw"] == len(expected_steps[150]["text"])
        if text_size == 5000:
            assert step["text"] == expected_steps[150]["text"]
            assert not step["truncated"]
        else:
            assert step["truncated"]
            assert step["text"].startswith(expected_steps[150]["text"][:6000])
    timeline = json.loads(format_session_timeline(direct))["timeline"]
    assert len(timeline["stdout_observations"]) == 8
    assert all(len(event["text"]) <= 160 for event in timeline["stdout_observations"])
    assert all("raw" not in event for event in timeline["stdout_observations"])


def test_direct_malformed_progress_is_retained_without_inventing_steps(tmp_path):
    events = [{"type": "progress", "text": "observed", "raw": ["malformed"]}]
    handle = SimpleNamespace(
        visible_events=events,
        last_steps=[],
        reset=lambda: None,
        send=lambda message: "completed",
        close=lambda: None,
    )
    store = SessionStore(tmp_path / "sessions")
    session = make_direct_run_session_fn(
        client_factory=lambda: SimpleNamespace(respond=lambda *args: {"score": 3}),
        tracker=FakeTracker(),
        store=store,
        sim_personas={},
    )(Persona("p", "s", "d", "g", "b"), SeedScenario("task"), handle)
    loaded = store.load(session.session_id)
    assert loaded.user_outcome["execution_record"]["events"] == events
    assert loaded.transcript.turns[1].steps == []


def _handle(tmp_path, body, *, budget="0.1", grace="0.5"):
    script = tmp_path / "entry.py"
    script.write_text(body)
    return _HarnessHandle(
        [sys.executable, str(script)],
        tmp_path,
        {
            "AUTO_DESIGNER_HARNESS_REQUEST_BUDGET_SECONDS": budget,
            "AUTO_DESIGNER_HARNESS_TERMINATION_GRACE_SECONDS": grace,
        },
        "",
    )


def test_real_subprocess_can_deliver_timeout_reply_during_grace(tmp_path):
    handle = _handle(
        tmp_path,
        """import json,sys,time,os
obj=json.loads(sys.stdin.readline())
time.sleep(float(obj['budget_seconds']) + .05)
print(json.dumps({'type':'reply','text':json.dumps({'budget':obj['budget_seconds'],'env':os.environ['HARNESS_TASK_BUDGET_SECONDS']}),'status':'timed_out'}),flush=True)
""",
    )
    try:
        reply = json.loads(handle.send("task"))
        assert reply == {"budget": 0.1, "env": "0.1"}
        assert handle.request_outcomes[-1]["termination_source"] == "harness_reply"
        assert handle.request_outcomes[-1]["infrastructure_limit_seconds"] == 0.6
    finally:
        handle.close()


@pytest.mark.parametrize(
    ("output", "origin"),
    [
        ("", "transport"),
        ("bad json", "protocol"),
        ('{"type":"error","text":"failed"}', "harness_error"),
    ],
)
def test_request_failure_does_not_claim_product_reply(tmp_path, output, origin):
    handle = _handle(
        tmp_path,
        f"import sys\nsys.stdin.readline()\nprint({output!r},flush=True)\n"
        if output
        else "import sys\nsys.stdin.readline()\n",
    )
    try:
        with pytest.raises(RuntimeError):
            handle.send("task")
        assert handle.request_outcomes[-1]["status"] == "crashed"
        assert handle.request_outcomes[-1]["termination_source"] == origin
    finally:
        handle.close()


def test_direct_timeout_retains_received_steps_and_supports_evidence_tools(tmp_path):
    handle = _handle(
        tmp_path,
        """import json,sys,time
sys.stdin.readline()
print(json.dumps({'type':'progress','kind':'tool','text':'read task input'}),flush=True)
time.sleep(300)
""",
        budget="0.1",
        grace="0.4",
    )
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    review = SimpleNamespace(
        respond=lambda *args: {
            "verdict": "file_issue",
            "score": 1,
            "reason": "timeout",
            "issue": "No terminal reply",
        }
    )
    runner = make_direct_run_session_fn(
        client_factory=lambda: review, tracker=tracker, store=store, sim_personas={}
    )
    session = runner(
        Persona("p", "senior", "python", "task", "brief"), SeedScenario("do task"), handle
    )
    loaded = store.load(session.session_id)
    assert loaded.sim_trace is None
    assert loaded.user_outcome["harness_messages"] == 1
    assert loaded.user_outcome["followups"] == 0
    assert loaded.transcript.turns[1].steps == [{"kind": "tool", "text": "read task input"}]
    timeline = json.loads(format_session_timeline(loaded))["timeline"]
    assert timeline["interaction_mode"] == "direct"
    assert timeline["requests"][0]["termination_source"] == "infrastructure"
    beat = format_harness_beat(session=loaded, turn=1, occurrence=0)
    assert beat["stop_kind"] == "infrastructure_timeout"
    assert beat["steps"][0]["text"] == "read task input"
    step = format_harness_step(session=loaded, turn=1, occurrence=0, step_i=0)
    assert step["text"] == "read task input"
    assert step["stop_kind"] == "infrastructure_timeout"
    assert not format_harness_beat(session=loaded, turn=2, occurrence=0)["ok"]
    with bind_usage_context(role="owner"):
        assert not format_harness_beat(session=loaded, turn=1, occurrence=0)["ok"]
    with (
        bind_session_store(store),
        bind_usage_context(role="triager", session_id="another-session"),
    ):
        assert not get_harness_step(session_id=loaded.session_id, turn=1, occurrence=0, step_i=0)[
            "ok"
        ]


def test_source_sha_is_recovered_from_trusted_launch_receipt():
    session = Session(
        Persona("p", "s", "d", "g", "b"),
        SeedScenario("task"),
        Transcript([Turn("harness", "done")]),
        FeelingScore(1, "ok"),
    )
    session.workspace_evidence = {
        "observation": {"status": "not_supported", "artifact": {"harness_sha": "a" * 40}}
    }
    assert build_evidence_envelope(session).harness_source["ref"] == "a" * 40


@pytest.mark.parametrize("succeeds", [True, False])
def test_missing_submit_has_one_bounded_completion_retry(tmp_path, monkeypatch, succeeds):
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    role = triage.Triager(tracker, store, str(tmp_path), str(tmp_path))
    calls = []
    submitted = json.dumps({"dispositions": [{"issue": 25, "disposition": "needs_info"}]})

    def run(*args, **kwargs):
        calls.append((args[1], kwargs))
        return (
            submitted
            if succeeds and len(calls) == 2
            else "[Error: Maximum iteration limit reached.]"
        )

    monkeypatch.setattr(triage, "run_agent_def", run)
    issue = SimpleNamespace(number=25, title="Timeout", body="No reply", labels=["report"])
    with bind_usage_context(session_id="missing"):
        result = role._run_agent(pending=[issue])
    assert len(calls) == 2
    assert calls[1][1]["max_iterations"] == 8
    assert "needs_info" in calls[1][0]
    assert (triage.read_submit(result, "dispositions") is not None) is succeeds
