"""Empty SeedSource (spec-0009/T2).

Coverage: additive hard evidence (no import of empty module, only import seed_source registers it), empty directory isolation landing, optional requirements document writing and doc_name override, serialization round-trip for kind=empty."""

from __future__ import annotations

from pathlib import Path

from ahe_beta.models import WorkspaceSpec


def test_empty_auto_registered_without_importing_module() -> None:
    # Additive hard evidence: this test does not import sources.empty, only imports seed_source; empty is in the registry.
    from ahe_beta.user.sim import seed_source

    assert "empty" in seed_source.available_kinds()


def test_empty_provisions_empty_isolated_dir() -> None:
    from ahe_beta.user.sim import seed_source

    a = seed_source.provision(WorkspaceSpec(kind="empty"))
    b = seed_source.provision(WorkspaceSpec(kind="empty"))
    assert a.cwd != b.cwd
    assert a.evidence["patch_capability"] == "not_applicable"
    a.freeze_patch_base()
    assert a.export_patch() == ("", "")
    assert Path(a.cwd).is_dir()
    assert not any(Path(a.cwd).iterdir())  # Pure empty directory when no doc


def test_empty_writes_doc_and_doc_name_override() -> None:
    from ahe_beta.user.sim import seed_source

    ws = seed_source.provision(WorkspaceSpec(kind="empty", params={"doc": "build X"}))
    assert (Path(ws.cwd) / "SPEC.md").read_text() == "build X"

    ws2 = seed_source.provision(
        WorkspaceSpec(kind="empty", params={"doc": "y", "doc_name": "REQUIREMENTS.md"})
    )
    assert (Path(ws2.cwd) / "REQUIREMENTS.md").read_text() == "y"


def test_empty_spec_roundtrip() -> None:
    e = WorkspaceSpec(kind="empty", params={"doc": "d"})
    assert WorkspaceSpec.from_dict(e.to_dict()) == e
