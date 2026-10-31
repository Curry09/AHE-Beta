"""Transport aliases for the pinned judge; never select a different model."""

from __future__ import annotations

OFFICIAL_MODEL = "claude-opus-5"
MODEL_NAMES = {OFFICIAL_MODEL, "anthropic/" + OFFICIAL_MODEL}


def validate_model(model):
    if not isinstance(model, str) or model not in MODEL_NAMES:
        raise ValueError(
            "judge.model must be claude-opus-5 or anthropic/claude-opus-5; "
            "the official judge cannot be replaced"
        )
    return model


def runtime_model(wire_model):
    # LiteLLM consumes one provider prefix. A namespace required by the gateway
    # must survive it; the official final verifier uses the wire name directly.
    return "anthropic/" + validate_model(wire_model)


def canonical_model(model):
    return OFFICIAL_MODEL if isinstance(model, str) and model in MODEL_NAMES else model


def transport_options(options=None):
    options = options or {}
    model = validate_model(options.get("model", OFFICIAL_MODEL))
    normalize = options.get("normalize_usage", False)
    if type(normalize) is not bool:
        raise ValueError("judge.normalize_usage must be true or false")
    return {"model": model, "normalize_usage": normalize}
