"""蒸馏侧（spec-0006）：persona 卡库读写 + 契约约束校验。

卡 schema 的唯一公共契约见 tools/persona-distill/card-schema.md；
卡 → sim 9 维 Persona 的注入映射见 ahe_beta.user.sim.persona_io（0006/T2）。
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
