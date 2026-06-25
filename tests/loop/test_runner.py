"""spec-0004/T2：HarborRunner 首跑 / 恢复 / 幂等跳过单测（orchestrator + checkpoint 注入 spy）。"""

from __future__ import annotations

import pytest

from auto_designer.loop.run_state import RunState, read_run_state, write_run_state
from auto_designer.loop.runner import HarborRunner


class _FakeOrch:
    """run_round 按脚本返回新 ref，并记录每轮入参。"""

    def __init__(self, refs: list[str]) -> None:
        self._refs = refs
        self.calls: list[str] = []

    def run_round(self, ref: str) -> str:
        self.calls.append(ref)
        return self._refs[len(self.calls) - 1]


class _SaveSpy:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, state_dir, dest):
        self.calls.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("artifact", encoding="utf-8")
        return dest


def _runner(tmp_path, orch, load_fn=None) -> HarborRunner:
    return HarborRunner(
        orchestrator=orch,
        state_dir=tmp_path / "state",
        artifact_dir=tmp_path / "artifacts",
        save_fn=_SaveSpy() if load_fn is None else _SaveSpy(),
        load_fn=load_fn or (lambda a, s: None),
    )


def test_first_run_emits_per_round(tmp_path) -> None:
    orch = _FakeOrch(["v2", "v3"])
    save = _SaveSpy()
    runner = HarborRunner(
        orchestrator=orch,
        state_dir=tmp_path / "state",
        artifact_dir=tmp_path / "artifacts",
        save_fn=save,
        load_fn=lambda a, s: None,
    )
    latest = runner.run(initial_release_ref="v1", n_rounds=2, checkpoint_artifact=None)
    assert orch.calls == ["v1", "v2"]  # 上轮返回喂下轮
    assert len(save.calls) == 2  # 每轮一个 checkpoint
    assert latest == save.calls[-1]
    rs = read_run_state(tmp_path / "state")
    assert rs.round == 2 and rs.current_release_ref == "v3"


def test_resume_skips_completed_rounds(tmp_path) -> None:
    state_dir = tmp_path / "state"

    def fake_load(artifact, sdir):
        write_run_state(sdir, RunState(round=2, phase="c", current_release_ref="v3"))

    orch = _FakeOrch(["v4", "v5"])
    save = _SaveSpy()
    runner = HarborRunner(
        orchestrator=orch,
        state_dir=state_dir,
        artifact_dir=tmp_path / "artifacts",
        save_fn=save,
        load_fn=fake_load,
    )
    runner.run(initial_release_ref="v1", n_rounds=4, checkpoint_artifact=tmp_path / "ckpt.tar.gz")
    assert orch.calls == ["v3", "v4"]  # 只跑第 3、4 轮，从 run_state 的 ref 续起
    assert len(save.calls) == 2
    assert read_run_state(state_dir).round == 4


def test_resume_already_complete_no_rounds(tmp_path) -> None:
    def fake_load(artifact, sdir):
        write_run_state(sdir, RunState(round=4, current_release_ref="v5"))

    orch = _FakeOrch([])
    save = _SaveSpy()
    runner = HarborRunner(
        orchestrator=orch,
        state_dir=tmp_path / "state",
        artifact_dir=tmp_path / "artifacts",
        save_fn=save,
        load_fn=fake_load,
    )
    ckpt = tmp_path / "ckpt.tar.gz"
    latest = runner.run(initial_release_ref="v1", n_rounds=4, checkpoint_artifact=ckpt)
    assert orch.calls == []  # 全部轮已完成
    assert save.calls == []
    assert latest == ckpt  # 返回传入的 checkpoint


def test_nonpositive_rounds_raises(tmp_path) -> None:
    runner = _runner(tmp_path, _FakeOrch([]))
    with pytest.raises(ValueError):
        runner.run(initial_release_ref="v1", n_rounds=0)
