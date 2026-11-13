"""stdio-jsonl-v1 transport around the unmodified published AHE code agent."""

from __future__ import annotations

import contextlib
import getpass
import json
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path


def configure(raw, options):
    """Map only model operating parameters, never prompts/tools/middleware."""
    import copy

    value = copy.deepcopy(raw)
    llm = value["llm_config"]
    api = options.get("api_type", "native")
    if api != "native":
        llm["api_type"] = api
    if llm["api_type"] not in {
        "openai_responses",
        "openai_chat_completion",
        "anthropic_chat_completion",
    }:
        raise ValueError("Unsupported AHE protocol")
    llm["model"] = os.environ["LLM_MODEL"]
    llm["base_url"] = os.environ["LLM_BASE_URL"]
    llm["api_key"] = "${env.LLM_API_KEY}"
    llm["max_tokens"] = options["max_output_tokens"]
    llm["timeout"] = options["timeout_seconds"]
    # NexAU's separate read/stream-idle timeout must match the task budget too.
    llm["stream_idle_timeout_ms"] = int(options["timeout_seconds"] * 1000)
    if options.get("stream", "native") != "native":
        llm["stream"] = options["stream"]
    if llm["api_type"] == "openai_responses":
        llm["reasoning"] = dict(llm.get("reasoning", {}), effort=options["reasoning_effort"])
        llm.pop("reasoning_effort", None)
        # Responses has its own reasoning object, not a Chat thinking extension.
    elif llm["api_type"] == "anthropic_chat_completion":
        llm.pop("reasoning", None)
        llm.pop("reasoning_effort", None)
        llm["extra_body"] = {
            "thinking": {"type": "enabled" if options.get("thinking", True) else "disabled"},
            "reasoning_effort": options["reasoning_effort"],
        }
    else:
        llm.pop("reasoning", None)
        llm["reasoning_effort"] = options["reasoning_effort"]
        llm["extra_body"] = {
            "thinking": {"type": "enabled" if options.get("thinking", True) else "disabled"}
        }
    return value


