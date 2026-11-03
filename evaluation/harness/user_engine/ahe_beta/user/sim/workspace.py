"""Seed workspace materialization (spec-0008/T1 → spec-0009/T1).

0008/T1 uses local copytree to duplicate fixture into isolated directory here; 0009/T1 abstracts the mechanism to a pluggable `SeedSource` registry (see seed_source.py + sources/local_fixture.py). This module devolves to:
  - `seed_workspaces_root()`: shared helper for fixture asset root (reused by local-fixture source);
  - `materialize()`: compatibility wrapper delegating to registry `provision`, zero changes to 0008 call sites (loop/sim_user).
"""

from __future__ import annotations

from pathlib import Path

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.runtime import Workspace


def seed_workspaces_root() -> Path:
    """Absolute path of backend/seed_workspaces/ (this file resides in backend/ahe_beta/user/sim/)."""
    return Path(__file__).resolve().parents[3] / "seed_workspaces"


def materialize(spec: WorkspaceSpec, dest_root: str | None = None) -> Workspace:
    """Compatibility wrapper: delegate to pluggable SeedSource registry by spec.kind, return absolute path of isolated workspace directory.

    Deferred import breaks potential cycle: seed_source auto-discovery imports local_fixture, which depends on this module's seed_workspaces_root; this module thus does not import seed_source at top level.
    """
    from ahe_beta.user.sim.seed_source import provision

    return provision(spec, dest_root)
