"""harness 种子 entry.py 的 _reply 鲁棒性单测：空回复不得静默通过（不依赖真 nexau/网络）。

entry.py 在 harness_template/（非包），用 importlib 按路径加载；_reply 仅依赖 agent.run，注入假 agent。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_ENTRY = Path(__file__).resolve().parents[2] / "harness_template" / "entry.py"


def _load_entry() -> ModuleType:
    spec = importlib.util.spec_from_file_location("harness_template_entry", _ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Agent:
    """按预设序列逐次返回；Exception 项被 raise，其余原样返回。记录调用次数。"""

    def __init__(self, outs: list) -> None:
        self._outs = list(outs)
        self.calls = 0

    def run(self, *, message: str):
        value = self._outs[self.calls]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture()
def entry(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load_entry()
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)  # 退避不真睡
    return module


def _no_rebuild():
    """非超时用例不该触发重建；若被调用即失败。"""
    raise AssertionError("rebuild 不应被调用")


def test_reply_returns_nonempty_text(entry: ModuleType) -> None:
    agent = _Agent(["hello"])
    out_agent, text = entry._reply(agent, "hi", _no_rebuild)
    assert text == "hello"
    assert out_agent is agent  # 未重建，沿用同实例
    assert agent.calls == 1


def test_reply_retries_on_blank_then_succeeds(entry: ModuleType) -> None:
    agent = _Agent(["", "   ", "real answer"])
    out_agent, text = entry._reply(agent, "hi", _no_rebuild)
    assert text == "real answer"
    assert out_agent is agent  # 空回复同 agent 重试，不重建
    assert agent.calls == 3  # 空串/纯空白都触发重试


def test_reply_all_blank_returns_explicit_marker(entry: ModuleType) -> None:
    agent = _Agent(["", "", "", ""])
    _, out = entry._reply(agent, "hi", _no_rebuild)
    assert out != ""  # 关键：绝不静默返回空
    assert out.startswith("[harness error]")


def test_reply_exception_then_marker(entry: ModuleType) -> None:
    agent = _Agent(
        [RuntimeError("502"), RuntimeError("502"), RuntimeError("502"), RuntimeError("502")]
    )
    _, out = entry._reply(agent, "hi", _no_rebuild)
    assert out.startswith("[harness error]")


def test_reply_timeout_rebuilds_agent_then_succeeds(entry: ModuleType) -> None:
    """超时分支：放弃的旧 agent 持锁不可用 → 重建新 agent 续跑，回传 live agent。"""
    stale = _Agent([TimeoutError("agent.run 超时 >240s")])
    fresh = _Agent(["after rebuild"])
    out_agent, text = entry._reply(stale, "hi", lambda: fresh)
    assert text == "after rebuild"
    assert out_agent is fresh  # 已切到重建后的新实例
    assert stale.calls == 1 and fresh.calls == 1
