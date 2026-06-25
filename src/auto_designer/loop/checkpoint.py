"""checkpoint 存取（spec-0004/T1）：把自包含 STATE_DIR 打包成可下载 artifact，反向还原。

STATE_DIR 收敛全部可恢复状态：gitea/(sqlite+repos) + sessions/ + metrics.jsonl + run_state.json。
checkpoint 是这些权威源的整体快照，非第二权威。save 原子（tmp + rename），保证沙盒中途死时
上一个 checkpoint 始终可用；load 校验自包含（四类齐全）后才算可用。
"""

from __future__ import annotations

import os
import tarfile
from pathlib import Path

# STATE_DIR 自包含所需的四类（load 时校验齐全）。
REQUIRED_MEMBERS = ("gitea", "sessions", "metrics.jsonl", "run_state.json")


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


def load_checkpoint(artifact: Path, state_dir: Path) -> None:
    """把 artifact 还原到 state_dir；校验四类齐全后才置为可用，否则抛错。"""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(artifact, "r:gz") as tf:
        tf.extractall(state_dir, filter="data")
    missing = [m for m in REQUIRED_MEMBERS if not (state_dir / m).exists()]
    if missing:
        raise ValueError(f"checkpoint 不自包含，缺：{missing}")
