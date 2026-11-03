"""spec-0005/T6: scripted harness stub (implements HarnessInterface send/reset/close) and offline demo smoke test."""

from __future__ import annotations

import pytest

from ahe_beta.harness.interface import HarnessInterface
from ahe_beta.user.sim import demo
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.scenarios import SplitBillHarness


def test_stubs_satisfy_repo_harness_interface() -> None:
    # align with existing repo contract: stub satisfies HarnessInterface (send/reset/close)
    assert isinstance(ScriptedHarness(), HarnessInterface)
    assert isinstance(SplitBillHarness(), HarnessInterface)


def test_scripted_harness_returns_str_and_trajectory() -> None:
    h = ScriptedHarness()
    first = h.send("please implement to_user_tz")
    assert isinstance(first, str) and "to_user_tz" in first and "Traceback" not in first
    crash = h.send("please run it once")
    # request execution -> error exposed in text
    assert isinstance(crash, str) and "Traceback" in crash


def test_reset_rewinds_script() -> None:
    h = ScriptedHarness()
    h.send("a")
    h.send("b")
    h.reset()
    again = h.send("please implement to_user_tz")
    assert "to_user_tz" in again and h.step == 1  # after reset restart from first step


def test_close_then_use_raises_and_is_idempotent() -> None:
    # align with FakeHarness behavior: after close send/reset raises RuntimeError, repeated close does not raise
    for stub in (ScriptedHarness(), SplitBillHarness()):
        stub.close()
        stub.close()  # idempotent: repeated close does not error
        with pytest.raises(RuntimeError):
            stub.send("x")
        with pytest.raises(RuntimeError):
            stub.reset()


def test_split_bill_bug_shows_in_text_only_when_probed() -> None:
    h1 = SplitBillHarness()
    h1.send("add split_bill to the repo")  # step1: paste initial implementation
    normal = h1.send("just run it")  # general requirement to run -> standard even-division use case
    assert isinstance(normal, str) and "100.00" in normal  # appears fine

    h2 = SplitBillHarness()
    h2.send("add split_bill to the repo")
    probed = h2.send("what about splitting by 3? does it sum exactly?")
    assert isinstance(probed, str) and "99.99" in probed  # probe boundaries -> bug emerges in text


def test_demo_runs_offline_without_key() -> None:
    personas = demo.make_personas()
    # Spec-0037/T2: Capability fork 2 + tempo⊥d43 fork 2
    assert len(personas) == 4
    demo.main()  # Offline script backend runs through without throwing exceptions
