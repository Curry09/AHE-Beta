"""Adapter for sim user agent closed-loop integration (loop/sim_user.py).

Offline verification using Fake tracker + ScriptedPersonaClient + ScriptedHarness: adapter runs sim, persists issue_artifact to tracker, converts SessionResult to models.Session into store, per-turn and end-of-turn callbacks on_turn.
"""

from __future__ import annotations

import pytest

from ahe_beta.loop.sim_user import (
    _infer_kind,
    _issue_draft_from_body,
    make_sim_run_session_fn,
    result_to_sim_trace,
    result_to_turns,
)
from ahe_beta.models import Persona, SeedScenario, Session, WorkspaceSpec
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import bind_usage_context
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.loop import SessionResult, TurnLog
from ahe_beta.user.sim.persona_client import ScriptedPersonaClient
from ahe_beta.user.sim.run_live import expert


class _NonGitWorkspace:
    def __init__(self, cwd):
        self.cwd = cwd
        self.evidence = {"patch_capability": "not_applicable"}

    def freeze_patch_base(self):
        pass

    def export_patch(self):
        return "", ""

    def review_file_listing(self):
        return {"returncode": 0, "stdout": ""}

    def close(self):
        pass


def _turn(
    turn: int,
    action: str,
    channel: str,
    message: str,
    harness_output: str,
    *,
    perceive: str = "",
    verdict: str = "unsure",
    phase: str = "active",
) -> TurnLog:
    return TurnLog(
        turn=turn,
        phase=phase,
        action_space=[],
        perceive=perceive,
        verdict=verdict,
        action=action,
        message=message,
        executor="x",
        channel=channel,
        patience=3,
        trust="ok",
        harness_output=harness_output,
    )


def test_result_to_turns_dedupes_repeated_harness_snapshot() -> None:
    """harness_output is a snapshot of 'the previous round's reply as seen by this round's persona', potentially repeated across rounds with no new replies.

    result_to_turns must deduplicate by 'true new harness reply' only; otherwise the same reply expands into multiple harness rounds, misaligning with user.
    """
    completion = '{"result": "done: split_bill implemented"}'
    res = SessionResult(
        persona_id="P-0991",
        end_reason="accepted",
        turns=[
            _turn(0, "send_message", "emit", "Please inspect billing/core.py ...", ""),
            _turn(1, "silent_reflect", "silent", "", completion),  # Snapshot same completion
            _turn(2, "silent_reflect", "silent", "", completion),
            _turn(3, "silent_reflect", "silent", "", completion),
            _turn(4, "accept", "emit", "Looks good, thanks.", completion),
        ],
    )

    turns = result_to_turns(res)

    # accept is a local terminal note in persona, not a user turn sent to harness
    roles = [t.role for t in turns]
    assert roles == ["user", "harness"]
    assert turns[1].content == completion
    assert turns[0].content.startswith("Please inspect")


def test_result_to_sim_trace_keeps_perceive_alongside_dialogue() -> None:
    """God-view projection preserves reasoning; message/harness_output aligns with perceive on the same row, no post-hoc reconciliation needed."""
    res = SessionResult(
        persona_id="P-0991",
        end_reason="abandoned",
        turns=[
            _turn(
                0,
                "send_message",
                "emit",
                "fix DST",
                "",
                perceive="starting",
                verdict="unsure",
            ),
            _turn(
                1,
                "keep_waiting",
                "silent",
                "",
                "still working...",
                perceive="[stuck|peek→keep_waiting] spinner",
                verdict="stuck",
                phase="waiting",
            ),
        ],
        signals=["WAIT_GAP: intent=peek action=keep_waiting"],
    )
    trace = result_to_sim_trace(res)
    assert trace.persona_id == "P-0991"
    assert trace.end_reason == "abandoned"
    assert trace.signals == ["WAIT_GAP: intent=peek action=keep_waiting"]
    assert len(trace.turns) == 2
    assert trace.turns[0].message == "fix DST"
    assert trace.turns[0].perceive == "starting"
    assert trace.turns[1].phase == "waiting"
    assert "peek" in trace.turns[1].perceive
    assert trace.turns[1].harness_output == "still working..."


