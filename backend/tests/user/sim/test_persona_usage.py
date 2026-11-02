from __future__ import annotations

from types import SimpleNamespace

import pytest

from ahe_beta.user.sim import persona_client as module


class _Completions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _client(*outcomes: object) -> module.ApiPersonaClient:
    client = module.ApiPersonaClient.__new__(module.ApiPersonaClient)
    client.model = "test-model"
    client.temperature = 0.0
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(list(outcomes))))
    return client


def _response(*, usage: object = None, request_id: str = "req-1") -> object:
    return SimpleNamespace(
        usage=usage,
        id=request_id,
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
    )


def test_create_records_reported_usage_for_each_successful_provider_call(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(module, "record_usage", lambda **event: events.append(event))

    response = _response(usage={"prompt_tokens": 7, "completion_tokens": 3})
    assert _client(response)._create([{"role": "user", "content": "hi"}], 100) is response

    assert len(events) == 1
    assert events[0]["usage"] == {"prompt_tokens": 7, "completion_tokens": 3}
    assert events[0]["request_id"] == "req-1"
    assert events[0]["model"] == "test-model"


def test_create_records_rejected_flag_and_fallback_as_separate_calls(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(module, "record_usage", lambda **event: events.append(event))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    rejected = RuntimeError("flag rejected")
    response = _response(usage=None)
    assert _client(rejected, response)._create([], 100) is response

    assert len(events) == 2
    assert events[0]["success"] is False
    assert events[0]["error"] is rejected
    assert events[1]["usage"] is None


@pytest.mark.parametrize(
    "model",
    [
        "glm-5.3",
        "z-ai/glm-5.3",
        "glm53_512k_o64k_pd128_mlc",
        "glm53-flash-lmdeploy-dp8ep8-512k-96gpu-mtp3-pool-1014",
        "glm-5.2",
    ],
)
def test_glm_deployment_aliases_keep_server_thinking_defaults(monkeypatch, model):
    monkeypatch.delenv("USER_LLM_REASONING_EFFORT", raising=False)
    response = _response()
    client = _client(response)
    client.model = model
    assert client._create([], 32768) is response
    request = client.client.chat.completions.calls[0]
    assert request["model"] == model
    assert request["max_tokens"] == 32768
    assert "extra_body" not in request and "reasoning_effort" not in request


def test_create_records_every_failed_retry_before_raising(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(module, "record_usage", lambda **event: events.append(event))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    failures = [RuntimeError(f"failure-{index}") for index in range(10)]

    with pytest.raises(RuntimeError, match="failure-9"):
        _client(*failures)._create([], 100)

    assert len(events) == 10
    assert all(event["success"] is False for event in events)


def test_create_rejects_persona_context_above_256k_before_provider_call(
    monkeypatch,
) -> None:
    monkeypatch.setattr(module, "PERSONA_MAX_CONTEXT_TOKENS", 4)
    client = _client(_response())

    with pytest.raises(module.PersonaContextLimitError, match="prompt_too_large"):
        client._create([{"role": "user", "content": "prompt is too large"}], 32768)
    assert client.client.chat.completions.calls == []


def test_empty_content_retry_records_both_successful_provider_calls(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(module, "record_usage", lambda **event: events.append(event))
    empty = _response(usage={"prompt_tokens": 4, "completion_tokens": 0}, request_id="empty")
    complete = _response(usage={"prompt_tokens": 5, "completion_tokens": 3}, request_id="complete")
    complete.choices[0].message.content = '{"verdict":"accept"}'

    client = _client(empty, complete)
    result = client.respond("system", "user")

    assert result == {"verdict": "accept"}
    assert [event["request_id"] for event in events] == ["empty", "complete"]
    calls = client.client.chat.completions.calls
    assert [call["max_tokens"] for call in calls] == [32768, 32768]


def test_complete_empty_retry_never_exceeds_persona_output_budget() -> None:
    empty = _response()
    complete = _response()
    complete.choices[0].message.content = "done"
    client = _client(empty, complete)

    assert client.complete([{"role": "user", "content": "hi"}]) == "done"
    calls = client.client.chat.completions.calls
    assert [call["max_tokens"] for call in calls] == [32768, 32768]
