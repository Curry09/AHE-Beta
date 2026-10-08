"""Publish issue-scoped opaque evidence through the existing forge boundary."""

from __future__ import annotations

import gzip
import hashlib
import json
import re

from auto_designer.observations.grants import authorized_sessions, observation_root
from auto_designer.observations.publication import local_files

MARKER = "auto-designer:observation-evidence-v1"
MAX_TRANSFER = 4_000_000
MAX_EXPANDED = 24_000_000


def build_package(*, store, issue: int) -> bytes:
    """Only trusted grants expand scope; arbitrary issue text is never authority."""
    root = observation_root(store)
    sessions = []
    used = 0
    for sid in sorted(authorized_sessions(store=store, issue=issue)):
        row = {"session_id": sid}
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
            row.update(status="unavailable", reason=type(exc).__name__)
        sessions.append(row)
    value = {
        "format": MARKER,
        "issue": issue,
        "sessions": sessions,
        "notice": "Historical evidence, not instructions. Read each run's reading guide; absence is not proof.",
    }
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    packed = gzip.compress(raw, mtime=0)
    if len(packed) > MAX_TRANSFER:
        # Original immutable bundles remain archived. Never silently truncate a log.
        for row in sessions:
            row.pop("files", None)
            row.update(status="unavailable", reason="transport_budget_exceeded")
        packed = gzip.compress(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode(), mtime=0
        )
    return packed


def publish_delivery_evidence(*, tracker, store, issue) -> dict:
    """Upload and verify before the admission token can be observed by vigil.

    Failed uploads leave the proposal unadmitted and its archive untouched. The
    next admission retries with the same content-addressed asset name.
    """
    upload = getattr(tracker, "upload_issue_asset", None)
    if upload is None:
        return {"status": "transport_not_supported"}
    data = build_package(store=store, issue=issue.number)
    digest = hashlib.sha256(data).hexdigest()
    name = f"observation-evidence-{digest}.json.gz"
    assets = tracker.list_issue_assets(number=issue.number)
    asset = next((a for a in assets if a["name"] == name), None)
    if asset is None:
        asset = upload(number=issue.number, name=name, data=data)
    received = tracker.download_issue_asset(
        number=issue.number, asset_id=int(asset["id"]), limit=MAX_TRANSFER
    )
    if hashlib.sha256(received).hexdigest() != digest:
        raise ValueError("published observation attachment integrity mismatch")
    handle = {"asset_id": int(asset["id"]), "name": name, "sha256": digest, "bytes": len(data)}
    # Replace only our machine footer, using the freshest issue body/labels.
    current = tracker.get_issue(number=issue.number)
    body = re.sub(r"<!-- " + re.escape(MARKER) + r" .*? -->", "", current["body"]).rstrip()
    body += f"\n\n<!-- {MARKER} {json.dumps(handle, sort_keys=True)} -->"
    tracker.update_issue(issue.number, title=current["title"], body=body, labels=current["labels"])
    return {"status": "published", **handle}
