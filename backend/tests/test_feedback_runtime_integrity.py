"""Spec-0084/T2: preserve actor ownership, missing measurements and publication identity."""

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ahe_beta.loop.sim_user import make_direct_run_session_fn, make_sim_run_session_fn
from ahe_beta.models import Persona, SeedScenario, WorkspaceSpec
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.dimensions import D1Eval
from ahe_beta.user.sim.persona_client import (
    AgenticPersonaClient,
    ApiPersonaClient,
    PersonaContextLimitError,
    ScriptedPersonaClient,
)
from ahe_beta.user.sim.run_live import expert
from ahe_beta.user.sim.runtime import LocalWorkspaceRuntime, ReviewSnapshot

PERSONA = Persona("reviewer", "expert", "python", "finish", "plain")


def workspace(tmp_path):
    path = tmp_path / "task"
    path.mkdir()
    (path / "value.txt").write_text("baseline\n")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "add", "value.txt"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        cwd=path,
        check=True,
    )
    return LocalWorkspaceRuntime(str(path))


class Harness:
    observation_source = None
    request_outcomes = []

    def __init__(self, ws=None):
        self.workspace = ws
        self.messages = []
        self.closed = False

    def reset(self):
        pass

    def bind_execution_contract(self, contract):
        self.contract = contract

    def send(self, message):
        self.messages.append(message)
        if self.workspace:
            self.workspace.write_text("value.txt", "actor output\n")
        return "Delivered the requested file."

    def close(self):
        self.closed = True


class Review:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "task_assessment": "fulfilled",
            "score": 4,
            "reason": "works",
            "opportunities": [],
        }
        self.error = error
        self.calls = 0

    def respond(self, system, user):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def direct(tmp_path, review, tracker=None, store=None):
    return make_direct_run_session_fn(
        client_factory=lambda: review,
        tracker=tracker or FakeTracker(),
        store=store or SessionStore(tmp_path / "sessions"),
        sim_personas={"reviewer": expert()},
    )


def test_actor_outputs_are_frozen_before_readonly_review(tmp_path):
    ws = workspace(tmp_path)
    harness = Harness(ws)
    declaration = {
        "id": "result",
        "source": "workspace",
        "path": "value.txt",
        "content_type": "text/plain",
        "required": True,
        "max_bytes": 1024,
    }

    class ProbingReview(Review):
        def bind_session(self, *, persona, workspace_dir):
            self.snapshot = workspace_dir

        def respond(self, system, user):
            assert harness.closed and ws._closed
            assert isinstance(self.snapshot, ReviewSnapshot)
            assert self.snapshot.read_text("value.txt") == "actor output\n"
            assert self.snapshot.read_text("artifacts/result") == "actor output\n"
            with pytest.raises(PermissionError):
                self.snapshot.write_text("value.txt", "reviewer changed it")
            with pytest.raises(PermissionError):
                self.snapshot.run("echo changed > value.txt")
            return super().respond(system, user)

    review = ProbingReview()
    store = SessionStore(tmp_path / "sessions")
    session = direct(tmp_path, review, store=store)(
        PERSONA,
        SeedScenario(
            "produce value",
            WorkspaceSpec("prebuilt", params={"evaluation_artifacts": [declaration]}),
        ),
        harness,
        workspace_dir=ws,
    )
    row = session.workspace_evidence["evaluation_artifacts"]["entries"][0]
    content = (store.root.parent / row["path"]).read_bytes()
    assert content == b"actor output\n"
    assert row["sha256"] == hashlib.sha256(content).hexdigest()
    assert session.report_plan == [] and session.issue_refs == []
    assert harness.messages == ["produce value"]
    assert harness.contract == session.execution_contract
    assert session.execution_contract["followup_input"] == "unavailable"


@pytest.mark.parametrize("score", [None, True, "3", 2.9, 2.0, 0, 5])
def test_direct_invalid_score_never_backfills_a_rating(tmp_path, score):
    review = Review({"task_assessment": "fulfilled", "score": score, "opportunities": []})
    session = direct(tmp_path, review)(PERSONA, SeedScenario("task"), Harness())
    assert session.feeling is None
    assert session.feedback["experience"]["status"] == ("missing" if score is None else "invalid")
    assert session.feedback["task_assessment"]["status"] == "fulfilled"
    assert session.issue_refs == []


