import json
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import yaml

from evaluation.configuration import HARNESS_NAMES, Configuration, ConfigurationError
from evaluation.harness.runtime_bootstrap import configure_yaml, patch_sdk
from evaluation.preparation import freeze_harness
from evaluation.results import OutcomeKind, TrialResult


def cfg(tmp_path, **overrides):
    raw = {
        "version": 1,
        "actor": {"model": "fixture-model", "base_url": "https://fixture.invalid/v1"},
    }
    raw.update(overrides)
    return Configuration.from_mapping(raw, tmp_path / "evaluation.yaml")


@pytest.mark.parametrize(
    "change",
    [
        {
            "actor": {
                "base_url": "https://fixture.invalid/v1",
                "api_key": "do-not-store-credentials",
            }
        },
        {"execution": {"concurrency": 0}},
        {"harnesses": [["bad"]]},
        {"tasks": "unknown"},
        {"actor": {"base_url": "https://user:password@fixture.invalid"}},
        {"execution": {"timeout_seconds": 9999}},
        {"user": {"enabled": "true"}},
    ],
)
def test_invalid_configuration_fails_before_network(tmp_path, change):
    with pytest.raises(ConfigurationError):
        cfg(tmp_path, **change)


def test_defaults_and_one_task_selection(tmp_path):
    c = cfg(tmp_path)
    assert len(c.task_names()) == 38
    assert c.data["execution"] == {
        "provider": "e2b",
        "concurrency": 4,
        "repetitions": 1,
        "time_adaptation": False,
    }
    assert c.data["actor"]["stream"] == "native"
    assert c.path("harnesses") == tmp_path.parent / "harnesses"


def test_archive_reused_and_original_untouched(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "entry.py").write_text('def main(): pass\nif __name__ == "__main__": main()\n')
    (source / "agent.yaml").write_text("llm_config:\n  max_tokens: 32\n  timeout: 300\n")
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    a = freeze_harness("v0", source, tmp_path / "cache", {})
    b = freeze_harness("v0", source, tmp_path / "cache", {})
    assert a["archive"] == b["archive"] and a["sha256"] == b["sha256"]
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    with tarfile.open(a["archive"]) as t:
        assert t.extractfile("_harness_entry.py").read() == before["entry.py"]
        assert t.extractfile("entry.py").read() != before["entry.py"]
        assert t.extractfile("fulltrace.py").read()


def test_runtime_options_apply_to_nested_agents_and_actual_sdk(tmp_path, monkeypatch):
    p = tmp_path / "agent.yaml"
    p.write_text("llm_config:\n  timeout: 300\n  stream: true\nsystem_prompt: keep this\n")
    options = {
        "max_output_tokens": 65536,
        "timeout_seconds": 1200,
        "reasoning_effort": "max",
        "stream": "native",
        "thinking": True,
    }
    configure_yaml(tmp_path, options)
    data = yaml.safe_load(p.read_text())
    assert data["llm_config"]["timeout"] == 1200
    assert data["llm_config"]["stream"] is True and data["system_prompt"] == "keep this"
    from openai import OpenAI
    from openai.resources.chat.completions import AsyncCompletions, Completions

    # monkeypatch ensures the global SDK methods are restored after this test.
    monkeypatch.setattr(Completions, "create", Completions.create)
    monkeypatch.setattr(AsyncCompletions, "create", AsyncCompletions.create)
    observed = []

    def provider(request):
        observed.append(json.loads(request.content))
        assert request.extensions["timeout"]["read"] == 1200
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "ok",
                            "reasoning_content": "complete reasoning",
                        },
                    }
                ],
            },
        )

    patch_sdk(options)
    with OpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(provider)),
    ) as client:
        answer = client.chat.completions.create(
            model="fixture",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=3,
            timeout=1,
        )
    assert observed[0]["max_tokens"] == 65536 and observed[0]["reasoning_effort"] == "max"
    assert (
        observed[0]["thinking"] == {"type": "enabled"}
        and answer.choices[0].message.reasoning_content == "complete reasoning"
    )


