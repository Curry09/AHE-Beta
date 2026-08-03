# Harness Connector Interface

This document belongs to auto-designer, not to the harness template. It describes how the platform-side connector and launcher talk to a harness process.

The harness product itself exposes human-facing behavior. The connector adapts simulated user actions to that behavior; persona, feeling, issue, round, triage, and trace metadata stay on the platform side.

## Transport

The target transport is stdio JSON Lines: one JSON object per line.

## stdio-jsonl-v1

### Input

```json
{"type":"message","text":"Fix the failing test"}
{"type":"interrupt"}
{"type":"shutdown"}
```

### Output

```json
{"type":"progress","kind":"tool","text":"Running tests"}
{"type":"reply","text":"Done","steps":[]}
{"type":"error","message":"LLM_API_KEY is missing","recoverable":false}
```

## Legacy compatibility

Old harness refs may still use:

```json
{"message":"Fix the failing test"}
{"control":"interrupt"}
{"progress":{"kind":"tool","text":"Running tests"}}
{"reply":"Done","steps":[]}
```

The launcher supports both formats. New templates should declare `protocol: stdio-jsonl-v1` in `params.yaml`.

## Platform seam API (Spec-0036)

User messages share **one stdin write**:

- `write_message(text)` — always writes a message frame; queueing/busy behavior is harness-owned.
- `begin` / `emit_message` — deprecated aliases of `write_message` (no “official round vs mid-flight” split).

Soft wake on stdout:

- `poll(timeout)` — records `progress` / `status` and keeps waiting; returns on `type=reply` (or legacy `reply` field), or `pending` on timeout. **Not** gated by a write-path flag.
- Blocking `send(text)` = `write_message` + poll until reply.

Outer channel (unchanged from Spec-0022):

- `interrupt` / `shutdown` — not ordinary messages.

## Ownership

- Harness: product behavior and `/help` content.
- Connector: simulated-user action adaptation; exposes unified `write_message` + optional poll/drain.
- Launcher: checkout, process lifecycle, stdio encoding/decoding.
