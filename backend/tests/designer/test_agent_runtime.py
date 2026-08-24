# Spec-0029/T2：agent_runtime 公共运行时单测（不跑真 nexau，只测纯逻辑部分）。
"""read_submit 四路（正常/再编码/散文/未调 submit）、run_with_timeout 跨线程 contextvars、norm_label。"""

from __future__ import annotations

import json

from auto_designer.designer.agent_runtime import (
    norm_label,
    read_submit,
    run_agent_def,
    run_with_timeout,
)
from auto_designer.designer.session_timeline import bind_session_store, get_session_timeline
from auto_designer.usage import current_usage_context
from auto_designer.user.session_store import SessionStore


def test_read_submit_normal() -> None:
    text = json.dumps({"dispositions": [{"issue": 1, "disposition": "accept"}]})
    assert read_submit(text, "dispositions") == [{"issue": 1, "disposition": "accept"}]


def test_read_submit_double_encoded() -> None:
    inner = json.dumps({"proposals": [{"title": "t", "fields": {}}]})
    assert read_submit(json.dumps(inner), "proposals") == [{"title": "t", "fields": {}}]


def test_read_submit_empty_array_is_valid() -> None:
    assert read_submit('{"proposals": []}', "proposals") == []  # 合法的「本轮无产出」


def test_read_submit_no_submit_returns_none() -> None:
    assert read_submit("我没调 submit 就跑完了", "dispositions") is None  # 散文
    assert read_submit("", "dispositions") is None
    assert read_submit('{"other": []}', "dispositions") is None  # 键不对
    assert read_submit('{"dispositions": "not-a-list"}', "dispositions") is None


def test_read_submit_filters_non_dict_items() -> None:
    text = json.dumps({"gate_decisions": [{"issue": 1, "disposition": "hold"}, "junk", 3]})
    assert read_submit(text, "gate_decisions") == [{"issue": 1, "disposition": "hold"}]


def test_run_with_timeout_propagates_contextvars(tmp_path) -> None:
    """bind_session_store 注入的 store 须能被 worker 线程里的 tool 读到（copy_context 跨线程）。"""
    store = SessionStore(tmp_path / "sessions")
    with bind_session_store(store):
        out = run_with_timeout(lambda: get_session_timeline(session_id="nope"), 10)
    assert out["ok"] is False
    assert "not bound" not in out["error"]  # store 已跨线程绑定上
    assert "not found" in out["error"]  # 到了「查不到该 session」这步 = 绑定成功


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
        raise AssertionError("应抛 TimeoutError")
    except TimeoutError:
        pass


def test_norm_label_whitespace_tolerant() -> None:
    assert norm_label("涉及 issue") == norm_label("涉及issue") == "涉及issue"
    assert norm_label("  根因  区域 ") == "根因区域"
