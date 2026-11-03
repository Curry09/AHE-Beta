"""
feeling.py
experience score (FeelingScore 1–4 + reason) — aligned with the AHE-Beta spec-0001 training signal contract.

Two parallel outputs (each produced at session end, mutually validating):
- ① LLM self-assessment (parse_feeling_llm): persona in-role gives "this experience" a score of 1–4 + reason,
     aligned with spec-0001/T3 "FeelingScore produced by LLM after session end" (similar to CC scoring).
- ② Framework-derived (derive_feeling): deterministic aggregation from subjective end state (end_reason /
     verdict / trust), reproducible, for independent diagnosis only, does not fill in missing self-assessment.

Iron rules:
- User experience is a *subjective* signal, derived only from persona's end state (end_reason / verdict / patience /
  trust), never read objective ground truth (gold). This aligns with the project's "training signal = user experience,
  benchmark held-out".
- Produced once at session end (not scored per turn), aligned with FeelingScore's "one score per session" form.

Scoring rules (similar to CC 1–4; higher value = better user experience):
  4  Smooth & satisfied: accepted deliverable, process had minimal back-and-forth (failed_blame_harness <= 1
     and trust did not shift to doubt)
  3  Friction but accepted: ultimately accepted, but multiple harness complaints mid-session or trust already
     shifted to skeptical
  2  Not truly resolved: ran full rounds without convergence / filed issue to close out (constructive but
     frustrating)
  1  Gave up: proactive give_up, abandoned mid-conversation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# end_reason -> baseline score. Other reasons (terminated, etc.) map to default 2.
_BASE_BY_END = {
    "accepted": 4,
    "max_turns": 2,
    "issue_filed": 2,
    "abandoned": 1,
}

_VERDICT_TEXT = {
    4: "The user accepted the delivery smoothly.",
    3: "The user eventually accepted, but the process involved repeated attempts or declining trust.",
    2: "The session ended without a real resolution (turn limit reached or issue filed).",
    1: "The user gave up during the session.",
}


@dataclass
class FeelingScore:
    """1–4 experience score + reason (produced at session end, used as training signal). Out-of-bounds is a
    construction-time failure."""

    score: int
    reason: str

    def __post_init__(self) -> None:
        assert type(self.score) is int and 1 <= self.score <= 4, (
            f"Experience score must be an integer from 1..4: {self.score!r}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeelingScore:
        return cls(score=data["score"], reason=data["reason"])


def parse_feeling_llm(ret: dict) -> FeelingScore | None:
    """Parse 1–4 experience score from the persona LLM's session-end self-assessment dict (output method per
    spec-0001/T3).

    Expects ret in the form {"score": <1..4>, "reason": "<...>"}. On invalid input (missing field / non-integer /
    out-of-bounds), returns None; missing measurement cannot backfill derived score. Out-of-bounds triggers
    FeelingScore.__post_init__ assertion failure -> caught as None, both preserving "out-of-bounds is illegal"
    and preventing loop crash.
    """
    if not isinstance(ret, dict) or "score" not in ret:
        return None
    score = ret["score"]
    if type(score) is not int:
        return None
    reason = str(ret.get("reason", "")).strip()
    try:
        return FeelingScore(score=score, reason=reason)
    except AssertionError:
        return None


def experience_feedback(ret: dict | None, *, source: str, error: str | None = None) -> dict:
    """Spec-0084/T2: one strict scale for both interaction modes, including missingness."""
    if error is not None:
        return {"status": "unavailable", "score": None, "source": source, "reason": error}
    value = ret if isinstance(ret, dict) else {}
    feeling = parse_feeling_llm(value)
    return {
        "status": "rated" if feeling else ("missing" if value.get("score") is None else "invalid"),
        "score": feeling.score if feeling else None,
        "source": source,
        "reason": feeling.reason
        if feeling
        else str(value.get("reason") or "No valid integer rating supplied"),
    }


def derive_feeling(end_reason: str, turns: list) -> FeelingScore:
    """Derive experience score from a session's end state. Consumes only subjective signals (end_reason / verdict /
    trust).

    turns: list[TurnLog]; reads only verdict / trust subjective fields, does not depend on objective lines.
    """
    fails = sum(1 for t in turns if t.verdict == "failed_blame_harness")
    stucks = sum(1 for t in turns if t.verdict == "stuck")
    final_trust = turns[-1].trust if turns else "balanced"

    score = _BASE_BY_END.get(end_reason, 2)
    # Even if ultimately accepted, multiple harness complaints / multiple stalls / trust collapsed to skeptical -> lower one notch to "acceptance with friction"
    if score == 4 and (fails >= 2 or stucks >= 2 or final_trust == "skeptical"):
        score = 3

    reason = (
        f"end={end_reason}; harness-blamed failures={fails}; stuck turns={stucks}; "
        f"final trust={final_trust}. " + _VERDICT_TEXT[score]
    )
    return FeelingScore(score=score, reason=reason)
