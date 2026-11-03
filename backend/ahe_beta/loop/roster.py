"""Roster: quantities of each class of agent, serving as the single source of truth between "backend orchestration" and "frontend town rooms".

Backend run.py uses this to decide how many user sessions / triager shards / architects / divergents / owner reviews / delivery parallelism;
frontend reads the same via /api/config, room capacity matches backend. Default: 3 users · 1 triager · 1 Architect · 0 divergent · 0 owner · 1 developer;
overridable via environment variables N_USERS/N_TRIAGERS/N_ARCHITECTS/N_DIVERGENTS/N_OWNERS/N_DEVELOPERS (non-negative integers).

Spec-0032/T4: developer semantics changed from "number of in-process nexau dev instances" to "delivery parallelism K" -- direct pass-through to OpenAgents
`vigil --parallel K` (K workers each claim one subject, worktrees isolated for true parallelism; K=1 means serial). Key names and env names preserved for backward compatibility.
"""

from __future__ import annotations

import os

# role -> default count. Keys match role values in /api/agents, frontend divides rooms accordingly.
DEFAULT_ROSTER: dict[str, int] = {
    "user": 3,
    "triager": 1,  # Spec-0029: number of shards -- k-th triager processes pending[k::n], true parallelism
    "architect": 1,
    "divergent": 0,  # Disabled by default; N_DIVERGENTS=1 enables divergent PM (discovery track, output undergoes Owner admission)
    "owner": 0,  # Default zero-LLM mechanical handoff; N_OWNERS=1 enables Owner model review
    "developer": 1,  # Spec-0032: delivery surface concurrency K (vigil --parallel); conservative default serial
}

# role -> environment variable name for override.
_ENV_KEYS: dict[str, str] = {
    "user": "N_USERS",
    "triager": "N_TRIAGERS",
    "architect": "N_ARCHITECTS",
    "divergent": "N_DIVERGENTS",
    "owner": "N_OWNERS",
    "developer": "N_DEVELOPERS",
}


def _read_count(*, role: str) -> int:
    raw = os.environ.get(_ENV_KEYS[role])
    if raw is None or raw.strip() == "":
        return DEFAULT_ROSTER[role]
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_ROSTER[role]
    return value if value >= 0 else DEFAULT_ROSTER[role]


def load_roster() -> dict[str, int]:
    """Return current roster {user, triager, architect, developer}; environment variables override defaults."""

    return {role: _read_count(role=role) for role in DEFAULT_ROSTER}
