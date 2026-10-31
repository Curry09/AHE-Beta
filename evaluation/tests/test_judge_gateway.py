"""Public YAML, the worker, official vote checks and real loopback HTTP agree."""

from __future__ import annotations

import asyncio
import copy
import http.client
import json
import shlex
import threading
import urllib.error
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evaluation.benchmarks.harbor_index.grading import _ensemble_ok, grade_issues
from evaluation.benchmarks.harbor_index.judge import runtime_model
from evaluation.benchmarks.harbor_index.profile import verifier_env
from evaluation.benchmarks.harbor_index.source import PIN
from evaluation.benchmarks.harbor_index.support import anthropic_gateway_proxy as bridge
from evaluation.benchmarks.harbor_index.support.are_sidecar import AreSidecar
from evaluation.configuration import Configuration, ConfigurationError, load
from evaluation.harbor.contracts import resolve_contract
from evaluation.harbor.job import job_config
from evaluation.report import comparison_signature


def configuration(tmp_path, **judge):
    return Configuration.from_mapping(
        {
            "version": 1,
            "paths": {"runs": str(tmp_path / "runs")},
            "actor": {"base_url": "https://actor.invalid/v1"},
            "judge": judge,
        },
        tmp_path / "evaluation.yaml",
    )


def test_public_yaml_keeps_official_judge_defaults():
    config = load(Path(__file__).resolve().parents[2] / "evaluation.yaml")
    assert config.data["judge"] == {
        "base_url": None,
        "api_key_env": "JUDGE_API_KEY",
        "model": "claude-opus-5",
        "normalize_usage": False,
    }


@pytest.mark.parametrize("model", ["claude-opus-5", "anthropic/claude-opus-5"])
def test_public_yaml_allows_only_official_judge_wire_names(tmp_path, model):
    path = tmp_path / "evaluation.yaml"
    path.write_text(
        "version: 1\nactor:\n  base_url: https://actor.invalid/v1\n"
        "judge:\n  base_url: https://gateway.invalid/api\n"
        f"  model: {model}\n  normalize_usage: true\n"
    )
    selected = load(path).data["judge"]
    assert selected["model"] == model and selected["normalize_usage"] is True
    env = verifier_env("gaia2-timed-1", {"judge": selected})
    assert json.loads(env["JUDGE_MODELS"]) == [model]
    assert env["JUDGE_REPEATS"] == PIN["judge"]["JUDGE_REPEATS"] == "3"


@pytest.mark.parametrize("model", [None, 42, [], {}, "claude-opus-5.5", "openai/claude-opus-5"])
def test_public_yaml_cannot_replace_the_official_judge(tmp_path, model):
    with pytest.raises(ConfigurationError, match="official judge cannot be replaced"):
        configuration(tmp_path, model=model)


@pytest.mark.parametrize("options", [{"normalize_usage": True}, {"normalize_usage": "true"}])
def test_usage_compatibility_is_explicit_and_requires_a_gateway(tmp_path, options):
    with pytest.raises(ConfigurationError, match="judge.normalize_usage"):
        configuration(tmp_path, **options)


def manifest_and_trial(tmp_path, judge):
    root = tmp_path / "task"
    root.mkdir()
    (root / "task.toml").write_text(
        "[agent]\ntimeout_sec=7200\n[environment]\ncpus=1\nmemory_mb=1024\n"
        "[verifier]\ntimeout_sec=1800\n"
    )
    config = configuration(tmp_path, **judge)
    settings = {k: config.data[k] for k in ("actor", "user", "judge", "experience")}
    manifest = {
        "cases": [{"benchmark": "Harbor Index", "task_id": "gaia2-fixture", "root": str(root)}],
        "harnesses": [
            {
                "id": "v0",
                "archive": "harness.tar.gz",
                "sha256": "frozen",
                "revision": "fixed",
                "runtime": {},
            }
        ],
        "resolved_cases": {"Harbor Index/gaia2-fixture": resolve_contract(root)},
        "harness_model": "openai/fixture",
        "provider": {"type": "e2b"},
        "metadata": {"evaluation_runtime": settings},
    }
    trial = {"benchmark": "Harbor Index", "task_id": "gaia2-fixture", "harness": "v0"}
    return manifest, trial


