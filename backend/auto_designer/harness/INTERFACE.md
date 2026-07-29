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

## Ownership

- Harness: product behavior and `/help` content.
- Connector: simulated-user action adaptation.
- Launcher: checkout, process lifecycle, stdio encoding/decoding.