def test_missing_and_unavailable_review_are_distinct_and_do_not_create_bugs(tmp_path):
    missing = direct(
        tmp_path / "missing", Review({"task_assessment": "unknown", "opportunities": []})
    )(
        PERSONA,
        SeedScenario("task"),
        Harness(),
    )
    unavailable = direct(tmp_path / "unavailable", Review(error=RuntimeError("gateway offline")))(
        PERSONA,
        SeedScenario("task"),
        Harness(),
    )
    assert missing.feedback["experience"]["status"] == "missing"
    assert unavailable.feedback["experience"]["status"] == "unavailable"
    assert missing.feeling is unavailable.feeling is None
    assert missing.issue_refs == unavailable.issue_refs == []


def test_partial_report_publication_recovers_without_actor_or_reviewer(tmp_path):
    class FailAfterCreate(FakeTracker):
        failed = False

        def create_issue_once(self, draft, *, operation_key):
            ref = super().create_issue_once(draft, operation_key=operation_key)
            if ref.number == 2 and not self.failed:
                self.failed = True
                raise RuntimeError("connection lost after remote creation")
            return ref

    review = Review(
        {
            "task_assessment": "unfulfilled",
            "score": 2,
            "reason": "not delivered",
            "opportunities": [
                {"kind": "diagnostic", "title": "failure", "body": "Goal was not delivered."},
                {"kind": "feature", "title": "suggestion", "body": "Please make progress clearer."},
            ],
        }
    )
    tracker = FailAfterCreate()
    store = SessionStore(tmp_path / "sessions")
    run = direct(tmp_path, review, tracker=tracker, store=store)
    harness = Harness()
    with bind_usage_context(session_id="stable-session"):
        with pytest.raises(RuntimeError, match="connection lost"):
            run(PERSONA, SeedScenario("task"), harness)
        pending = store.load("stable-session")
        assert len(pending.report_plan) == 2 and pending.issue_refs == []
        original_plan = pending.report_plan
        result = run.load_completed_session("stable-session")
        rerun = run(PERSONA, SeedScenario("task"), harness)
    assert result.report_plan == original_plan == rerun.report_plan
    assert len(result.issue_refs) == len(tracker.list_open_issues()) == 2
    assert review.calls == 1 and harness.messages == ["task"]
    receipt = json.loads((store.root / "reports/stable-session.json").read_text())
    assert receipt["completed"] is True and len(receipt["refs"]) == 2
    assert "root cause is unconfirmed" in tracker.list_open_issues()[0].body
    assert "feature" in tracker.list_open_issues()[1].labels


def test_final_check_uses_live_workspace_and_does_not_end_actor(tmp_path):
    ws = workspace(tmp_path)
    calls = []

    def llm(messages):
        calls.append(messages[-1]["content"])
        if len(calls) == 1:
            return json.dumps({"tool": "read_file", "args": {"path": "value.txt"}})
        if len(calls) == 2:
            ws.write_text("value.txt", "later actor change")
            return json.dumps({"tool": "read_file", "args": {"path": "value.txt"}})
        return json.dumps({"perceive": "read the current workspace", "check_status": "completed"})

    client = AgenticPersonaClient(llm)
    client.bind_session(expert(), ws)
    result = client.respond("system", "<main_final_check>Inspect the file.</main_final_check>")
    assert result["check_status"] == "completed"
    assert "baseline" in calls[1]
    assert "later actor change" in calls[2]
    assert not ws._closed  # The user can still choose continue after checking.


