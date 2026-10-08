# Spec-0047/T5：错误率保护只暂停本实验。
from __future__ import annotations

from pathlib import Path

from auto_designer.experiment import health


def test_error_rate_pauses_only_that_experiment(tmp_path: Path) -> None:
    for _ in range(health.WINDOW):
        health.record(experiment_id="bad", success=False, kind="http", root=tmp_path)
        health.record(experiment_id="good", success=True, kind="http", root=tmp_path)
    assert health.should_pause(experiment_id="bad", root=tmp_path) is True
    assert health.should_pause(experiment_id="good", root=tmp_path) is False
    health.resume(experiment_id="bad", root=tmp_path)
    assert health.should_pause(experiment_id="bad", root=tmp_path) is False
