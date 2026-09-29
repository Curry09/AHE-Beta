"""Spec-0039/T2：Gitea issue timeline 分页与 label 方向归一。"""

from __future__ import annotations

from typing import Any

from auto_designer.tracker import gitea as gitea_module
from auto_designer.tracker.gitea import GiteaTracker
from auto_designer.web.issue_timeline import build_issue_timeline


class _Resp:
    def __init__(self, payload: Any) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = ""
        self.content = b"x"

    def json(self) -> Any:
        return self._payload


class _TimelineSession:
    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.headers: dict[str, str] = {}
        self.pages = pages
        self.calls: list[str] = []

    def request(self, method: str, url: str, json=None, timeout=None):
        assert method == "GET" and timeout is not None
        self.calls.append(url)
        return _Resp(self.pages[len(self.calls) - 1])


def test_list_timeline_pages_and_normalizes_label_direction(monkeypatch):
    monkeypatch.setattr(gitea_module, "_TIMELINE_PAGE_SIZE", 2)
    tracker = GiteaTracker(base_url="http://gitea", owner="o", repo="r", token="t")
    session = _TimelineSession(
        [
            [
                {
                    "id": 1,
                    "type": "label",
                    "body": "1",
                    "label": {"name": "ready"},
                    "user": {"login": "synthesizer"},
                    "created_at": "2026-08-09T10:00:00Z",
                },
                {
                    "id": 2,
                    "type": "label",
                    "body": "",
                    "label": {"name": "proposal"},
                    "user": {"login": "synthesizer"},
                    "created_at": "2026-08-09T10:00:00Z",
                },
            ],
            [
                {
                    "id": 3,
                    "type": "comment",
                    "body": "admit",
                    "user": {"login": "synthesizer"},
                    "created_at": "2026-08-09T10:00:01Z",
                }
            ],
        ]
    )
    tracker._session = session

    events = tracker.list_timeline(number=7)

    assert [event["operation"] for event in events] == ["add", "remove", "unknown"]
    assert events[0]["label"] == "ready" and events[0]["actor"] == "synthesizer"
    assert "page=1&limit=2" in session.calls[0]
    assert "page=2&limit=2" in session.calls[1]


def _event(
    label: str, operation: str, created_at: str, *, actor: str = "synthesizer"
) -> dict[str, Any]:
    return {
        "id": f"{created_at}:{label}:{operation}",
        "type": "label",
        "body": "1" if operation == "add" else "",
        "label": label,
        "operation": operation,
        "actor": actor,
        "created_at": created_at,
    }


def test_replay_normal_needs_human_is_additive_and_preserves_dimensions():
    events = [
        _event("proposal", "add", "2026-08-09T10:00:00Z"),
        _event("from-synthesize", "add", "2026-08-09T10:00:00Z"),
        _event("round-1", "add", "2026-08-09T10:00:00Z"),
        _event("proposal", "remove", "2026-08-09T10:01:00Z"),
        _event("openagents", "add", "2026-08-09T10:01:00Z"),
        _event("P1", "add", "2026-08-09T10:01:00Z"),
        _event("ready", "add", "2026-08-09T10:01:01Z"),
        _event("needs-human", "add", "2026-08-09T10:02:00Z"),
    ]
    result = build_issue_timeline(
        issue={
            "labels": ["from-synthesize", "round-1", "openagents", "P1", "ready", "needs-human"],
            "created_at": "2026-08-09T10:00:00Z",
        },
        events=events,
    )

    assert result["complete"] is True
    assert result["current"]["plane"] == "ready"
    assert result["current"]["blocked"] is True
    assert result["current"]["provenance"] == "from-synthesize"
    assert result["current"]["round"] == 1
    assert result["anomalies"] == []


def test_replay_put_replacement_exposes_metadata_loss_without_backfilling_current():
    events = [
        _event("proposal", "add", "2026-08-09T10:00:00Z"),
        _event("from-synthesize", "add", "2026-08-09T10:00:00Z"),
        _event("round-1", "add", "2026-08-09T10:00:00Z"),
        _event("proposal", "remove", "2026-08-09T10:01:00Z"),
        _event("openagents", "add", "2026-08-09T10:01:00Z"),
        _event("P1", "add", "2026-08-09T10:01:00Z"),
        _event("ready", "add", "2026-08-09T10:01:01Z"),
        _event("needs-human", "add", "2026-08-09T10:02:00Z"),
        _event("openagents", "remove", "2026-08-09T10:02:00Z"),
        _event("ready", "remove", "2026-08-09T10:02:00Z"),
        _event("P1", "remove", "2026-08-09T10:02:00Z"),
        _event("from-synthesize", "remove", "2026-08-09T10:02:00Z"),
        _event("round-1", "remove", "2026-08-09T10:02:00Z"),
    ]
    result = build_issue_timeline(
        issue={"labels": ["needs-human"], "created_at": "2026-08-09T10:00:00Z"},
        events=events,
    )

    assert result["current"]["plane"] is None
    assert result["current"]["provenance"] is None
    assert result["last_known"] == {
        "plane": "ready",
        "provenance": "from-synthesize",
        "priority": "P1",
        "round": 1,
    }
    codes = {anomaly["code"] for anomaly in result["anomalies"]}
    assert {
        "plane-drop-without-terminal",
        "provenance-lost",
        "priority-lost",
        "round-lost",
        "blocking-destroyed-metadata",
    } <= codes
    assert result["transitions"][-1]["title"] == "标签完整性异常"


def test_replay_reports_exclusive_conflict_incomplete_history_and_current_drift():
    events = [
        _event("proposal", "add", "2026-08-09T10:05:00Z"),
        _event("from-synthesize", "add", "2026-08-09T10:05:00Z"),
        _event("from-triage", "add", "2026-08-09T10:05:00Z"),
    ]
    result = build_issue_timeline(
        issue={"labels": ["ready"], "created_at": "2026-08-09T10:00:00Z"},
        events=events,
    )

    codes = {anomaly["code"] for anomaly in result["anomalies"]}
    assert result["complete"] is False
    assert {
        "exclusive-dimension-conflict",
        "incomplete-history",
        "timeline-current-drift",
    } <= codes
    assert result["current"]["plane"] == "ready", "当前标签仍是真值，不以回放结果覆盖"
