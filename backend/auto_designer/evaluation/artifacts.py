"""Spec-0083/T3: one bounded, binary artifact collector for both interactions."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from auto_designer.user.sim.runtime import utc_now


def collect_session_artifacts(
    *, workspace, sessions_root: Path, session_id: str, provenance: dict, declarations: list[dict]
) -> dict:
    """Retain original outputs before cleanup; missing evidence never becomes complete."""
    attempt_id = uuid.uuid4().hex
    keys = ("run_id", "round_no", "slot", "task_id", "task_digest", "harness_sha")
    identity = {key: provenance.get(key) for key in keys}
    identity["session_id"] = session_id
    receipt = {
        "contract_version": 1,
        "identity": identity,
        "attempt_id": attempt_id,
        "collected_at": utc_now(),
        "complete": False,
        "entries": [],
    }
    collection_error = None
    try:
        quiesce = getattr(workspace, "quiesce", None)
        if callable(quiesce):
            quiesce()
        finalize = getattr(workspace, "finalize_task", None)
        if callable(finalize):
            finalize()
    except Exception as exc:  # noqa: BLE001 - preserve failure and still clean up
        collection_error = type(exc).__name__
    for declaration in declarations:
        row = {
            key: declaration[key]
            for key in ("id", "source", "content_type", "required", "max_bytes")
        }
        try:
            if collection_error:
                raise RuntimeError(collection_error)
            if declaration["source"] != "workspace":
                raise NotImplementedError(
                    "Managed service evidence requires the environment broker"
                )
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", declaration["id"]):
                raise ValueError("Invalid artifact id")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", session_id):
                raise ValueError("Invalid session id")
            payload = workspace.export_file(declaration["path"], declaration["max_bytes"])
            if not isinstance(payload, bytes) or len(payload) > declaration["max_bytes"]:
                raise OverflowError("Artifact exceeds its byte limit")
            relative = f"evaluation-artifacts/{session_id}/{attempt_id}/{declaration['id']}"
            destination = Path(sessions_root).parent / relative
            if any(part.is_symlink() for part in [destination, *destination.parents]):
                raise ValueError("Artifact destination contains a symlink")
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(payload)
            destination.chmod(0o600)
            row.update(
                status="collected",
                path=relative,
                bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        except FileNotFoundError:
            row.update(status="missing", reason="declared_file_not_found")
        except OverflowError:
            row.update(status="over_limit", reason="declared_byte_limit_exceeded")
        except Exception as exc:  # noqa: BLE001 - one failed output must not skip cleanup
            row.update(status="collection_failed", reason=type(exc).__name__)
        receipt["entries"].append(row)
    receipt["complete"] = all(
        not row["required"] or row["status"] == "collected" for row in receipt["entries"]
    )
    return receipt
