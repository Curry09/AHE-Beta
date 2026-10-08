# Time accounting and provider-latency isolation specification

Status: **implemented behind an opt-in configuration flag; enabled for the formal E2B scaling plan**
Scope: all harness, simulated-user, triage, designer, PM, and developer model
calls in the evaluation suite.

This specification defines which elapsed time is evidence of a harness or
mechanism failure and which elapsed time is external model-provider latency.
It is intended to prevent unstable Boyue/GLM service latency from being scored
as an agent timeout.

The configuration key is `latency_isolated_timeout`. It is deliberately
opt-in: `enabled: false` preserves the legacy wall-clock behavior, while
`enabled: true` activates the accounting and timeout classes below.

## 1. Principle

The runtime MUST preserve raw wall-clock measurements, but mechanism timeout
decisions MUST use active execution time. Time spent waiting for a model
provider is recorded separately and MUST NOT consume the mechanism budget.

The runtime MUST NOT infer that a slow request is a harness failure merely
because its wall-clock duration is large. Conversely, excluding provider wait
MUST NOT permit an unbounded hung request: provider calls and the complete run
retain independent safety limits.

## 2. Clocks

Every role operation MUST maintain these monotonic clocks:

```text
wall_elapsed       = end_monotonic - start_monotonic
provider_wait      = union of all model-request intervals
active_elapsed     = wall_elapsed - provider_wait
```

`provider_wait` includes DNS/connect, server queueing, time-to-first-token,
stream read, and provider retry/backoff while a model request is active. If
requests overlap, intervals MUST be unioned rather than summed twice.

`active_elapsed` includes local agent reasoning between requests, tool calls,
workspace access, subprocesses, parsing, checkpointing, and harness control
logic. A heartbeat or a log line does not pause the active clock.

The runtime SHOULD additionally record `unknown_elapsed` for intervals whose
state cannot be determined. Unknown time MUST NOT silently be reported as
active model work; it is an infrastructure diagnostic.

## 3. Timeout classes

The timeout decision MUST use the following precedence:

| Condition | Classification | Mechanism failure? |
|---|---|---:|
| `active_elapsed > mechanism_deadline` | `mechanism_timeout` | yes |
| one model request exceeds its provider deadline | `provider_timeout` | no |
| wall guard reached while waiting for provider | `infrastructure_timeout` | no |
| wall guard reached while active/tool work is running | `controller_timeout` | infrastructure/unknown |
| explicit task grader failure | `task_failure` | task result |

`provider_timeout`, `infrastructure_timeout`, and `controller_timeout` MUST be
persisted as infrastructure outcomes and MUST NOT be converted into task
passes or mechanism failures.

## 4. Deadlines

The existing official task deadline remains the authoritative benchmark
deadline. This specification changes accounting and classification; it does
not silently change the official benchmark protocol.

Each operation has three independent limits:

```text
mechanism_deadline       official/role active-time budget
provider_request_deadline  maximum one model request wait
wall_guard               absolute safety limit for the operation
```

The outer task deadline continues to cover orchestration and persistence, but
the runtime MUST derive its outcome from the clock state at expiry. If the
outer deadline expires during a provider wait, the result is an
`infrastructure_timeout` with the provider interval attached.

Token counts are diagnostic and MAY trigger context compaction or an explicit
context limit. They MUST NOT be used as a linear substitute for elapsed time:
the same token count can have materially different provider latency.

## 5. Provider-call instrumentation

All OpenAI-compatible and Anthropic-compatible calls MUST pass through a
shared instrumentation wrapper. It MUST emit one event for each attempt:

```json
{
  "event": "model_call",
  "call_id": "...",
  "role": "triager",
  "provider": "boyue",
  "model": "glm-5.3",
  "started_at": "...",
  "finished_at": "...",
  "latency_ms": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "request_id": "...",
  "attempt": 1,
  "status": "success|provider_timeout|error"
}
```

