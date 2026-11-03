# Spec-0029/T8 (Spec-0032/T4 adjustment): roster composition parsing—developer semantics changed to delivery-side concurrency K.
"""Verify load_roster: default user3/triager1/architect1/divergent0/owner0/developer1; each N_* override."""

from __future__ import annotations

from ahe_beta.loop.roster import DEFAULT_ROSTER, load_roster

_ALL_ENVS = (
    "N_USERS",
    "N_TRIAGERS",
    "N_ARCHITECTS",
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
        "architect": 1,
        "divergent": 0,
        "owner": 0,
        # Spec-0032: delivery-side concurrency K (vigil --parallel), conservative default serial
        "developer": 1,
    }
    assert DEFAULT_ROSTER["owner"] == 0


def test_triager_override(monkeypatch) -> None:
    monkeypatch.setenv("N_TRIAGERS", "2")
    assert load_roster()["triager"] == 2  # Shard count


def test_zero_owner_disables_admission_review(monkeypatch) -> None:
    monkeypatch.setenv("N_OWNERS", "0")
    assert load_roster()["owner"] == 0  # 0 valid: model review skipped, all proposals held


def test_zero_triagers_allowed(monkeypatch) -> None:
    monkeypatch.setenv("N_TRIAGERS", "0")
    assert load_roster()["triager"] == 0


def test_invalid_falls_back(monkeypatch) -> None:
    for raw in ("abc", "-1", "1.5"):
        monkeypatch.setenv("N_OWNERS", raw)
        assert load_roster()["owner"] == 0  # Invalid / negative falls back to default


def test_all_roles_overridable(monkeypatch) -> None:
    monkeypatch.setenv("N_USERS", "6")
    monkeypatch.setenv("N_ARCHITECTS", "2")
    monkeypatch.setenv("N_DIVERGENTS", "1")
    monkeypatch.setenv("N_DEVELOPERS", "4")
    r = load_roster()
    assert (r["user"], r["architect"], r["divergent"], r["developer"]) == (6, 2, 1, 4)
