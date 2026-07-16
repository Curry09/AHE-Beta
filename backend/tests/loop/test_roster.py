# Spec-0020/T3：dev 领取策略配置（N_BUG_FIRST_DEVS）解析单测。
"""验证 load_dev_pick_policies：默认 1 个 bug_first；0/超编/非法值各回落到位；空编制返回空。"""

from __future__ import annotations

from auto_designer.loop.roster import load_dev_pick_policies


def test_default_one_bug_first(monkeypatch) -> None:
    monkeypatch.delenv("N_BUG_FIRST_DEVS", raising=False)
    assert load_dev_pick_policies(n_developers=3) == [
        "bug_first",
        "design_first",
        "design_first",
    ]


def test_zero_means_all_design_first(monkeypatch) -> None:
    monkeypatch.setenv("N_BUG_FIRST_DEVS", "0")
    assert load_dev_pick_policies(n_developers=3) == ["design_first"] * 3


def test_over_roster_truncates_to_all_bug_first(monkeypatch) -> None:
    monkeypatch.setenv("N_BUG_FIRST_DEVS", "99")
    assert load_dev_pick_policies(n_developers=2) == ["bug_first"] * 2


def test_invalid_values_fall_back_to_default(monkeypatch) -> None:
    for raw in ("-1", "abc", "1.5", "  "):
        monkeypatch.setenv("N_BUG_FIRST_DEVS", raw)
        assert load_dev_pick_policies(n_developers=3) == [
            "bug_first",
            "design_first",
            "design_first",
        ]


def test_zero_developers_yields_empty(monkeypatch) -> None:
    monkeypatch.setenv("N_BUG_FIRST_DEVS", "2")
    assert load_dev_pick_policies(n_developers=0) == []
