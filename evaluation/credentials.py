"""Resolve role-specific credentials at execution; manifests contain references only."""

import os
from pathlib import Path

from dotenv import load_dotenv


def values(settings, env_file=None, require=True):
    if env_file:
        load_dotenv(Path(env_file), override=True)
    actor = settings["actor"]
    user = settings["user"]
    judge = settings["judge"]

    def secret(name, needed):
        value = os.environ.get(name, "")
        if needed and not value:
            raise ValueError("Missing credential environment variable: " + name)
        return value

    actor_key = secret(actor["api_key_env"], require)
    user_key = secret(user["api_key_env"], require and user["enabled"])
    judge_key = secret(judge["api_key_env"], False)
    result = {
        "LLM_API_KEY": actor_key,
        "LLM_BASE_URL": actor["base_url"],
        "USER_LLM_API_KEY": user_key,
        "USER_LLM_BASE_URL": user["base_url"],
        "USER_LLM_REASONING_EFFORT": user["reasoning_effort"],
        "USER_LLM_MAX_OUTPUT_TOKENS": str(user["max_output_tokens"]),
        "CLAUDE_ACTOR_API_KEY": secret(actor["anthropic_api_key_env"], False),
        "CLAUDE_LLM_BASE_URL": actor.get("anthropic_base_url") or "",
        "JUDGE_ANTHROPIC_API_KEY": judge_key,
        "JUDGE_ANTHROPIC_BASE_URL": judge.get("base_url")
        or ("https://api.anthropic.com" if judge_key else ""),
        "ANTHROPIC_API_KEY": judge_key,
        "ANTHROPIC_BASE_URL": judge.get("base_url")
        or ("https://api.anthropic.com" if judge_key else ""),
    }
    os.environ.update(result)
    os.environ.setdefault("E2B_HTTP_VERSION", "1.1")
    return result


def preflight(manifest, env_file=None):
    settings = manifest["metadata"]["evaluation_runtime"]
    result = values(settings, env_file)
    if not os.environ.get("E2B_API_KEY"):
        raise ValueError("Missing credential environment variable: E2B_API_KEY")
    if any(h["id"] == "claude-code" for h in manifest["harnesses"]):
        if not settings["actor"].get("anthropic_base_url"):
            raise ValueError("Claude Code requires actor.anthropic_base_url in evaluation.yaml")
        if not result["CLAUDE_ACTOR_API_KEY"]:
            raise ValueError(
                "Missing credential environment variable: "
                + settings["actor"]["anthropic_api_key_env"]
            )
    needs_judge = False
    for case in manifest["cases"]:
        for p in Path(case["root"]).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".sh", ".yaml", ".yml", ".toml"}:
                if b"ANTHROPIC_API_KEY" in p.read_bytes():
                    needs_judge = True
                    break
    if needs_judge and not result["JUDGE_ANTHROPIC_API_KEY"]:
        raise ValueError("Selected official verifiers require " + settings["judge"]["api_key_env"])
    return result
