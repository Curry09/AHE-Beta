"""divergent 落候选 + designer.gate_once 晋升（stub agent，不跑真 LLM）。"""

from __future__ import annotations

from pathlib import Path

from auto_designer.designer.designer import Designer, GateOutcome
from auto_designer.designer.divergent import Divergent, DivergentOutcome
from auto_designer.designer.issue_schema import (
    DIVERGENT,
    RFC_LABEL,
    TRIAGED,
)
from auto_designer.models import (
    FeelingScore,
    IssueDraft,
    Persona,
    SeedScenario,
    Session,
    Transcript,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _seed_session(store: SessionStore, *, score: int = 3) -> None:
    store.save(
        Session(
            persona=_persona(),
            scenario=SeedScenario(description="s"),
            transcript=Transcript(turns=[]),
            feeling=FeelingScore(score=score, reason="timeout then ask status"),
        )
    )


def _rfc_fields() -> dict:
    return {
        "问题": "用户反复用聊天补状态交接",
        "根因": "产品面缺少可触发的状态契约",
        "涉及 issue": "session=abc",
        "方向": "默认行为 + 显式触发",
        "验收": "timeout 后追问状态轮次下降",
    }


class _StubDivergent(Divergent):
    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned

    def _run_agent(self, **_kwargs) -> str:
        return self._canned


class _StubGateDesigner(Designer):
    def __init__(self, *args, canned: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._canned = canned
        self.gate_calls = 0

    def _run_agent(self, **_kwargs) -> str:
        return "[]"

    def _run_gate_agent(self, **_kwargs) -> str:
        self.gate_calls += 1
        return self._canned


def test_divergent_creates_unclaimable_candidates(tmp_path: Path) -> None:
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store)
    canned = (
        '[{"title": "状态交接产品化", "fields": '
        + str(_rfc_fields()).replace("'", '"')
        + "}]"
    )
    # proper json
    import json

    canned = json.dumps(
        [{"title": "状态交接产品化", "fields": _rfc_fields()}], ensure_ascii=False
    )
    d = _StubDivergent(
        tracker,
        store,
        str(tmp_path / "harness"),
        str(tmp_path / "agent"),
        canned=canned,
        round_provider=lambda: 2,
    )
    out = d.propose_once()
    assert isinstance(out, DivergentOutcome)
    assert out.count == 1
    issues = tracker.list_open_issues()
    assert len(issues) == 1
    assert DIVERGENT in issues[0].labels
    assert "round-2" in issues[0].labels
    assert TRIAGED not in issues[0].labels
    assert RFC_LABEL not in issues[0].labels


def test_gate_promote_hold_drop(tmp_path: Path) -> None:
    import json

    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    _seed_session(store)
    a = tracker.create_issue(
        IssueDraft(title="cand-a", body="x", labels=[DIVERGENT, "round-1"])
    )
    b = tracker.create_issue(
        IssueDraft(title="cand-b", body="y", labels=[DIVERGENT, "round-1"])
    )
    c = tracker.create_issue(
        IssueDraft(title="cand-c", body="z", labels=[DIVERGENT, "round-2"])
    )
    canned = json.dumps(
        [
            {"issue": a.number, "disposition": "promote", "note": "两轮仍出现"},
            {"issue": b.number, "disposition": "hold", "note": "再看一轮"},
            {"issue": c.number, "disposition": "drop", "note": "已被 RFC 覆盖"},
        ],
        ensure_ascii=False,
    )
    g = _StubGateDesigner(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent"), canned=canned
    )
    out = g.gate_once()
    assert isinstance(out, GateOutcome)
    assert out.promoted == [a.number]
    assert b.number in out.held
    assert out.dropped == [c.number]

    open_issues = {i.number: i for i in tracker.list_open_issues()}
    assert a.number in open_issues
    assert DIVERGENT not in open_issues[a.number].labels
    assert TRIAGED in open_issues[a.number].labels
    assert "feature" in open_issues[a.number].labels
    assert b.number in open_issues
    assert DIVERGENT in open_issues[b.number].labels
    assert c.number not in open_issues  # dropped closed


def test_gate_skips_llm_when_no_candidates(tmp_path: Path) -> None:
    tracker = FakeTracker()
    store = SessionStore(tmp_path / "sessions")
    g = _StubGateDesigner(
        tracker, store, str(tmp_path / "harness"), str(tmp_path / "agent"), canned="[]"
    )
    out = g.gate_once()
    assert out.promoted == out.held == out.dropped == []
    assert g.gate_calls == 0


def test_orchestrator_order_includes_divergent_and_gate(tmp_path: Path) -> None:
    """d 段顺序：triage → (synth∥divergent) → gate → b。"""
    import subprocess

    from auto_designer.dev.agentic_developer import DevOutcome
    from auto_designer.loop.orchestrator import Orchestrator
    from auto_designer.models import Persona, SeedScenario

    repo = tmp_path / "harness"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "f").write_text("v0\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@x",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "seed",
        ],
        check=True,
        capture_output=True,
    )

    events: list[str] = []

    class _L:
        def launch(self, ref, workspace_dir=None):
            return ("h", ref)

    class _T:
        def triage_once(self):
            events.append("triage")

    class _D:
        def propose_once(self):
            events.append("synthesize")

        def gate_once(self):
            events.append("gate")
            return GateOutcome()

    class _V:
        def propose_once(self):
            events.append("divergent")
            return DivergentOutcome()

    class _Dev:
        def work_one(self, skip=None):
            events.append("dev")
            return DevOutcome()

    def run_session(persona, scenario, harness, *, workspace_dir=None):
        events.append("session")

    orch = Orchestrator(
        launcher=_L(),
        harness_repo=str(repo),
        fixed_set=[
            (
                Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s"),
                SeedScenario(description="s"),
            )
        ],
        developer_agents=[_Dev()],
        run_session_fn=run_session,
        initial_ref="main",
        triagers=[_T()],
        designers=[_D()],
        divergents=[_V()],
    )
    orch.run_round("main")
    # session then triage; synth∥divergent 顺序不定；gate 在二者之后；dev 最后
    assert events[0] == "session"
    assert events[1] == "triage"
    assert set(events[2:4]) == {"synthesize", "divergent"}
    assert events[4] == "gate"
    assert events[5] == "dev"