The role record MUST aggregate `wall_elapsed`, `active_elapsed`,
`provider_wait_ms`, `unknown_elapsed_ms`, `model_call_count`, and
`provider_timeout_count`. Existing `usage.jsonl` latency records remain valid
and MUST be retained.

## 6. Watchdog and cancellation

The current whole-agent `thread.join(fixed_timeout)` behavior MUST NOT be the
mechanism timeout implementation. It cannot distinguish a local tool from a
slow provider request and leaves a model call running after the controller has
exited.

The replacement MUST:

1. enter a provider-wait scope before every model request;
2. pause only the active clock during that scope;
3. enforce the provider request deadline inside the model client;
4. checkpoint before retrying or abandoning a timed-out request; and
5. use cancellable process/task boundaries, or an equivalent cooperative
   cancellation mechanism, so a timed-out request cannot outlive the
   controller unnoticed.

When a provider request is in flight and the active budget is otherwise
available, the watchdog MUST wait for the provider deadline rather than label
the role as a mechanism timeout.

## 7. Retry and resume

Only provider/network failures are retryable as provider failures. A retry MUST
have a new `call_id`, preserve the operation key, and be bounded by the wall
guard. A completed model response MUST NOT be replayed as a new role operation.

After a provider timeout, the recovery ledger MUST record:

```text
operation_key
call_id
provider_wait_ms
active_elapsed_ms
timeout_class
retry_index
checkpoint_path
```

Resume MUST reconnect to the same sandbox, repository, session, and operation
key. It MUST not replay a completed user session or duplicate a completed
delivery operation.

## 8. Context growth and provider degradation

Large prompts are a provider-risk signal, not direct evidence of a mechanism
failure. The runtime SHOULD:

- emit a warning before the configured context threshold;
- compact or summarize evidence before issuing another model request;
- exclude binary caches, SQLite databases, and generated worktrees from text
  observation scans; and
- retain the pre-compaction token counts and a hash of the compacted evidence.

Provider latency percentiles SHOULD be reported per role/model, but a slow
percentile MUST remain a provider-health signal unless active execution also
exceeds its mechanism deadline.

## 9. Result and scoring contract

Every trial result MUST expose both raw and effective timing:

```json
{
  "timing": {
    "wall_ms": 0,
    "active_ms": 0,
    "provider_wait_ms": 0,
    "unknown_ms": 0,
    "mechanism_deadline_ms": 0,
    "wall_guard_ms": 0,
    "timeout_class": null
  }
}
```

Headline harness/agent completion metrics MUST use the effective mechanism
classification. Provider and infrastructure failures MUST be reported in a
separate stratum and excluded from task correctness scores. Raw wall time and
provider latency remain available for reproducibility and cost analysis.

Historical runs using the old wall-clock-only implementation MUST be marked
`legacy_wall_clock`. A post-hoc derived classification MAY be generated when
the run contains model-call intervals; the original result MUST NOT be
overwritten.

## 10. Acceptance tests

The implementation is accepted only if all cases pass:

1. A mock 1K-token model call that sleeps 300 seconds records
   `provider_wait_ms≈300000`, does not advance `active_elapsed`, and is not a
   `mechanism_timeout`.
2. A local tool that runs beyond the mechanism deadline with no model request
   is classified `mechanism_timeout`.
3. A provider request exceeding its own deadline is classified
   `provider_timeout`, checkpointed, and resumed without a duplicate operation.
4. Overlapping provider calls count their interval union once.
5. A wall guard reached during an API wait is `infrastructure_timeout`; the
   same guard reached during active tool work is not silently reclassified.
6. The N1 triage trace can be replayed to show provider wait separately from
   active time; its 900-second wall expiry is not reported as a mechanism
   timeout solely because of Boyue latency.
7. The dashboard displays wall time, active time, provider wait, and timeout
   class without exposing API keys or prompt bodies.