def test_judge_selection_reaches_job_without_changing_actor_or_budgets(tmp_path):
    manifest, trial = manifest_and_trial(tmp_path, {"model": "anthropic/claude-opus-5"})
    job = job_config(manifest, trial, tmp_path / "jobs", "fixture")
    assert json.loads(job["verifier"]["env"]["JUDGE_MODELS"]) == ["anthropic/claude-opus-5"]
    assert job["verifier"]["env"]["JUDGE_REPEATS"] == "3"
    assert job["evaluation_runtime"]["judge"] == manifest["metadata"]["evaluation_runtime"]["judge"]
    actor = job["agents"][0]
    assert actor["kwargs"]["request_timeout_sec"] == 7200
    assert actor["override_timeout_sec"] == 7800
    assert not any("JUDGE" in key for key in actor["env"])
    assert "integration_judge_model" not in job
    assert job["environment"]["kwargs"]["benchmark_options"] == {
        "judge": {"model": "anthropic/claude-opus-5", "normalize_usage": False}
    }


def test_prepared_manifest_freezes_judge_gateway_conditions(tmp_path, monkeypatch):
    from evaluation import preparation
    from evaluation.config import CaseRef

    monkeypatch.setattr(
        preparation,
        "prepare",
        lambda *args: (
            {},
            [CaseRef("Harbor Index", "fixture", "fixed", "digest", str(tmp_path))],
            {},
            [{"id": "v0"}],
        ),
    )
    first, _ = preparation.plan(configuration(tmp_path))
    config = configuration(
        tmp_path,
        base_url="https://gateway.invalid",
        model="anthropic/claude-opus-5",
        normalize_usage=True,
    )
    second, _ = preparation.plan(config)
    assert second["metadata"]["evaluation_runtime"]["judge"] == config.data["judge"]
    assert first["manifest_digest"] != second["manifest_digest"]
    assert comparison_signature(first) != comparison_signature(second)


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://other.invalid"},
        {"model": "anthropic/claude-opus-5"},
        {"normalize_usage": True},
    ],
)
def test_pairing_detects_judge_endpoint_alias_and_compatibility_drift(tmp_path, change):
    manifest, _ = manifest_and_trial(tmp_path, {"base_url": "https://gateway.invalid"})
    other = copy.deepcopy(manifest)
    other["metadata"]["evaluation_runtime"]["judge"].update(change)
    assert comparison_signature(manifest) != comparison_signature(other)


@pytest.mark.parametrize("selected", [None, "claude-opus-5", "anthropic/claude-opus-5"])
@pytest.mark.parametrize("benchmark", ["Harbor", "Harbor Index"])
def test_worker_transports_options_without_importing_or_configuring_index(
    tmp_path, monkeypatch, selected, benchmark
):
    import builtins

    from evaluation.harbor import worker
    from harbor.job import Job

    manifest, trial = manifest_and_trial(tmp_path, {} if selected is None else {"model": selected})
    case = manifest["cases"][0]
    case["benchmark"] = trial["benchmark"] = benchmark
    contract = manifest["resolved_cases"].pop("Harbor Index/gaia2-fixture")
    manifest["resolved_cases"][benchmark + "/gaia2-fixture"] = contract
    job = job_config(manifest, trial, tmp_path / "jobs", "fixture")
    if selected is None:
        job.pop("evaluation_runtime")
    job["integration_runtime_digest"] = "test-runtime"
    path = tmp_path / "job.json"
    path.write_text(json.dumps(job))
    for key in (
        "ACTOR_API_KEY",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "HARBOR_INDEX_JUDGE_MODEL",
        "HARBOR_INDEX_JUDGE_NORMALIZE_USAGE",
    ):
        monkeypatch.setenv(key, "host-sentinel")
    # The resolver intentionally sets role env in a dedicated child process.
    # Preserve this test process's original environment around the worker probe.
    import os

    original = dict(os.environ)
    run = AsyncMock()
    create = AsyncMock(return_value=SimpleNamespace(run=run))
    monkeypatch.setattr(Job, "create", create)
    monkeypatch.setattr(worker, "runtime_identity", lambda: {"digest": "test-runtime"})
    original_import = builtins.__import__

    def import_without_index(name, *args, **kwargs):
        if name.startswith("evaluation.benchmarks.harbor_index"):
            raise AssertionError("Generic worker must not import an Index implementation")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_index)
    try:
        asyncio.run(worker.main(SimpleNamespace(config=path, env_file=None)))
        assert os.environ["HARBOR_INDEX_JUDGE_MODEL"] == "host-sentinel"
        assert os.environ["HARBOR_INDEX_JUDGE_NORMALIZE_USAGE"] == "host-sentinel"
        kwargs = create.await_args.args[0].environment.kwargs
        if benchmark == "Harbor Index":
            assert kwargs["benchmark_options"]["judge"]["model"] == (selected or "claude-opus-5")
        else:
            assert "benchmark_options" not in kwargs
        assert "evaluation_runtime" not in create.await_args.args[0].model_dump()
        run.assert_awaited_once()
    finally:
        os.environ.clear()
        os.environ.update(original)


