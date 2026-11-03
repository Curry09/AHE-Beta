"""checkpoint save/load (spec-0004/T1): package self-contained STATE_DIR as downloadable artifact, reverse restore.

STATE_DIR converges all recoverable state: gitea/(sqlite+repos) + sessions/ + metrics.jsonl + run_state.json.
checkpoint is a complete snapshot of these authoritative sources, not a secondary copy. save is atomic (tmp + rename), ensuring that
when sandbox dies mid-execution, the previous checkpoint remains always available; load verifies self-containment (all four categories present) before considering usable.
"""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

# Four categories required for STATE_DIR self-containment (verified on load).
REQUIRED_MEMBERS = ("gitea", "sessions", "metrics.jsonl", "run_state.json")
RECOVERY_MEMBERS = ("recovery.json", "recovery.jsonl")


def save_checkpoint(state_dir: Path, dest: Path) -> Path:
    """Atomically pack STATE_DIR as dest (tar.gz); return artifact path."""
    state_dir = Path(state_dir)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with tarfile.open(tmp, "w:gz") as tf:
        for item in sorted(state_dir.iterdir()):
            tf.add(item, arcname=item.name)
    # Atomic placement: partial writes do not corrupt the previous usable checkpoint
    os.replace(tmp, dest)
    return dest


def load_checkpoint(artifact: Path, state_dir: Path, *, require_recovery: bool = False) -> None:
    """Restore artifact to state_dir; verify all four categories present before marking usable, otherwise raise error."""
    state_dir = Path(state_dir)
    with tarfile.open(artifact, "r:gz") as tf:
        roots = {Path(member.name).parts[0] for member in tf.getmembers() if member.name}
        missing = [member for member in REQUIRED_MEMBERS if member not in roots]
        has_recovery = "recovery.json" in roots or "recovery.jsonl" in roots
        if require_recovery or has_recovery:
            missing.extend(member for member in RECOVERY_MEMBERS if member not in roots)
        if missing:
            raise ValueError(f"Checkpoint is not self-contained; missing: {missing}")
        state_dir.mkdir(parents=True, exist_ok=True)
        tf.extractall(state_dir, filter="data")
    if has_recovery or require_recovery:
        _validate_recovery_receipts(state_dir)


def _validate_recovery_receipts(state_dir: Path) -> None:
    """Ensure every output receipt referenced by the recovery snapshot is archived."""
    try:
        state = json.loads((state_dir / "recovery.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid checkpoint recovery.json") from exc
    for round_state in (state.get("rounds") or {}).values():
        for stage in (round_state.get("stages") or {}).values():
            for unit in (stage.get("units") or {}).values():
                rel = unit.get("output_artifact")
                if not rel:
                    continue
                path = (state_dir / rel).resolve()
                if not path.is_relative_to(state_dir.resolve()) or not path.is_file():
                    raise ValueError(f"Checkpoint is missing a recovery receipt: {rel}")
