# Spec-0025/T6：roster 编制解析——含 triager（issue 规范化角色）与 divergent。
"""验证 load_roster：默认 user3/triager1/designer1/divergent0/developer3；各 N_* 覆盖。"""

from __future__ import annotations

from auto_designer.loop.roster import DEFAULT_ROSTER, load_roster


def test_defaults(monkeypatch) -> None:
    for k in ("N_USERS", "N_TRIAGERS", "N_DESIGNERS", "N_DIVERGENTS", "N_DEVELOPERS"):
        monkeypatch.delenv(k, raising=False)
    assert load_roster() == {
        "user": 3,
        "triager": 1,
        "designer": 1,
        "divergent": 0,
        "developer": 3,
    }
    assert DEFAULT_ROSTER["triager"] == 1
    assert DEFAULT_ROSTER["divergent"] == 0


def test_triager_override(monkeypatch) -> None:
    monkeypatch.setenv("N_TRIAGERS", "2")
    assert load_roster()["triager"] == 2


def test_zero_triagers_allowed(monkeypatch) -> None:
    monkeypatch.setenv("N_TRIAGERS", "0")
    assert load_roster()["triager"] == 0  # 0 合法（关掉 triage 段）


def test_invalid_falls_back(monkeypatch) -> None:
    for raw in ("abc", "-1", "1.5"):
        monkeypatch.setenv("N_TRIAGERS", raw)
        assert load_roster()["triager"] == 1  # 非法/负值回落默认


def test_all_roles_overridable(monkeypatch) -> None:
    monkeypatch.setenv("N_USERS", "6")
    monkeypatch.setenv("N_DESIGNERS", "2")
    monkeypatch.setenv("N_DIVERGENTS", "1")
    monkeypatch.setenv("N_DEVELOPERS", "4")
    r = load_roster()
    assert (r["user"], r["designer"], r["divergent"], r["developer"]) == (6, 2, 1, 4)