def fixture_task(tmp_path):
    p = tmp_path / "task"
    p.mkdir()
    (p / "task.toml").write_text(
        "[agent]\ntimeout_sec=90\n[environment]\ncpus=1\nmemory_mb=1024\n[verifier]\ntimeout_sec=20\n"
    )
    return p


@pytest.mark.parametrize("name", HARNESS_NAMES)
@pytest.mark.parametrize("simulated", [True, False])
def test_all_harnesses_use_task_budget_and_common_runtime(tmp_path, name, simulated):
    from evaluation.harbor.contracts import resolve_contract
    from evaluation.harbor.job import job_config

    root = fixture_task(tmp_path)
    contract = resolve_contract(root)
    settings = cfg(tmp_path).data
    h = {
        "id": name,
        "archive": "one.tar.gz",
        "sha256": "frozen",
        "revision": "fixed",
        "runtime": {},
    }
    if name in {"claude-code", "meta-harness"}:
        h.update(kind="native", agent=name, version="pinned", process_runtime={})
    manifest = {
        "cases": [{"benchmark": "Harbor", "task_id": "fixture", "root": str(root)}],
        "harnesses": [h],
        "resolved_cases": {"Harbor/fixture": contract},
        "harness_model": "openai/fixture",
        "interactions": [{"user_model": "openai/fixture"}],
        "provider": {"type": "e2b"},
        "metadata": {
            "evaluation_runtime": {k: settings[k] for k in ("actor", "user", "judge", "experience")}
        },
    }
    trial = {
        "benchmark": "Harbor",
        "task_id": "fixture",
        "harness": name,
        "interaction": "simulated_user" if simulated else "direct",
        "time_adaptation": False,
    }
    job = job_config(manifest, trial, tmp_path / "jobs", "fixture")
    actor = job["agents"][0]
    assert actor["kwargs"]["request_timeout_sec"] == 90 and actor["override_timeout_sec"] == 690
    assert actor["kwargs"]["llm_options"]["max_output_tokens"] == 65536
    assert job["n_attempts"] == 1 and job["retry"]["max_retries"] == 0
    if name == "claude-code":
        assert "${CLAUDE_ACTOR_API_KEY}" in actor["env"].values()
    assert job["verifier"]["env"]["ANTHROPIC_API_KEY"] == "${JUDGE_ANTHROPIC_API_KEY}"


def test_credentials_are_isolated_by_role_and_not_in_manifest(tmp_path, monkeypatch):
    from evaluation.credentials import values

    data = cfg(
        tmp_path,
        user={"api_key_env": "USER_TEST_KEY", "base_url": "https://user.invalid/v1"},
        judge={"api_key_env": "JUDGE_TEST_KEY", "base_url": "https://judge.invalid"},
    ).data
    for key, value in [
        ("ACTOR_API_KEY", "actor-only"),
        ("USER_TEST_KEY", "user-only"),
        ("JUDGE_TEST_KEY", "judge-only"),
    ]:
        monkeypatch.setenv(key, value)
    # values intentionally configures worker env; restore those variables after the test.
    for key in [
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "USER_LLM_API_KEY",
        "USER_LLM_BASE_URL",
        "USER_LLM_REASONING_EFFORT",
        "USER_LLM_MAX_OUTPUT_TOKENS",
        "CLAUDE_ACTOR_API_KEY",
        "CLAUDE_LLM_BASE_URL",
        "JUDGE_ANTHROPIC_API_KEY",
        "JUDGE_ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "E2B_HTTP_VERSION",
    ]:
        monkeypatch.setenv(key, "")
    resolved = values(data)
    assert resolved["LLM_API_KEY"] == "actor-only" and resolved["USER_LLM_API_KEY"] == "user-only"
    assert resolved["ANTHROPIC_API_KEY"] == "judge-only"
    assert "actor-only" not in json.dumps(data)


