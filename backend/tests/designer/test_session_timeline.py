"""设计师 get_session_timeline：落盘 god-view 原样取用（暂不脱敏）。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_designer.designer.session_timeline import (
    bind_session_store,
    format_session_timeline,
    get_session_timeline,
)
from auto_designer.models import (
    FeelingScore,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    SimTrace,
    SimTurn,
    Transcript,
)
from auto_designer.user.session_store import SessionStore


def _persona() -> Persona:
    return Persona(identity="i", level="l", domain="d", goal="g", speaking_style="s")


def _session_with_trace(*, issue_n: int | None = 7) -> Session:
    turns = [
        SimTurn(
            turn=1,
            phase="opening",
            action_space=["send_task"],
            perceive="Nothing yet; starting timeutils/core.py DST task.",
            verdict="unsure",
            action="send_task",
            message="please fix",
            executor="harness",
            channel="emit",
            patience=5,
            trust="skeptical",
            harness_output="",
        ),
        SimTurn(
            turn=2,
            phase="active",
            action_space=["ask_harness_run"],
            perceive="Looks plausible but I can't verify localize_safe.",
            verdict="unsure",
            action="ask_harness_run",
            message="run it",
            executor="harness",
            channel="emit",
            patience=5,
            trust="skeptical",
            harness_output="I added to_user_tz in timeutils/core.py:\n\ndef f():\n    pass\n",
        ),
    ]
    refs = [IssueRef(number=issue_n, url=f"fake://{issue_n}", state="open")] if issue_n else []
    return Session(
        persona=_persona(),
        scenario=SeedScenario(description="Fix DST in timeutils"),
        transcript=Transcript(turns=[]),
        feeling=FeelingScore(score=1, reason="waited too long then crash"),
        issue_refs=refs,
        sim_trace=SimTrace(
            persona_id="P-1",
            end_reason="issue_filed",
            turns=turns,
            signals=["WAIT_GAP: intent=peek status action=keep_waiting"],
        ),
    )


def test_format_passthrough_keeps_stored_fields(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = _session_with_trace()
    store.save(sess)
    text = format_session_timeline(store.load(sess.session_id))
    data = json.loads(text)
    assert data["session_id"] == sess.session_id
    assert data["feeling"]["score"] == 1
    assert data["sim_trace"]["end_reason"] == "issue_filed"
    # 原样保留落盘内容（含路径/代码片段）
    t2 = data["sim_trace"]["turns"][1]
    assert "timeutils/core.py" in t2["harness_output"]
    assert t2["perceive"] == "Looks plausible but I can't verify localize_safe."


def test_tool_by_issue_and_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = _session_with_trace(issue_n=42)
    store.save(sess)
    assert 42 in store.index()[-1]["issue_numbers"]

    with bind_session_store(store):
        by_issue = get_session_timeline(issue_number=42)
        by_sid = get_session_timeline(session_id=sess.session_id)
    assert by_issue["ok"] is True
    assert by_sid["ok"] is True
    assert by_issue["session_id"] == sess.session_id
    payload = json.loads(by_issue["timeline"])
    assert payload["sim_trace"]["turns"][0]["action"] == "send_task"

    with bind_session_store(store):
        miss = get_session_timeline(issue_number=999)
    assert miss["ok"] is False
