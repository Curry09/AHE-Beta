"""Count returned usage once per API response; expose missing accounting."""

import json
from pathlib import Path


def response_usage(body):
    try:
        value = json.loads(body)
        if not isinstance(value, dict):
            return None
        usage = value.get("usage")
        if usage and value.get("type") == "message":
            usage = dict(usage, _protocol="anthropic_messages")
        return usage
    except (ValueError, UnicodeDecodeError):
        found = None
        messages_usage = {}
        message_stopped = False
        for line in body.decode("utf-8", errors="replace").splitlines():
            if line.startswith("data:"):
                try:
                    value = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if not isinstance(value, dict):
                    continue
                if value.get("type") == "message_start":
                    messages_usage.update((value.get("message") or {}).get("usage") or {})
                if value.get("type") == "message_delta":
                    messages_usage.update(value.get("usage") or {})
                if value.get("type") == "message_stop":
                    message_stopped = True
                usage = value.get("usage")
                if not usage and isinstance(value.get("response"), dict):
                    usage = value["response"].get("usage")
                if usage:
                    found = usage
        if messages_usage:
            return dict(messages_usage, _protocol="anthropic_messages", _complete=message_stopped)
        return found


def total(usage):
    if usage.get("_protocol") == "anthropic_messages":
        return usage.get(
            "total_tokens",
            sum(
                usage.get(key) or 0
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                )
            ),
        )
    return usage.get(
        "total_tokens",
        usage.get("prompt_tokens", usage.get("input_tokens", 0))
        + usage.get("completion_tokens", usage.get("output_tokens", 0)),
    )


def collect(agent, raw_agent_result=None, native_kind=None):
    agent = Path(agent)
    by_role = {}
    coverage = {}
    for role in ("actor", "simulated-user"):
        folder = agent / "full-call-traces" / role
        responses = list(folder.glob("*.response.body"))
        requests = list(folder.glob("*.request.body"))
        usages = []
        for p in responses:
            usage = response_usage(p.read_bytes())
            # message_start has input usage even when a stream is cut off.
            # Such partial accounting must not be marked complete.
            if usage:
                usages.append(usage)
        by_role[role] = sum(total(u) for u in usages)
        complete_usages = sum(u.get("_complete", True) for u in usages)
        coverage[role] = {
            "captured_requests": len(requests),
            "captured_responses": len(responses),
            "responses_with_usage": len(usages),
            "responses_with_complete_usage": complete_usages,
            "usage_complete": bool(requests) and complete_usages == len(requests),
        }
    if native_kind == "claude-code":
        result = raw_agent_result or {}
        a = result.get("n_input_tokens")
        b = result.get("n_output_tokens")
        by_role["actor"] = (a or 0) + (b or 0)
        coverage["actor"].update(
            raw_http_capture=False,
            native_cli_trajectory=True,
            usage_complete=a is not None and b is not None,
        )
    return {
        "actor_tokens": by_role["actor"],
        "user_tokens": by_role["simulated-user"],
        "total_tokens": sum(by_role.values()),
        "coverage": coverage,
    }
