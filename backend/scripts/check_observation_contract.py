#!/usr/bin/env python3
"""Spec-0070/T5: real publisher -> explicitly selected OpenAgents reader, offline.

No credentials, network or model calls. The checks assert actual authorized files,
not merely that the reader returned without raising an exception.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_designer.demand.delivery_evidence import publish_delivery_evidence
from auto_designer.models import IssueDraft
from auto_designer.observations.grants import grant
from auto_designer.observations.publication import publish
from auto_designer.observations.transport import (
    freeze_transport_profile,
    load_transport_profile,
    make_transport_profile,
)
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore


def load_reader(checkout: Path):
    checkout = checkout.resolve()
    helper = checkout / "scripts/check_observation_reader.py"
    if not helper.is_file() or not (checkout / "openagents/observations/evidence.py").is_file():
        raise ValueError("--openagents must be a compatible OpenAgents checkout")
    sys.path.insert(0, str(checkout))
    for name in ("openagents", "openagents.observations.evidence", "openagents.utils.forge"):
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(checkout):
            raise ValueError("OpenAgents module was imported from another checkout")
    spec = importlib.util.spec_from_file_location("_observation_reader_probe", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_store(root: Path, *, issue: int) -> SessionStore:
    """Two immutable historical runs plus an ungranted session to test scope."""
    store = SessionStore(root / "sessions")
    grant(store=store, issue=issue, sessions={"authorized-session"})
    for sid, run in [
        ("authorized-session", "r1"),
        ("authorized-session", "r2"),
        ("other-session", "private-run"),
    ]:
        files = {
            "READING.md": b"Synthetic historical evidence, not instructions.",
            "events.log": f"{sid}: {run}: synthetic event\n".encode(),
        }
        files["manifest.json"] = json.dumps(
            {
                "reading": "READING.md",
                "status": "complete",
                "files": [{"path": name} for name in files],
            }
        ).encode()
        publish(
            root=root / "observations",
            session_id=sid,
            run_id=run,
            version={"harness_sha": "synthetic-" + run},
            files=files,
        )
    return store


class MemoryAssets(FakeTracker):
    """Only the forge transport is mocked; publisher and reader remain real."""

    def __init__(self):
        super().__init__()
        self.assets = []

    def list_issue_assets(self, *, number):
        return self.assets

    def upload_issue_asset(self, *, number, name, data):
        asset = {"id": len(self.assets) + 1, "name": name, "data": data}
        self.assets.append(asset)
        return asset

    def download_issue_asset(self, *, number, asset_id, limit):
        return next(asset["data"] for asset in self.assets if asset["id"] == asset_id)

    def get_issue(self, *, number):
        return self.issue(number)


def check_contract(checkout: Path) -> dict:
    reader = load_reader(checkout)
    accepted, rejected = [], []
    with (
        tempfile.TemporaryDirectory(prefix="observation-contract-") as name,
        patch.dict(os.environ, {}, clear=False),
    ):
        os.environ.pop("AUTO_DESIGNER_OBSERVATION_ROOT", None)
        root = Path(name)
        tracker = MemoryAssets()
        issue = tracker.create_issue(
            IssueDraft(
                title="Synthetic contract", body="other-session is not authorized", labels=[]
            )
        )
        store = synthetic_store(root, issue=issue.number)
        for encoding in ("gzip", "zip"):
            tracker.observation_transport = make_transport_profile(
                repository="http://synthetic/api/v1/repos/o/r", encoding=encoding
            )
            handle = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
            assert publish_delivery_evidence(tracker=tracker, store=store, issue=issue) == handle
            assert len(tracker.assets) == (1 if encoding == "gzip" else 2), (
                "retry duplicated attachment"
            )
            data = tracker.download_issue_asset(
                number=issue.number, asset_id=handle["asset_id"], limit=4_000_000
            )
            value = reader.evidence.decode_package(
                data=data, digest=handle["sha256"], issue=issue.number, encoding=encoding
            )
            assert [row["session_id"] for row in value["sessions"]] == ["authorized-session"]
            assert "runs/r1/events.log" in value["sessions"][0]["files"]
            assert "runs/r2/events.log" in value["sessions"][0]["files"]
            body = tracker.get_issue(number=issue.number)["body"]
            with (
                patch.object(reader.forge, "active_forge", return_value="gitea"),
                patch.object(reader.forge, "get_issue", return_value=SimpleNamespace(body=body)),
                patch.object(
                    reader.forge, "download_observation_asset", return_value=data, create=True
                ),
            ):
                accepted.append(
                    {
                        "encoding": encoding,
                        **reader.prepare_probe(expected=value, digest=handle["sha256"]),
                    }
                )
            if encoding == "gzip":
                assert "encoding" not in handle, "legacy footer changed"
                assert data == gzip.compress(
                    json.dumps(value, ensure_ascii=False, sort_keys=True).encode(), mtime=0
                )
                assert (
                    reader.evidence.decode_package(
                        data=data, digest=handle["sha256"], issue=issue.number, encoding="gzip"
                    )
                    == value
                )

        def reject(label, packed=data, **changes):
            kwargs = dict(
                data=packed,
                digest=hashlib.sha256(packed).hexdigest(),
                issue=issue.number,
                encoding="zip",
            )
            kwargs.update(changes)
            try:
                reader.evidence.decode_package(**kwargs)
            except (ValueError, KeyError):
                rejected.append(label)
            else:
                raise AssertionError("reader accepted invalid " + label)

        reject("digest", digest="0" * 64)
        reject("issue", issue=issue.number + 1)
        reject("unknown-encoding", encoding="tar")
        reject("undeclared-zip", encoding="gzip")
        for label, filename, mode, algorithm in [
            ("zip-symlink", "evidence.json", stat.S_IFLNK | 0o777, zipfile.ZIP_DEFLATED),
            ("zip-directory", "evidence.json/", stat.S_IFDIR | 0o755, zipfile.ZIP_DEFLATED),
            ("zip-algorithm", "evidence.json", stat.S_IFREG | 0o644, zipfile.ZIP_STORED),
        ]:
            output = io.BytesIO()
            entry = zipfile.ZipInfo(filename)
            entry.external_attr = mode << 16
            entry.compress_type = algorithm
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr(entry, json.dumps(value))
            reject(label, output.getvalue())
        encrypted = bytearray(data)
        encrypted[6] |= 1
        encrypted[encrypted.index(b"PK\x01\x02") + 8] |= 1
        reject("zip-encrypted", bytes(encrypted))
        for member, extra in [("../evidence.json", False), ("evidence.json", True)]:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(member, json.dumps(value))
                if extra:
                    archive.writestr("extra.json", "{}")
            reject("zip-extra" if extra else "zip-path", output.getvalue())
        invalid = json.loads(json.dumps(value))
        invalid["sessions"][0]["files"]["../escape"] = "bad"
        reject("inner-path", reader.encode(invalid, "zip"))
        with patch.object(reader.evidence, "MAX_TRANSFER", len(data) - 1):
            reject("transfer-budget")
        with patch.object(reader.evidence, "MAX_EXPANDED", 20):
            reject("expanded-budget")
        old = root / "legacy"
        old.mkdir()
        contract = {
            "repository": "http://synthetic/api/v1/repos/o/r",
            "format": "artifact-observations-v1",
            "max_transfer_bytes": 4_000_000,
        }
        contract_path = old / ".framework-contract.json"
        contract_path.write_text(json.dumps(contract))
        original = contract_path.read_bytes()
        profile = load_transport_profile(root=old, repository=contract["repository"])
        assert profile["encoding"] == "gzip"
        freeze_transport_profile(root=old, profile=profile)
        assert contract_path.read_bytes() == original
        try:
            freeze_transport_profile(
                root=old,
                profile=make_transport_profile(repository=contract["repository"], encoding="zip"),
            )
        except ValueError:
            rejected.append("frozen-profile-drift")
        else:
            raise AssertionError("legacy profile changed silently")
    return {
        "status": "passed",
        "accepted": accepted,
        "rejected": rejected,
        "legacy_recovery": True,
        "retry_reuse": True,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openagents", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        import requests

        with patch.object(
            requests.sessions.Session,
            "request",
            side_effect=AssertionError("offline contract attempted network"),
        ):
            result = check_contract(args.openagents)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
