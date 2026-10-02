"""One-turn LLM user simulator for non-interactive benchmark tasks."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

SYSTEM_PROMPT = """You simulate a rigorous but fair end user in an agent benchmark.
The agent received an original task and has now returned its first reply. Write
exactly one follow-up user message asking the agent to inspect and verify its
actual work and fix any remaining issue before acceptance.

Stay strictly within the original task. Do not add requirements, provide a
solution, claim access to hidden tests, or mention this simulation. Ground the
follow-up only in the original task and the agent reply. If the reply admits
missing or uncertain work, focus on that. Be concise (at most 100 words).
Output only the follow-up message."""


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def generate_followup(
    *,
    instruction: str,
    agent_reply: str,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float = 120.0,
) -> dict:
    """Generate one auditable follow-up using an OpenAI-compatible endpoint."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "<original_task>\n"
                    f"{instruction}\n"
                    "</original_task>\n\n"
                    "<agent_first_reply>\n"
                    f"{agent_reply}\n"
                    "</agent_first_reply>"
                ),
            },
        ],
        "temperature": 0,
        "seed": 17,
        "max_tokens": 256,
    }
    endpoint = base_url.rstrip("/") + "/chat/completions"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    followup = _content_text(result["choices"][0]["message"].get("content"))
    if not followup:
        raise RuntimeError("user simulator returned empty content")
    return {
        "schema_version": 1,
        "kind": "llm-generated-user-followup",
        "model": model,
        "base_url": base_url,
        "temperature": 0,
        "seed": 17,
        "max_tokens": 256,
        "system_prompt": SYSTEM_PROMPT,
        "followup": followup,
        "response_id": result.get("id"),
        "provider": result.get("provider"),
        "usage": result.get("usage"),
    }
