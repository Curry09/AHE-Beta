"""spec-0004/T1：checkpoint save/load 自包含与原子性单测。"""

from __future__ import annotations

import pytest

from ahe_beta.loop.checkpoint import (
    RECOVERY_MEMBERS,
    REQUIRED_MEMBERS,
    load_checkpoint,
    save_checkpoint,
)


def _make_state_dir(root, *, complete: bool = True):
    state = root / "state"
    (state / "gitea").mkdir(parents=True)
    (state / "gitea" / "gitea.db").write_text("sqlite", encoding="utf-8")
    (state / "sessions").mkdir()
    (state / "sessions" / "s1.json").write_text("{}", encoding="utf-8")
    (state / "metrics.jsonl").write_text('{"t":1}\n', encoding="utf-8")
    if complete:
        (state / "run_state.json").write_text('{"round": 1}', encoding="utf-8")
    return state


def _read(p):
    return p.read_text(encoding="utf-8")


def test_save_load_round_trip(tmp_path) -> None:
    state = _make_state_dir(tmp_path)
    artifact = save_checkpoint(state, tmp_path / "ckpt.tar.gz")
    assert artifact.exists()

    restored = tmp_path / "restored"
    load_checkpoint(artifact, restored)
    assert _read(restored / "gitea" / "gitea.db") == "sqlite"
    assert _read(restored / "sessions" / "s1.json") == "{}"
    assert _read(restored / "metrics.jsonl") == '{"t":1}\n'
    assert _read(restored / "run_state.json") == '{"round": 1}'


def test_load_validates_self_contained(tmp_path) -> None:
    state = _make_state_dir(tmp_path, complete=False)  # 缺 run_state.json
    artifact = save_checkpoint(state, tmp_path / "ckpt.tar.gz")
    with pytest.raises(ValueError):
        load_checkpoint(artifact, tmp_path / "restored")


def test_save_atomic_no_tmp_left(tmp_path) -> None:
    state = _make_state_dir(tmp_path)
    dest = tmp_path / "ckpt.tar.gz"
    save_checkpoint(state, dest)
    assert dest.exists()
    assert not (tmp_path / "ckpt.tar.gz.tmp").exists()


def test_required_members_constant() -> None:
    assert set(REQUIRED_MEMBERS) == {"gitea", "sessions", "metrics.jsonl", "run_state.json"}
    assert set(RECOVERY_MEMBERS) == {"recovery.json", "recovery.jsonl"}


def test_new_checkpoint_requires_complete_recovery_ledger(tmp_path) -> None:
    state = _make_state_dir(tmp_path)
    (state / "recovery.json").write_text('{"rounds": {}}', encoding="utf-8")
    artifact = save_checkpoint(state, tmp_path / "ckpt.tar.gz")
    with pytest.raises(ValueError, match="recovery.jsonl"):
        load_checkpoint(artifact, tmp_path / "restored")


def test_recovery_receipts_are_validated(tmp_path) -> None:
    state = _make_state_dir(tmp_path)
    (state / "recovery.jsonl").write_text("{}\n", encoding="utf-8")
    (state / "recovery.json").write_text(
        '{"rounds":{"1":{"stages":{"users":{"units":{"op":{"output_artifact":'
        '"recovery-receipts/1/users/op.json"}}}}}}}',
        encoding="utf-8",
    )
    artifact = save_checkpoint(state, tmp_path / "ckpt.tar.gz")
    with pytest.raises(ValueError, match="receipt"):
        load_checkpoint(artifact, tmp_path / "restored")
