# Harness Connector Interface

This document belongs to ahe-beta, not to the harness template. It describes how the platform-side connector and launcher talk to a harness process.

The harness product itself exposes human-facing behavior. The connector adapts simulated user actions to that behavior; persona, feeling, issue, round, triage, and trace metadata stay on the platform side.

## Transport

The target transport is stdio JSON Lines: one JSON object per line.

## Message format

### Input

```json
{"type":"message","text":"Fix the failing test","task_id":"task-1","message_id":"m-1","contract_id":"<declaration sha256>","followup_input":"unavailable","task_budget_seconds":7200,"remaining_budget_seconds":7200,"budget_source":"task_metadata","task_deadline_utc":"<audit timestamp>"}
{"type":"interrupt"}
{"type":"shutdown"}
```

### Output

```json
{"type":"progress","kind":"tool","text":"Running tests"}
{"type":"reply","text":"Done","status":"completed","termination_reason":"complete_task","task_id":"task-1","message_id":"m-1","steps":[]}
{"type":"error","message":"LLM_API_KEY is missing","recoverable":false}
```

## Platform seam API (Spec-0036)

User messages share **one stdin write**:

- `write_message(text)` — always writes a message frame; queueing/busy behavior is harness-owned.
- `begin` / `emit_message` — deprecated aliases of `write_message` (no “official round vs mid-flight” split).

Soft wake on stdout:

- `poll(timeout)` — records `progress` / `status` and keeps waiting; returns on `type=reply`, or `pending` on timeout. **Not** gated by a write-path flag.
- Blocking `send(text)` = `write_message` + poll until reply.

Outer channel (unchanged from Spec-0022):

- `interrupt` / `shutdown` — not ordinary messages.

A terminal reply includes `status` and `termination_reason`. Receiving a reply does not by itself establish successful execution or objective task correctness.

## Ownership

- Harness: product behavior and `/help` content.
- Connector: simulated-user action adaptation; exposes unified `write_message` + optional poll/drain.
- Launcher: checkout, process lifecycle, stdio encoding/decoding.

## Execution conditions (Spec-0084/T3)

Before the first goal, call `bind_execution_contract(declaration)` on the launched handle.
The runner starts one wall-clock task budget at first goal dispatch. Task metadata wins over the
runtime operator fallback; controls, queues, follow-ups and process reset never renew it.
The Seed anchors remaining time at enqueue with its monotonic clock, and subsequent frames
can only tighten the deadline. Optional message activity limits cannot exceed task remaining time.
A separate termination grace permits cancellation and evidence retention, never additional solving.

A bound task accepts only matching task/message identities. Unknown or duplicate replies are
recorded as unmatched sideband events and cannot end the current request. Missing/invalid terminal
status or reason is incomplete with `protocol_invalid_terminal`; a nonempty text is not success.
Manual sessions without negotiated execution conditions remain unknown. `/help`, `/exit` and
`/quit` return `kind=builtin_command`, `status=acknowledged`, `termination_reason=builtin_command`;
they acknowledge their own message and do not complete or renew an active task.
