"""Pluggable seed workspace provisioning interface (spec-0009/T1).

Abstract the single "local copytree" path hardcoded in workspace.materialize by 0008/T1 into a
`SeedSource` registered and dispatched by `WorkspaceSpec.kind`: the provisioning side can evolve independently, while the consumer interface
(SeedScenario.description + the workspace directory used as cwd by Sandbox) remains frozen.

Registration: each source implementation registers itself in the module-level `_REGISTRY` via `@register("<kind>")`; this module
traverses the `sources/` subpackage at import time and imports each module to trigger registration. Thus "add a source = add a module
in sources/" requires no changes to this file (the spec-0009/T2 empty source uses this mechanism).

Out of scope (left to downstream specs): dependency provisioning/environment builds, containerized "runnable handle" runtimes, git@commit retrieval,
and objective Oracle scoring. This group's interface remains "directory + local shell".
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Protocol

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.runtime import Workspace


class SeedSource(Protocol):
    """Implementation protocol for provisioning an isolated workspace directory.

    `kind` is the registration key; `provision` materializes a fresh isolated directory per spec and returns its absolute path (for Sandbox to use as cwd). Each call must not pollute others.
    """

    kind: str

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> Workspace: ...


_REGISTRY: dict[str, SeedSource] = {}


def register(kind: str):
    """Class decorator: instantiate this source and register it to `_REGISTRY` under `kind`."""

    def deco(source_cls):
        _REGISTRY[kind] = source_cls()
        return source_cls

    return deco


def available_kinds() -> list[str]:
    """All registered kinds (sorted, for error messages and self-inspection)."""
    return sorted(_REGISTRY)


def get_source(kind: str) -> SeedSource:
    """Get source by kind; raise ValueError if unregistered and list all registered kinds."""
    try:
        return _REGISTRY[kind]
    except KeyError:
        raise ValueError(
            f"Unknown seed source kind={kind!r}; registered kinds: {available_kinds()}"
        ) from None


def provision(spec: WorkspaceSpec, dest_root: str | None = None) -> Workspace:
    """Top-level dispatch: local source returns directory, container source returns runtime with explicit lifecycle."""
    return get_source(spec.kind).provision(spec, dest_root)


def _discover() -> None:
    """At import time, traverse sources/ subpackage and import each one, triggering each source's @register self-registration."""
    from ahe_beta.user.sim import sources as _sources_pkg

    for mod in pkgutil.iter_modules(_sources_pkg.__path__):
        importlib.import_module(f"{_sources_pkg.__name__}.{mod.name}")


_discover()
