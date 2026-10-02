"""Local input checks for persona probes; these helpers never call a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_PERSONA_LIBRARY = Path(__file__).resolve().parents[3] / "examples/personas/library.json"


def add_persona_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--persona-library",
        type=Path,
        default=DEFAULT_PERSONA_LIBRARY,
        help="Persona card library; defaults to examples/personas/library.json",
    )
    parser.add_argument(
        "--check-inputs",
        action="store_true",
        help="Check local files/personas and exit without credentials, models or providers",
    )


def load_persona_cards(path: Path) -> list[dict]:
    if not path.is_file():
        raise SystemExit(f"Persona library does not exist: {path}")
    cards = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cards, list) or any(
        not isinstance(card, dict) or not isinstance(card.get("id"), str) for card in cards
    ):
        raise SystemExit("Persona library must contain an array of cards with string ids")
    if len({card["id"] for card in cards}) != len(cards):
        raise SystemExit("Persona library contains duplicate ids")
    return cards


def selected_personas(cards: list[dict], ids: list[str]) -> list[dict]:
    lookup = {card["id"]: card for card in cards}
    missing = sorted(set(ids) - lookup.keys())
    if missing:
        raise SystemExit(f"Persona ids not found in selected library: {', '.join(missing)}")
    return [lookup[persona_id] for persona_id in ids]
