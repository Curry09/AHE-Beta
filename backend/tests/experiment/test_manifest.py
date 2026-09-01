# Spec-0047/T2：manifest 原子创建与 journal 追加。
from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_designer.experiment.manifest import (
    ManifestError,
    append_journal,
    assert_immutable,
    create_manifest,
    last_state,
    read_manifest,
)


def test_create_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    create_manifest(path=path, data={"id": "a", "pin": "sha"})
    assert read_manifest(path=path)["id"] == "a"
    with pytest.raises(ManifestError, match="已存在"):
        create_manifest(path=path, data={"id": "b"})
    assert read_manifest(path=path)["id"] == "a"


def test_journal_appends_and_manifest_stays(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    journal = tmp_path / "journal.jsonl"
    frozen = {"experiment_id": "e0", "hash": "abc"}
    create_manifest(path=manifest, data=frozen)
    append_journal(
        path=journal, action="create", from_state="ABSENT", to_state="CREATED", resources={}
    )
    append_journal(
        path=journal,
        action="start",
        from_state="CREATED",
        to_state="RUNNING",
        resources={"compose": "adx-e0"},
    )
    assert last_state(path=journal) == "RUNNING"
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["seq"] == 1
    assert json.loads(lines[1])["seq"] == 2
    assert_immutable(path=manifest, expected=frozen)
    with pytest.raises(ManifestError, match="漂移"):
        assert_immutable(path=manifest, expected={"experiment_id": "other"})


def test_manifest_has_no_secret_keys(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    create_manifest(
        path=path,
        data={"experiment_id": "e0", "models": {"profile": "glm"}, "images": {"vigil": "sha256:x"}},
    )
    text = path.read_text(encoding="utf-8")
    assert "TOKEN" not in text
    assert "api_key" not in text
