"""Durable stage and work-item recovery ledger.

The ledger records intent and progress; SessionStore, Gitea and git remain the
authoritative sources for their own data.  Callers save model output before
applying an external side effect, then reconcile the external postcondition
before marking a unit complete.
"""

from __future__ import annotations

import copy
import dataclasses
import fcntl
import hashlib
import json
import os
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATE_FILE = "recovery.json"
EVENT_FILE = "recovery.jsonl"
RECEIPTS_DIR = "recovery-receipts"

_STAGE_COMPLETE = "completed"
_SECRET_KEYS = {
    "access_token",
    "anthropic_api_key",
    "anthropic_auth_token",
    "api_key",
    "authorization",
    "claude_code_oauth_token",
    "gitea_token",
    "llm_api_key",
    "openai_api_key",
    "password",
    "personal_access_tokens",
    "secret",
    "token",
}
_SAFE_COMPONENT = re.compile(r"[^a-zA-Z0-9_.-]+")
_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class RecoveryError(RuntimeError):
    """Base error for recovery state that cannot safely be continued."""


class RecoveryStateMissing(RecoveryError):
    """A resume was requested for a run without a recovery ledger."""


class RecoveryCorruptError(RecoveryError):
    """The durable snapshot or one of its receipts is malformed or torn."""


class RecoveryIdentityError(RecoveryError):
    """The immutable experiment identity differs from the saved identity."""


class RecoveryConflictError(RecoveryError):
    """A frozen input, output, or postcondition conflicts with durable state."""


class StaleRevisionError(RecoveryError):
    """Another controller committed a newer recovery revision."""


class UnsafeRecoveryDataError(RecoveryError):
    """A payload contains a credential-shaped key and must not be persisted."""


@dataclass(frozen=True)
class RecoveryIdentity:
    """Fields that must remain unchanged for the lifetime of an experiment."""

    experiment_id: str
    run_id: str
    config_hash: str
    controller_sha: str
    plan_hash: str

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