def test_expert_final_check_writes_and_executes_own_test(tmp_path):
    ws = workspace(tmp_path)
    script = iter(
        [
            {
                "tool": "write_file",
                "args": {
                    "path": "user_check.py",
                    "content": "from pathlib import Path\nassert Path('value.txt').read_text() == 'baseline\\n'\nprint('user check passed')\n",
                },
            },
            {"tool": "run_shell", "args": {"cmd": f"{sys.executable} user_check.py"}},
            {"perceive": "my own check passed", "check_status": "completed"},
        ]
    )
    calls = []

    def llm(messages):
        calls.append(messages[-1]["content"])
        return json.dumps(next(script))

    client = AgenticPersonaClient(llm)
    client.bind_session(expert(), ws)
    result = client.respond("system", "<main_final_check>Check the result.</main_final_check>")
    assert result["check_status"] == "completed"
    assert "user check passed" in calls[2]
    assert ws.read_text("user_check.py").startswith("from pathlib import Path")
    assert not ws._closed


@pytest.mark.parametrize("stage", ["main_judge", "waiting_judge", "main_final_check"])
@pytest.mark.parametrize(
    "ability,allowed", [(D1Eval.SHALLOW, False), (D1Eval.COMPETENT, True), (D1Eval.EXPERT, True)]
)
def test_interactive_tool_dispatch_respects_persona_write_capability(
    tmp_path, stage, ability, allowed
):
    ws = workspace(tmp_path)
    conclusion = (
        {"perceive": "checked", "check_status": "completed"}
        if stage == "main_final_check"
        else {"perceive": "checked", "judgment": "on_track"}
        if stage == "waiting_judge"
        else {"perceive": "checked", "verdict": "satisfied"}
    )

    calls = []
    path = f"user-{ability.value}.txt"
    script = iter(
        [{"tool": "write_file", "args": {"path": path, "content": "user edit"}}, conclusion]
    )

    def llm(messages):
        calls.append(messages[-1]["content"])
        return json.dumps(next(script))

    client = AgenticPersonaClient(llm)
    client.bind_session(replace(expert(), d1=ability), ws)
    client.respond("system", f"<{stage}>Check this result.</{stage}>")
    assert ("unknown or unavailable tool" not in calls[1]) is allowed
    assert Path(ws.resolve(path)).is_file() is allowed


def test_simulated_user_edits_are_frozen_with_their_tool_trace(tmp_path):
    ws = workspace(tmp_path)
    harness = Harness(ws)
    check = (
        "from pathlib import Path\n"
        "assert Path('value.txt').read_text() == 'user corrected output\\n'\n"
        "print('user test passed')\n"
    )
    script = iter(
        [
            {"perceive": "starting", "verdict": "unsure", "task_load": "normal"},
            {"intent": "start", "needs_final_check": False, "check_goal": ""},
            {"action": "send_message", "message": "write the file", "gap": False},
            {"tool": "write_file", "args": {"path": "user_notes.txt", "content": "my inspection"}},
            {"perceive": "I want to correct and test it", "verdict": "unsure"},
            {"intent": "check my correction", "needs_final_check": True, "check_goal": "test it"},
            {
                "tool": "write_file",
                "args": {"path": "value.txt", "content": "user corrected output\n"},
            },
            {"tool": "write_file", "args": {"path": "user_check.py", "content": check}},
            {"tool": "run_shell", "args": {"cmd": f"{sys.executable} user_check.py"}},
            {"perceive": "my correction passed my test", "check_status": "completed"},
            {"perceive": "the result includes my correction", "verdict": "satisfied"},
            {"intent": "accept the combined result", "needs_final_check": False, "check_goal": ""},
            {"action": "accept", "message": "I corrected it and checked it", "gap": False},
            {"score": 3, "reason": "I had to correct it myself"},
        ]
    )
    observed = []

    def llm(messages):
        obj = next(script)
        if "tool" in obj:
            assert not harness.closed and not ws._closed
        if "score" in obj:
            assert harness.closed and ws._closed
        observed.append(messages[-1]["content"])
        return json.dumps(obj)

    client = AgenticPersonaClient(llm)
    store = SessionStore(tmp_path / "sessions")
    run = make_sim_run_session_fn(
        client_factory=lambda: client,
        tracker=FakeTracker(),
        store=store,
        sim_personas={PERSONA.identity: expert()},
    )
    session = run(PERSONA, SeedScenario("write the file"), harness, workspace_dir=ws)
    assert "user test passed" in "\n".join(observed)
    assert session.workspace_evidence["actor_freeze"]["status"] == "frozen"
    prediction = store.root.parent / session.workspace_evidence["prediction"]["path"]
    assert "+user corrected output" in prediction.read_text()
    assert "+print('user test passed')" in prediction.read_text()
    restored = store.load(session.session_id).to_dict()
    traces = [call for turn in restored["sim_trace"]["turns"] for call in turn["persona_trace"]]
    own_tools = [
        step for call in traces for step in call.get("steps", []) if step["kind"] == "tool"
    ]
    assert any(
        step["text"].startswith("write_file ") and '"path": "value.txt"' in step["text"]
        for step in own_tools
    )
    assert any(step["text"].startswith("run_shell ") for step in own_tools)
    assert restored["execution_receipt"]["user_assistance"] == "recorded_in_sim_trace"