@pytest.mark.parametrize("wire_model", ["claude-opus-5", "anthropic/claude-opus-5"])
def test_litellm_consumes_only_the_transport_provider_prefix(wire_model):
    from litellm import get_llm_provider

    model, provider, *_ = get_llm_provider(
        model=runtime_model(wire_model), custom_llm_provider="anthropic"
    )
    assert (model, provider) == (wire_model, "anthropic")


def report(model="anthropic/claude-opus-5"):
    return {
        "reward": 1,
        "runs": [
            {"model": model, "repeat": n, "provider": "anthropic", "reward": 1} for n in (1, 2, 3)
        ],
    }


def test_valid_alias_votes_still_require_three_successful_official_runs(tmp_path):
    value = report()
    assert _ensemble_ok(value)
    for change in (
        {"model": "claude-opus-5.5"},
        {"provider": "openai"},
        {"error": "unavailable"},
        {"repeat": 2},
    ):
        invalid = copy.deepcopy(value)
        invalid["runs"][0].update(change)
        assert not _ensemble_ok(invalid)
    value["runs"].pop()
    assert not _ensemble_ok(value)


def test_antihack_alias_keeps_quorum_and_decision_rules(tmp_path):
    (tmp_path / "test-stdout.txt").write_text("official tests completed")
    runs = [{"model": "anthropic/claude-opus-5", "repeat": n, "is_hack": False} for n in (1, 2, 3)]
    detail = {
        "reward": 1,
        "gate": {
            "n_total": 3,
            "n_verdicts": 3,
            "quorum": 2,
            "ran": True,
            "clean_fraction": 1,
            "decision": "clean",
            "runs": runs,
        },
    }
    path = tmp_path / "reward_detail.json"
    path.write_text(json.dumps(detail))
    rewards = {"reward": 1, "reward_hack_judge_ran": 1}
    assert not grade_issues("algotune-fixture", rewards, tmp_path)
    runs[0]["model"] = "claude-opus-5.5"
    path.write_text(json.dumps(detail))
    assert grade_issues("algotune-fixture", rewards, tmp_path)


@contextmanager
def serving(server):
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@contextmanager
def upstream(status=200):
    seen = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append(
                {
                    "path": self.path,
                    "body": self.rfile.read(int(self.headers["Content-Length"])),
                    "headers": self.headers,
                }
            )
            body = (
                json.dumps(
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "model": "anthropic/claude-opus-5",
                        "content": [{"type": "text", "text": "MATCH"}],
                        "stop_reason": "end_turn",
                        "stop_sequence": None,
                        "usage": {"input_tokens": 7, "output_tokens": 1, "server_tool_use": None},
                    }
                ).encode()
                if status == 200
                else b'{"error":{"type":"rate_limit_error","message":"retry later"}}'
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Request-Id", "upstream-fixture")
            self.send_header("Retry-After", "17")
            self.end_headers()
            self.wfile.write(body)

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Upstream)) as server:
        yield f"http://127.0.0.1:{server.server_port}/gateway", seen


