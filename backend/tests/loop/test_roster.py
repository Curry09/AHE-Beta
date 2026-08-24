# Spec-0029/T8（Spec-0032/T4 调整）：roster 编制解析——developer 语义改为交付面并发 K。
"""验证 load_roster：默认 user3/triager1/designer1/divergent0/owner1/developer1；各 N_* 覆盖。"""

from __future__ import annotations

from auto_designer.loop.roster import DEFAULT_ROSTER, load_roster

_ALL_ENVS = (
    "N_USERS",
    "N_TRIAGERS",
    "N_DESIGNERS",
    "N_DIVERGENTS",
    "N_OWNERS",
    "N_DEVELOPERS",
)


def test_defaults(monkeypatch) -> None:
    for k in _ALL_ENVS:
        monkeypatch.delenv(k, raising=False)
    assert load_roster() == {
        "user": 3,
        "triager": 1,
        "designer": 1,
        "divergent": 0,
        "owner": 1,
        "developer": 1,  # Spec-0032：交付面并发 K（vigil --parallel），保守默认串行
    }
    assert DEFAULT_ROSTER["owner"] == 1


def test_triager_override(monkeypatch) -> None:
    monkeypatch.setenv("N_TRIAGERS", "2")
    assert load_roster()["triager"] == 2  # 分片数


def test_zero_owner_disables_admission_review(monkeypatch) -> None:
    monkeypatch.setenv("N_OWNERS", "0")
    assert load_roster()["owner"] == 0  # 0 合法：模型评审跳过、全部提案 hold


def test_zero_triagers_allowed(monkeypatch) -> None:
    monkeypatch.setenv("N_TRIAGERS", "0")
    assert load_roster()["triager"] == 0


def test_invalid_falls_back(monkeypatch) -> None:
    for raw in ("abc", "-1", "1.5"):
        monkeypatch.setenv("N_OWNERS", raw)
        assert load_roster()["owner"] == 1  # 非法/负值回落默认


def test_all_roles_overridable(monkeypatch) -> None:
    monkeypatch.setenv("N_USERS", "6")
    monkeypatch.setenv("N_DESIGNERS", "2")
    monkeypatch.setenv("N_DIVERGENTS", "1")
    monkeypatch.setenv("N_DEVELOPERS", "4")
    r = load_roster()
    assert (r["user"], r["designer"], r["divergent"], r["developer"]) == (6, 2, 1, 4)
