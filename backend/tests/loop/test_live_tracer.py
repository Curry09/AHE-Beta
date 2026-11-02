from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from nexau import SpanType

from ahe_beta.loop import live_tracer as module
from ahe_beta.usage import bind_usage_context, current_usage_context


def test_llm_span_records_usage_with_execution_and_outer_context(monkeypatch) -> None:
    events: list[tuple[dict[str, object], object]] = []

    def capture(**event: object) -> None:
        events.append((event, current_usage_context()))

    monkeypatch.setattr(module, "record_usage", capture)
    tracer = module.StepTracer(lambda _kind, _text: None)
    tracer.set_session_id("agent-run-1")
    span = tracer.start_span("chat", SpanType.LLM, inputs={})

    with bind_usage_context(round_no=3, role="architect"):
        tracer.end_span(
            span,
            outputs={
                "usage": {"prompt_tokens": 11, "completion_tokens": 4},
                "model": "model-a",
                "id": "req-1",
            },
        )

    assert len(events) == 1
    event, context = events[0]
    assert event["usage"] == {"prompt_tokens": 11, "completion_tokens": 4}
    assert event["model"] == "model-a"
    assert event["request_id"] == "req-1"
    assert context.round_no == 3
    assert context.role == "architect"
    assert context.agent_id == "agent-run-1"


def test_llm_span_records_unavailable_usage_and_error(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(module, "record_usage", lambda **event: events.append(event))
    tracer = module.StepTracer(lambda _kind, _text: None)
    span = tracer.start_span("chat", SpanType.LLM, inputs={})
    failure = RuntimeError("provider failed")

    tracer.end_span(span, outputs={}, error=failure)

    assert len(events) == 1
    assert events[0]["usage"] is None
    assert events[0]["success"] is False
    assert events[0]["error"] is failure


def test_concurrent_tracers_do_not_cross_agent_or_role_context(monkeypatch) -> None:
    observed: list[tuple[str | None, str | None]] = []

    def capture(**_event: object) -> None:
        context = current_usage_context()
        observed.append((context.agent_id, context.role))

    monkeypatch.setattr(module, "record_usage", capture)

    def finish(agent_id: str, role: str) -> None:
        tracer = module.StepTracer(lambda _kind, _text: None)
        tracer.set_session_id(agent_id)
        span = tracer.start_span("chat", SpanType.LLM, inputs={})
        with bind_usage_context(role=role):
            tracer.end_span(span, outputs={"usage": {"input_tokens": 1}})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda args: finish(*args), [("agent-a", "triager"), ("agent-b", "owner")]))

    assert sorted(observed) == [("agent-a", "triager"), ("agent-b", "owner")]