def dialogue(tmp_path):
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / "public-instruction.md").write_text("Fix the public fixture task")
    session = {
        "elapsed_seconds": 90,
        "deadline_seconds": 90,
        "stop_reason": "simulator_invalid:RuntimeError",
        "result": {
            "last_progress": {
                "turns": [
                    {
                        "turn": 1,
                        "message": "Please fix it",
                        "harness_output": "A complete public reply",
                        "patience": 5,
                        "trust": "balanced",
                        "persona_trace": [{"system": "Original persona system"}],
                    }
                ],
                "experience": {"score": 4, "reason": "OLD_SCORE_SENTINEL"},
            }
        },
    }
    (agent / "user-session-result.json").write_text(json.dumps(session))
    (agent / "hidden-verifier.json").write_text("HIDDEN_RESULT_SENTINEL")
    return agent


def test_rating_uses_full_dialogue_excludes_prior_scores_and_unknown_cause(tmp_path):
    from evaluation.experience import prepare

    request, _ = prepare(dialogue(tmp_path), cfg(tmp_path).data)
    prompt = json.dumps(request)
    assert "A complete public reply" in prompt and "Original persona system" in prompt
    assert "OLD_SCORE_SENTINEL" not in prompt and "HIDDEN_RESULT_SENTINEL" not in prompt
    assert "unclassified integration error" in prompt
    assert "Do not infer a communication failure" in prompt


def test_insufficient_evidence_has_no_invented_score(tmp_path):
    from evaluation.experience import rate

    tmp_path.joinpath("agent").mkdir()
    client = Mock()
    value = rate(tmp_path / "agent", cfg(tmp_path).data, tmp_path / "rating", client)
    assert value["status"] == "unavailable" and value["score"] is None
    client.chat.completions.with_raw_response.create.assert_not_called()


def test_valid_rating_immutable_and_full_reasoning_saved(tmp_path):
    from evaluation.experience import rate

    agent = dialogue(tmp_path)
    full = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": '{"score": 2, "reason": "I still need evidence"}',
                    "reasoning_content": "reasoning " * 2000,
                },
            }
        ],
        "usage": {"total_tokens": 99},
    }
    raw = SimpleNamespace(
        http_response=SimpleNamespace(content=json.dumps(full).encode(), status_code=200)
    )
    client = Mock()
    client.chat.completions.with_raw_response.create.return_value = raw
    a = rate(agent, cfg(tmp_path).data, tmp_path / "rating", client)
    b = rate(agent, cfg(tmp_path).data, tmp_path / "rating", client)
    assert (
        a == b
        and a["score"] == 2
        and client.chat.completions.with_raw_response.create.call_count == 1
    )
    assert json.loads((tmp_path / "rating/response.json").read_text()) == full


def test_review_failure_does_not_change_actor_success(tmp_path, monkeypatch):
    import evaluation.runner as runner

    original = TrialResult(
        "one",
        1,
        OutcomeKind.TASK_SUCCESS,
        True,
        True,
        True,
        True,
        20,
        artifacts={"source_result": str(tmp_path / "result.json")},
    )

    def fail(*args, **kwargs):
        raise RuntimeError("offline fixture failure")

    monkeypatch.setattr(runner, "rate", fail)
    result = runner.add_experience(
        original,
        {"interaction": "simulated_user"},
        {"metadata": {"evaluation_runtime": cfg(tmp_path).data}},
        tmp_path / "attempt",
    )
    assert (
        result.passed
        and result.outcome == original.outcome
        and result.metrics["experience"]["score"] is None
    )


def test_stream_usage_counted_once_and_missing_usage_exposed(tmp_path):
    from evaluation.usage import collect

    folder = tmp_path / "full-call-traces/actor"
    folder.mkdir(parents=True)
    (folder / "one.request.body").write_text("{}")
    (folder / "one.response.body").write_text(
        'data: {"usage":{"total_tokens":9}}\n\ndata: {"usage":{"total_tokens":10}}\n\ndata: [DONE]\n'
    )
    value = collect(tmp_path)
    assert value["actor_tokens"] == 10 and value["coverage"]["actor"]["usage_complete"]
    (folder / "two.request.body").write_text("{}")
    value = collect(tmp_path)
    assert value["actor_tokens"] == 10 and not value["coverage"]["actor"]["usage_complete"]


def test_sdk_client_can_initialize_with_host_socks_proxy(monkeypatch):
    from openai import OpenAI

    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    with OpenAI(api_key="offline-fixture", base_url="https://fixture.invalid/v1"):
        pass
