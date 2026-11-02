"""checkpoint 存取（spec-0004/T1）：把自包含 STATE_DIR 打包成可下载 artifact，反向还原。

STATE_DIR 收敛全部可恢复状态：gitea/(sqlite+repos) + sessions/ + metrics.jsonl + run_state.json。
checkpoint 是这些权威源的整体快照，非第二权威。save 原子（tmp + rename），保证沙盒中途死时
上一个 checkpoint 始终可用；load 校验自包含（四类齐全）后才算可用。
"""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

# STATE_DIR 自包含所需的四类（load 时校验齐全）。
REQUIRED_MEMBERS = ("gitea", "sessions", "metrics.jsonl", "run_state.json")
RECOVERY_MEMBERS = ("recovery.json", "recovery.jsonl")


def save_checkpoint(state_dir: Path, dest: Path) -> Path:
    """原子打包 STATE_DIR 为 dest（tar.gz）；返回 artifact 路径。"""
    state_dir = Path(state_dir)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with tarfile.open(tmp, "w:gz") as tf:
        for item in sorted(state_dir.iterdir()):
            tf.add(item, arcname=item.name)
    os.replace(tmp, dest)  # 原子置位：部分写不污染上一个可用 checkpoint
    return dest


def load_checkpoint(artifact: Path, state_dir: Path, *, require_recovery: bool = False) -> None:
    """把 artifact 还原到 state_dir；校验四类齐全后才置为可用，否则抛错。"""
    state_dir = Path(state_dir)
    with tarfile.open(artifact, "r:gz") as tf:
        roots = {Path(member.name).parts[0] for member in tf.getmembers() if member.name}
        missing = [member for member in REQUIRED_MEMBERS if member not in roots]
        has_recovery = "recovery.json" in roots or "recovery.jsonl" in roots
        if require_recovery or has_recovery:
            missing.extend(member for member in RECOVERY_MEMBERS if member not in roots)
        if missing:
            raise ValueError(f"checkpoint 不自包含，缺：{missing}")
        state_dir.mkdir(parents=True, exist_ok=True)
        tf.extractall(state_dir, filter="data")
    if has_recovery or require_recovery:
        _validate_recovery_receipts(state_dir)


def _validate_recovery_receipts(state_dir: Path) -> None:
    """Ensure every output receipt referenced by the recovery snapshot is archived."""
    try:
        state = json.loads((state_dir / "recovery.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("checkpoint recovery.json 无效") from exc
    for round_state in (state.get("rounds") or {}).values():
        for stage in (round_state.get("stages") or {}).values():
            for unit in (stage.get("units") or {}).values():
                rel = unit.get("output_artifact")
                if not rel:
                    continue
                path = (state_dir / rel).resolve()
                if not path.is_relative_to(state_dir.resolve()) or not path.is_file():
                    raise ValueError(f"checkpoint 缺 recovery receipt：{rel}")
