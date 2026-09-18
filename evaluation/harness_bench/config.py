"""Load JSON/YAML plans into the typed schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import EvaluationPlan, PlanError


def load_plan(path: str | Path) -> EvaluationPlan:
    source = Path(path)
    if not source.is_file():
        raise PlanError(f"plan does not exist: {source}")
    if source.suffix.lower() == ".json":
        payload: Any = json.loads(source.read_text(encoding="utf-8"))
    else:
        try:
            from ruamel.yaml import YAML
        except ImportError as exc:  # pragma: no cover - repository dependency
            raise PlanError("YAML plans require ruamel.yaml") from exc
        payload = YAML(typ="safe").load(source.read_text(encoding="utf-8"))
    return EvaluationPlan.from_mapping(payload)
