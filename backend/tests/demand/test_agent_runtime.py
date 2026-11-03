# Spec-0029/T2: unit tests for the agent_runtime shared runtime (does not run real nexau; only the pure-logic parts are tested).
"""read_submit four paths (normal/re-encoded/prose/submit not called), run_with_timeout cross-thread contextvars."""

from __future__ import annotations

import json

from ahe_beta.demand.agent_runtime import (
    read_submit,
    run_agent_def,
    run_with_timeout,
)
from ahe_beta.demand.session_timeline import bind_session_store, get_session_timeline
from ahe_beta.usage import current_usage_context
from ahe_beta.user.session_store import SessionStore


def test_read_submit_normal() -> None:
    text = json.dumps({"dispositions": [{"issue": 1, "disposition": "accept"}]})
    assert read_submit(text, "dispositions") == [{"issue": 1, "disposition": "accept"}]


def test_read_submit_double_encoded() -> None:
    inner = json.dumps({"proposals": [{"title": "t", "fields": {}}]})
    assert read_submit(json.dumps(inner), "proposals") == [{"title": "t", "fields": {}}]


def test_read_submit_empty_array_is_valid() -> None:
    assert read_submit('{"proposals": []}', "proposals") == []  # Legitimate "no output this round"


def test_read_submit_no_submit_returns_none() -> None:
    assert (
        read_submit("I did not tune it submit It completed running", "dispositions") is None
    )  # Prose
    assert read_submit("", "dispositions") is None
    assert read_submit('{"other": []}', "dispositions") is None  # Wrong keys
    assert read_submit('{"dispositions": "not-a-list"}', "dispositions") is None


def test_read_submit_filters_non_dict_items() -> None:
    text = json.dumps({"gate_decisions": [{"issue": 1, "disposition": "hold"}, "junk", 3]})
    assert read_submit(text, "gate_decisions") == [{"issue": 1, "disposition": "hold"}]


def test_run_with_timeout_propagates_contextvars(tmp_path) -> None:
    """The store injected by bind_session_store must be readable by the tool in the worker thread (copy_context across threads)."""
    store = SessionStore(tmp_path / "sessions")
    with bind_session_store(store):
        out = run_with_timeout(lambda: get_session_timeline(session_id="nope"), 10)
    assert out["ok"] is False
    assert "not bound" not in out["error"]  # The store is bound across threads
    assert "not found" in out["error"]  # Reaching the "session not found" step = binding succeeded


def test_run_agent_def_uses_explicit_role_instead_of_directory_name(tmp_path, monkeypatch) -> None:
    import nexau

    observed = []

    class FakeConfig:
        max_iterations = 1
        resolved_tracer = None

    class FakeAgentConfig:
        @staticmethod
        def from_yaml(*, config_path):
            assert config_path.name == "agent.yaml"
            return FakeConfig()

    class FakeAgent:
        def __init__(self, *, config):
            self.config = config

        def run(self, *, message):
            observed.append((message, current_usage_context()))
            return {"ok": True}

    monkeypatch.setattr(nexau, "AgentConfig", FakeAgentConfig)
    monkeypatch.setattr(nexau, "Agent", FakeAgent)
    agent_dir = tmp_path / "misleading-directory-name"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text("unused", encoding="utf-8")

    out = run_agent_def(
        agent_dir,
        "review",
        store=SessionStore(tmp_path / "sessions"),
        repo=tmp_path,
        role="owner",
        timeout=5,
    )

    assert json.loads(out) == {"ok": True}
    assert observed[0][1].role == "owner"
    assert observed[0][1].operation == "nexau-agent"


def test_run_with_timeout_raises_on_timeout() -> None:
    import time

    try:
        run_with_timeout(lambda: time.sleep(5), 1)
        raise AssertionError("Should throw TimeoutError")
    except TimeoutError:
        pass


def test_run_agent_def_records_demand_and_keeps_return(tmp_path, monkeypatch) -> None:
    import nexau

    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("AHE_BETA_RUN_ID", "run-x")

    class FakeConfig:
        max_iterations = 1
        resolved_tracer = None

    class FakeAgentConfig:
        @staticmethod
        def from_yaml(*, config_path):
            return FakeConfig()

    class FakeAgent:
        def __init__(self, *, config):
            self.config = config

        def run(self, *, message):
            return {"decisions": []}

    monkeypatch.setattr(nexau, "AgentConfig", FakeAgentConfig)
    monkeypatch.setattr(nexau, "Agent", FakeAgent)
    agent_dir = tmp_path / "owner"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text("unused", encoding="utf-8")

    out = run_agent_def(
        agent_dir,
        "review",
        store=SessionStore(tmp_path / "sessions"),
        repo=tmp_path,
        role="owner",
        timeout=5,
        subject={"kind": "round", "id": "3"},
    )
    assert json.loads(out) == {"decisions": []}
    files = list((tmp_path / "demand").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["side"] == "demand"
    assert data["role"] == "owner"
    assert data["subject"] == {"kind": "round", "id": "3"}
    assert data["output"]["status"] == "success"


def test_run_agent_def_timeout_still_records(tmp_path, monkeypatch) -> None:
    import time

    import nexau

    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))

    class FakeConfig:
        max_iterations = 1
        resolved_tracer = None

    class FakeAgentConfig:
        @staticmethod
        def from_yaml(*, config_path):
            return FakeConfig()

    class FakeAgent:
        def __init__(self, *, config):
            self.config = config

        def run(self, *, message):
            time.sleep(5)
            return "never"

    monkeypatch.setattr(nexau, "AgentConfig", FakeAgentConfig)
    monkeypatch.setattr(nexau, "Agent", FakeAgent)
    agent_dir = tmp_path / "owner"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text("unused", encoding="utf-8")
    captured = []

    try:
        run_agent_def(
            agent_dir,
            "review",
            store=SessionStore(tmp_path / "sessions"),
            repo=tmp_path,
            role="owner",
            timeout=1,
            subject={"kind": "round", "id": "1"},
            on_history=captured.append,
        )
        raise AssertionError("Should throw TimeoutError")
    except TimeoutError:
        pass
    data = json.loads(next((tmp_path / "demand").glob("*.json")).read_text(encoding="utf-8"))
    assert data["output"]["status"] == "timeout"
    assert captured == []  # Never capture history from a still-running timed-out call.


def test_run_agent_def_no_submit_status(tmp_path, monkeypatch) -> None:
    import nexau

    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))

    class FakeConfig:
        max_iterations = 1
        resolved_tracer = None

    class FakeAgentConfig:
        @staticmethod
        def from_yaml(*, config_path):
            return FakeConfig()

    class FakeAgent:
        def __init__(self, *, config):
            self.config = config

        def run(self, *, message):
            return "I did not tune it submit"

    monkeypatch.setattr(nexau, "AgentConfig", FakeAgentConfig)
    monkeypatch.setattr(nexau, "Agent", FakeAgent)
    agent_dir = tmp_path / "owner"
    agent_dir.mkdir()
    (agent_dir / "agent.yaml").write_text("unused", encoding="utf-8")

    out = run_agent_def(
        agent_dir,
        "review",
        store=SessionStore(tmp_path / "sessions"),
        repo=tmp_path,
        role="owner",
        timeout=5,
        subject={"kind": "round", "id": "1"},
    )
    assert out == "I did not tune it submit"
    data = json.loads(next((tmp_path / "demand").glob("*.json")).read_text(encoding="utf-8"))
    assert data["output"]["status"] == "no_submit"
