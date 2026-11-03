"""Skill placeholder interface (spec-0008/T3).

Reserved for high-depth persona: "domain playbook" extension—D2 depth-driven attachment of some **generic methodologies** fragments, woven into inner system. Placeholder this round—only minimal built-in generic set, no real playbook library.

Red line (held-out): skills must be generic, transferable work methods, **never** containing specific bugs, answers, benchmarks, or scenario-specific knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dimensions import D2Depth, Persona


@dataclass(frozen=True)
class Skill:
    """One generic methodology fragment: name identifies it; prompt is injected into inner system."""

    name: str
    prompt: str


# Generic, scenario-agnostic methodology (placeholder collection). Mounted only at senior depth; demonstration extension point.
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
    """Select skills by persona D2 depth (placeholder). senior -> generic playbook; others -> empty."""
    if persona.d2.depth == D2Depth.SENIOR:
        return list(_SENIOR_PLAYBOOK)
    return []