def test_result_to_turns_includes_pending_harness_reply() -> None:
    """Live snapshot: pending harness replies already received but not yet logged with the next TurnLog must be included in conversation; otherwise the dashboard shows only user messages with no replies during long harness tasks. Deduplicate against the last logged reply snapshot."""
    res = SessionResult(
        persona_id="P-0991",
        end_reason="max_turns",
        turns=[_turn(1, "send_message", "emit", "Implement the interpreter ...", "")],
        pending_harness_output="done: interpreter implemented",
    )
    turns = result_to_turns(res)
    assert [(t.role, t.content) for t in turns] == [
        ("user", "Implement the interpreter ..."),
        ("harness", "done: interpreter implemented"),
    ]

    # Pending content identical to the last logged harness snapshot → treat as same row, no duplication
    res.turns.append(_turn(2, "send_message", "emit", "again", "done: interpreter implemented"))
    roles = [t.role for t in result_to_turns(res)]
    assert roles == ["user", "harness", "user"]


def _model_persona(sp) -> Persona:
    return Persona(
        identity=sp.persona_id,
        level=sp.d1.value,
        domain="/".join(sp.d2.stack) or "general",
        goal="task",
        speaking_style="s",
    )


def test_sim_adapter_files_issue_saves_session_and_emits(tmp_path) -> None:
    # Coerce evidence → file_issue (deterministically raise issue under ScriptedPersonaClient×ScriptedHarness)
    sp = expert()
    mp = _model_persona(sp)
    tracker = FakeTracker()
    store = SessionStore(tmp_path)
    seen: list[tuple[bool, str | None]] = []

    fn = make_sim_run_session_fn(
        # Spec-0017/T2: factory injection, create fresh per session
        client_factory=ScriptedPersonaClient,
        tracker=tracker,
        store=store,
        sim_personas={mp.identity: sp},
        on_turn=lambda ident, sim_p, res, running, *, session_id=None: seen.append(
            (running, session_id)
        ),
    )
    session = fn(mp, SeedScenario(description="task"), ScriptedHarness())

    assert isinstance(session, Session)
    assert session.persona.identity == sp.persona_id
    # issue truly persisted to tracker, session holds receipt
    open_issues = tracker.list_open_issues()
    assert len(open_issues) == 1
    assert "bug" in open_issues[0].labels
    assert session.issue_refs and session.issue_refs[0].number == open_issues[0].number
    # session persisted, readable on retrieval
    loaded = store.load(session.session_id)
    assert loaded.session_id == session.session_id
    # god-view also persisted: reasoning and decision timeline readable on retrieval
    assert session.sim_trace is not None
    assert loaded.sim_trace is not None
    assert loaded.sim_trace.persona_id == sp.persona_id
    assert loaded.sim_trace.turns  # at least one decision round
    assert any(t.perceive or t.verdict or t.action for t in loaded.sim_trace.turns)
    # user agent raw invocation: full system/user persisted (for downstream KV reuse analysis)
    assert any(t.persona_trace for t in loaded.sim_trace.turns)
    first_call = next(c for t in loaded.sim_trace.turns for c in t.persona_trace)
    assert first_call.role in ("decide", "main_judge", "main_judge_intent")
    assert first_call.system  # complete system text as-is
    assert first_call.user
    assert first_call.parsed  # at least one contract field
    assert loaded.sim_trace.persona_tail  # file_issue / rate called at end of session
    assert {c.role for c in loaded.sim_trace.persona_tail} >= {"file_issue", "rate"}
    # per-round callback (multiple True, no session_id) + final callback once False (with session_id for dashboard archive correlation)
    assert seen and seen[-1] == (False, session.session_id)
    assert any(running for running, _ in seen[:-1])
    assert all(sid is None for _, sid in seen[:-1])


