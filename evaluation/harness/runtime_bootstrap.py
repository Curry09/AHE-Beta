"""Runtime-only model configuration and complete capture; original entry stays unchanged."""

from __future__ import annotations

import functools
import inspect
import json
import os
import runpy
from pathlib import Path


def request_options(options):
    result = {
        "max_tokens": options["max_output_tokens"],
        "timeout": options["timeout_seconds"],
        "reasoning_effort": options["reasoning_effort"],
    }
    if options.get("stream") != "native":
        result["stream"] = options["stream"]
    return result


def patch_sdk(options):
    from openai.resources.chat.completions import AsyncCompletions, Completions

    overrides = request_options(options)

    def wrap(original):
        def prepare(kwargs):
            out = dict(kwargs)
            out.update(overrides)
            if options.get("thinking"):
                out["extra_body"] = {
                    **out.get("extra_body", {}),
                    "thinking": {"type": "enabled"},
                }
            return out

        if inspect.iscoroutinefunction(original):

            @functools.wraps(original)
            async def invoke(self, *args, **kwargs):
                return await original(self, *args, **prepare(kwargs))
        else:

            @functools.wraps(original)
            def invoke(self, *args, **kwargs):
                return original(self, *args, **prepare(kwargs))

        return invoke

    Completions.create = wrap(Completions.create)
    AsyncCompletions.create = wrap(AsyncCompletions.create)


def configure_yaml(root, options):
    import yaml

    touched = []
    for path in sorted(root.rglob("*.yaml")):
        # Only agent declarations: prompts, tool contracts and policies stay intact.
        value = yaml.safe_load(path.read_text())
        if not isinstance(value, dict) or not isinstance(value.get("llm_config"), dict):
            continue
        llm = value["llm_config"]
        llm["max_tokens"] = options["max_output_tokens"]
        llm["timeout"] = options["timeout_seconds"]
        llm["stream_idle_timeout_ms"] = int(options["timeout_seconds"] * 1000)
        llm["reasoning_effort"] = options["reasoning_effort"]
        if options.get("stream") != "native":
            llm["stream"] = options["stream"]
        if options.get("thinking"):
            llm["extra_body"] = {
                **llm.get("extra_body", {}),
                "thinking": {"type": "enabled"},
            }
        path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True))
        touched.append(str(path.relative_to(root)))
    return touched


def main():
    root = Path(__file__).parent
    options = json.loads(os.environ["HARNESS_LLM_OPTIONS_JSON"])
    if options.get("stream", "native") != "native":
        os.environ["LLM_STREAM"] = "1" if options["stream"] else "0"
    import fulltrace

    logs = Path(os.environ.get("HARNESS_LOG_DIR", "/logs/agent"))
    fulltrace.install("actor", logs / "full-call-traces/actor")
    touched = configure_yaml(root, options)
    patch_sdk(options)
    os.environ["LLM_MAX_OUTPUT_TOKENS"] = str(options["max_output_tokens"])
    record = logs / "resolved-llm-options.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(dict(options, configured_agent_files=touched), indent=2) + "\n")
    entry = runpy.run_path(str(root / "_harness_entry.py"), run_name="_frozen_harness")
    namespace = entry["main"].__globals__
    if "_make_step_collector" in namespace:
        fulltrace.wrap_collector_factory(namespace)
    entry["main"]()


if __name__ == "__main__":
    main()