def request(server, body=None, path="/v1/messages", method="POST"):
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        client.request(
            method,
            path,
            body=body,
            headers={
                "x-api-key": "fixture-secret",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        client.close()


def test_real_http_bridge_preserves_request_content_headers_and_token_usage(monkeypatch, capsys):
    timeouts = []
    original = bridge.urllib.request.urlopen

    def observe(req, *, timeout):
        timeouts.append(timeout)
        return original(req, timeout=timeout)

    monkeypatch.setattr(bridge.urllib.request, "urlopen", observe)
    body = b'{"model":"anthropic/claude-opus-5", "max_tokens":2048,"messages":[{"role":"user","content":"judge this exact text"}]}'
    with upstream() as (base, seen), serving(bridge.create_server(base, 7200)) as server:
        status, headers, response = request(server, body, path="/v1/messages?beta=true")
        assert status == 200 and headers["Request-Id"] == "upstream-fixture"
        assert seen[0]["body"] == body and seen[0]["path"] == "/gateway/v1/messages?beta=true"
        assert seen[0]["headers"]["x-api-key"] == "fixture-secret"
        assert seen[0]["headers"]["anthropic-version"] == "2023-06-01"
        parsed = json.loads(response)
        assert parsed["content"] == [{"type": "text", "text": "MATCH"}]
        assert parsed["usage"] == {"input_tokens": 7, "output_tokens": 1, "server_tool_use": {}}
        assert timeouts == [7200]
    logs = capsys.readouterr().out
    assert "fixture-secret" not in logs and "judge this exact text" not in logs


def test_real_http_bridge_preserves_rate_limit_status_and_retry_header():
    with upstream(429) as (base, seen), serving(bridge.create_server(base, 1800)) as server:
        status, headers, response = request(server, b'{"model":"anthropic/claude-opus-5"}')
        assert status == 429 and headers["Retry-After"] == "17"
        assert response == b'{"error":{"type":"rate_limit_error","message":"retry later"}}'
        assert len(seen) == 1


def test_bridge_health_and_stream_rejection_never_call_judge():
    with upstream() as (base, seen), serving(bridge.create_server(base, 1800)) as server:
        assert request(server, method="GET", path="/health")[2] == bridge.HEALTH_BODY
        assert request(server, b'{"stream":true}')[0] == 400
        assert request(server, b"not json")[0] == 400
        assert request(server, b"{}", path="/other")[0] == 404
        assert not seen


def test_bridge_network_errors_do_not_leak_credentials(monkeypatch):
    def unavailable(*args, **kwargs):
        raise urllib.error.URLError("fixture-secret in a sensitive upstream diagnostic")

    monkeypatch.setattr(bridge.urllib.request, "urlopen", unavailable)
    with serving(bridge.create_server("http://gateway.invalid", 1800)) as server:
        status, _, response = request(server, b"{}")
        assert status == 502 and json.loads(response)["error"]["type"] == "URLError"
        assert b"fixture-secret" not in response


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"usage":{}}',
        b'{"usage":{"server_tool_use":{"web_search_requests":2}}}',
        b'{"error":"unavailable"}',
    ],
)
def test_unrelated_response_bytes_stay_intact(body):
    assert bridge.normalize_response(body) == body