def test_recovery_context_supplies_stable_session_id_and_loader(tmp_path) -> None:
    sp = expert()
    mp = _model_persona(sp)
    store = SessionStore(tmp_path)
    fn = make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,
        tracker=FakeTracker(),
        store=store,
        sim_personas={mp.identity: sp},
    )
    with bind_usage_context(session_id="op-stable-session", round_no=1):
        session = fn(mp, SeedScenario(description="task"), ScriptedHarness())
    assert session.session_id == "op-stable-session"
    assert fn.load_completed_session("op-stable-session") == session


def test_issue_side_effect_is_reconciled_after_crash_before_session_save(tmp_path) -> None:
    sp = expert()
    mp = _model_persona(sp)
    tracker = FakeTracker()

    class FailOnceStore(SessionStore):
        failed = False

        def save(self, session):
            if not self.failed:
                self.failed = True
                raise RuntimeError("injected after issue create")
            return super().save(session)

    store = FailOnceStore(tmp_path)
    fn = make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,
        tracker=tracker,
        store=store,
        sim_personas={mp.identity: sp},
    )
    with bind_usage_context(session_id="op-stable-session", round_no=1):
        with pytest.raises(RuntimeError, match="injected"):
            fn(mp, SeedScenario(description="task"), ScriptedHarness())
    with bind_usage_context(session_id="op-stable-session", round_no=1):
        session = fn(mp, SeedScenario(description="task"), ScriptedHarness())
    assert len(tracker.list_open_issues()) == 1
    assert len(session.issue_refs) == 1


def test_sim_adapter_wraps_harness_in_connector(tmp_path, monkeypatch) -> None:
    """sim_user integrates with harness only through platform connector; text sent to harness remains human-like."""
    sp = expert()
    mp = _model_persona(sp)
    seen = []

    class _SpyConnector:
        def __init__(self, harness) -> None:
            self._harness = harness
            self.sent: list[str] = []
            self.help_text = getattr(harness, "help_text", "")
            seen.append(self)

        def send(self, message: str) -> str:
            return self.send_user_message(message)

        def send_user_message(self, text: str) -> str:
            self.sent.append(text)
            return self._harness.send(text)

        def reset(self) -> None:
            self._harness.reset()

        def close(self) -> None:
            self._harness.close()

    monkeypatch.setattr("ahe_beta.loop.sim_user.HarnessConnector", _SpyConnector)
    fn = make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
        sim_personas={mp.identity: sp},
        round_provider=lambda: 9,
    )

    fn(mp, SeedScenario(description="task"), ScriptedHarness())

    assert len(seen) == 1
    assert seen[0].sent
    joined = "\n".join(seen[0].sent).lower()
    forbidden_platform_terms = (
        "round-9",
        "persona",
        "sim_trace",
        "feeling",
        "triage",
        "needs-triage",
    )
    for term in forbidden_platform_terms:
        assert term not in joined


def test_sim_adapter_no_issue_when_not_filed(tmp_path) -> None:
    sp = expert()
    mp = _model_persona(sp)
    tracker = FakeTracker()
    store = SessionStore(tmp_path)

    # client always satisfied → will not file_issue → should have no issue persisted to store
    class _HappyClient:
        def respond(self, system: str, user: str) -> dict:
            if "<rate_experience>" in user:
                return {"score": 4, "reason": "great"}
            if "<main_judge>" in user or "<main_judge_intent>" in user:
                return {
                    "perceive": "",
                    "verdict": "satisfied",
                    "intent": "accept",
                    "task_load": "normal",
                }
            if "<main_intent>" in user:
                return {"intent": "accept"}
            return {
                "perceive": "",
                "verdict": "satisfied",
                "action": "accept",
                "message": "ok",
                "gap": False,
            }

    fn = make_sim_run_session_fn(
        client_factory=_HappyClient, tracker=tracker, store=store, sim_personas={mp.identity: sp}
    )
    session = fn(mp, SeedScenario(description="task"), ScriptedHarness())

    assert session.issue_refs == []
    assert tracker.list_open_issues() == []


