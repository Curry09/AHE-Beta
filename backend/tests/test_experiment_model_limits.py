"""Spec-0084/T3: declared capacities have honest static, never dynamic, guarantees."""

import pytest

from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.model_limits import model_limit_report


def test_unknown_model_capacity_is_not_guessed():
    report = model_limit_report({"model": "large-512k-model"}, role="harness")
    assert report["status"] == "unverified"
    assert report["context_window_tokens"] is None
    assert report["max_context_tokens"] == 256000
    assert report["max_tokens"] == 32768
    assert report["dynamic_token_count_verified"] is False


def test_256k_input_plus_32k_output_does_not_fit_256k_capacity():
    with pytest.raises(ConfigError, match="exceeds declared context"):
        model_limit_report({"limits": {"context_window_tokens": 262144}}, role="harness")


def test_explicit_lower_input_threshold_can_fit_same_model():
    report = model_limit_report(
        {
            "limits": {
                "context_window_tokens": 262144,
                "max_context_tokens": 228352,
                "reserved_output_tokens": 32768,
                "input_headroom_tokens": 1024,
            }
        },
        role="harness",
    )
    assert report["status"] == "verified_static"
    assert report["max_context_tokens"] == 228352


@pytest.mark.parametrize(
    "limits",
    [
        {"reserved_output_tokens": 32000},
        {"max_context_tokens": True},
        {"input_headroom_tokens": -1},
        {"context_window_tokens": 0},
        {"max_context_tokens": 1.0},
        {"unknown": 100},
    ],
)
def test_invalid_or_underreserved_limits_fail(limits):
    with pytest.raises(ConfigError):
        model_limit_report({"limits": limits}, role="user")
