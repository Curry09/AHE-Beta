"""Spec-0079/T2: parent evidence stays read-only and outside child session metrics."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from ahe_beta.experiment.config import ConfigError
from ahe_beta.models import Session
from ahe_beta.observations.grants import grant
from ahe_beta.observations.grants import observation_root as resolved_observation_root
from ahe_beta.observations.publication import local_files
from ahe_beta.user.session_store import (
    SessionConflictError,
    _index_entry,
    read_assessment_summaries,
)


class ContinuationEvidenceView:
    """A bootstrap-only facade; historical numbers resolve solely through the explicit map."""

    def __init__(
        self, *, child_store: Any, parent_root: Path, export: dict, issue_map: dict
    ) -> None:
        self._child = child_store
        self._parent_root = parent_root
        self._selected = {item["session_id"]: item for item in export["boundary"]["sessions"]}
        self._issue_map = issue_map
        collection = parent_root / "collection.json"
        receipt = json.loads(collection.read_text()) if collection.is_file() else {}
        self._projections = receipt.get("public_projections", {})
        self._archive_files = receipt.get("files", {})
        for sid in self._selected:
            if (child_store.root / f"{sid}.json").exists():
                raise SessionConflictError("Parent and child session identities collide")

    @property
    def root(self) -> Path:
        return self._child.root

    def load(self, session_id: str) -> Session:
        selected = self._selected.get(session_id)
        if selected is None:
            return self._child.load(session_id)
        raw = (self._parent_root / selected["path"]).read_bytes()
        expected = selected["sha256"]
        projection = self._projections.get(selected["path"])
        if projection is not None:
            if (
                projection.get("original_sha256") != expected
                or projection.get("reason") != "credential_redaction"
            ):
                raise ConfigError("Continuation parent session projection is invalid")
            expected = projection["archive_sha256"]
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ConfigError("Continuation parent session content changed")
        data = json.loads(raw)
        session = Session.from_dict(data)
        if session.session_id != session_id:
            raise ConfigError("Continuation parent session identity changed")
        return session

    def find_session_id_by_issue(self, issue_number: int) -> str | None:
        rows = [
            item
            for item in self._issue_map.values()
            if int(item["current_number"]) == int(issue_number)
        ]
        if rows:
            ids = set().union(*(set(item["session_ids"]) for item in rows))
            if len(ids) != 1:
                raise ConfigError("Continuation report does not identify a single source session")
            return next(iter(ids))
        return self._child.find_session_id_by_issue(issue_number)

    def load_user_feedback_envelope(self, session_id: str) -> dict:
        if session_id not in self._selected:
            return self._child.load_user_feedback_envelope(session_id)
        session = self.load(session_id)
        from ahe_beta.demand.evidence_contract import EvidenceEnvelope, build_evidence_envelope

        if session.user_feedback_envelope:
            envelope = EvidenceEnvelope.from_dict(session.user_feedback_envelope)
            if envelope.evidence_categories:
                return envelope.to_dict()
        return build_evidence_envelope(session).to_dict()

    def index(self, *, include_invalid: bool = False) -> list[dict]:
        rows = []
        for sid, selected in self._selected.items():
            row = _index_entry(self.load(sid))
            row["source_n_issues"] = row["n_issues"]
            row["source_issue_numbers"] = row["issue_numbers"]
            row["issue_numbers"] = [
                item["current_number"]
                for item in self._issue_map.values()
                if sid in item["session_ids"]
            ]
            row["n_issues"] = len(row["issue_numbers"])
            row["source_session_sha256"] = selected["sha256"]
            if selected["path"] in self._projections:
                row["source_public_projection"] = dict(self._projections[selected["path"]])
            if include_invalid or row["evaluation_status"] == "valid":
                rows.append(row)
        return rows

    def load_assessment_summaries(self, session_id: str) -> list[dict]:
        """Spec-0084/T5: retain parent measurements without mixing them into child metrics."""
        if session_id not in self._selected:
            return self._child.load_assessment_summaries(session_id)
        session = self.load(session_id)
        round_no = session.session_provenance.get("round_no")
        if type(round_no) is not int:
            return []
        relative = f"assessment/feedback/round-{round_no}.json"
        digest = self._archive_files.get(relative)
        if digest is None:
            if (self._parent_root / relative).exists():
                raise ConfigError("Continuation assessment is not in the verified archive")
            return []
        return read_assessment_summaries(
            self._parent_root / "assessment", session, archive_sha256=digest
        )


def _verified_bundle(root: Path) -> dict[str, bytes]:
    """Validate each native declared byte without rebuilding or upgrading its manifest."""
    files = local_files(root)
    raw = files["manifest.json"]
    document = json.loads(raw)
    for item in document["files"]:
        data = files[item["path"]]
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ConfigError("Continuation native observation hash changed")
        if "bytes" in item and len(data) != item["bytes"]:
            raise ConfigError("Continuation native observation size changed")
    return files


def install_parent_observations(
    *, parent_root: Path, export: dict, observation_root: Path, issue_map: dict, store: Any
) -> dict:
    """Install exact native bytes and create new grants only for explicitly mapped evidence."""
    if resolved_observation_root(store).resolve() != observation_root.resolve():
        raise ConfigError("Continuation observation root differs from the current grant authority")
    result = {}
    for selected in export["boundary"]["sessions"]:
        sid = selected["session_id"]
        source = selected.get("observation_path")
        if not source:
            result[sid] = {"status": "unavailable", "reason": "No native parent observation"}
            continue
        try:
            files = _verified_bundle(parent_root / source)
        except (OSError, ValueError, KeyError, TypeError, ConfigError):
            result[sid] = {"status": "unavailable", "reason": "Native parent bytes not verified"}
            continue
        destination = observation_root / sid
        if destination.exists():
            existing = _verified_bundle(destination)
            if existing != files:
                raise ConfigError(
                    "Continuation observation identity collides with current evidence"
                )
        else:
            observation_root.mkdir(parents=True, exist_ok=True)
            stage = observation_root / f".{sid}.continuation"
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir()
            for name, data in files.items():
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            stage.replace(destination)
        result[sid] = {
            "status": "available",
            "sha256": hashlib.sha256(files["manifest.json"]).hexdigest(),
        }
    for mapped in issue_map.values():
        grant(store=store, issue=mapped["current_number"], sessions=set(mapped["session_ids"]))
    return result


def verify_installed_parent_observations(
    *, export: dict, observation_root: Path, receipt: dict
) -> None:
    """Read-only verification of the immutable import receipt and installed native bytes."""
    expected = {selected["session_id"] for selected in export["boundary"]["sessions"]}
    if set(receipt) != expected:
        raise ConfigError("Continuation native observation receipt selection changed")
    for selected in export["boundary"]["sessions"]:
        sid = selected["session_id"]
        row = receipt[sid]
        if row.get("status") == "unavailable":
            if (observation_root / sid).exists():
                raise ConfigError("Unavailable continuation observation gained unverified bytes")
            continue
        if row.get("status") != "available" or not selected.get("observation_path"):
            raise ConfigError("Continuation native observation receipt changed")
        try:
            files = _verified_bundle(observation_root / sid)
        except (OSError, ValueError, KeyError, TypeError, ConfigError) as exc:
            raise ConfigError("Continuation installed native observation changed") from exc
        if hashlib.sha256(files["manifest.json"]).hexdigest() != row.get("sha256"):
            raise ConfigError("Continuation installed native manifest changed")
