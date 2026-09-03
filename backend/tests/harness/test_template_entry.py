"""harness 种子 entry.py 的 _reply 鲁棒性单测：空回复不得静默通过（不依赖真 nexau/网络）。

entry.py 在 harness_template/（非包），用 importlib 按路径加载；_reply 仅依赖 agent.run，注入假 agent。
"""

from __future__ import annotations

import importlib.util
import queue
import threading
from pathlib import Path
from types import ModuleType

import pytest

_ENTRY = Path(__file__).resolve().parents[2] / "harness_template" / "entry.py"
_TEMPLATE = _ENTRY.parent


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
        self.history: list = []

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


def _no_rebuild(_stale):
    """非超时用例不该触发重建；若被调用即失败。"""
    raise AssertionError("rebuild 不应被调用")


def test_meta_spec_documents_baseline_and_changeability() -> None:
    """Meta-Spec 提供项目基线，但不把当前实现冻结成不可修改。"""
    text = (_TEMPLATE / "META_SPEC.md").read_text(encoding="utf-8")
    assert "session_id" in text
    assert "NexAU" in text and "均可修改" in text
    assert "不是实现冻结清单" in text


def test_reply_returns_nonempty_text(entry: ModuleType) -> None:
    agent = _Agent(["hello"])
    out_agent, text, status = entry._reply(agent, "hi", _no_rebuild)
    assert text == "hello"
    assert status == "completed"
    assert out_agent is agent  # 未重建，沿用同实例
    assert agent.calls == 1


def test_reply_retries_on_blank_then_succeeds(entry: ModuleType) -> None:
    agent = _Agent(["", "   ", "real answer"])
    out_agent, text, status = entry._reply(agent, "hi", _no_rebuild)
    assert text == "real answer"
    assert status == "completed"
    assert out_agent is agent  # 空回复同 agent 重试，不重建
    assert agent.calls == 3  # 空串/纯空白都触发重试


def test_reply_all_blank_returns_explicit_marker(entry: ModuleType) -> None:
    agent = _Agent(["", "", "", ""])
    _, out, status = entry._reply(agent, "hi", _no_rebuild)
    assert out != ""  # 关键：绝不静默返回空
    assert out.startswith("[harness error]")
    assert status == "crashed"


def test_reply_exception_then_marker(entry: ModuleType) -> None:
    agent = _Agent(
        [RuntimeError("502"), RuntimeError("502"), RuntimeError("502"), RuntimeError("502")]
    )
    _, out, status = entry._reply(agent, "hi", _no_rebuild)
    assert out.startswith("[harness error]")
    assert status == "crashed"


def test_run_supervised_has_no_wall_clock_timeout(entry: ModuleType) -> None:
    """慢 agent 只能由完成或 persona interrupt 结束，不再被 harness deadline 丢弃。"""

    release = threading.Event()

    class SlowAgent:
        def run(self, *, message: str):  # noqa: ARG002
            release.wait()
            return "finished"

    box: dict = {}
    worker = threading.Thread(
        target=lambda: box.setdefault("out", entry._run_supervised(SlowAgent(), "hi", None))
    )
    worker.start()
    assert worker.is_alive()
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert box["out"] == "finished"


def test_snapshot_and_restore_history_roundtrip(entry: ModuleType) -> None:
    """_snapshot_history / _restore_history：rebuild 接线用的纯辅助，不依赖真 nexau。"""
    src = _Agent([])
    src.history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    snap = entry._snapshot_history(src)
    dst = _Agent([])
    entry._restore_history(dst, snap)
    assert dst.history == src.history


class _StopExec:
    """假 executor：force_stop 置位 stopped 事件（模拟 nexau 优雅停止原语，线程安全）。"""

    def __init__(self) -> None:
        self.stopped = threading.Event()

    def force_stop(self) -> None:
        self.stopped.set()


class _StoppableAgent:
    """agent.run 阻塞到 executor.force_stop 置位才优雅返回（模拟保留会话的可中断 run）。"""

    def __init__(self) -> None:
        self.executor = _StopExec()
        self.calls = 0
        self.history: list = ["kept"]

    def run(self, *, message: str):  # noqa: ARG002
        self.calls += 1
        self.executor.stopped.wait(timeout=5)  # 收到停止信号即优雅退出
        return "partial work (discarded on interrupt)"


def test_reply_interrupt_gracefully_stops_and_keeps_agent(entry: ModuleType) -> None:
    """打断：ctrl_q 收到 interrupt → force_stop 优雅停 → 回定型 [interrupted]，不重试、保留同 agent（会话不丢）。"""
    agent = _StoppableAgent()
    ctrl_q: queue.Queue = queue.Queue()
    threading.Timer(0.2, lambda: ctrl_q.put({"control": "interrupt"})).start()
    out_agent, text, status = entry._reply(agent, "hi", _no_rebuild, ctrl_q)
    assert text == entry._INTERRUPT_REPLY
    assert out_agent is agent  # 优雅停止保留 history → 沿用同实例，未重建
    assert agent.executor.stopped.is_set()  # 确实置了停止信号
    assert status == "interrupted"


class _UnstoppableAgent:
    """无 executor.force_stop（老 nexau）：打断无法优雅停 → 只能丢弃该实例、重建避自锁。"""

    def __init__(self) -> None:
        self.calls = 0
        self.history: list = ["from-stale"]
        self._never = threading.Event()

    def run(self, *, message: str):  # noqa: ARG002
        self.calls += 1
        self._never.wait(timeout=5)  # 用 Event.wait 真阻塞（time.sleep 被 fixture 补成 no-op）
        return "x"


def test_reply_interrupt_without_stop_capability_rebuilds_with_history(entry: ModuleType) -> None:
    stale = _UnstoppableAgent()
    fresh = _Agent(["after rebuild interrupt"])
    ctrl_q: queue.Queue = queue.Queue()
    ctrl_q.put({"control": "interrupt"})  # 起手即有打断

    def rebuild(old):
        fresh.history = list(getattr(old, "history", []) or [])
        return fresh

    out_agent, text, status = entry._reply(stale, "hi", rebuild, ctrl_q)
    assert text == entry._INTERRUPT_REPLY  # 打断仍回定型回复，不重试
    assert out_agent is fresh  # 没有优雅停止能力 → 重建避自锁
    assert fresh.history == ["from-stale"]
    assert status == "interrupted"
