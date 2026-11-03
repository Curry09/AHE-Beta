---
number: "0019"
title: "Relax launcher non-reply sideband handling (progress, etc.)"
issue: 0
slug: control-sideband-peek-wait
summary: "Relax the harness stdout sideband protocol (accept any non-reply JSON and write it to last_sideband/last_progress); control() continues to support both sideband ack and terminal reply shapes (wire compatible). The user-side path for peek/status via control has been superseded by 0022 and abandoned (original T2). See 0022 for the current user wait loop."
tasks:
  - id: T1
    title: "launcher: accept all non-reply sidebands + route control sideband/terminal responses separately"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0022/T1
        type: note
    parallel: false
    files:
      - backend/ahe_beta/harness/launcher.py
      - backend/tests/harness/test_launcher.py
    scope: "Relax the stdout protocol: a round may contain any number of non-reply JSON sideband lines (progress/other fields); only a line containing reply ends the round; unknown sidebands do not cause protocol violations. poll accumulates last_sideband/last_progress. control(name) waits for a reply or a sideband ack that is not progress-only; expose in_flight. The main user sim path uses only interrupt; peek-via-control is no longer invoked from the user menu (see 0022)."
    acceptance: "poll does not raise a protocol violation for sideband JSON containing only unknown keys and writes it to last_sideband; progress maps to last_progress; control('interrupt') returns a reply and in_flight is False. Unit tests cover unknown sidebands and interrupt termination; status sidebands remain testable on the wire but are not a current user-side capability."
---

# 0019 · Relax launcher non-reply sideband handling (progress, etc.)

<!-- This file is maintained by the spec tool: frontmatter is structured source data (including the tasks DAG), and the body is a nine-section, group-level rust-RFC overview. -->

## Summary

On top of `begin/poll/control` in 0013, relax the launcher's acceptance of stdout **non-reply sideband** messages: any non-reply JSON is accepted and mapped to `last_sideband` / `last_progress` for use by the heartbeat activity bar. `control()` still distinguishes between "sideband ack" and "terminal reply" on the wire.

**On the user side**, peek/status no longer goes through `invoke_control`; that path (originally T2 in this group) has been abandoned and replaced by the **0022** inner and outer windows (inner=message). This group's live snapshot retains only **T1 (launcher pipeline)**.

## Motivation

When the initial `poll` was too narrow, sideband messages other than `progress`/`reply` caused protocol violations, leaving the activity bar and future sideband messages unsupported. The pipeline needs to be relaxed.

Subsequently, control was used for peek on the user side; that design conflicted with "inner=message" and has been moved out of this group. Relaxing the pipeline itself remains valuable (progress accumulation).

## Guide-level explanation

- Launcher accepts all non-reply sideband messages; `in_flight` is true until the terminal reply.
- How the user-side wait loop makes decisions and what the menu contains → **0022**.
- If the harness still implements status sideband control, the launcher can accept it, but the seed MANUAL does not claim this user capability.

## Reference-level explanation

### Anchors

- `harness/launcher.py`: `_ingest_sideband`, `last_sideband`, `control()`, `in_flight`; also `emit_message` in 0022.
- Unit tests: `tests/harness/test_launcher.py`.

### DAG

T1 only.

### Adjacent groups

- **0013**: envelope unpacking, interrupt, progress emission.
- **0022**: user-side IO and wait menu; replaces the original T2 in this group.

## Drawbacks

Sideband ack still uses a "not pure progress" heuristic; this only affects callers that still invoke `control(non-interrupt)`.

## Rationale and alternatives

Retain T1 and remove the user-side peek Task: this decouples the pipeline from product semantics. The alternative, "abandon the entire group", would lose the still-live description of sideband reception; rejected.

## Prior art

0013 stdio JSONL; 0022 inner and outer channels.

## Unresolved questions

Whether the control surface will eventually be narrowed to interrupt only.

## Future possibilities

Correlate frames with `control_result`; or document a short timeout for "progress sideband only, no status ack".
