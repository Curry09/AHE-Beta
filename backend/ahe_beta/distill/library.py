"""PersonaLibrary (spec-0006/T1): minimal read/write and contract constraint validation for the
    persona card library.

A single library file (JSON) holds multiple "6-dimensional behavioral card" records; the only
public contract for card schema is in tools/persona-distill/card-schema.md. The library itself is
pure data access:

- Read side is **forward compatible with unknown keys** (ignores without error, preserves as-is),
  enabling schema evolution (Postel's law).
- `validate_card` is an **independent strict validation gate** (called explicitly at collection/
  ingestion time, for tests), decoupled from the permissive access layer: asserts that cards
  contain only contract-allowed top-level keys (thus no benchmark/trace-derived fields), and
  D5.area ∈ controlled vocabulary.

The card → sim dimension injection mapping (grounded coverage derivation) is not here; see
0006/T2 card_to_persona.
"""

from __future__ import annotations

import json
from pathlib import Path

# Code copy of the single source of truth for "D5.area controlled vocabulary" from card-schema.md (single token).
D5_AREA_VOCAB: frozenset[str] = frozenset(
    {
        "web-backend",
        "web-frontend",
        "scientific-computing",
        "data-viz",
        "ml-ai",
        "data-analysis",
        "dev-tooling",
        "data-eng",
        "infra-devops",
        "databases",
        "systems-runtime",
        "security",
        "mobile",
        "cross-stack",
    }
)

# Top-level keys allowed in card records per card-schema.md. Whitelist implements "no benchmark/trace-derived fields":
# Any field outside the contract (e.g., benchmark scores, trace features) falls outside the whitelist and is rejected by validate_card.
ALLOWED_CARD_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "authenticity",
        "era",
        "dimensions",
        "provenance",
        "behavioral_prediction",
        # Record of rejected cards (not ingested):
        "reject_reason",
        "action",
    }
)


def validate_card(record: dict) -> None:
    """Validate a card record per card-schema.md; raise ValueError if non-conformant.

    Only enforce contract-level hard constraints (whitelist + D5.area controlled vocabulary),
    not replace the real-world gate for extracting skill validity.
    """
    extra = set(record) - ALLOWED_CARD_KEYS
    if extra:
        raise ValueError(
            f"Card record contains fields outside the contract {sorted(extra)} (possibly benchmark/trace-derived fields); "
            f"See card-schema.md for allowed top-level keys: {sorted(ALLOWED_CARD_KEYS)}"
        )
    dims = record.get("dimensions")
    if isinstance(dims, dict):
        d5 = dims.get("D5_domain")
        if isinstance(d5, dict) and "area" in d5:
            area = d5["area"]
            if area not in D5_AREA_VOCAB:
                raise ValueError(
                    f"D5.area={area!r} is outside the controlled vocabulary (must be a single token); see card-schema.md: {sorted(D5_AREA_VOCAB)}"
                )


class PersonaLibrary:
    """Minimal library for a single JSON file hosting multiple card records. Single-process MVP;
    does not handle concurrent write races."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> list[dict]:
        """Read entire library; absent file is treated as an empty library (legitimate initial state)."""
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(
                f"Persona library file {self._path} must contain an array of card records"
            )
        return data

    def get(self, persona_id: str) -> dict:
        """Get one card by id; raise KeyError if not found."""
        for record in self.load():
            if record.get("id") == persona_id:
                return record
        raise KeyError(persona_id)

    def add(self, record: dict) -> None:
        """Append one card record and persist (permissive access; for strict validation, call
        validate_card explicitly)."""
        records = self.load()
        records.append(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