def test_proxy_startup_waits_for_health_and_uses_task_budget(tmp_path, monkeypatch):
    context = tmp_path / "environment"
    context.mkdir()
    (tmp_path / "task.toml").write_text("[agent]\ntimeout_sec=7200\n")
    child = SimpleNamespace(
        upload_file=AsyncMock(),
        exec=AsyncMock(
            side_effect=[
                SimpleNamespace(return_code=0, stdout="71\n"),
                SimpleNamespace(return_code=1, stdout=""),
                SimpleNamespace(return_code=0, stdout="http://127.0.0.1:41937\n"),
            ]
        ),
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    result = asyncio.run(
        AreSidecar(SimpleNamespace())._start_judge_proxy(
            child, "https://gateway.invalid/api", context
        )
    )
    assert result == "http://127.0.0.1:41937"
    launch = child.exec.await_args_list[0]
    assert launch.kwargs["env"]["ARE_JUDGE_TIMEOUT_SECONDS"] == "7200"
    assert child.exec.await_count == 3
    assert "p['pid']==71" in shlex.split(child.exec.await_args.args[0])[2]


@pytest.mark.parametrize("error", ["launch", "health"])
def test_proxy_startup_failure_does_not_start_are(tmp_path, error):
    (tmp_path / "task.toml").write_text("[agent]\ntimeout_sec=1800\n")
    responses = (
        [SimpleNamespace(return_code=1, stdout="")]
        if error == "launch"
        else [SimpleNamespace(return_code=0, stdout="71"), TimeoutError()]
    )
    child = SimpleNamespace(upload_file=AsyncMock(), exec=AsyncMock(side_effect=responses))
    with pytest.raises(RuntimeError, match="proxy launch failed|proxy never became healthy"):
        asyncio.run(
            AreSidecar(SimpleNamespace())._start_judge_proxy(
                child, "https://gateway.invalid", tmp_path / "environment"
            )
        )


@pytest.mark.parametrize("model", ["claude-opus-5", "anthropic/claude-opus-5"])
@pytest.mark.parametrize("normalize", [False, True])
def test_managed_are_uses_selected_transport_and_only_enables_proxy_explicitly(
    tmp_path, monkeypatch, model, normalize
):
    exercise_managed_are(tmp_path, monkeypatch, model, normalize)


def test_failed_proxy_readiness_stops_managed_environment_before_are_launch(tmp_path, monkeypatch):
    exercise_managed_are(tmp_path, monkeypatch, "anthropic/claude-opus-5", True, broken=True)


def exercise_managed_are(tmp_path, monkeypatch, model, normalize, broken=False):
    import yaml

    context = tmp_path / "environment"
    context.mkdir()
    (tmp_path / "task.toml").write_text("[agent]\ntimeout_sec=7200\n")
    (context / "scenario.json").write_text("{}")
    (context / "docker-compose.yaml").write_text(
        yaml.safe_dump(
            {
                "services": {
                    "main": {},
                    "are-sidecar": {
                        "image": "fixture@sha256:" + "0" * 64,
                        "command": ["python", "are_mcp_server_soft_judge.py"],
                    },
                }
            }
        )
    )
    instances = []

    class Environment:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            self.capabilities = SimpleNamespace(docker_compose=False)
            self.start = AsyncMock()
            self.stop = AsyncMock()
            self.upload_file = AsyncMock()
            self.download_dir = AsyncMock()
            self.exec = AsyncMock(side_effect=self.execute)
            instances.append(self)

        def child_kwargs(self):
            return {}

        async def execute(self, command, **kwargs):
            if "judge-proxy.json" in command:
                if broken:
                    raise TimeoutError()
                return SimpleNamespace(return_code=0, stdout="http://127.0.0.1:41937\n")
            return SimpleNamespace(return_code=0, stdout="71\n")

    parent = Environment(
        environment_dir=context,
        environment_name="gaia2-fixture",
        session_id="fixture",
        context_id="fixture",
        _verifier_environment=False,
        benchmark_options={"judge": {"model": model, "normalize_usage": normalize}},
        trial_paths=SimpleNamespace(trial_dir=tmp_path),
        benchmark="Harbor Index",
    )
    monkeypatch.setenv("HARBOR_INDEX_JUDGE_MODEL", "ignored-host-model")
    monkeypatch.setenv("HARBOR_INDEX_JUDGE_NORMALIZE_USAGE", "1" if not normalize else "0")
    monkeypatch.setenv("JUDGE_ANTHROPIC_API_KEY", "judge-only-fixture")
    monkeypatch.setenv("JUDGE_ANTHROPIC_BASE_URL", "https://gateway.invalid/api")
    from evaluation.benchmarks.harbor_index.profile import EnvironmentSupport

    support = EnvironmentSupport(parent)
    monkeypatch.setattr(AreSidecar, "_pump", AsyncMock())

    async def exercise():
        try:
            if broken:
                with pytest.raises(RuntimeError, match="proxy never became healthy"):
                    await support.start(tmp_path)
            else:
                await support.start(tmp_path)
        finally:
            await support.stop()

    asyncio.run(exercise())
    child = instances[1]
    child.stop.assert_awaited_once_with(True)
    launches = [
        c
        for c in child.exec.await_args_list
        if "nohup python are_mcp_server_soft_judge.py" in c.args[0]
    ]
    if broken:
        assert not launches
        return
    assert len(launches) == 1
    env = launches[0].kwargs["env"]
    assert env["ARE_JUDGE_MODEL"] == "anthropic/" + model
    assert env["ANTHROPIC_API_KEY"] == "judge-only-fixture"
    assert env["ANTHROPIC_BASE_URL"] == (
        "http://127.0.0.1:41937" if normalize else "https://gateway.invalid/api"
    )
    proxy_uploads = [
        c
        for c in child.upload_file.await_args_list
        if str(c.args[0]).endswith("anthropic_gateway_proxy.py")
    ]
    assert len(proxy_uploads) == int(normalize)
