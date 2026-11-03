"""seed_adapter.py (spec-0010/T2): injects seed cards into the 0009 SeedSource supply.

card_to_seed is the **sole bridge layer** between "card collection (seed card, 0010/T1)" and "0009 SeedSource engine": maps one card to spec-0001 models.SeedScenario by field — `task.prompt` → description, `source.repo` + `env.repo_at` → git workspace (0009/T4 kind="git" + params{repo, commit}), `env.setup` → venv-prefixed setup (0009/T3). Pure-text cards without repo degrade to workspace=None. Mirrors spec-0006/T2 card_to_persona symmetrically.

**Held-out boundary**: objective evaluation artifacts oracle / env.test_cmd / gates are benchmark-side evidence, extracted via extract_sidecar to a sidecar, **never enter** SeedScenario (or its to_dict / {version, seeds} envelope JSON) or training. Per CLAUDE.md "benchmark held-out throughout: no training participation, no release gating" — training signal draws only from subjective ratings, oracle belongs to harbor-side parallel evaluation, both physically isolated at the injection boundary. Card shape contract in tools/seed-distill/seed-card-schema.md.

Missing fields / invalid values (git type missing repo_at, repo_at still an unresolved placeholder, domain out of range) raise explicit errors (no silent defaults), exposing collection quality issues at the injection boundary; mirrors spec-0006/T2 error-on-invalid strategy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ahe_beta.distill.seed_library import validate_card
from ahe_beta.models import SeedScenario, WorkspaceSpec

if TYPE_CHECKING:
    from ahe_beta.distill.seed_library import SeedLibrary

# {version, seeds} envelope version: persistent artifact shape of card_to_seeds (envelope JSON schema version number).
SEED_ENVELOPE_VERSION = 1

# Held-out objective evaluation artifacts: stripped to sidecar at injection, never enter SeedScenario.
_SIDECAR_KEYS = ("oracle", "gates", "provenance")

# Bare interpreter command → command within per-workspace venv (aligned with spec-0009/T3 convention).
_VENV_BIN = {
    "pip": ".venv/bin/pip",
    "pip3": ".venv/bin/pip3",
    "python": ".venv/bin/python",
    "python3": ".venv/bin/python3",
}


def extract_sidecar(record: dict) -> dict:
    """Extract a card's held-out evaluation artifacts (oracle / test_cmd / gates + provenance).

    Spec-0010/T2: consumed by harbor-side parallel evaluation; **never** enters SeedScenario / training. Records only keys
    actually present in the card (forward compatible). test_cmd is nested in env, surfaced to top level here for sidecar consumption.
    """
    sidecar: dict = {key: record[key] for key in _SIDECAR_KEYS if key in record}
    env = record.get("env")
    if isinstance(env, dict) and "test_cmd" in env:
        sidecar["test_cmd"] = env["test_cmd"]
    return sidecar


def card_to_seed(record: dict) -> SeedScenario:
    """Map one seed card to models.SeedScenario; held-out fields (oracle/test_cmd/gates) are extracted.

    Spec-0010/T2: task.prompt → description (original text passed through verbatim, no oracle/test_cmd); cards with source.repo
    → WorkspaceSpec(kind="git", params={repo (URL), commit (resolved SHA)}, setup=venv-prefixed); pure-text cards without repo
    → workspace=None. Missing repo_at / unresolved placeholder / domain out of range raises explicit error.
    """
    # 1. Contract-level validation moved forward to injection boundary (domain/capability controlled, non-benchmark, whitelist).
    validate_card(record)

    # 2. task.prompt → description (held-out boundary: carry only the genuine request original text).
    task = record.get("task")
    if not isinstance(task, dict) or not task.get("prompt"):
        raise ValueError(
            "Card is missing task.prompt (the original text injected into SeedScenario.description)"
        )
    description = str(task["prompt"])

    # 3. If a real repo exists → git working directory; otherwise plain text (workspace=None).
    source = record.get("source") or {}
    repo = source.get("repo")
    if not repo or repo == "n/a":
        return SeedScenario(description=description, workspace=None)

    env = record.get("env") or {}
    repo_at = env.get("repo_at")
    if not repo_at:
        raise ValueError(
            "Git card is missing env.repo_at (the resolved parent commit SHA to restore)"
        )
    commit = _resolved_sha(repo_at=str(repo_at))
    workspace = WorkspaceSpec(
        kind="git",
        params={"repo": _repo_url(repo=str(repo)), "commit": commit},
        setup=_prefix_venv(setup=list(env.get("setup") or [])),
    )
    return SeedScenario(description=description, workspace=workspace)


def card_to_seeds(library: SeedLibrary) -> dict:
    """Inject each card in the library as a {version, seeds:[SeedScenario.to_dict()...]} envelope.

    Spec-0010/T2: Persistable {version, seeds} envelope (for side-path serialization / offline inspection).
    The held-out field has been stripped in card_to_seed, so the envelope JSON does not contain
    oracle/test_cmd/gates. run.py uses card_to_seed to inject SeedScenario directly, bypassing
    this envelope.
    """
    return {
        "version": SEED_ENVELOPE_VERSION,
        "seeds": [card_to_seed(record).to_dict() for record in library.load()],
    }


def _repo_url(repo: str) -> str:
    """owner/repo → https clone URL; if already a URL or git@ form, pass through as-is."""
    if "://" in repo or repo.startswith("git@"):
        return repo
    return f"https://github.com/{repo}.git"


def _resolved_sha(repo_at: str) -> str:
    """Validate that repo_at has been resolved to a real SHA; reject placeholders (e.g., `<parent-...>`)
    explicitly.

    Spec-0010/T2: Git sources in 0009/T4 checkout by commit; placeholders would fail during
    materialization—move validation earlier to the injection boundary.
    """
    val = repo_at.strip()
    if not val:
        raise ValueError("env.repo_at is empty (must be a resolved commit SHA)")
    if "<" in val or ">" in val or any(ch.isspace() for ch in val):
        raise ValueError(
            f"env.repo_at={repo_at!r} is still an unresolved placeholder (must be a resolved commit SHA; "
            "resolve the parent commit with git during harvest)"
        )
    return val


def _prefix_venv(setup: list[str]) -> list[str]:
    """Prefix env.setup with venv (align with 0009/T3): prepend `python -m venv .venv`, rewrite
    bare pip/python to .venv/bin/….

    Spec-0010/T2: Enable 0009/T3 ensure_deps to build per-workspace venv; Sandbox detects `.venv`
    successfully. Empty setup (no dependencies) does not create venv (returns [], no change from
    existing zero-dependency scenarios).
    """
    if not setup:
        return []
    steps = ["python -m venv .venv"]
    steps.extend(_venv_bin(command=cmd) for cmd in setup)
    return steps


def _venv_bin(command: str) -> str:
    """Rewrite the bare interpreter prefix (pip/python) of a setup command to .venv/bin/…; leave
    the rest unchanged."""
    parts = command.split()
    if parts and parts[0] in _VENV_BIN:
        parts[0] = _VENV_BIN[parts[0]]
        return " ".join(parts)
    return command