def canonical_json(value: Any) -> str:
    """Return a stable JSON representation after rejecting credential fields."""
    safe = _safe_value(value)
    return json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_value(value: Any) -> str:
    """SHA-256 of a canonical JSON value."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def operation_key(*parts: object) -> str:
    """Build an opaque, stable key without leaking the source values."""
    return f"op-{digest_value(list(parts))[:32]}"


def _safe_value(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.casefold().replace("-", "_")
            if normalized in _SECRET_KEYS or normalized.endswith(("_password", "_secret")):
                raise UnsafeRecoveryDataError(f"recovery payload contains secret field: {key}")
            result[key] = _safe_value(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"recovery payload is not JSON serializable: {type(value).__name__}")


def _thread_lock(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path.resolve(), threading.RLock())


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with tmp.open("x", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryCorruptError(f"invalid recovery file: {path.name}") from exc
    if not isinstance(value, dict):
        raise RecoveryCorruptError(f"recovery file is not an object: {path.name}")
    return value


def _contains(expected: Any, observed: Any) -> bool:
    """Return whether observed recursively contains the expected postcondition."""
    if isinstance(expected, Mapping):
        return isinstance(observed, Mapping) and all(
            key in observed and _contains(value, observed[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(observed, list) and expected == observed
    return expected == observed


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RecoveryStore:
    """Revisioned snapshot plus append-only transition log for one experiment."""

    def __init__(self, *, root: Path, state: dict[str, Any]) -> None:
        self.root = Path(root)
        self.state_path = self.root / STATE_FILE
        self.event_path = self.root / EVENT_FILE
        self.receipts_root = self.root / RECEIPTS_DIR
        self._lock_path = self.root / ".recovery.lock"
        self._state = state
        self._revision = int(state["revision"])

    @classmethod
    def initialize(cls, *, root: Path, identity: RecoveryIdentity) -> RecoveryStore:
        """Create a fresh ledger, refusing to overwrite any existing run."""
        root = Path(root)
        state_path = root / STATE_FILE
        root.mkdir(parents=True, exist_ok=True)
        with _thread_lock(state_path):
            lock_path = root / ".recovery.lock"
            with lock_path.open("a+b") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX)
                if state_path.exists():
                    raise RecoveryConflictError("recovery state already exists; use resume")
                state = {
                    "schema_version": SCHEMA_VERSION,
                    "revision": 0,
                    "identity": _safe_value(identity.to_dict()),
                    "round": 0,
                    "rounds": {},
                    "created_at": _now(),
                    "updated_at": _now(),
                }
                _atomic_json(state_path, state)
                cls._append_event_file(
                    root / EVENT_FILE,
                    {"at": _now(), "event": "initialized", "revision": 0},
                )
        return cls(root=root, state=state)

    @classmethod
    def open(cls, *, root: Path, identity: RecoveryIdentity) -> RecoveryStore:
        """Open an existing ledger and fail closed on schema or identity drift."""
        root = Path(root)
        path = root / STATE_FILE
        if not path.is_file():
            raise RecoveryStateMissing(
                "experiment has no recovery state; an explicit migration or fresh run is required"
            )
        state = _read_json(path)
        if state.get("schema_version") != SCHEMA_VERSION:
            raise RecoveryCorruptError(
                f"unsupported recovery schema: {state.get('schema_version')!r}"
            )
        if not isinstance(state.get("revision"), int) or state["revision"] < 0:
            raise RecoveryCorruptError("invalid recovery revision")
        if state.get("identity") != identity.to_dict():
            raise RecoveryIdentityError("immutable recovery identity changed")
        if not isinstance(state.get("rounds"), dict):
            raise RecoveryCorruptError("invalid recovery rounds")
        return cls(root=root, state=state)

    @property
    def revision(self) -> int:
        return self._revision

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def freeze_round(
        self, *, round_no: int, user_sha: str, plan: Any, plan_hash: str | None = None
    ) -> dict[str, Any]:
        """Persist a round plan once; later calls must provide byte-equivalent input."""
        if round_no < 1:
            raise ValueError("round_no must be positive")
        safe_plan = _safe_value(plan)
        frozen_hash = plan_hash or digest_value(safe_plan)
        next_state = self.snapshot()
        rounds = next_state["rounds"]
        existing = rounds.get(str(round_no))
        if existing is not None:
            if existing.get("user_sha") != user_sha or existing.get("plan_hash") != frozen_hash:
                raise RecoveryConflictError(f"round {round_no} frozen input changed")
            return copy.deepcopy(existing)
        rounds[str(round_no)] = {
            "status": "running",
            "user_sha": user_sha,
            "sealed_sha": None,
            "plan": safe_plan,
            "plan_hash": frozen_hash,
            "stages": {},
            "admitted_issue_ids": [],
        }
        next_state["round"] = max(int(next_state.get("round", 0)), round_no)
        self._commit(next_state, event="round_frozen", round_no=round_no)
        return copy.deepcopy(rounds[str(round_no)])

    def begin_unit(
        self,
        *,
        round_no: int,
        stage: str,
        key: str,
        input_value: Any,
        expected_postconditions: Any | None = None,
        dependencies: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Begin or retry one unit after checking frozen input and stage dependencies."""
        safe_input = _safe_value(input_value)
        input_digest = digest_value(safe_input)
        expected = _safe_value(expected_postconditions or {})
        next_state = self.snapshot()
        round_state = self._require_round(next_state, round_no)
        stages = round_state["stages"]
        missing = [
            name for name in dependencies if stages.get(name, {}).get("status") != _STAGE_COMPLETE
        ]
        if missing:
            raise RecoveryConflictError(
                f"stage {stage} cannot start before dependencies complete: {missing}"
            )
        stage_state = stages.setdefault(
            stage,
            {
                "status": "running",
                "input_digest": None,
                "units": {},
                "dependencies": list(dependencies),
            },
        )
        if list(stage_state.get("dependencies") or []) != list(dependencies):
            raise RecoveryConflictError(f"stage {stage} dependencies changed")
        unit = stage_state["units"].get(key)
        if unit is None:
            unit = {
                "status": "running",
                "attempt": 1,
                "input": safe_input,
                "input_digest": input_digest,
                "output_artifact": None,
                "output_digest": None,
                "expected_postconditions": expected,
                "observed_postconditions": None,
                "error": None,
            }
            stage_state["units"][key] = unit
        else:
            if unit.get("input_digest") != input_digest:
                raise RecoveryConflictError(f"input digest changed for {stage}/{key}")
            if unit.get("expected_postconditions") != expected:
                raise RecoveryConflictError(f"postconditions changed for {stage}/{key}")
            if unit.get("status") == _STAGE_COMPLETE:
                return copy.deepcopy(unit)
            unit.update(
                status="running",
                attempt=int(unit.get("attempt", 0)) + 1,
                error=None,
            )
        stage_state["status"] = "running"
        self._commit(next_state, event="unit_started", round_no=round_no, stage=stage, key=key)
        return copy.deepcopy(unit)

    def save_output(self, *, round_no: int, stage: str, key: str, output: Any) -> dict[str, Any]:
        """Atomically save immutable model output before external side effects."""
        safe_output = _safe_value(output)
        output_digest = digest_value(safe_output)
        next_state = self.snapshot()
        unit = self._require_unit(next_state, round_no, stage, key)
        existing_digest = unit.get("output_digest")
        if existing_digest and existing_digest != output_digest:
            raise RecoveryConflictError(f"output digest changed for {stage}/{key}")
        if existing_digest:
            return copy.deepcopy(unit)
        stage_component = _SAFE_COMPONENT.sub("_", stage).strip("._") or "stage"
        receipt_rel = Path(RECEIPTS_DIR) / str(round_no) / stage_component / f"{key}.json"
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "round": round_no,
            "stage": stage,
            "operation_key": key,
            "input_digest": unit["input_digest"],
            "output_digest": output_digest,
            "output": safe_output,
        }
        receipt_path = self.root / receipt_rel
        if receipt_path.exists():
            existing = _read_json(receipt_path)
            if existing != receipt:
                raise RecoveryConflictError(f"output receipt conflicts for {stage}/{key}")
        else:
            _atomic_json(receipt_path, receipt)
        unit.update(
            status="output_saved",
            output_artifact=receipt_rel.as_posix(),
            output_digest=output_digest,
        )
        self._commit(next_state, event="output_saved", round_no=round_no, stage=stage, key=key)
        return copy.deepcopy(unit)

    def read_output(self, *, round_no: int, stage: str, key: str) -> Any:
        """Read a saved output and verify all ledger and receipt digests."""
        unit = self._require_unit(self._state, round_no, stage, key)
        rel = unit.get("output_artifact")
        if not rel or not unit.get("output_digest"):
            raise RecoveryConflictError(f"unit has no saved output: {stage}/{key}")
        path = self.root / str(rel)
        receipt = _read_json(path)
        if (
            receipt.get("operation_key") != key
            or receipt.get("input_digest") != unit.get("input_digest")
            or receipt.get("output_digest") != unit.get("output_digest")
            or digest_value(receipt.get("output")) != unit.get("output_digest")
        ):
            raise RecoveryCorruptError(f"output receipt digest mismatch: {path}")
        return copy.deepcopy(receipt["output"])

    def reconcile_unit(
        self,
        *,
        round_no: int,
        stage: str,
        key: str,
        observed_postconditions: Any,
        satisfied: bool | None = None,
    ) -> bool:
        """Record authoritative observations and complete only when they satisfy intent."""
        observed = _safe_value(observed_postconditions)
        next_state = self.snapshot()
        unit = self._require_unit(next_state, round_no, stage, key)
        expected = unit.get("expected_postconditions") or {}
        matches = _contains(expected, observed) if satisfied is None else satisfied
        unit["observed_postconditions"] = observed
        if matches:
            unit.update(status=_STAGE_COMPLETE, error=None)
            event = "unit_reconciled"
        else:
            unit.update(status="blocked", error="external postcondition mismatch")
            next_state["rounds"][str(round_no)]["stages"][stage]["status"] = "blocked"
            event = "unit_blocked"
        self._commit(next_state, event=event, round_no=round_no, stage=stage, key=key)
        return matches

    def complete_unit(
        self, *, round_no: int, stage: str, key: str, observed_postconditions: Any | None = None
    ) -> None:
        """Mark a side-effect-free unit complete, or reconcile supplied observations."""
        unit = self._require_unit(self._state, round_no, stage, key)
        expected = unit.get("expected_postconditions") or {}
        observed = expected if observed_postconditions is None else observed_postconditions
        if not self.reconcile_unit(
            round_no=round_no,
            stage=stage,
            key=key,
            observed_postconditions=observed,
        ):
            raise RecoveryConflictError(f"postcondition mismatch for {stage}/{key}")

    def fail_unit(
        self, *, round_no: int, stage: str, key: str, error: str, blocked: bool = False
    ) -> None:
        """Persist a retryable failure or a business/configuration block."""
        next_state = self.snapshot()
        unit = self._require_unit(next_state, round_no, stage, key)
        unit.update(status="blocked" if blocked else "failed", error=_redact_error(error))
        if blocked:
            next_state["rounds"][str(round_no)]["stages"][stage]["status"] = "blocked"
        self._commit(next_state, event="unit_failed", round_no=round_no, stage=stage, key=key)

    def complete_stage(self, *, round_no: int, stage: str) -> None:
        """Complete a stage only after every declared unit and dependency completes."""
        next_state = self.snapshot()
        round_state = self._require_round(next_state, round_no)
        stage_state = round_state["stages"].get(stage)
        if not stage_state:
            raise RecoveryConflictError(f"stage has not started: {stage}")
        if stage_state.get("status") == _STAGE_COMPLETE:
            return
        missing_dependencies = [
            name
            for name in stage_state.get("dependencies") or []
            if round_state["stages"].get(name, {}).get("status") != _STAGE_COMPLETE
        ]
        incomplete = [
            key
            for key, unit in stage_state.get("units", {}).items()
            if unit.get("status") != _STAGE_COMPLETE
        ]
        if missing_dependencies or incomplete:
            raise RecoveryConflictError(
                f"stage {stage} incomplete; dependencies={missing_dependencies}, units={incomplete}"
            )
        stage_state["status"] = _STAGE_COMPLETE
        self._commit(next_state, event="stage_completed", round_no=round_no, stage=stage)

    def set_admitted_issue_ids(self, *, round_no: int, issue_ids: Sequence[int]) -> None:
        """Freeze the owner-admitted delivery set once."""
        values = sorted(set(int(number) for number in issue_ids))
        next_state = self.snapshot()
        round_state = self._require_round(next_state, round_no)
        existing = list(round_state.get("admitted_issue_ids") or [])
        if existing and existing != values:
            raise RecoveryConflictError(f"round {round_no} admitted issue set changed")
        if existing == values:
            return
        round_state["admitted_issue_ids"] = values
        self._commit(next_state, event="admitted_set_frozen", round_no=round_no)

    def seal_round(self, *, round_no: int, sealed_sha: str) -> None:
        """Seal a round once after all started stages are complete."""
        next_state = self.snapshot()
        round_state = self._require_round(next_state, round_no)
        incomplete = [
            name
            for name, stage in round_state["stages"].items()
            if stage.get("status") != _STAGE_COMPLETE
        ]
        if incomplete:
            raise RecoveryConflictError(f"round {round_no} has incomplete stages: {incomplete}")
        previous = round_state.get("sealed_sha")
        if previous and previous != sealed_sha:
            raise RecoveryConflictError(f"round {round_no} sealed SHA changed")
        if previous == sealed_sha and round_state.get("status") == _STAGE_COMPLETE:
            return
        round_state.update(status=_STAGE_COMPLETE, sealed_sha=sealed_sha)
        self._commit(next_state, event="round_sealed", round_no=round_no)

    def unit(self, *, round_no: int, stage: str, key: str) -> dict[str, Any] | None:
        round_state = self._state["rounds"].get(str(round_no)) or {}
        stage_state = (round_state.get("stages") or {}).get(stage) or {}
        value = (stage_state.get("units") or {}).get(key)
        return copy.deepcopy(value) if value is not None else None

    def round_state(self, *, round_no: int) -> dict[str, Any] | None:
        """Return a defensive copy of one frozen round."""
        value = self._state["rounds"].get(str(round_no))
        return copy.deepcopy(value) if value is not None else None

    def stage_status(self, *, round_no: int, stage: str) -> str:
        round_state = self._state["rounds"].get(str(round_no)) or {}
        return str(((round_state.get("stages") or {}).get(stage) or {}).get("status") or "pending")

    @staticmethod
    def _require_round(state: dict[str, Any], round_no: int) -> dict[str, Any]:
        try:
            return state["rounds"][str(round_no)]
        except KeyError as exc:
            raise RecoveryConflictError(f"round is not frozen: {round_no}") from exc

    @classmethod
    def _require_unit(
        cls, state: dict[str, Any], round_no: int, stage: str, key: str
    ) -> dict[str, Any]:
        round_state = cls._require_round(state, round_no)
        try:
            return round_state["stages"][stage]["units"][key]
        except KeyError as exc:
            raise RecoveryConflictError(f"unit has not started: {stage}/{key}") from exc

    def _commit(
        self,
        next_state: dict[str, Any],
        *,
        event: str,
        round_no: int | None = None,
        stage: str | None = None,
        key: str | None = None,
    ) -> None:
        with _thread_lock(self.state_path):
            self.root.mkdir(parents=True, exist_ok=True)
            with self._lock_path.open("a+b") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX)
                current = _read_json(self.state_path)
                disk_revision = current.get("revision")
                if disk_revision != self._revision:
                    raise StaleRevisionError(
                        f"recovery revision changed: expected {self._revision}, found {disk_revision}"
                    )
                next_revision = self._revision + 1
                next_state["revision"] = next_revision
                next_state["updated_at"] = _now()
                _atomic_json(self.state_path, next_state)
                row = {
                    "at": _now(),
                    "event": event,
                    "revision": next_revision,
                }
                if round_no is not None:
                    row["round"] = round_no
                if stage is not None:
                    row["stage"] = stage
                if key is not None:
                    row["operation_key"] = key
                self._append_event_file(self.event_path, row)
                self._state = next_state
                self._revision = next_revision

    @staticmethod
    def _append_event_file(path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (canonical_json(row) + "\n").encode()
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, encoded)
            os.fsync(fd)
        finally:
            os.close(fd)


def _redact_error(error: str) -> str:
    text = str(error)
    for name in _SECRET_KEYS:
        value = os.environ.get(name.upper(), "")
        if value:
            text = text.replace(value, f"${{{name.upper()}}}")
    return text[:2000]