def test_sim_adapter_flushes_mid_session_issue_notes(tmp_path) -> None:
    """report_issue notes mid-session and terminal artifact are created together in create_issue; behavior unchanged when notes absent."""
    sp = expert()
    mp = _model_persona(sp)
    tracker = FakeTracker()
    store = SessionStore(tmp_path)

    class _NoteClient:
        def respond(self, system: str, user: str) -> dict:
            if "<rate_experience>" in user:
                return {"score": 3, "reason": "ok"}
            if "<file_issue>" in user:
                return {"issue": "terminal voice issue"}
            if "<main_judge>" in user or "<main_judge_intent>" in user:
                return {
                    "perceive": "",
                    "verdict": "failed_blame_harness",
                    "intent": "file an issue",
                    "task_load": "normal",
                }
            if "<main_intent>" in user:
                return {
                    "intent": "start, then file an issue",
                    "needs_final_check": False,
                    "check_goal": "",
                }
            if "<main_act>" in user and "['send_message']" in user:
                return {
                    "action": "send_message",
                    "message": "please investigate the rounding bug",
                    "gap": False,
                }
            return {
                "perceive": "",
                "verdict": "failed_blame_harness",
                "action": "file_issue",
                "message": "filing",
                "gap": False,
            }

        def drain_issue_notes(self) -> list[str]:
            # Drained after first round respond; one-time marker used here to simulate mid-session recording
            notes = getattr(self, "_notes", ["mid-session: rounding bug"])
            self._notes = []
            return notes

    fn = make_sim_run_session_fn(
        client_factory=_NoteClient, tracker=tracker, store=store, sim_personas={mp.identity: sp}
    )
    session = fn(mp, SeedScenario(description="task"), ScriptedHarness())

    open_issues = tracker.list_open_issues()
    assert len(open_issues) == 2
    bodies = [i.body for i in open_issues]
    assert any("mid-session: rounding bug" in body for body in bodies)
    assert any("terminal voice issue" in b for b in bodies)
    assert len(session.issue_refs) == 2


def _fn(tmp_path):
    sp = expert()
    mp = _model_persona(sp)
    return make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
        sim_personas={mp.identity: sp},
    ), mp


