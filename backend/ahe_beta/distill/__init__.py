"""Distillation side (spec-0006): persona card library read/write + contract constraint validation.

The only public contract for card schema is in tools/persona-distill/card-schema.md;
the card → sim 9-dimensional Persona injection mapping is in ahe_beta.user.sim.persona_io
(0006/T2).
"""

from ahe_beta.distill.library import (
    ALLOWED_CARD_KEYS,
    D5_AREA_VOCAB,
    PersonaLibrary,
    validate_card,
)

__all__ = [
    "ALLOWED_CARD_KEYS",
    "D5_AREA_VOCAB",
    "PersonaLibrary",
    "validate_card",
]
