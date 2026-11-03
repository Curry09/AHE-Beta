"""Probe isolation, producer authority, and explicit-checkout CLI boundaries."""

import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

import check_gitea_evidence_transport as live
from ahe_beta.demand.delivery_evidence import build_package
from ahe_beta.execution_contract import build_execution_evidence
from check_observation_contract import load_reader, synthetic_store

ROOT = Path(__file__).resolve().parents[2]


def test_shared_execution_fixture_binds_actual_public_file_bytes():
    package = json.loads(
        (ROOT / "backend/tests/fixtures/execution_evidence_contract.json").read_text()
    )["package"]
    wire = package["execution_evidence"]
    assert (
        build_execution_evidence(
            issue=wire["issue"],
            contracts=wire["execution_contracts"],
            summaries=wire["assessment_summaries"],
        )
        == wire
    )
    sessions = {session["session_id"]: session for session in package["sessions"]}
    for contract in wire["execution_contracts"]:
        session = sessions[contract["session_id"]]
        files = session["files"]
        entries = {
            entry["path"]: entry["sha256"] for entry in json.loads(files["manifest.json"])["files"]
        }
        for ref in contract["public_refs"]:
            session_id, path = ref["path"].split("/", 1)
            assert session_id == session["session_id"]
            actual = hashlib.sha256(files[path].encode("utf-8")).hexdigest()
            assert actual == entries[path] == ref["sha256"]


def test_synthetic_probe_preserves_history_without_granting_other_session(tmp_path, monkeypatch):
    monkeypatch.delenv("AHE_BETA_OBSERVATION_ROOT", raising=False)
    store = synthetic_store(tmp_path, issue=7)
    value = json.loads(gzip.decompress(build_package(store=store, issue=7)))
    assert [row["session_id"] for row in value["sessions"]] == ["authorized-session"]
    files = value["sessions"][0]["files"]
    assert "runs/r1/events.log" in files
    assert "runs/r2/events.log" in files
    assert not any("other-session" in text for text in files.values())
    wrong_issue = json.loads(gzip.decompress(build_package(store=store, issue=8)))
    assert wrong_issue["sessions"] == []


def test_offline_requires_explicit_checkout():
    result = subprocess.run(
        [sys.executable, str(ROOT / "backend/scripts/check_observation_contract.py")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--openagents" in result.stderr


def test_invalid_checkout_does_not_fall_back_to_global_install(tmp_path):
    with pytest.raises(ValueError, match="checkout"):
        load_reader(tmp_path)


def test_live_requires_explicit_opt_in_before_any_network(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "backend/scripts/check_gitea_evidence_transport.py"),
            "--openagents",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "result"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "--live is required" in result.stderr
    assert not (tmp_path / "result").exists()


def test_env_file_is_data_not_shell_or_interpolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-expand")
    path = tmp_path / "private.env"
    path.write_text('GITEA_TOKEN="${UNRELATED_SECRET}$(touch should-not-exist)"\n')
    assert live.read_env(path)["GITEA_TOKEN"] == "${UNRELATED_SECRET}$(touch should-not-exist)"
    assert not (tmp_path / "should-not-exist").exists()


def test_probe_failure_still_closes_issue_and_redacts_error(tmp_path, monkeypatch):
    from types import SimpleNamespace

    closed = []

    class Tracker:
        def __init__(self, *args):
            pass

        def authenticated_login(self):
            return "synthetic-user"

        def _request(self, method, endpoint, payload):
            assert payload["private"] is True
            assert payload["name"].startswith("observation-transport-probe-")
            return {"private": True}

        def create_issue(self, draft):
            return SimpleNamespace(number=42)

        def select_observation_transport(self):
            raise RuntimeError("token-secret https://signed.example/?secret")

        def set_state(self, number, state, reason):
            closed.append((number, state, reason))

    monkeypatch.setattr(live, "GiteaTracker", Tracker)
    monkeypatch.setattr(live, "load_reader", lambda path: object())
    output = tmp_path / "result"
    result = live.probe(
        checkout=tmp_path,
        output=output,
        env={
            "GITEA_URL": "https://synthetic.example",
            "GITEA_USER": "synthetic-user",
            "GITEA_TOKEN": "token-secret",
        },
    )
    assert result["status"] == "failed"
    assert result["error"] == "RuntimeError"
    assert result["issue_closed"] is True
    assert closed[0][:2] == (42, "closed")
    report = (output / "result.json").read_text()
    assert "token-secret" not in report
    assert "signed.example" not in report
