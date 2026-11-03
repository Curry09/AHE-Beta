# Spec-0029/T2: Agent common runtime — single implementation for "run a nexau agent + read its submit artifact."
"""Common logic previously duplicated across four drivers (triage / architect / divergent / owner) is consolidated here:

- `run_with_timeout`: daemon thread runs call + timeout fallback; uses `contextvars.copy_context()` to carry main thread
  context (containing SessionStore injected via bind_session_store) into worker thread — new threads have empty context by default,
  otherwise agent calling get_session_timeline in worker thread reports "session store not bound" (verified in production).
- `run_agent_def`: load agent definition and run one round — bind sandbox work_dir (absolute path, prevent cwd drift) per call,
  AgentConfig.from_yaml, StepTracer (for kanban process flow), bind_session_store, timeout; returns agent.run return value
  (submit stop-tool echo JSON; falls back to dumps if not str).
- `read_submit`: extract submit payload array from agent.run return value — bounded iterative json.loads (compatible with nexau
  potentially encoding another layer) until dict, take key; if submit not called / parsing fails return None (caller no-op fallback).

Drivers thus become lean: "compose prompt → run_agent_def → read_submit → write tracker."
"""

from __future__ import annotations

import asyncio
import contextvars
import copy
import hashlib
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from ahe_beta.demand.observation_provider import (
    bind_observation_provider,
    bind_observation_scope,
)
from ahe_beta.demand.session_timeline import bind_session_store
from ahe_beta.invocation import record_invocation
from ahe_beta.observations.gaps import GapService, bind_gaps
from ahe_beta.usage import (
    bind_time_accounting,
    bind_usage_context,
    current_time_accounting,
    current_usage_context,
)
from ahe_beta.user.session_store import SessionStore

# Maximum nesting depth when unpacking and re-encoding return values: observed nexau re-encodes return as JSON once (thus ≥2), with margin reserved; bounded to prevent malformed input spinning.
_UNWRAP_MAX_DEPTH = 4


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class AgentTimeout(TimeoutError):
    """Timeout with a stable classification for scoring and recovery."""

    def __init__(self, message: str, *, timeout_class: str, timing: dict[str, object]):
        super().__init__(message)
        self.timeout_class = timeout_class
        self.timing = timing


def run_with_timeout(
    call: Callable[[], object],
    timeout: int,
    *,
    wall_guard: float | None = None,
    latency_isolated: bool = False,
    cancel: Callable[[], None] | None = None,
) -> object:
    """Run an agent with optional provider-wait-isolated accounting."""
    ctx = contextvars.copy_context()
    box: dict = {}

    def target() -> None:
        try:
            box["out"] = ctx.run(call)
        except Exception as exc:  # noqa: BLE001  pass through to caller
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    if not latency_isolated:
        t.join(timeout)
        if t.is_alive():
            if cancel is not None:
                cancel()
            raise AgentTimeout(
                f"agent timeout >{timeout}s", timeout_class="legacy_wall_timeout", timing={}
            )
    else:
        accounting = current_time_accounting()
        if accounting is None:
            raise RuntimeError("latency_isolated_timeout requires time accounting state")
        guard = timeout + (float(wall_guard) if wall_guard is not None else 600)
        while t.is_alive():
            timing = accounting.snapshot()
            active = float(timing["active_elapsed_ms"] or 0) / 1000
            wall = float(timing["wall_elapsed_ms"] or 0) / 1000
            if active >= timeout:
                if cancel is not None:
                    cancel()
                raise AgentTimeout(
                    f"agent active timeout >{timeout}s",
                    timeout_class="mechanism_timeout",
                    timing=timing,
                )
            if wall >= guard:
                timeout_class = (
                    "infrastructure_timeout"
                    if timing.get("provider_active")
                    else "controller_timeout"
                )
                if cancel is not None:
                    cancel()
                raise AgentTimeout(
                    f"agent wall guard >{guard}s",
                    timeout_class=timeout_class,
                    timing=timing,
                )
            t.join(0.25)
        # The polling interval may observe the worker only after it has
        # finished.  Enforce the active deadline at that boundary as well;
        # provider-wait time remains excluded from this check.
        timing = accounting.snapshot()
        wall = float(timing["wall_elapsed_ms"] or 0) / 1000
        if wall >= guard:
            timeout_class = (
                "infrastructure_timeout" if timing.get("provider_active") else "controller_timeout"
            )
            if cancel is not None:
                cancel()
            raise AgentTimeout(
                f"agent wall guard >{guard}s",
                timeout_class=timeout_class,
                timing=timing,
            )
        if float(timing["active_elapsed_ms"] or 0) / 1000 >= timeout:
            if cancel is not None:
                cancel()
            raise AgentTimeout(
                f"agent active timeout >{timeout}s",
                timeout_class="mechanism_timeout",
                timing=timing,
            )
    if "err" in box:
        raise box["err"]
    return box.get("out")


