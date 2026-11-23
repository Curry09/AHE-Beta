from pathlib import Path

from ahe_beta.demand.artifact import append_artifact_section, bind_artifact_handoff
from ahe_beta.integrations.hermit.contract import read_adapter_contract


def _adapter(root: Path) -> Path:
    meta = root / ".hermit"
    meta.mkdir(parents=True)
    (meta / "adapter.yaml").write_text(
        """template:\n  id: test-adapter\n  version: '1'\nstructure:\n  learnable:\n  - path: ADAPTER.md\n  - path: scripts/*.py\n  fixed:\n  - README.md\ncheck: .hermit/check.py:check\n"""
    )
    (meta / "EVOLVER.md").write_text("# Guide\n")
    return root


def test_contract_reads_manifest_and_renders_handoff(tmp_path):
    contract = read_adapter_contract(_adapter(tmp_path), tested_sha="abc123")

    assert contract.learnable_paths == ("ADAPTER.md", "scripts/*.py")
    assert contract.fixed_paths == (".hermit/**", "README.md")
    assert ".hermit/EVOLVER.md" in contract.guidance()
    assert "Tested Adapter commit: `abc123`" in contract.markdown()


def test_contract_section_is_scoped_and_idempotent(tmp_path):
    contract = read_adapter_contract(_adapter(tmp_path), tested_sha="abc123")

    with bind_artifact_handoff(contract.handoff()):
        body = append_artifact_section("### Boundary\n\nAdapter only")
        again = append_artifact_section(body)

    assert body == again
    assert body.startswith("## Adapter contract")
    assert body.count("## Adapter contract") == 1
