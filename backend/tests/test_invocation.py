# Spec-0049/T2：InvocationStore hermetic tests.
"""Round-trip, fail-open, and secret redaction."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from auto_designer.invocation import InvocationStore, record_invocation
from auto_designer.usage import bind_usage_context


def test_record_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("AUTO_DESIGNER_RUN_ID", "run-a")
    with bind_usage_context(round_no=2):
        record_invocation(
            side="demand",
            role="owner",
            subject={"kind": "round", "id": "2"},
            prompt="hello",
            structured={"decisions": []},
            status="success",
        )
    files = list((tmp_path / "demand").glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["round"] == 2
    assert data["side"] == "demand"
    assert data["input"]["prompt"] == "hello"
    index = (tmp_path / "index.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(index) == 1


def test_missing_env_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ROLE_RUNS_DIR", raising=False)
    record_invocation(
        side="demand",
        role="owner",
        subject={"kind": "round", "id": "1"},
        prompt="x",
        structured={},
        status="success",
    )
    assert list(tmp_path.iterdir()) == []


def test_write_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not-a-dir", encoding="utf-8")
    store = InvocationStore(root=blocked)
    assert store.record(payload={"side": "demand", "role": "x", "output": {}}) is None


def test_redacts_known_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("GITEA_TOKEN", "sekrit-token")
    record_invocation(
        side="demand",
        role="triager",
        subject={"kind": "report", "id": "1"},
        prompt="token=sekrit-token",
        structured={},
        status="success",
    )
    text = next((tmp_path / "demand").glob("*.json")).read_text(encoding="utf-8")
    assert "sekrit-token" not in text
    assert "${GITEA_TOKEN}" in text


def test_append_round_keeps_user_and_sealed_sha(tmp_path: Path) -> None:
    store = InvocationStore(root=tmp_path)
    store.write_manifest(data={"rounds": []})
    store.append_round(round_no=1, user_sha="aaa", sealed_sha="bbb")
    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert data["rounds"] == [{"round": 1, "user_sha": "aaa", "sealed_sha": "bbb"}]


def test_append_round_is_idempotent_and_conflict_visible(tmp_path: Path) -> None:
    store = InvocationStore(root=tmp_path)
    store.write_manifest(data={"rounds": []})
    store.append_round(round_no=1, user_sha="aaa", sealed_sha="bbb")
    store.append_round(round_no=1, user_sha="aaa", sealed_sha="bbb")
    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert len(data["rounds"]) == 1
    with pytest.raises(ValueError, match="conflicts"):
        store.append_round(round_no=1, user_sha="aaa", sealed_sha="changed")


def test_record_same_invocation_id_does_not_duplicate_index(tmp_path: Path) -> None:
    store = InvocationStore(root=tmp_path)
    payload = {
        "invocation_id": "fixed-id",
        "side": "demand",
        "role": "owner",
        "output": {"status": "success"},
    }
    assert store.record(payload=payload) == store.record(payload=payload)
    assert len((tmp_path / "index.jsonl").read_text().splitlines()) == 1


def test_concurrent_records_do_not_tear_index(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path))

    def _one(*, idx: int) -> None:
        record_invocation(
            side="demand",
            role="owner",
            subject={"kind": "round", "id": str(idx)},
            prompt=f"p{idx}",
            structured={"i": idx},
            status="success",
        )

    threads = [threading.Thread(target=_one, kwargs={"idx": i}) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    lines = (tmp_path / "index.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 12
    for line in lines:
        json.loads(line)
