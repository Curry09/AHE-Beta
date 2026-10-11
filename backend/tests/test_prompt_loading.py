"""Exercise shipped prompts through real runtimes and SDK requests, without a live model."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import nexau
import openai
import pytest

from auto_designer.demand.agent_runtime import read_submit, run_agent_def
from auto_designer.nexau_runtime import _default_nexau_backend
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.persona_client import ApiPersonaClient

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def gateway(monkeypatch, tmp_path):
    """Keep actual NexAU/SDK execution; replace only HTTP responses."""
    for prefix in ("LLM", "DEMAND_LLM", "USER_LLM"):
        monkeypatch.setenv(f"{prefix}_MODEL", f"offline-{prefix.lower()}")
        monkeypatch.setenv(f"{prefix}_BASE_URL", "https://offline.invalid/v1")
        monkeypatch.setenv(f"{prefix}_API_KEY", "offline-test")
        monkeypatch.delenv(f"{prefix}_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("SANDBOX_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("ROLE_RUNS_DIR", str(tmp_path / "role-runs"))
    monkeypatch.chdir(tmp_path)
    requests = []
    replies = [{"content": "offline completed"}]
    clients = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        reply = replies[min(len(requests) - 1, len(replies) - 1)]
        message = {"role": "assistant", **reply}
        return httpx.Response(
            200,
            json={
                "id": "offline-completion",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if "tool_calls" in reply else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    def sync_client(agent):
        client = openai.OpenAI(
            **agent.config.llm_config.to_client_kwargs(),
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        )
        clients.append(client)
        return client

    def async_client(agent):
        return openai.AsyncOpenAI(
            **agent.config.llm_config.to_client_kwargs(),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )

    monkeypatch.setattr(nexau.Agent, "_initialize_openai_client", sync_client)
    monkeypatch.setattr(nexau.Agent, "_initialize_async_openai_client", async_client)
    yield requests, replies, respond
    for client in clients:
        client.close()


def _tool_reply(*, name, arguments):
    return {
        "content": None,
        "tool_calls": [
            {
                "id": f"offline-{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


@pytest.mark.parametrize(
    ("role", "folder", "tool", "arguments"),
    [
        (
            "triager",
            "triage_agent",
            "submit_triage",
            {
                "dispositions": [
                    {
                        "issue": 1,
                        "disposition": "needs_info",
                        "reason": "Offline probe has no report evidence.",
                        "artifact": {
                            "reported_problem": "offline probe",
                            "user_impact": "unavailable",
                            "scope_boundary": "unavailable",
                            "evidence": [],
                            "uncertainties": ["no report evidence"],
                            "implementation_target": "uncertain",
                        },
                    }
                ]
            },
        ),
        ("synthesizer", "synthesizer", "submit_rfcs", {"proposals": []}),
        ("divergent", "divergent_pm", "submit_divergent", {"proposals": []}),
        ("owner", "owner", "submit_admission", {"decisions": []}),
    ],
)
def test_demand_runtime_sends_full_system_prompt_and_executes_stop_tool(
    role, folder, tool, arguments, gateway, tmp_path
):
    requests, replies, _ = gateway
    replies[:] = [_tool_reply(name=tool, arguments=arguments)]
    if role != "owner":
        replies.insert(0, _tool_reply(name="read_file", arguments={"file_path": "evidence.txt"}))
    repo = tmp_path / "harness-repo"
    repo.mkdir()
    (repo / "evidence.txt").write_text("bound-source-evidence", encoding="utf-8")
    definition = BACKEND / "agent_defs" / folder
    out = run_agent_def(
        definition,
        "offline role request",
        store=SessionStore(tmp_path / "sessions"),
        repo=repo,
        role=role,
        timeout=10,
        # NexAU reserves the final iteration for stopping; allow two model calls.
        max_iterations=3,
    )

    for key, items in arguments.items():
        assert read_submit(out, key) == items
    assert len(requests) == len(replies)
    assert requests[0]["model"] == "offline-demand_llm"
    messages = requests[0]["messages"]
    expected = (definition / "systemprompt.md").read_text(encoding="utf-8").rstrip("\n")
    assert [msg["content"] for msg in messages if msg["role"] == "system"] == [expected]
    assert any(
        msg["role"] == "user" and "offline role request" in msg["content"] for msg in messages
    )
    assert tool in {item["function"]["name"] for item in requests[0]["tools"]}
    if role != "owner":
        assert "bound-source-evidence" in json.dumps(requests[1]["messages"])
    else:
        assert {item["function"]["name"] for item in requests[0]["tools"]} == {
            "submit_admission",
            "submit_observation_gap",
        }


def test_seed_entry_sends_full_system_prompt_and_completes_task(gateway, monkeypatch, tmp_path):
    requests, replies, _ = gateway
    replies[:] = [
        _tool_reply(
            name="run_shell_command",
            arguments={"command": "printf 'workspace-probe' > prompt-probe.txt"},
        ),
        _tool_reply(name="complete_task", arguments={"result": "offline completed"}),
    ]
    workspace = tmp_path / "user-project"
    workspace.mkdir()
    monkeypatch.setenv("SANDBOX_WORK_DIR", str(workspace))
    root = BACKEND / "harness_template"
    monkeypatch.syspath_prepend(str(root))
    spec = importlib.util.spec_from_file_location("prompt_test_seed_entry", root / "entry.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    agent = entry._build_agent(None, "offline-session", "offline-agent")
    out = agent.run(message="offline seed request")

    assert "offline completed" in out
    assert len(requests) == 2
    assert requests[0]["model"] == "offline-llm"
    assert (workspace / "prompt-probe.txt").read_text() == "workspace-probe"
    assert not (tmp_path / "prompt-probe.txt").exists()
    expected = (root / "agents" / "main.md").read_text(encoding="utf-8").rstrip("\n")
    assert requests[0]["messages"][0] == {"role": "system", "content": expected}


def test_transient_runtime_loads_written_prompt_in_real_request(gateway):
    requests, _, _ = gateway
    assert _default_nexau_backend("Full transient role instructions.", "offline request") == (
        "offline completed"
    )
    assert len(requests) == 1
    assert requests[0]["model"] == "offline-llm"
    assert "Full transient role instructions." in requests[0]["messages"][0]["content"]
    assert "./prompt.md" not in requests[0]["messages"][0]["content"]


def test_persona_client_sends_supplied_system_text(gateway):
    requests, replies, respond = gateway
    replies[0]["content"] = '{"score": 4, "reason": "offline probe"}'
    client = ApiPersonaClient()
    client.client.close()
    client.client = openai.OpenAI(
        api_key="offline-test",
        base_url="https://offline.invalid/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    try:
        assert client.respond("Full persona instructions.", "<rate_experience>probe") == {
            "score": 4,
            "reason": "offline probe",
        }
    finally:
        client.client.close()
    assert len(requests) == 1
    assert requests[0]["model"] == "offline-user_llm"
    assert requests[0]["messages"][0] == {
        "role": "system",
        "content": "Full persona instructions.",
    }


def test_missing_system_prompt_fails_before_model_request(gateway, tmp_path):
    requests, _, _ = gateway
    config = nexau.AgentConfig.from_yaml(config_path=BACKEND / "harness_template" / "agent.yaml")
    config.system_prompt = str(tmp_path / "missing-prompt.md")
    agent = nexau.Agent(config=config)

    with pytest.raises(ValueError, match="Error building system prompt"):
        agent.run(message="offline request")
    assert not requests
