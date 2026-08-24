from __future__ import annotations

from types import SimpleNamespace

import pytest

from auto_designer.user.sim import persona_client as module


class _Completions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)

    def create(self, **_kwargs):
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


def test_create_records_every_failed_retry_before_raising(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(module, "record_usage", lambda **event: events.append(event))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    failures = [RuntimeError(f"failure-{index}") for index in range(10)]

    with pytest.raises(RuntimeError, match="failure-9"):
        _client(*failures)._create([], 100)

    assert len(events) == 10
    assert all(event["success"] is False for event in events)


def test_empty_content_retry_records_both_successful_provider_calls(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(module, "record_usage", lambda **event: events.append(event))
    empty = _response(usage={"prompt_tokens": 4, "completion_tokens": 0}, request_id="empty")
    complete = _response(
        usage={"prompt_tokens": 5, "completion_tokens": 3}, request_id="complete"
    )
    complete.choices[0].message.content = '{"verdict":"accept"}'

    result = _client(empty, complete).respond("system", "user")

    assert result == {"verdict": "accept"}
    assert [event["request_id"] for event in events] == ["empty", "complete"]
