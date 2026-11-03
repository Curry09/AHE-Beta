"""Local-fixture SeedSource (spec-0009/T1).

Continues the semantics of 0008/T1's original workspace.materialize: copytree the in-repo baseline
project fixture (backend/seed_workspaces/<fixture>/project) into a fresh isolated directory for each session.
As the registry's first and default implementation (kind="local-fixture"), guarantees 0008 behavior
and existing fixture compatibility.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.seed_source import register
from ahe_beta.user.sim.workspace import seed_workspaces_root


@register("local-fixture")
class LocalFixtureSource:
    kind = "local-fixture"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        if not spec.fixture:
            raise ValueError("local-fixture source requires a nonempty spec.fixture")
        src = seed_workspaces_root() / spec.fixture / "project"
        if not src.is_dir():
            raise FileNotFoundError(
                f"Seed workspace fixture does not exist: {spec.fixture} (looked in {src})"
            )
        base = dest_root or tempfile.mkdtemp(prefix="sim_ws_")
        dest = Path(base) / spec.fixture
        shutil.copytree(src, dest)
        return str(dest.resolve())
