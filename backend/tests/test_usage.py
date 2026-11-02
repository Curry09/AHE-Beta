from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from ahe_beta import usage as module
from ahe_beta.usage import UsageStore, bind_usage_context, current_usage_context, usage_fields


def test_usage_normalization_preserves_optional_fields() -> None:
    assert usage_fields(
        {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens_details": {"reasoning_tokens": 2},
        }
    ) == {
        "input_tokens": 10,
        "output_tokens": 4,
        "reasoning_tokens": 2,
        "cached_input_tokens": 3,
        "total_tokens": 14,
    }
    assert usage_fields(None) == {
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "cached_input_tokens": None,
        "total_tokens": None,
    }


def test_concurrent_context_and_jsonl_append_do_not_cross_or_corrupt(tmp_path) -> None:
    store = UsageStore(tmp_path / "usage.jsonl")

    def write(session_id: str) -> None:
        with bind_usage_context(session_id=session_id, role="user"):
            for _ in range(50):
                ctx = current_usage_context()
                store.append({"session_id": ctx.session_id, "role": ctx.role, "total_tokens": 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, ("one", "two")))

    rows = [json.loads(line) for line in store.path.read_text().splitlines()]
    assert len(rows) == 100
    assert sum(r["session_id"] == "one" for r in rows) == 50
    assert sum(r["session_id"] == "two" for r in rows) == 50


def test_summary_is_derived_from_filtered_raw_events(tmp_path) -> None:
    store = UsageStore(tmp_path / "usage.jsonl")
    store.append(
        {
            "role": "user",
            "session_id": "a",
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
            "usage_source": "reported",
        }
    )
    store.append(
        {
            "role": "architect",
            "session_id": "b",
            "input_tokens": 7,
            "output_tokens": 1,
            "total_tokens": 8,
            "reasoning_tokens": 1,
            "cached_input_tokens": 2,
            "usage_source": "reported",
        }
    )
    store.append(
        {
            "role": "architect",
            "session_id": "b",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "reasoning_tokens": None,
            "cached_input_tokens": None,
            "usage_source": "unavailable",
        }
    )
    assert store.summary()["total_tokens"] == 13
    assert store.summary(session_id="a")["total_tokens"] == 5
    assert store.summary()["unavailable_count"] == 1
    assert store.summary()["by_role"]["architect"]["event_count"] == 2
    assert store.summary()["by_role"]["architect"]["unavailable_count"] == 1
    assert store.summary(role="missing")["event_count"] == 0


def test_recording_failure_never_escapes_observability_boundary(monkeypatch) -> None:
    class BrokenStore:
        def append(self, _event) -> None:
            raise OSError("disk unavailable")

    monkeypatch.setattr(module, "default_usage_store", lambda: BrokenStore())
    module.record_usage(usage={"input_tokens": 1, "output_tokens": 2})
