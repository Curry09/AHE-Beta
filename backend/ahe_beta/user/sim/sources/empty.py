"""Empty SeedSource (spec-0009/T2).

Create a new isolated workspace directory; if `params.doc` is non-empty, write its text as a spec file
named `params.doc_name` (default "SPEC.md"), supporting the NL2Repo injection pattern of "single requirements
document, start from empty repo".

Pluggable proof: integrating it only adds this module—auto-discovered via spec-0009/T1's sources/ registry,
with seed_source / models / workspace and consuming code (sim_user / Sandbox) all unchanged. No introduction
of containers / git / dependency provisioning.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.runtime import LocalWorkspaceRuntime
from ahe_beta.user.sim.seed_source import register


@register("empty")
class EmptySource:
    kind = "empty"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> LocalWorkspaceRuntime:
        if dest_root is None:
            dest = Path(tempfile.mkdtemp(prefix="sim_ws_empty_"))
        else:
            dest = Path(dest_root) / "empty"
            dest.mkdir(parents=True, exist_ok=True)
        runtime = LocalWorkspaceRuntime(
            str(dest.resolve()),
            owns_tmp=dest_root is None,
            evidence={"patch_capability": "not_applicable"},
        )
        doc = spec.params.get("doc")
        if doc:
            name = spec.params.get("doc_name", "SPEC.md")
            runtime.write_text(name, doc)
        return runtime