def main():
    output = sys.stdout
    lock = threading.Lock()

    def emit(frame):
        with lock:
            output.write(json.dumps(frame, ensure_ascii=False, default=str) + "\n")
            output.flush()

    # Native initialization/diagnostic prints must not enter the wire protocol.
    with contextlib.redirect_stdout(sys.stderr):
        import fulltrace
        import yaml
        from nexau import Agent, AgentConfig
        from nexau.archs.main_sub.execution.hooks import HookResult, Middleware
        from nexau.archs.main_sub.execution.middleware.agent_events_middleware import (
            AgentEventsMiddleware,
        )

        root = Path(__file__).resolve().parent
        logs = Path(os.environ.get("HARNESS_LOG_DIR", "/logs/agent"))
        options = json.loads(os.environ["HARNESS_LLM_OPTIONS_JSON"])
        raw = yaml.safe_load((root / "code_agent.yaml").read_text())
        effective = configure(raw, options)
        generated = root / "_ahe_runtime.yaml"
        generated.write_text(yaml.safe_dump(effective, sort_keys=False, allow_unicode=True))
        fulltrace.store(
            logs / "resolved-llm-options.json",
            fulltrace.bytes_of(
                {
                    **options,
                    "api_type": effective["llm_config"]["api_type"],
                    "effective_llm_config": effective["llm_config"],
                    "configured_agent_files": ["_ahe_runtime.yaml"],
                }
            ),
        )

        class Observer(Middleware):
            """Write full inputs/results immediately; never alter hook values."""

            stop_reason = None
            model_output_limit = False

            def before_tool(self, hook):
                fulltrace.event(
                    "tool_started",
                    name=hook.tool_name,
                    tool_call_id=hook.tool_call_id,
                    inputs=hook.tool_input,
                )
                emit({"type": "progress", "phase": "tool_started", "tool": hook.tool_name})
                return HookResult.no_changes()

            def after_tool(self, hook):
                fulltrace.event(
                    "tool_finished",
                    name=hook.tool_name,
                    tool_call_id=hook.tool_call_id,
                    outputs=hook.tool_output,
                )
                return HookResult.no_changes()

            def after_model(self, hook):
                model = hook.model_response
                if model is not None:
                    raw_message = model.raw_message
                    stop = (
                        raw_message.get("stop_reason")
                        if isinstance(raw_message, dict)
                        else getattr(raw_message, "stop_reason", None)
                    )
                    if stop == "max_tokens":
                        self.model_output_limit = True
                        fulltrace.event("model_output_limit", stop_reason=stop)
                    usage = model.usage.to_dict()
                    input_total = (
                        usage["input_tokens"]
                        + usage["cache_read_tokens"]
                        + usage["cache_creation_tokens"]
                    )
                    # OpenAI output already includes reasoning. Never add it twice.
                    emit(
                        {
                            "type": "usage",
                            "usage": {
                                "prompt_tokens": input_total,
                                "completion_tokens": usage["completion_tokens"],
                                "total_tokens": usage["total_tokens"],
                                "reasoning_tokens": usage["reasoning_tokens"],
                                "cached_tokens": usage["cache_read_tokens"],
                            },
                        }
                    )
                    fulltrace.event(
                        "model_completed",
                        usage=usage,
                        response=model.to_dict() if hasattr(model, "to_dict") else str(model),
                    )
                return HookResult.no_changes()

            def after_agent(self, hook):
                self.stop_reason = getattr(hook.stop_reason, "name", str(hook.stop_reason))
                fulltrace.event(
                    "agent_finished", stop_reason=self.stop_reason, response=hook.agent_response
                )
                return HookResult.no_changes()

        def on_event(event):
            # Raw reasoning deltas stay in the audit record, never in user feedback.
            fulltrace.event("nexau_event", data=event.model_dump(mode="json"))

        observer = Observer()
        config = AgentConfig.from_yaml(config_path=generated)
        config.middlewares = [
            *(config.middlewares or []),
            observer,
            AgentEventsMiddleware(session_id="harbor-ahe", on_event=on_event),
        ]
        agent = Agent(config=config)
        sandbox = agent.sandbox_manager.instance
        if sandbox is None:
            raise RuntimeError("AHE local sandbox failed to start")
        emit({"type": "ready", "harness": "ahe", "protocol": "stdio-jsonl-v1"})
        for line in sys.stdin:
            try:
                frame = json.loads(line)
                if frame.get("type") == "shutdown":
                    break
                if frame.get("type") != "message" or not isinstance(frame.get("text"), str):
                    raise ValueError("Expected a stdio-jsonl-v1 message with text")
                observer.stop_reason = None
                observer.model_output_limit = False
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                env = {
                    "date": now,
                    "username": os.getenv("USER") or getpass.getuser(),
                    "working_directory": str(sandbox.work_dir),
                }
                fulltrace.event("user_message", text=frame["text"])
                response = agent.run(message=frame["text"], context={**env, "env_content": env})
                tracer = agent.global_storage.get("tracer")
                if hasattr(tracer, "dump_traces"):
                    fulltrace.store(
                        logs / "ahe-native-spans.json", fulltrace.bytes_of(tracer.dump_traces())
                    )
                failed = observer.stop_reason in {
                    "ERROR_OCCURRED",
                    "CONTEXT_TOKEN_LIMIT",
                    "MAX_ITERATIONS_REACHED",
                    "USER_INTERRUPTED",
                }
                if not isinstance(response, str) or not response.strip():
                    failed = True
                limit = observer.model_output_limit and failed
                text = str(
                    response
                    or (
                        "[model output limit] max_tokens reached before a usable reply"
                        if limit
                        else "[harness error] Empty AHE reply"
                    )
                )
                emit(
                    {
                        "type": "reply",
                        "text": text,
                        "status": "error" if failed else "ok",
                        "failure_kind": "model_output_limit" if limit else None,
                        "stop_reason": observer.stop_reason,
                    }
                )
                if failed:
                    break
            except Exception as error:
                fulltrace.event("adapter_error", error=type(error).__name__, message=str(error))
                traceback.print_exc(file=sys.stderr)
                emit(
                    {
                        "type": "reply",
                        "status": "error",
                        "text": "[harness error] " + type(error).__name__ + ": " + str(error),
                    }
                )
                break


if __name__ == "__main__":
    main()
