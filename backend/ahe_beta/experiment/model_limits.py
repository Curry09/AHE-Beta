"""Explicit model capacity declarations and static checks (Spec-0084/T3).

These are configuration checks, not provider token counts or dynamic compression.
Unknown model capacity is never inferred from the model's name.
"""

from __future__ import annotations

from typing import Any

DEFAULT_INPUT_TOKENS = 256000
DEFAULT_OUTPUT_TOKENS = 32768


def model_limit_report(model: dict[str, Any], *, role: str) -> dict[str, Any]:
    from ahe_beta.experiment.config import ConfigError

    limits = model.get("limits") or {}
    allowed = {
        "context_window_tokens",
        "max_context_tokens",
        "reserved_output_tokens",
        "input_headroom_tokens",
    }
    if set(limits) - allowed:
        raise ConfigError(f"Unknown model limits for {role}")
    for key, value in limits.items():
        minimum = 0 if key == "input_headroom_tokens" else 1
        if type(value) is not int or value < minimum:
            raise ConfigError(f"models.{role}.limits.{key} must be an integer >= {minimum}")
    context = limits.get("context_window_tokens")
    input_limit = limits.get("max_context_tokens", DEFAULT_INPUT_TOKENS)
    reserved = limits.get("reserved_output_tokens", DEFAULT_OUTPUT_TOKENS)
    headroom = limits.get("input_headroom_tokens", 0)
    if reserved < DEFAULT_OUTPUT_TOKENS:
        raise ConfigError(
            f"models.{role}: reserved_output_tokens must cover max_tokens={DEFAULT_OUTPUT_TOKENS}"
        )
    if context is not None and input_limit + reserved + headroom > context:
        raise ConfigError(
            f"models.{role}: input threshold {input_limit} + output reserve {reserved} + "
            f"headroom {headroom} exceeds declared context capacity {context}"
        )
    return {
        "role": role,
        "status": "verified_static" if context is not None else "unverified",
        "context_window_tokens": context,
        "max_context_tokens": input_limit,
        "reserved_output_tokens": reserved,
        "input_headroom_tokens": headroom,
        "max_tokens": DEFAULT_OUTPUT_TOKENS,
        "dynamic_token_count_verified": False,
    }


def validate_model_limits(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        model_limit_report(config["models"][role], role=role)
        for role in ("user", "harness", "demand")
    ]
