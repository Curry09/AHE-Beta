"""进行中会话 live 通道单测：write/read/clear 往返 + 缺省态。"""

from __future__ import annotations

from pathlib import Path

from auto_designer.loop.live import clear_live, read_live, write_live


def test_read_absent_is_inactive(tmp_path: Path) -> None:
    assert read_live(data_dir=tmp_path) == {"active": False}


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    write_live(
        data_dir=tmp_path,
        persona_identity="独立开发者",
        scenario="慢查询排查",
        turns=[{"role": "user", "content": "hi"}],
    )
    live = read_live(data_dir=tmp_path)
    assert live["active"] is True
    assert live["persona_identity"] == "独立开发者"
    assert live["turns"] == [{"role": "user", "content": "hi"}]
    assert "updated_at" in live


def test_clear_is_idempotent(tmp_path: Path) -> None:
    write_live(data_dir=tmp_path, persona_identity="x", scenario="y", turns=[])
    clear_live(data_dir=tmp_path)
    clear_live(data_dir=tmp_path)  # 幂等：再清不报错
    assert read_live(data_dir=tmp_path) == {"active": False}
