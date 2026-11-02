"""spec-0001/T2：HarnessInterface 协议与 FakeHarness 行为单测。"""

from __future__ import annotations

import pytest

from ahe_beta.harness.interface import FakeHarness, HarnessInterface


def test_satisfies_protocol() -> None:
    assert isinstance(FakeHarness(), HarnessInterface)


def test_script_injection_in_order() -> None:
    h = FakeHarness(script=["r1", "r2", "r3"])
    assert [h.send("a"), h.send("b"), h.send("c")] == ["r1", "r2", "r3"]
    assert h.sent == ["a", "b", "c"]


def test_callback_injection_dynamic() -> None:
    h = FakeHarness(callback=lambda m: f"echo:{m}")
    assert h.send("x") == "echo:x"
    assert h.send("y") == "echo:y"


def test_script_and_callback_mutually_exclusive() -> None:
    with pytest.raises(ValueError):
        FakeHarness(script=["r"], callback=lambda m: m)


def test_no_injection_returns_placeholder() -> None:
    h = FakeHarness()
    assert isinstance(h.send("x"), str) and h.send("x") != ""


def test_reset_clears_sent_and_cursor() -> None:
    h = FakeHarness(script=["r1", "r2"])
    h.send("a")
    h.send("b")
    h.reset()
    assert h.sent == []
    assert h.send("c") == "r1"  # 游标复位，从脚本首条开始


def test_close_then_send_or_reset_raises() -> None:
    h = FakeHarness()
    h.close()
    with pytest.raises(RuntimeError):
        h.send("x")
    with pytest.raises(RuntimeError):
        h.reset()


def test_close_idempotent() -> None:
    h = FakeHarness()
    h.close()
    h.close()  # 不抛错


def test_script_exhausted_raises_index_error() -> None:
    h = FakeHarness(script=["only"])
    h.send("a")
    with pytest.raises(IndexError):
        h.send("b")


def test_empty_reply_not_an_error() -> None:
    h = FakeHarness(script=[""])
    assert h.send("a") == ""