def test_client_factory_gives_each_session_its_own_instance(tmp_path) -> None:
    """Spec-0017/T2: One instance per session—factory invoked per session, bind_session does not overwrite (root fix for concurrent cross-session). Use recording-style fake: record both factory-produced instances and (persona, workspace) each instance binds to. Run two sessions concurrently (thread barrier synchronized), assert each session's instances are independent and each binds its own workspace."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    sp = expert()
    mp = _model_persona(sp)

    class _RecordingClient(ScriptedPersonaClient):
        def __init__(self) -> None:
            super().__init__()
            self.bound: list[tuple[object, str | None]] = []

        def bind_session(self, *, persona, workspace_dir) -> None:
            self.bound.append((persona, workspace_dir))

    made: list[_RecordingClient] = []

    def factory() -> _RecordingClient:
        c = _RecordingClient()
        made.append(c)
        return c

    fn = make_sim_run_session_fn(
        client_factory=factory,
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
        sim_personas={mp.identity: sp},
    )

    barrier = threading.Barrier(2)

    def one(ws: str) -> None:
        barrier.wait()
        fn(
            mp,
            SeedScenario(description="task"),
            ScriptedHarness(),
            workspace_dir=_NonGitWorkspace(ws),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, ["/ws/a", "/ws/b"]))

    assert len(made) == 2 and made[0] is not made[1]  # Independent instance per session
    # Each client first sees its own interaction workspace, then its own immutable terminal view.
    all_bound = [c.bound for c in made]
    assert all(len(b) == 2 for b in all_bound)
    assert {b[0][1].cwd for b in all_bound} == {"/ws/a", "/ws/b"}
    assert all(b[1][1].runtime_id == "review-snapshot" for b in all_bound)


def test_fallback_materialize_then_ensure_deps(tmp_path, monkeypatch) -> None:
    """Spec-0009/T3: Direct fallback bypass orchestrator—when workspace_dir not provided but scenario carries workspace, run() materializes itself and must symmetrically call ensure_deps after materialization (order: materialize first)."""
    events: list = []
    monkeypatch.setattr(
        "ahe_beta.loop.sim_user.materialize_workspace",
        lambda spec: (
            events.append(("materialize", spec.fixture)) or _NonGitWorkspace(f"/ws/{spec.fixture}")
        ),
    )
    monkeypatch.setattr(
        "ahe_beta.loop.sim_user.ensure_deps",
        lambda ws, spec: events.append(("ensure_deps", ws)),
    )
    fn, mp = _fn(tmp_path)
    scenario = SeedScenario(
        description="task",
        workspace=WorkspaceSpec(fixture="funcy", setup=["python -m venv .venv"]),
    )

    fn(mp, scenario, ScriptedHarness())  # No workspace_dir provided → take fallback branch

    assert events[0] == ("materialize", "funcy")
    assert events[1][0] == "ensure_deps"
    assert events[1][1].cwd == "/ws/funcy"


def test_main_path_does_not_ensure_deps_in_sim_user(tmp_path, monkeypatch) -> None:
    """Orchestrator main path with workspace_dir provided: dependencies already staged by orchestrator, sim_user does not repeat materialize/ensure_deps (inverse assertion)."""
    monkeypatch.setattr(
        "ahe_beta.loop.sim_user.materialize_workspace",
        lambda spec: (_ for _ in ()).throw(AssertionError("Main path should not materialize")),
    )
    monkeypatch.setattr(
        "ahe_beta.loop.sim_user.ensure_deps",
        lambda ws, spec: (_ for _ in ()).throw(AssertionError("Main path should not ensure_deps")),
    )
    fn, mp = _fn(tmp_path)
    scenario = SeedScenario(
        description="task",
        workspace=WorkspaceSpec(fixture="funcy", setup=["python -m venv .venv"]),
    )

    # workspace_dir provided (orchestrator already materialized+ensured) → sim_user no longer touches these two, pass if no exception thrown
    fn(mp, scenario, ScriptedHarness(), workspace_dir=_NonGitWorkspace("/given/ws"))


# ---- Spec-0025/T2: Raw issue structuring—tentative type + needs-triage + round labels ----


def test_infer_kind_defaults_bug_and_detects_feature() -> None:
    assert _infer_kind("Package installation failed，Abandoned after repeated timeouts") == "bug"
    assert _infer_kind("Please add a batch export feature") == "feature"
    assert _infer_kind("would be nice to add a dark mode") == "feature"
    assert _infer_kind("I hope the report can include a summary") == "feature"
    assert _infer_kind("Can you export the results as CSV?") == "feature"
    assert _infer_kind("Please support batch imports") == "feature"


def test_raw_issue_labels_type_and_needs_triage() -> None:
    draft = _issue_draft_from_body("unidecode Installation failed，Abandoned after timeout")
    assert "bug" in draft.labels  # Tentative type (triage will confirm)
    assert "needs-triage" in draft.labels  # Awaiting triage, dev does not claim
    # Do not add label when no round number
    assert not any(lb.startswith("round-") for lb in draft.labels)


def test_raw_issue_stamps_round_when_given() -> None:
    draft = _issue_draft_from_body("Broken", round_no=3)
    assert "round-3" in draft.labels
    assert "needs-triage" in draft.labels


def test_round_provider_threads_round_into_issue(tmp_path) -> None:
    sp = expert()
    mp = _model_persona(sp)
    tracker = FakeTracker()
    store = SessionStore(tmp_path)
    fn = make_sim_run_session_fn(
        client_factory=ScriptedPersonaClient,
        tracker=tracker,
        store=store,
        sim_personas={mp.identity: sp},
        round_provider=lambda: 5,  # Spec-0025/T6 will pass actual round number, fixed to 5 here
    )
    fn(mp, SeedScenario(description="task"), ScriptedHarness())
    issues = tracker.list_open_issues()
    assert issues and "round-5" in issues[0].labels and "needs-triage" in issues[0].labels
