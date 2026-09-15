# Spec-0049/T2：角色调用 fail-open 落盘 + 实验切片 manifest。
"""Persist one JSON file per role invocation under ROLE_RUNS_DIR.

Missing ROLE_RUNS_DIR or I/O errors never raise to the caller. Manifest rounds record
user_sha and sealed_sha so a later auditor can attribute feeling deltas.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auto_designer.usage import current_usage_context

_LOCK = threading.RLock()
_SECRET_ENV_NAMES = (
    "GITEA_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "USER_LLM_API_KEY",
    "DESIGNER_LLM_API_KEY",
    "HARNESS_LLM_API_KEY",
    "LLM_API_KEY",
    "OPENAI_API_KEY",
)


class InvocationStore:
    """Atomic JSON writer for one experiment run_id directory."""

    def __init__(self, *, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def record(self, *, payload: dict[str, Any]) -> Path | None:
        """Write one invocation JSON and append its index entry once. Fail-open."""
        try:
            side = str(payload.get("side") or "demand")
            role = str(payload.get("role") or "unknown")
            invocation_id = str(payload.get("invocation_id") or uuid.uuid4().hex)
            captured = str((payload.get("env") or {}).get("captured_at") or "")
            stamp = captured.replace(":", "").replace("-", "")[:15] or "unknown"
            rel = Path(side) / f"{stamp}_{role}_{invocation_id[:8]}.json"
            path = self._root / rel
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            with _LOCK:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    # Spec-0064/T1: a replayed saved model output must not create a
                    # second audit index entry or overwrite different content.
                    return path if path.read_text(encoding="utf-8") == body else None
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(body, encoding="utf-8")
                tmp.replace(path)
                index = self._root / "index.jsonl"
                line = json.dumps(
                    {
                        "invocation_id": invocation_id,
                        "side": side,
                        "role": role,
                        "status": (payload.get("output") or {}).get("status"),
                        "path": str(rel).replace("\\", "/"),
                    },
                    ensure_ascii=False,
                )
                with index.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            return path
        except Exception:
            return None

    def write_manifest(self, *, data: dict[str, Any]) -> None:
        path = self._root / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def append_round(self, *, round_no: int, user_sha: str | None, sealed_sha: str | None) -> None:
        path = self._root / "manifest.json"
        row = {"round": round_no, "user_sha": user_sha, "sealed_sha": sealed_sha}
        with _LOCK:
            try:
                current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except Exception:
                current = {}
            rounds = list(current.get("rounds") or [])
            existing = next((item for item in rounds if item.get("round") == round_no), None)
            if existing is not None:
                if existing.get("user_sha") != user_sha:
                    raise ValueError(f"round {round_no} invocation manifest conflicts")
                existing_sealed = existing.get("sealed_sha")
                # Round start records the observation SHA before delivery has a
                # sealed result.  Filling that result is the only permitted
                # mutation.  A resume may replay the start assertion (None)
                # after the row is already sealed; that must be idempotent and
                # must never clear or replace the recorded SHA.
                if sealed_sha is None or existing_sealed == sealed_sha:
                    return
                if existing_sealed is not None:
                    raise ValueError(f"round {round_no} invocation manifest conflicts")
                existing["sealed_sha"] = sealed_sha
                current["rounds"] = sorted(
                    rounds, key=lambda item: int(item["round"])
                )
                self.write_manifest(data=current)
                return
            rounds.append(row)
            current["rounds"] = sorted(rounds, key=lambda item: int(item["round"]))
            self.write_manifest(data=current)


def role_runs_dir() -> Path | None:
    raw = os.environ.get("ROLE_RUNS_DIR", "").strip()
    return Path(raw) if raw else None


def _redact(*, text: str) -> str | None:
    out = text
    for name in _SECRET_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if not value:
            continue
        out = out.replace(value, f"${{{name}}}")
        if value in out:
            return None
    return out


def record_invocation(
    *,
    side: str,
    role: str,
    subject: dict[str, str],
    prompt: str,
    context: str = "",
    placeholders: dict[str, str] | None = None,
    structured: object,
    status: str,
    error: str | None = None,
    replayable: bool = True,
    model: str | None = None,
    agent_def_pin: str | None = None,
    evidence: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Fail-open write of one role invocation. No-op when ROLE_RUNS_DIR is unset.

    ``evidence`` is compact access metadata (level/source ids), never the raw
    session payload.
    """
    try:
        root = role_runs_dir()
        if root is None:
            return
        prompt_text = _redact(text=prompt)
        context_text = _redact(text=context)
        if prompt_text is None or context_text is None:
            return
        ctx = current_usage_context()
        payload = {
            "schema_version": 1,
            "invocation_id": uuid.uuid4().hex,
            "run_id": os.environ.get("AUTO_DESIGNER_RUN_ID") or ctx.run_id,
            "round": ctx.round_no,
            "side": side,
            "role": role,
            "subject": subject,
            "replayable": replayable,
            "input": {
                "prompt": prompt_text,
                "context": context_text,
                "placeholders": placeholders or {},
            },
            "output": {"structured": structured, "status": status, "error": error},
            "env": {
                "model": model,
                "agent_def_pin": agent_def_pin,
                "captured_at": datetime.now(UTC).isoformat(),
            },
        }
        if evidence is not None:
            payload["input"]["evidence"] = dict(evidence)
        if metrics is not None:
            payload["metrics"] = dict(metrics)
        InvocationStore(root=root).record(payload=payload)
    except Exception:
        return


def init_manifest(*, roster: dict[str, Any], models: dict[str, str]) -> None:
    try:
        root = role_runs_dir()
        if root is None:
            return
        InvocationStore(root=root).write_manifest(
            data={
                "run_id": os.environ.get("AUTO_DESIGNER_RUN_ID"),
                "roster": roster,
                "models": models,
                "rounds": [],
            }
        )
    except Exception:
        return


def append_round(*, round_no: int, user_sha: str | None, sealed_sha: str | None) -> None:
    try:
        root = role_runs_dir()
        if root is None:
            return
        InvocationStore(root=root).append_round(
            round_no=round_no, user_sha=user_sha, sealed_sha=sealed_sha
        )
    except Exception:
        return