def run_agent_def(
    agent_def_dir: str | Path,
    message: str,
    *,
    store: SessionStore,
    repo: str | Path,
    role: str,
    timeout: int,
    on_event: Callable[[str, str], None] | None = None,
    max_iterations: int | None = None,
    subject: dict[str, str] | None = None,
    replayable: bool = True,
    evidence: dict[str, object] | None = None,
    allowed_session_ids: set[str] | frozenset[str] | None = None,
    observation_root: str | Path | None = None,
    tracker=None,
    source_issue_ids: set[int] | None = None,
    restored_timing: dict[str, object] | None = None,
    history: list[object] | None = None,
    on_history: Callable[[list[object]], None] | None = None,
) -> str:
    """Load nexau agent definition from agent_def_dir and run one round with message, returning the return value of agent.run (str).

    Spec-0049/T3: filled message and output are fail-open written to ROLE_RUNS_DIR/demand;
    Spec-0055: optional evidence metadata is synced to disk for offline boundary replay.
    """

    from ahe_beta.demand.source import current_harness_source

    source = current_harness_source()
    if source is not None:
        repo = source.snapshot()
        message += (
            f"\n\nHarness source is the immutable tested commit {source.sha}. "
            f"Read its source at {repo}; do not infer the version from another checkout."
        )
        evidence = {**(evidence or {}), "harness_source": {"ref": source.sha, "repo": str(repo)}}
    import nexau
    from nexau import Agent, AgentConfig  # noqa: PLC0415  runtime dependency, lazy load

    message += f"\nRead-only NexAU source root: {Path(nexau.__file__).resolve().parents[1]}."

    cfg = AgentConfig.from_yaml(config_path=Path(agent_def_dir) / "agent.yaml")
    sandbox_config = getattr(cfg, "sandbox_config", None)
    if sandbox_config is not None and getattr(sandbox_config, "type", None) == "local":
        # Bind per invocation instead of relying on a shared environment lookup.
        sandbox_config.work_dir = str(Path(repo).resolve())
    reasoning_effort = os.environ.get("DEMAND_LLM_REASONING_EFFORT", "").strip()
    if reasoning_effort and getattr(cfg, "llm_config", None) is not None:
        cfg.llm_config.extra_params["reasoning_effort"] = reasoning_effort
    if max_iterations is not None:
        cfg.max_iterations = min(int(cfg.max_iterations or max_iterations), max_iterations)
    from ahe_beta.loop.live_tracer import StepTracer  # noqa: PLC0415  nexau dependency, lazy load

    run_metrics: dict[str, object] = {"tool_calls": 0}

    def trace_event(kind: str, text: str) -> None:
        if kind == "tool":
            run_metrics["tool_calls"] = int(run_metrics.get("tool_calls") or 0) + 1
        if on_event is not None:
            on_event(kind, text)

    cfg.resolved_tracer = StepTracer(trace_event)
    subj = subject or {"kind": "round", "id": str(current_usage_context().round_no or "")}
    pin = _agent_def_pin(agent_def_dir=Path(agent_def_dir))
    model = os.environ.get("DEMAND_LLM_MODEL")
    history_context = (
        json.dumps(history, ensure_ascii=False, default=lambda item: item.model_dump(mode="json"))
        if history
        else ""
    )
    if history:
        evidence = {
            **(evidence or {}),
            "history_in_context": "nexau_messages",
            "history_messages": len(history),
        }
    scoped_sessions = set(allowed_session_ids or ())
    if role in {"triager", "triage", "triage_agent"}:
        scoped_sessions = {str(current_usage_context().session_id or "unavailable")}
    if role not in {
        "triager",
        "triage",
        "triage_agent",
        "divergent",
        "pm",
        "divergent_pm",
        "architect",
    }:
        scoped_sessions = set()
    # Spec-0084/T4: a separate trusted lane is present in every real role invocation.
    # Owner receives only public facts for its proposal grants, not raw session tools.
    from ahe_beta.demand.evidence_contract import (
        execution_for_sessions,
        format_execution_facts,
    )
    from ahe_beta.observations.grants import authorized_sessions

    contract_sessions = scoped_sessions - {"unavailable"}
    if role == "owner":
        contract_sessions = set().union(
            *(authorized_sessions(store=store, issue=number) for number in source_issue_ids or ())
        )
    facts = execution_for_sessions(store=store, session_ids=contract_sessions)
    fixed_conditions = format_execution_facts(facts)
    if fixed_conditions:
        message += (
            "\n\n## Trusted execution conditions and safe acceptance summary (outside the model-authored proposal body)\n"
            + fixed_conditions
        )
        evidence = {
            **(evidence or {}),
            "execution_contract_ids": [row["contract_id"] for row in facts["execution_contracts"]],
            "assessment_receipt_ids": [row["receipt_id"] for row in facts["assessment_summaries"]],
        }
    with (
        bind_gaps(
            GapService(
                store=store,
                tracker=tracker,
                role=role,
                subject=json.dumps(subj, sort_keys=True),
                sessions=scoped_sessions,
                issues=set(source_issue_ids or ()),
            )
            if tracker is not None
            else None
        ),
        bind_session_store(store),
        bind_observation_provider(
            store, allowed_session_ids=scoped_sessions, observation_root=observation_root
        ) as observations,
        bind_observation_scope(allowed_session_ids=scoped_sessions),
        bind_usage_context(role=role, operation="nexau-agent"),
    ):
        if role != "owner":
            message += "\n\n" + observations.prompt_index()
            evidence = {
                **(evidence or {}),
                "observation_sessions": sorted(scoped_sessions),
                "observation_manifests": [str(paths[0]) for paths in observations.files.values()],
            }
        agent = Agent(config=cfg)
        started = time.monotonic()
        latency_isolated = _env_bool("AHE_BETA_LATENCY_ISOLATED_TIMEOUT")
        wall_guard = int(os.environ.get("AHE_BETA_LATENCY_WALL_GUARD_SECONDS", "0") or 0)
        with bind_time_accounting(
            enabled=latency_isolated,
            restored=restored_timing,
        ) as accounting:
            try:

                def cancel_agent() -> None:
                    try:
                        asyncio.run(agent.stop(force=True, timeout=5))
                    except Exception:
                        pass

                out = run_with_timeout(
                    lambda: (
                        agent.run(message=message)
                        if history is None
                        else agent.run(message=message, history=history)
                    ),
                    timeout,
                    wall_guard=wall_guard or None,
                    latency_isolated=latency_isolated,
                    cancel=cancel_agent,
                )
            except TimeoutError as exc:
                accounting.finish()
                run_metrics["timeout_class"] = getattr(exc, "timeout_class", "legacy_wall_timeout")
                run_metrics["time_accounting"] = (
                    getattr(exc, "timing", None) or accounting.snapshot()
                )
                run_metrics["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
                record_invocation(
                    side="demand",
                    role=role,
                    subject=subj,
                    prompt=message,
                    context=history_context,
                    structured=None,
                    status="timeout",
                    error=str(exc),
                    replayable=replayable,
                    model=model,
                    agent_def_pin=pin,
                    evidence=evidence,
                    metrics=run_metrics,
                )
                raise
            accounting.finish()
            run_metrics["time_accounting"] = accounting.snapshot()
            run_metrics["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        # Capture only a returned invocation, never a still-running timed-out thread.
        # Keep the framework's native messages, including paired tool calls/results.
        if on_history is not None:
            on_history(copy.deepcopy(list(agent.history)))
    text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    structured, status = _structured_status(text=text)
    record_invocation(
        side="demand",
        role=role,
        subject=subj,
        prompt=message,
        context=history_context,
        structured=structured,
        status=status,
        replayable=replayable,
        model=model,
        agent_def_pin=pin,
        evidence=evidence,
        metrics=run_metrics,
    )
    return text


def _agent_def_pin(*, agent_def_dir: Path) -> str | None:
    path = agent_def_dir / "agent.yaml"
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return f"sha256:{digest}"


def _structured_status(*, text: str) -> tuple[object, str]:
    node: object = text
    for _ in range(_UNWRAP_MAX_DEPTH):
        if not isinstance(node, str):
            break
        try:
            node = json.loads(node)
        except (ValueError, TypeError):
            return {"raw": text}, "no_submit"
    if isinstance(node, dict):
        return node, "success"
    return {"raw": text}, "no_submit"


def read_submit(text: str, key: str) -> list[dict] | None:
    """agent.run return value → submit payload array (each item a dict).

    Normal path: text is a `{"<key>": [...]}` JSON string echoed by submit binding (nexau has already
    validated structure against input_schema). Compatible with re-encoding one layer (bounded successive
    json.loads until a dict is obtained). Agent never called submit (hit max_iterations, etc.) → returned
    text is something else / non-compliant JSON → return None; caller falls back to no-op for this round.
    Submitted but empty array → return [] (valid "no output this round").
    """
    node: object = text
    for _ in range(_UNWRAP_MAX_DEPTH):
        if not isinstance(node, str):
            break
        try:
            node = json.loads(node)
        except (ValueError, TypeError):
            return None
    if not isinstance(node, dict):
        return None
    raw = node.get(key)
    if not isinstance(raw, list):
        return None
    return [d for d in raw if isinstance(d, dict)]
