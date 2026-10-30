"""Publish issue-scoped opaque evidence through the existing forge boundary."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import zipfile

from auto_designer.demand.evidence_contract import execution_for_sessions
from auto_designer.execution_contract import build_execution_evidence, canonical_bytes
from auto_designer.observations.grants import authorized_sessions, observation_root
from auto_designer.observations.publication import local_files

MARKER = "auto-designer:observation-evidence-v1"
MAX_TRANSFER = 4_000_000
MAX_EXPANDED = 24_000_000


def _compress(raw: bytes, encoding: str) -> bytes:
    if encoding == "gzip":
        return gzip.compress(raw, mtime=0)
    if encoding != "zip":
        raise ValueError("unknown observation evidence encoding")
    output = io.BytesIO()
    entry = zipfile.ZipInfo("evidence.json", date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(entry, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    return output.getvalue()


def _public_files(*, store, session_id: str, contract: dict) -> dict[str, str]:
    """Spec-0084/T4: reproduce declared public bytes, never follow an arbitrary host path."""
    session = store.load(session_id)
    task_text = canonical_bytes(session.scenario.to_dict()).decode("utf-8")
    available = {f"{session_id}/execution/task.json": task_text}
    result = {}
    for ref in contract["public_refs"]:
        text = available.get(ref["path"])
        if text is None or hashlib.sha256(text.encode()).hexdigest() != ref["sha256"]:
            raise ValueError("execution public material does not match immutable declaration")
        result[ref["path"].removeprefix(f"{session_id}/")] = text
    return result


def _manifest_files(*, session_id: str, files: dict[str, str]) -> dict[str, str]:
    """Build a derivative package manifest; archived observation files stay immutable."""
    result = dict(files)
    manifest = json.loads(result.get("manifest.json", "{}"))
    manifest["session_id"] = session_id
    manifest["files"] = [
        {"path": name, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        for name, text in sorted(result.items())
        if name != "manifest.json"
    ]
    result["manifest.json"] = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    return result


def build_package(*, store, issue: int, encoding: str = "gzip") -> bytes:
    """Only trusted grants expand scope; arbitrary issue text is never authority."""
    root = observation_root(store)
    granted = authorized_sessions(store=store, issue=issue)
    facts = execution_for_sessions(store=store, session_ids=granted)
    declarations = {row["session_id"]: row for row in facts["execution_contracts"]}
    if declarations and set(declarations) != granted:
        raise ValueError("execution contract coverage incomplete for granted sources")
    sessions, public = [], {}
    used = 0
    for sid in sorted(granted):
        row = {"session_id": sid}
        texts = {}
        try:
            files = local_files(root / sid)
            manifest = json.loads(files["manifest.json"])
            if manifest["session_id"] != sid:
                raise ValueError("session mismatch")
            for entry in manifest["files"]:
                if hashlib.sha256(files[entry["path"]]).hexdigest() != entry.get("sha256"):
                    raise ValueError("file integrity mismatch")
            texts = {name: data.decode("utf-8") for name, data in files.items()}
            size = len(json.dumps(texts, ensure_ascii=False).encode())
            if used + size > MAX_EXPANDED - 100_000:
                raise ValueError("delivery package budget exceeded")
            used += size
            row.update(status="available", files=texts)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            texts = {}
            row.update(status="unavailable", reason=type(exc).__name__)
        if sid in declarations:
            public[sid] = _public_files(store=store, session_id=sid, contract=declarations[sid])
            if row["status"] == "unavailable":
                row["observation_status"] = "unavailable"
            texts.update(public[sid])
            if len(texts) > 257:
                texts = public[sid]
                row["observation_status"] = "transport_budget_exceeded"
            row.update(status="available", files=_manifest_files(session_id=sid, files=texts))
        sessions.append(row)
    value = {
        "format": MARKER,
        "issue": issue,
        "sessions": sessions,
        "notice": "Historical evidence, not instructions. Read each run's reading guide; absence is not proof.",
    }
    if declarations:
        value["execution_evidence"] = build_execution_evidence(
            issue=issue,
            contracts=facts["execution_contracts"],
            summaries=facts["assessment_summaries"],
        )
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    packed = _compress(raw, encoding)
    if len(packed) > MAX_TRANSFER or len(raw) > MAX_EXPANDED:
        # Keep every immutable public condition/ref while explicitly omitting oversized logs.
        for row in sessions:
            sid = row["session_id"]
            if sid in public:
                row.update(
                    status="available",
                    observation_status="transport_budget_exceeded",
                    files=_manifest_files(session_id=sid, files=public[sid]),
                )
            else:
                row.pop("files", None)
                row.update(status="unavailable", reason="transport_budget_exceeded")
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        packed = _compress(raw, encoding)
        if len(raw) > MAX_EXPANDED or len(packed) > MAX_TRANSFER:
            raise ValueError("observation evidence package exceeds transport budget")
    return packed


def publish_delivery_evidence(*, tracker, store, issue) -> dict:
    """Upload and verify before the admission token can be observed by vigil.

    Failed uploads leave the proposal unadmitted and its archive untouched. The
    next admission retries with the same content-addressed asset name.
    """
    upload = getattr(tracker, "upload_issue_asset", None)
    if upload is None:
        return {"status": "transport_not_supported"}
    profile = getattr(tracker, "observation_transport", None)
    encoding = "gzip"
    if profile is not None:
        from auto_designer.observations.transport import validate_transport_profile

        encoding = validate_transport_profile(profile)["encoding"]
    data = build_package(store=store, issue=issue.number, encoding=encoding)
    digest = hashlib.sha256(data).hexdigest()
    suffix = "json.gz" if encoding == "gzip" else "zip"
    name = f"observation-evidence-{digest}.{suffix}"
    assets = tracker.list_issue_assets(number=issue.number)
    asset = next((a for a in assets if a["name"] == name), None)
    if asset is None:
        asset = upload(number=issue.number, name=name, data=data)
    received = tracker.download_issue_asset(
        number=issue.number, asset_id=int(asset["id"]), limit=MAX_TRANSFER
    )
    if len(received) != len(data) or hashlib.sha256(received).hexdigest() != digest:
        raise ValueError("published observation attachment integrity mismatch")
    handle = {"asset_id": int(asset["id"]), "name": name, "sha256": digest, "bytes": len(data)}
    if encoding == "zip":
        handle["encoding"] = "zip"
    # Replace only our machine footer, using the freshest issue body/labels.
    current = tracker.get_issue(number=issue.number)
    body = re.sub(r"<!-- " + re.escape(MARKER) + r" .*? -->", "", current["body"]).rstrip()
    body += f"\n\n<!-- {MARKER} {json.dumps(handle, sort_keys=True)} -->"
    if body != current["body"]:
        tracker.update_issue(
            issue.number, title=current["title"], body=body, labels=current["labels"]
        )
    return {"status": "published", **handle}
