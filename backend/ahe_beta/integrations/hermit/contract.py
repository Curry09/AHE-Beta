"""Read and render the Hermit Adapter contract for feedback handoffs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

import yaml

from ahe_beta.demand.artifact import ArtifactHandoff


@dataclass(frozen=True)
class HermitAdapterContract:
    """Immutable contract for one tested Hermit Adapter checkout."""

    tested_sha: str
    manifest_sha256: str
    guide_sha256: str
    learnable_paths: tuple[str, ...]
    fixed_paths: tuple[str, ...]
    check: str | None

    def guidance(self) -> str:
        """Render the Hermit contract as instructions for feedback roles."""
        learnable = ", ".join(self.learnable_paths) or "(none declared)"
        fixed = ", ".join(self.fixed_paths) or "(none declared)"
        check = self.check or "(no template-specific checker declared)"
        return (
            "The evolving product is an external Hermit Adapter deployed to an unchanged host.\n"
            "Read the Adapter contract from .hermit/adapter.yaml and the learner guide from .hermit/EVOLVER.md.\n"
            "The machine-readable learnable paths for this tested checkout are: "
            f"{learnable}.\n"
            f"The fixed paths are: {fixed}.\n"
            f"The template checker is {check}.\n"
            "Propose changes only within the declared learnable surface. The host, user simulator, "
            "task inputs, task verifier and evaluation scores remain fixed. Preserve both direct and "
            "interactive task behavior. Feedback describes user experience, so do not generalize a "
            "task-specific rule to all requests without evidence. The delivery repository contains "
            "the Adapter, not the AHE controller or a NexAU seed Harness.\n\n"
            f"Tested Adapter commit: {self.tested_sha}\n"
            f"Adapter manifest SHA-256: {self.manifest_sha256}\n"
            f"Adapter guide SHA-256: {self.guide_sha256}"
        )

    def markdown(self) -> str:
        """Render the contract as a stable issue and spec section."""
        learnable = ", ".join(f"`{path}`" for path in self.learnable_paths) or "(none declared)"
        fixed = ", ".join(f"`{path}`" for path in self.fixed_paths) or "(none declared)"
        check = f"`{self.check}`" if self.check else "(none declared)"
        return (
            "## Adapter contract\n\n"
            "This handoff targets the Adapter declared by the following immutable contract.\n\n"
            f"- Tested Adapter commit: `{self.tested_sha}`\n"
            f"- Manifest: `.hermit/adapter.yaml` (`{self.manifest_sha256}`)\n"
            f"- Learner guide: `.hermit/EVOLVER.md` (`{self.guide_sha256}`)\n"
            f"- Learnable paths: {learnable}\n"
            f"- Fixed paths: {fixed}\n"
            f"- Checker: {check}\n\n"
            "The host, user simulator, task inputs, verifier and evaluation scores are fixed. "
            "Keep direct and interactive behavior working."
        )

    def handoff(self) -> ArtifactHandoff:
        """Return the generic demand-layer handoff without exposing Hermit types there."""
        return ArtifactHandoff(
            guidance=self.guidance(),
            markdown=self.markdown(),
            marker="## Adapter contract",
        )


def read_adapter_contract(repo: str | Path, *, tested_sha: str) -> HermitAdapterContract:
    """Read and hash one Hermit Adapter checkout's manifest and learner guide."""
    root = Path(repo).resolve()
    manifest_path = root / ".hermit" / "adapter.yaml"
    guide_path = root / ".hermit" / "EVOLVER.md"
    if not manifest_path.is_file():
        raise ValueError(f"Adapter manifest is missing: {manifest_path}")
    if not guide_path.is_file():
        raise ValueError(f"Adapter guide is missing: {guide_path}")
    data = yaml.safe_load(manifest_path.read_text()) or {}
    structure = data.get("structure") or {}
    learnable = tuple(
        str(item.get("path") if isinstance(item, dict) else item)
        for item in structure.get("learnable") or []
    )
    fixed = [".hermit/**"]
    fixed.extend(str(item) for item in structure.get("fixed") or [] if str(item) != ".hermit/**")
    return HermitAdapterContract(
        tested_sha=str(tested_sha),
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        guide_sha256=hashlib.sha256(guide_path.read_bytes()).hexdigest(),
        learnable_paths=learnable,
        fixed_paths=tuple(fixed),
        check=str(data.get("check")) if data.get("check") else None,
    )
