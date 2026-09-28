"""Atomic run cursor plus append-only transition journal."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any


class RunStateStore:
    def __init__(self, run_root: str | Path, manifest: Mapping[str, Any]) -> None:
        self.root = Path(run_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.journal_path = self.root / "journal.jsonl"
        self._lock = RLock()
        self.manifest_digest = str(manifest["manifest_digest"])
        self.trial_ids = tuple(str(item["trial_id"]) for item in manifest["trials"])
        if not self.state_path.exists():
            self._write(
                {
                    "schema_version": 1,
                    "revision": 0,
                    "manifest_digest": self.manifest_digest,
                    "trials": {
                        trial_id: {"status": "planned", "attempts": 0}
                        for trial_id in self.trial_ids
                    },
                }
            )
        self.load()

    def load(self) -> dict[str, Any]:
        with self._lock:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state.get("manifest_digest") != self.manifest_digest:
                raise ValueError("run state belongs to a different manifest")
            if set(state.get("trials", {})) != set(self.trial_ids):
                raise ValueError("run state trial set drifted from manifest")
            return state

    def _write(self, state: Mapping[str, Any]) -> None:
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, self.state_path)

    def transition(self, trial_id: str, status: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            state = self.load()
            if trial_id not in state["trials"]:
                raise KeyError(f"unknown trial: {trial_id}")
            old_status = state["trials"][trial_id]["status"]
            state["revision"] += 1
            state["trials"][trial_id] = {
                **state["trials"][trial_id],
                **fields,
                "status": status,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self._write(state)
            event = {
                "revision": state["revision"],
                "trial_id": trial_id,
                "from": old_status,
                "to": status,
                "fields": fields,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            with self.journal_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return state
