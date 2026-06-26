"""spec-0005/T6：脚本化 harness 桩（respond->str）与离线 demo 烟测。"""

from __future__ import annotations

from auto_designer.user.sim import demo
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.scenarios import SplitBillHarness


def test_scripted_harness_returns_str_and_trajectory() -> None:
    h = ScriptedHarness()
    first = h.respond("please implement to_user_tz")
    assert isinstance(first, str) and "to_user_tz" in first and "Traceback" not in first
    crash = h.respond("please run it once")
    assert isinstance(crash, str) and "Traceback" in crash  # 要求运行 -> 报错暴露在文本


def test_split_bill_bug_shows_in_text_only_when_probed() -> None:
    h1 = SplitBillHarness()
    h1.respond("add split_bill to the repo")          # step1: 贴初始实现
    normal = h1.respond("just run it")                # 泛泛要求跑 -> 常规偶整除用例
    assert isinstance(normal, str) and "100.00" in normal  # 看着没问题

    h2 = SplitBillHarness()
    h2.respond("add split_bill to the repo")
    probed = h2.respond("what about splitting by 3? does it sum exactly?")
    assert isinstance(probed, str) and "99.99" in probed   # 探边界 -> bug 浮现在文本


def test_demo_runs_offline_without_key() -> None:
    personas = demo.make_personas()
    assert len(personas) == 2
    demo.main()  # 离线脚本后端跑通两 persona, 不应抛异常
