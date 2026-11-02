"""Persist evidence authority separately from model-authored issue text."""

import json
import os
import uuid
from pathlib import Path

from ahe_beta.observations.publication import safe_relative


def observation_root(store) -> Path:
    return Path(
        os.environ.get("AHE_BETA_OBSERVATION_ROOT", str(store.root.parent / "observations"))
    )


def grant(*, store, issue: int, sessions: set[str], pm_origin: bool = False) -> None:
    if any(safe_relative(sid) != sid or "/" in sid for sid in sessions):
        raise ValueError("invalid granted session identity")
    root = observation_root(store) / ".grants"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / f"{int(issue)}.json"
    temp = root / f".{uuid.uuid4().hex}.tmp"
    temp.write_text(
        json.dumps({"issue": issue, "sessions": sorted(sessions), "pm_origin": pm_origin})
    )
    temp.replace(path)


def authorized_sessions(*, store, issue: int) -> set[str]:
    try:
        value = json.loads((observation_root(store) / ".grants" / f"{int(issue)}.json").read_text())
        return set(value["sessions"]) if value["issue"] == issue else set()
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def sessions_for_issues(*, store, issues: list) -> set[str]:
    """Model-authored source text can reference evidence but cannot confer new access."""
    return set().union(*(authorized_sessions(store=store, issue=i.number) for i in issues))


def is_pm_source(*, store, issue: int) -> bool:
    try:
        value = json.loads((observation_root(store) / ".grants" / f"{int(issue)}.json").read_text())
        return value["issue"] == issue and value.get("pm_origin") is True
    except (OSError, ValueError, KeyError, TypeError):
        return False