def test_terminal_stage_cannot_dispatch_authoring_or_shell_tools(tmp_path):
    ws = workspace(tmp_path)
    calls = []
    script = iter(
        [
            {"tool": "write_file", "args": {"path": "value.txt", "content": "reviewer output"}},
            {"tool": "run_shell", "args": {"cmd": "echo reviewer > value.txt"}},
            {"tool": "read_file", "args": {"path": "value.txt"}},
            {"task_assessment": "unknown", "opportunities": [], "score": None},
        ]
    )

    def llm(messages):
        calls.append(messages[-1]["content"])
        return json.dumps(next(script))

    client = AgenticPersonaClient(llm)
    client.bind_session(expert(), ReviewSnapshot({"value.txt": b"actor output"}))
    review = client.respond("system", "<direct_review>Review this output.</direct_review>")
    assert review["task_assessment"] == "unknown"
    assert "unknown or unavailable tool" in calls[1]
    assert "unknown or unavailable tool" in calls[2]
    assert "actor output" in calls[3]
    assert ws.read_text("value.txt") == "baseline\n"


def test_finalizer_runs_once_before_prediction_and_review(tmp_path):
    original = workspace(tmp_path)

    class FinalizingWorkspace(LocalWorkspaceRuntime):
        finalized = 0

        def finalize_task(self):
            self.finalized += 1
            self.write_text("final.txt", "trusted finalization")

    ws = FinalizingWorkspace(original.cwd)
    session = direct(tmp_path, Review())(
        PERSONA, SeedScenario("task"), Harness(ws), workspace_dir=ws
    )
    assert ws.finalized == 1
    prediction = session.workspace_evidence["prediction"]
    data = (tmp_path / prediction["path"]).read_text()
    assert "trusted finalization" in data


def test_declared_persona_input_threshold_is_checked_before_dispatch(monkeypatch):
    monkeypatch.setenv("USER_LLM_MAX_CONTEXT_TOKENS", "10")
    client = ApiPersonaClient.__new__(ApiPersonaClient)
    with pytest.raises(PersonaContextLimitError) as error:
        client._create([{"role": "user", "content": "x" * 1000}], 32768)
    assert error.value.limit == 10 and error.value.attempts == 0


def test_simulated_terminal_review_failure_keeps_frozen_actor_artifacts(tmp_path):
    ws = workspace(tmp_path)
    harness = Harness(ws)

    class Client(ScriptedPersonaClient):
        def _respond_body(self, system, user):
            if "<rate_experience>" in user:
                assert harness.closed and ws._closed
                raise RuntimeError("review service offline")
            return super()._respond_body(system, user)

    sim_persona = expert()
    run = make_sim_run_session_fn(
        client_factory=Client,
        tracker=FakeTracker(),
        store=SessionStore(tmp_path / "sessions"),
        sim_personas={PERSONA.identity: sim_persona},
    )
    session = run(PERSONA, SeedScenario("write the file"), harness, workspace_dir=ws)
    assert session.feeling is None
    assert session.feedback["experience"]["status"] == "unavailable"
    assert (
        session.workspace_evidence["prediction"]["sha256"]
        == session.workspace_evidence["diff_sha256"]
    )
    assert session.workspace_evidence["actor_freeze"]["status"] == "frozen"
