"""SeedLibrary (spec-0010/T1): minimal read/write and contract constraint validation for the
    seed card library.

A single library file (JSON) holds multiple source-agnostic seed card records; the only public
contract for card schema is in tools/seed-distill/seed-card-schema.md. The library itself is pure
data access (matching PersonaLibrary from 0006):

- Read side is **forward compatible with unknown keys** (ignores without error, preserves as-is),
  enabling schema evolution (Postel's law).
- `validate_card` is an **independent strict validation gate** (called explicitly at collection/
  ingestion time, for tests), decoupled from the permissive access layer: asserts that cards
  contain only contract-allowed top-level keys (thus no benchmark/trace-derived fields),
  `source.not_in_benchmark` is always true (prevents benchmark pollution), domain ∈ controlled
  vocabulary, and capability_probed ⊆ capability taxonomy.

The held-out field (oracle/test_cmd/gates) is retained with card collection; the injection
mapping to SeedScenario (including held-out field stripping) is not here, see 0010/T2
seed_adapter.card_to_seed.
"""

from __future__ import annotations

import json
from pathlib import Path

# Code copy of the single source of truth for "domain controlled vocabulary" from seed-card-schema.md; shared with persona D5.area on the same 14 token.
DOMAIN_VOCAB: frozenset[str] = frozenset(
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

# Code copy of the single source of truth for "capability taxonomy" from seed-card-schema.md.
CAPABILITY_TAXONOMY: frozenset[str] = frozenset(
    {
        "intent-inference",
        "correctness-edgecase",
        "long-output",
        "tool-use-verification",
        "scope-discipline",
        "env-setup",
        "error-recovery",
        "explanation-teaching",
    }
)

# Top-level keys allowed in card records per seed-card-schema.md. Whitelist implements "no benchmark/trace-derived fields":
# Any field outside the contract (e.g., benchmark scores, trace features) falls outside the whitelist and is rejected by validate_card.
ALLOWED_CARD_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "source",
        "task",
        "domain",
        "capability_probed",
        "difficulty",
        "scope",
        "autonomy_required",
        "oracle",
        "env",
        "pairing_constraints",
        "gates",
        "provenance",
        # Record of rejected cards (not ingested):
        "reject_reason",
        "action",
    }
)


def validate_card(record: dict) -> None:
    """Validate a seed card record per seed-card-schema.md; raise ValueError if non-conformant.

    Spec-0010/T1: Only enforce contract-level hard constraints (whitelist + not_in_benchmark gate
    + domain/capability controlled vocabularies), not replace the two gates for extracting skill
    validity (oracle gate + harbor reproducibility gate). Rejected cards (with reject_reason,
    not entering the seed library) are outside this gate—only validates real cards destined for
    ingestion.
    """
    # 1. Whitelist: any top-level key outside the contract (suspected benchmark/trace-derived field) is rejected.
    extra = set(record) - ALLOWED_CARD_KEYS
    if extra:
        raise ValueError(
            f"Card record contains fields outside the contract {sorted(extra)} (possibly benchmark/trace-derived fields); "
            f"See seed-card-schema.md for allowed top-level keys: {sorted(ALLOWED_CARD_KEYS)}"
        )
    # 2. Non-benchmark gate (contract iron rule #3): source.not_in_benchmark is always true.
    source = record.get("source")
    if isinstance(source, dict):
        if source.get("not_in_benchmark") is not True:
            raise ValueError(
                "Card source.not_in_benchmark must be true (prevent benchmark contamination of training targets); "
                "See seed-card-schema.md rule #3"
            )
    # 3. domain ∈ controlled vocabulary (single token).
    domain = record.get("domain")
    if domain is not None and domain not in DOMAIN_VOCAB:
        raise ValueError(
            f"domain={domain!r} is outside the controlled vocabulary (must be a single token); see seed-card-schema.md: {sorted(DOMAIN_VOCAB)}"
        )
    # 4. capability_probed ⊆ capability taxonomy.
    caps = record.get("capability_probed")
    if caps is not None:
        unknown = set(caps) - CAPABILITY_TAXONOMY
        if unknown:
            raise ValueError(
                f"capability_probed contains capabilities outside the taxonomy {sorted(unknown)}; "
                f"See seed-card-schema.md: {sorted(CAPABILITY_TAXONOMY)}"
            )


class SeedLibrary:
    """Minimal library for a single JSON file hosting multiple seed card records. Single-process MVP;
    does not handle concurrent write races."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> list[dict]:
        """Read entire library; absent file is treated as an empty library (legitimate initial state).

        Top level may be a bare card array, or a harvest output envelope
        `{version, harvested_at, note, seeds:[...]}` (forward compatible: extract seeds array,
        ignore other metadata keys).
        """
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("seeds"), list):
            return data["seeds"]
        if not isinstance(data, list):
            raise ValueError(
                f"Seed library file {self._path} must contain a card-record array or a {{seeds:[...]}} envelope"
            )
        return data

    def get(self, seed_id: str) -> dict:
        """Fetch a card by id; raises KeyError if not found."""
        for record in self.load():
            if record.get("id") == seed_id:
                return record
        raise KeyError(seed_id)

    def add(self, record: dict) -> None:
        """Append a card record and persist to disk (lenient on access; call validate_card explicitly for strict validation)."""
        records = self.load()
        records.append(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
