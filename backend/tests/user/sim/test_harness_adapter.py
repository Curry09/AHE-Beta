"""spec-0005/T6：脚本化 harness 桩（实现 HarnessInterface send/reset/close）与离线 demo 烟测。"""

from __future__ import annotations

import pytest

from ahe_beta.harness.interface import HarnessInterface
from ahe_beta.user.sim import demo
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.scenarios import SplitBillHarness


def test_stubs_satisfy_repo_harness_interface() -> None:
    # 与仓库已有契约对齐: 桩满足 HarnessInterface(send/reset/close)
    assert isinstance(ScriptedHarness(), HarnessInterface)
    assert isinstance(SplitBillHarness(), HarnessInterface)


def test_scripted_harness_returns_str_and_trajectory() -> None:
    h = ScriptedHarness()
    first = h.send("please implement to_user_tz")
    assert isinstance(first, str) and "to_user_tz" in first and "Traceback" not in first
    crash = h.send("please run it once")
    assert isinstance(crash, str) and "Traceback" in crash  # 要求运行 -> 报错暴露在文本


def test_reset_rewinds_script() -> None:
    h = ScriptedHarness()
    h.send("a")
    h.send("b")
    h.reset()
    again = h.send("please implement to_user_tz")
    assert "to_user_tz" in again and h.step == 1  # reset 后从首步重来


def test_close_then_use_raises_and_is_idempotent() -> None:
    # 与 FakeHarness 行为对齐: close 后 send/reset 抛 RuntimeError, 重复 close 不抛
    for stub in (ScriptedHarness(), SplitBillHarness()):
        stub.close()
        stub.close()  # 幂等: 重复 close 不报错
        with pytest.raises(RuntimeError):
            stub.send("x")
        with pytest.raises(RuntimeError):
            stub.reset()


def test_split_bill_bug_shows_in_text_only_when_probed() -> None:
    h1 = SplitBillHarness()
    h1.send("add split_bill to the repo")  # step1: 贴初始实现
    normal = h1.send("just run it")  # 泛泛要求跑 -> 常规偶整除用例
    assert isinstance(normal, str) and "100.00" in normal  # 看着没问题

    h2 = SplitBillHarness()
    h2.send("add split_bill to the repo")
    probed = h2.send("what about splitting by 3? does it sum exactly?")
    assert isinstance(probed, str) and "99.99" in probed  # 探边界 -> bug 浮现在文本


def test_demo_runs_offline_without_key() -> None:
    personas = demo.make_personas()
    # Spec-0037/T2: 能力分叉 2 + tempo⊥d43 分叉 2
    assert len(personas) == 4
    demo.main()  # 离线脚本后端跑通，不应抛异常
