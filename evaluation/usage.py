"""Count returned usage once per API response; expose missing accounting."""

import json
from pathlib import Path


def response_usage(body):
    try:
        value = json.loads(body)
        return value.get("usage") if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        found = None
        for line in body.decode("utf-8", errors="replace").splitlines():
            if line.startswith("data:"):
                try:
                    value = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if value.get("usage"):
                    found = value["usage"]
        return found


def total(usage):
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
            if usage:
                usages.append(usage)
        by_role[role] = sum(total(u) for u in usages)
        coverage[role] = {
            "captured_requests": len(requests),
            "captured_responses": len(responses),
            "responses_with_usage": len(usages),
            "usage_complete": bool(requests) and len(usages) == len(requests),
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
