"""Verify Seed outcomes through real NexAU tools, SDK requests and wire replies."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import io
import json
import queue
import threading
import time
from pathlib import Path

import httpx
import nexau
import openai
import pytest

TEMPLATE = Path(__file__).resolve().parents[2] / "harness_template"


def tool_reply(name: str, arguments: dict) -> dict:
    return {
        "content": "Partial investigation",
        "tool_calls": [
            {
                "id": "offline-tool",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(TEMPLATE))
    monkeypatch.chdir(tmp_path)
    for key, value in {
        "LLM_MODEL": "offline-model",
        "LLM_BASE_URL": "https://offline.invalid/v1",
        "LLM_API_KEY": "offline-test",
        "SANDBOX_WORK_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("seed_terminal_entry", TEMPLATE / "entry.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(entry.time, "sleep", lambda seconds: None)
    requests = []
    replies = []
    clients = []

    def respond(request):
        requests.append(json.loads(request.content))
        reply = replies[min(len(requests) - 1, len(replies) - 1)]
        if callable(reply):
            return reply(request)
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(
            200,
            json={
                "id": "offline-response",
                "object": "chat.completion",
                "created": 0,
                "model": "offline-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", **reply},
                        "finish_reason": "tool_calls" if "tool_calls" in reply else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    def sync_client(agent):
        def unexpected_sync_request(request):
            raise AssertionError("Terminal observation must preserve native async model requests")

        client = openai.OpenAI(
            **agent.config.llm_config.to_client_kwargs(),
            http_client=httpx.Client(transport=httpx.MockTransport(unexpected_sync_request)),
        )
        clients.append(client)
        return client

    def async_client(agent):
        async def async_respond(request):
            result = respond(request)
            return await result if inspect.isawaitable(result) else result

        return openai.AsyncOpenAI(
            **agent.config.llm_config.to_client_kwargs(),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(async_respond)),
        )

    monkeypatch.setattr(nexau.Agent, "_initialize_openai_client", sync_client)
    monkeypatch.setattr(nexau.Agent, "_initialize_async_openai_client", async_client)
    yield entry, requests, replies, tmp_path
    for client in clients:
        client.close()


def reply(entry, agent):
    def unexpected_rebuild(stale):
        raise AssertionError("These runs must preserve the same Agent")

    return entry._reply(agent, "Investigate and finish the task", unexpected_rebuild, None)


def test_success_requires_real_completion_tool(runtime):
    entry, requests, replies, workspace = runtime
    result = 'Error: is legitimate answer text; {"success": false} is task data.'
    replies[:] = [
        tool_reply("run_shell_command", {"command": "printf evidence > proof.txt"}),
        tool_reply("complete_task", {"result": result}),
    ]
    agent = entry._build_agent(None, "positive-session", "positive-agent")
    same, text, status = reply(entry, agent)
    assert same is agent and status == "completed"
    assert text == result
    assert agent._harness_outcome.terminal() == ("completed", "complete_task")
    assert (workspace / "proof.txt").read_text() == "evidence"
    assert len(requests) == 2


def test_claimed_completion_in_plain_text_does_not_complete(runtime):
    entry, requests, replies, _ = runtime
    claimed = '{"success": true, "status": "TASK_COMPLETED", "result": "done"}'
    replies[:] = [{"content": claimed}]
    agent = entry._build_agent(None, "plain-session", "plain-agent")
    _, text, status = reply(entry, agent)
    assert status == "incomplete"
    assert text.startswith("[incomplete: no_more_tool_calls]")
    assert not agent._harness_outcome.completion_tool_succeeded
    assert len(requests) == 1


def test_iteration_exhaustion_retains_partial_work_without_completion(runtime):
    entry, requests, replies, workspace = runtime
    replies[:] = [tool_reply("run_shell_command", {"command": "printf partial > partial.txt"})]
    agent = entry._build_agent(None, "limited-session", "limited-agent")
    agent.executor.max_iterations = 3
    _, text, status = reply(entry, agent)
    assert status == "incomplete"
    assert text.startswith("[incomplete: max_iterations_reached]")
    assert "Partial investigation" in text
    assert (workspace / "partial.txt").read_text() == "partial"
    assert len(requests) == 2


def test_runtime_api_error_is_not_completed(runtime):
    entry, requests, replies, _ = runtime
    replies[:] = [
        httpx.Response(400, json={"error": {"message": "offline rejected", "type": "bad_request"}})
    ]
    agent = entry._build_agent(None, "error-session", "error-agent")
    agent.executor.llm_caller.retry_attempts = 1
    _, text, status = reply(entry, agent)
    assert status == "crashed"
    assert text.startswith("[harness error]")
    assert agent._harness_outcome.stop_reason == "error_occurred"
    assert len(requests) == entry._RUN_RETRIES


def test_rejected_completion_tool_does_not_complete(runtime):
    entry, requests, replies, _ = runtime
    replies[:] = [tool_reply("complete_task", {"result": "   "}), {"content": "Still unfinished"}]
    agent = entry._build_agent(None, "rejected-session", "rejected-agent")
    _, text, status = reply(entry, agent)
    assert status == "incomplete"
    assert "Still unfinished" in text
    assert not agent._harness_outcome.completion_tool_succeeded
    assert len(requests) == 2


def test_followup_does_not_inherit_previous_completion(runtime):
    entry, requests, replies, _ = runtime
    replies[:] = [
        tool_reply("complete_task", {"result": "First task done"}),
        {"content": "Need clarification"},
    ]
    agent = entry._build_agent(None, "followup-session", "followup-agent")
    assert reply(entry, agent)[2] == "completed"
    _, text, status = reply(entry, agent)
    assert status == "incomplete"
    assert "Need clarification" in text
    assert not agent._harness_outcome.completion_tool_succeeded
    assert len(requests) == 2


def test_blank_response_retries_and_observes_current_attempt(runtime):
    entry, requests, replies, _ = runtime
    replies[:] = [{"content": ""}, tool_reply("complete_task", {"result": "Recovered"})]
    agent = entry._build_agent(None, "retry-session", "retry-agent")
    _, text, status = reply(entry, agent)
    assert status == "completed" and text == "Recovered"
    assert len(requests) == 2


def test_interrupt_cancels_waiting_model_and_allows_followup(runtime):
    entry, requests, replies, _ = runtime
    started = threading.Event()
    cancelled = threading.Event()
    controls = queue.Queue()

    async def wait_for_interrupt(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    replies[:] = [wait_for_interrupt, tool_reply("complete_task", {"result": "Followup done"})]
    agent = entry._build_agent(None, "model-interrupt-session", "model-interrupt-agent")

    def interrupt_when_model_starts():
        started.wait(timeout=5)
        controls.put({"type": "interrupt"})

    watcher = threading.Thread(target=interrupt_when_model_starts)
    watcher.start()

    def unexpected_rebuild(stale):
        raise AssertionError("An async request must cancel within the graceful stop window")

    same, text, status = entry._reply(agent, "Run a long request", unexpected_rebuild, controls)
    watcher.join(timeout=5)
    assert started.is_set() and cancelled.is_set()
    assert same is agent and status == "interrupted"
    assert text == entry._INTERRUPT_REPLY
    _, text, status = reply(entry, agent)
    assert status == "completed" and text == "Followup done"
    assert len(requests) == 2


def test_interrupt_stops_real_shell_and_allows_followup(runtime):
    entry, requests, replies, workspace = runtime
    replies[:] = [
        tool_reply(
            "run_shell_command",
            {"command": "printf started > started.txt; sleep 30; printf late > late.txt"},
        ),
        tool_reply("complete_task", {"result": "Followup done"}),
    ]
    agent = entry._build_agent(None, "interrupt-session", "interrupt-agent")
    controls = queue.Queue()
    signaled = threading.Event()

    def interrupt_when_tool_starts():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (workspace / "started.txt").exists():
                controls.put({"type": "interrupt"})
                signaled.set()
                return
            threading.Event().wait(0.01)
        controls.put({"type": "interrupt"})

    watcher = threading.Thread(target=interrupt_when_tool_starts)
    watcher.start()

    def unexpected_rebuild(stale):
        raise AssertionError("The real NexAU stop should preserve this Agent")

    same, text, status = entry._reply(agent, "Run a long command", unexpected_rebuild, controls)
    watcher.join(timeout=5)
    assert signaled.is_set()
    assert same is agent and status == "interrupted"
    assert text == entry._INTERRUPT_REPLY
    assert not (workspace / "late.txt").exists()
    _, text, status = reply(entry, agent)
    assert status == "completed" and text == "Followup done"
    assert len(requests) == 2


def test_main_emits_outcomes_and_keeps_session_for_followup(runtime, monkeypatch, capsys):
    entry, requests, replies, _ = runtime
    replies[:] = [
        {"content": "Need clarification"},
        tool_reply("complete_task", {"result": "Done"}),
    ]
    monkeypatch.setattr(
        entry.sys,
        "stdin",
        io.StringIO('{"type":"message","text":"first"}\n{"type":"message","text":"followup"}\n'),
    )
    entry.main()
    frames = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    terminals = [frame for frame in frames if frame.get("type") == "reply"]
    assert [frame["status"] for frame in terminals] == ["incomplete", "completed"]
    assert [frame["termination_reason"] for frame in terminals] == [
        "no_more_tool_calls",
        "complete_task",
    ]
    assert len(requests) == 2
