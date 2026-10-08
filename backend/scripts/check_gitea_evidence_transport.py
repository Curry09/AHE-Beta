#!/usr/bin/env python3
"""Spec-0070/T5: explicit live synthetic probe; creates a private repository and issue.

Credentials are read only from environment or --env-file. No model is called.
The issue is closed after testing; its private repository and synthetic attachments
remain available for separately authorized container/E2B readback checks.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_designer.demand.delivery_evidence import build_package, publish_delivery_evidence
from auto_designer.models import IssueDraft
from auto_designer.observations.transport import freeze_transport_profile
from auto_designer.tracker.gitea import GiteaTracker
from check_observation_contract import load_reader, synthetic_store


def read_env(path: Path | None) -> dict:
    values = dict(os.environ)
    if path:
        # dotenv parsing, never shell evaluation, interpolation or logging.
        from dotenv import dotenv_values

        values.update(
            {
                key: value
                for key, value in dotenv_values(path, interpolate=False).items()
                if value is not None
            }
        )
    return values


def probe(
    *,
    checkout: Path,
    output: Path,
    env: dict,
    base_url: str | None = None,
    owner: str | None = None,
) -> dict:
    reader = load_reader(checkout)
    base_url = (base_url or env.get("GITEA_URL", "")).rstrip("/")
    owner = owner or env.get("GITEA_USER") or env.get("GITEA_OWNER") or env.get("OWNER")
    token = env.get("GITEA_TOKEN") or env.get("TOKEN")
    if not base_url or not owner or not token:
        raise ValueError("GITEA_URL, GITEA_USER and GITEA_TOKEN are required")
    origin = urlsplit(base_url)
    if (
        origin.scheme not in ("http", "https")
        or not origin.hostname
        or origin.username is not None
        or origin.password is not None
        or origin.query
        or origin.fragment
    ):
        raise ValueError("probe base URL must not contain credentials, query or fragment")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ").lower() + "-" + uuid.uuid4().hex[:8]
    repo = "observation-transport-probe-" + run_id
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "status": "failed",
        "base_url": base_url,
        "owner": owner,
        "repo": repo,
        "issue": None,
        "issue_closed": False,
        "no_model_calls": True,
    }
    tracker = GiteaTracker(base_url, owner, repo, token)
    issue = None
    try:
        if tracker.authenticated_login() != owner:
            raise ValueError("probe owner must be the authenticated personal account")
        created = tracker._request(
            "POST",
            "/user/repos",
            {
                "name": repo,
                "private": True,
                "auto_init": False,
                "description": "Synthetic evidence compatibility probe; contains no real experiment feedback.",
            },
        )
        if created.get("private") is not True:
            raise ValueError("probe repository was not private")
        issue = tracker.create_issue(
            IssueDraft(
                title="Synthetic observation transport compatibility probe",
                body="Synthetic authorized evidence only. Created for explicit cross-repository compatibility verification; close after readback.",
                labels=[],
            )
        )
        result["issue"] = issue.number
        profile = tracker.select_observation_transport()
        from openagents.observations.capabilities import describe

        capabilities = describe()
        assert capabilities["schema"] == "openagents-observation-reader-capabilities-v1"
        assert capabilities["marker"] == "auto-designer:observation-evidence-v1"
        assert capabilities["zip_profile"] == "single-evidence-json-v1"
        assert profile["encoding"] in capabilities["encodings"]
        assert profile["download_policy"] in capabilities["download_policies"]
        for key in ("max_transfer_bytes", "max_expanded_bytes"):
            assert capabilities[key] == profile[key]
        tracker.bind_observation_transport(profile=profile, reader_verified=True)
        tracker.preflight_observations()
        with (
            tempfile.TemporaryDirectory(prefix="live-evidence-publisher-") as temporary,
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("AUTO_DESIGNER_OBSERVATION_ROOT", None)
            root = Path(temporary)
            freeze_transport_profile(root=root / "observations", profile=profile)
            store = synthetic_store(root, issue=issue.number)
            handle = publish_delivery_evidence(tracker=tracker, store=store, issue=issue)
            assert publish_delivery_evidence(tracker=tracker, store=store, issue=issue) == handle
            assert len(tracker.list_issue_assets(number=issue.number)) == 1
            packed = build_package(store=store, issue=issue.number, encoding=profile["encoding"])
            assert hashlib.sha256(packed).hexdigest() == handle["sha256"]
            if profile["encoding"] == "gzip":
                inner = gzip.decompress(packed)
            else:
                with zipfile.ZipFile(io.BytesIO(packed)) as archive:
                    inner = archive.read("evidence.json")
            expected = json.loads(inner)
            expected_path = output / "expected-package.json"
            expected_path.write_bytes(inner)
            result.update(
                {
                    "profile": profile,
                    "sha256": handle["sha256"],
                    "asset_id": handle["asset_id"],
                    "expected_package": str(expected_path.resolve()),
                }
            )
            os.environ["OBSERVATION_PROBE_TOKEN"] = token
            reader.forge.configure(
                name="gitea",
                settings={
                    "base_url": base_url,
                    "owner": owner,
                    "repo": repo,
                    "token_env": "OBSERVATION_PROBE_TOKEN",
                },
            )
            result["reader"] = reader.prepare_probe(expected=expected, digest=handle["sha256"])
            result["status"] = "passed"
    except Exception as exc:
        result["error"] = type(exc).__name__
    finally:
        if issue is not None:
            try:
                tracker.set_state(
                    issue.number, "closed", reason="Synthetic compatibility probe completed."
                )
                result["issue_closed"] = True
            except Exception as exc:
                result["status"] = "failed"
                result["cleanup_error"] = type(exc).__name__
        (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="required acknowledgement of private probe repository creation",
    )
    parser.add_argument("--openagents", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--owner")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new directory for sanitized results and synthetic expected JSON",
    )
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; this command creates a private repository and issue")
    try:
        result = probe(
            checkout=args.openagents,
            output=args.output_dir,
            env=read_env(args.env_file),
            base_url=args.base_url,
            owner=args.owner,
        )
    except Exception as exc:
        result = {"status": "failed", "error": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
