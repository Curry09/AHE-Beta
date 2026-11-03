"""skill placeholder interface (spec-0008/T3).

Reserved for high-depth personas: "domain playbook" extension slot where D2 depth-driven general methodology snippets
are attached to the inner system. This iteration is placeholder only — provides minimal built-in general collection,
does not ingest real playbook library.

Red line (held-out): skills must be general, transferable work methods, absolutely must not contain specific bugs,
answers, benchmarks, or scenario-specific knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dimensions import D2Depth, Persona


@dataclass(frozen=True)
class Skill:
    """A general methodology snippet: name identifies it, prompt is injected into inner system."""

    name: str
    prompt: str


# General, scenario-agnostic methodology (placeholder collection). Mounted only at senior depth, demonstrates extension slot.
_SENIOR_PLAYBOOK: list[Skill] = [
    Skill(
        "reproduce-first",
        "Before judging whether something works, reproduce it with the smallest possible run "
        "rather than reasoning about it in your head.",
    ),
    Skill(
        "probe-boundaries",
        "When you do decide to check, spend your effort on the boundary/edge inputs that are "
        "most likely to break things, not the happy path you already expect to pass.",
    ),
]


def select_skills(persona: Persona) -> list[Skill]:
    """Select skills by persona's D2 depth (placeholder). senior → general playbook; others → empty."""
    if persona.d2.depth == D2Depth.SENIOR:
        return list(_SENIOR_PLAYBOOK)
    return []
