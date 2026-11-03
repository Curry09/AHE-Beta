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
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ahe_beta.demand.delivery_evidence import publish_delivery_evidence
from ahe_beta.execution_contract import (
    build_execution_evidence,
    canonical_bytes,
    canonical_sha256,
    make_execution_contract,
)
from ahe_beta.models import (
    IssueDraft,
    Persona,
    SeedScenario,
    Session,
    Transcript,
    WorkspaceSpec,
)
from ahe_beta.observations.grants import grant
from ahe_beta.observations.publication import publish
from ahe_beta.observations.transport import (
    freeze_transport_profile,
    load_transport_profile,
    make_transport_profile,
)
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.user.session_store import SessionStore


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
        os.environ.pop("AHE_BETA_OBSERVATION_ROOT", None)
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


def check_execution_publication(*, checkout: Path) -> dict:
    """Current Session -> publisher -> required reader -> actual role contexts."""
    reader = load_reader(checkout)
    fixture_path = (
        Path(__file__).resolve().parents[1] / "tests/fixtures/execution_evidence_contract.json"
    )
    counterpart = checkout / "tests/fixtures/execution_evidence_contract.json"
    # Update both copies and regenerate derived hashes together; the reader pin
    # must identify the matching fixture version.
    assert fixture_path.read_bytes() == counterpart.read_bytes(), "shared execution fixture drift"
    fixture = json.loads(fixture_path.read_text())["package"]
    wire = fixture["execution_evidence"]
    assert (
        build_execution_evidence(
            issue=wire["issue"],
            contracts=wire["execution_contracts"],
            summaries=wire["assessment_summaries"],
        )
        == wire
    ), "publisher canonical encoding differs from reader fixture"
    accepted, rejected = [], []
    with tempfile.TemporaryDirectory(prefix="execution-publication-") as name:
        root = Path(name)
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        store = SessionStore(root / "sessions")
        tracker = MemoryAssets()
        issue = tracker.create_issue(
            IssueDraft(title="Two original conditions", body="public goal", labels=[])
        )
        contracts, summaries = [], []
        for number, followup in enumerate(("unavailable", "possible"), 1):
            sid = f"current-session-{number}"
            provenance = {
                "contract_version": 1,
                "run_id": "synthetic-run",
                "round_no": 1,
                "slot": number - 1,
                "persona_id": "synthetic",
                "task_id": f"task-{number}",
                "task_digest": "1" * 64,
                "task_kind": "ordinary",
                "interaction": "direct" if number == 1 else "simulated_user",
                "harness_sha": "synthetic-user-sha",
            }
            scenario = SeedScenario(
                description="Fix the calculation result in the public example and deliver result.txt.",
                workspace=WorkspaceSpec(
                    params={
                        key: provenance[key]
                        for key in ("task_id", "task_digest", "task_kind", "interaction")
                    }
                ),
            )
            contract = make_execution_contract(
                session_id=sid,
                task_id=f"task-{number}",
                task_digest="1" * 64,
                followup_input=followup,
                task_budget_seconds=7200 if number == 1 else None,
                budget_source="task_metadata" if number == 1 else "unverified",
                public_refs=[
                    {
                        "kind": "task",
                        "path": f"{sid}/execution/task.json",
                        "sha256": canonical_sha256(scenario.to_dict()),
                    }
                ],
            )
            session = Session(
                persona=Persona("synthetic", "test", "test", "test", "test"),
                scenario=scenario,
                transcript=Transcript(),
                session_id=sid,
                execution_contract=contract,
                session_provenance=provenance,
            )
            store.save(session)
            contracts.append(contract)
            summaries.append(
                {
                    "receipt_id": f"receipt-{number}",
                    "session_id": sid,
                    "contract_id": contract["contract_id"],
                    "assessment_kind": "independent",
                    "status": "completed" if number == 1 else "unavailable",
                    "passed": False if number == 1 else None,
                    "score": None,
                    "metric_definition": None,
                    "source_sha256": "2" * 64,
                }
            )
        grant(store=store, issue=issue.number, sessions={c["session_id"] for c in contracts})
        assessment = root / "assessment"
        (assessment / "feedback").mkdir(parents=True)
        (assessment / "feedback/round-1.json").write_bytes(
            canonical_bytes(
                {
                    "round_no": 1,
                    "user_sha": "synthetic-user-sha",
                    "summaries": summaries,
                    "sha256": canonical_sha256(summaries),
                }
            )
        )
        (assessment / "private-grader-output.json").write_text("PRIVATE_GRADER_CANARY")
        store.bind_assessment_root(assessment)
        expected = build_execution_evidence(
            issue=issue.number, contracts=contracts, summaries=summaries
        )
        for encoding in ("gzip", "zip"):
            tracker.observation_transport = make_transport_profile(
                repository="http://synthetic/api/v1/repos/o/r", encoding=encoding
            )
            handle = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
            assert publish_delivery_evidence(tracker=tracker, store=store, issue=issue) == handle
            data = tracker.download_issue_asset(
                number=issue.number, asset_id=handle["asset_id"], limit=4_000_000
            )
            value = reader.evidence.decode_package(
                data=data, digest=handle["sha256"], issue=issue.number, encoding=encoding
            )
            assert value["execution_evidence"] == expected
            assert "PRIVATE_GRADER_CANARY" not in json.dumps(value)
            assert all(row["observation_status"] == "unavailable" for row in value["sessions"])
            body = tracker.get_issue(number=issue.number)["body"]
            with (
                patch.object(reader.forge, "active_forge", return_value="gitea"),
                patch.object(reader.forge, "get_issue", return_value=SimpleNamespace(body=body)),
                patch.object(
                    reader.forge, "download_observation_asset", return_value=data, create=True
                ),
            ):
                scope = reader.evidence.prepare(
                    work_dir=root,
                    issue=issue.number,
                    role="developer",
                    execution_required=True,
                )
                reader.verify_scope(scope=scope, expected=value, digest=handle["sha256"])
                assert scope["execution_evidence"] == expected
                accepted.append(encoding)
        published_fixture = root / "published-fixture.json"
        published_fixture.write_text(json.dumps({"package": value}, ensure_ascii=False))
        contexts = reader.check_execution_contract(fixture=published_fixture)
        # Recompute the outer envelope hash: inner semantic integrity must still reject.
        invalids = []
        missing = json.loads(json.dumps(value))
        del missing["execution_evidence"]
        invalids.append(("required-block-missing", missing))
        for label in ("contract-digest", "public-material-digest", "private-summary-field"):
            changed = json.loads(json.dumps(value))
            payload = changed["execution_evidence"]
            if label == "contract-digest":
                payload["execution_contracts"][0]["followup_input"] = "unknown"
            elif label == "public-material-digest":
                changed["sessions"][0]["files"]["execution/task.json"] = "changed public task"
            else:
                payload["assessment_summaries"][0]["private_logs"] = "PRIVATE_GRADER_CANARY"
            invalids.append((label, changed))
        for label, invalid in invalids:
            packed = reader.encode(invalid, "zip")
            handle = {
                "asset_id": 1,
                "sha256": hashlib.sha256(packed).hexdigest(),
                "bytes": len(packed),
                "encoding": "zip",
            }
            body = f"<!-- {reader.evidence.MARKER} {json.dumps(handle)} -->"
            with (
                patch.object(reader.forge, "active_forge", return_value="gitea"),
                patch.object(reader.forge, "get_issue", return_value=SimpleNamespace(body=body)),
                patch.object(
                    reader.forge, "download_observation_asset", return_value=packed, create=True
                ),
            ):
                try:
                    reader.evidence.prepare(
                        work_dir=root,
                        issue=issue.number,
                        role="developer",
                        execution_required=True,
                    )
                except reader.evidence.execution_contracts.ExecutionContractUnavailable:
                    rejected.append(label)
                else:
                    raise AssertionError("required reader accepted " + label)
    return {
        "status": "passed",
        "shared_fixture_identical": True,
        "published_encodings": accepted,
        "private_material_absent": True,
        "rejected": rejected,
        "role_contexts": contexts,
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
            result["execution_evidence"] = check_execution_publication(checkout=args.openagents)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
