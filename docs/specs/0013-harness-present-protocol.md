---
number: "0013"
title: "Harness Presentation and Interaction Protocol: Envelope Unwrapping · Layered Process Streams · Interruption/Heartbeat"
issue: 0
slug: harness-present-protocol
summary: "Fully separate user-facing harness presentation from internal processes, and complete the interaction protocol for slow sessions: unwrap complete_task envelopes; expose only the observation layer of internal processes through steps; emit mid-flight {\"progress\":…} activity strips while running (stdout may carry multiple side-channel lines, while the terminal state remains one line containing reply); control:interrupt returns [interrupted]; launcher begin/poll/control uses segmented polling without blindly killing processes. Implementation targets: harness_template + harness/launcher. See 0019 for relaxed side-channel handling and continued waiting with peek."
tasks:
  - id: T1
    title: "Unwrap complete_task envelopes + layer process streams + begin/poll/control heartbeat protocol"
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/entry.py
      - backend/ahe_beta/harness/launcher.py
      - backend/ahe_beta/harness/interface.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/models.py
      - backend/tests/harness/test_template_entry.py
      - backend/tests/harness/test_launcher.py
    scope: "entry.py: line-delimited JSON on stdin (message/control); within a turn, first emit zero or more {\"progress\":{kind,text}} activity-strip lines (_emit_progress shares _stdout_lock with terminal reply to prevent interleaving), followed by one terminal {\"reply\", \"steps\"?} line. Unwrap envelopes with _unwrap_reply; steps provides observations only; interrupt→[interrupted]. Document budget controls in comments. launcher begin/poll/control: return pending while the process is alive; last_steps/last_progress side channels (see 0019 for progress reception and relaxed handling of unknown side channels). Record steps in models/sim_user."
    acceptance: "Terminal reply is nonempty and unwrapped; progress lines may be emitted while running and do not replace reply; steps does not enter reply; interrupt→[interrupted]; poll returns pending while alive. Unit tests cover envelopes, steps, and interruption; align progress emission and reception with 0019."
  - id: T2
    title: "v0 seed self-test smoke + MANUAL presentation contract"
    status: pending
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/harness_template/tests/test_smoke.py
      - backend/harness_template/MANUAL.md
    scope: "Minimal smoke test in tests/test_smoke.py; MANUAL.md records the presentation contract—a single terminal reply, a visible activity strip (progress) while waiting, [interrupted]/timeout semantics, and the control plane—consistent with entry. tests/ contains only tests for the harness itself (see 0015)."
    acceptance: "smoke passes; MANUAL describes the division of responsibilities between activity strip / terminal reply, consistent with entry behavior."
---

# 0013 · Harness Presentation and Interaction Protocol: Envelope Unwrapping · Layered Process Streams · Interruption/Heartbeat

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level nine-section rust-RFC overview. -->

## Summary

Standardize the user-facing presentation and interaction protocol of the harness as a “launchable program + black-box conversation contract”:

1. **Envelope unwrapping**—strip the `complete_task` envelope down to `output.result`, so the user sees only the final answer;
2. **Layered process streams**—internal `steps` exposes only the observation layer, and the persona consumes only `reply`;
3. **In-flight activity strip**—a turn may first emit zero or more `{"progress":{kind,text}}` lines (sharing the stdout lock with terminal reply), while the terminal state remains one line containing `reply`;
4. **Interruption/segmented polling**—`control:interrupt` → `[interrupted]`; launcher `begin/poll/control` returns pending for a live process without blindly killing it.

See **0019** for relaxed side-channel keys and continued waiting with peek. Implementation targets: `harness_template/` + `harness/launcher.py`.

## Motivation

The harness is a black-box conversation contract: receive messages on stdin and reply on stdout. Envelope leakage, process streams contaminating the user experience, and the lack of a protocol for slow sessions must be addressed at the root; waiting must also expose a visible activity strip for 0012 heartbeat decisions.

## Guide-level explanation

- **Protocol frames.** stdin: `{"message"}` / `{"control"}`. stdout: multiple `progress` lines may appear while running; one terminal `{"reply", "steps"?}` line.
- **reply is for people**; `steps` is an observation side channel; `progress` is live status, not the final answer (MANUAL activity strip).
- **Interruption** → `[interrupted]`, preserving the session.
- **Do not blindly kill long tasks**: `poll` with a live process → pending.
- **Visible budget controls** (`_RUN_RETRIES` / `max_iterations`); the harness imposes no wall-clock limit on an entire turn.

## Reference-level explanation

### Code anchors

- `harness_template/entry.py`: `_emit_progress`, `_stdout_lock`, envelope unwrapping, interrupt, tracer→steps.
- `harness/launcher.py`: `begin`/`poll`/`control`, `last_steps`/`last_progress` (see 0019 for relaxed reception).
- `MANUAL.md`: division of responsibilities between activity strip + terminal reply.

### Contract table

| Concern | Contract for this group |
|---|---|
| Completion | Unwrap down to `output.result` |
| Internal process | `steps` is observation-only |
| In flight | Multiple `progress` lines, without replacing reply |
| Slow sessions | begin/poll/control, pending for live processes |
| Interruption | `[interrupted]` |

### DAG

```mermaid
graph LR
  T1[T1 Protocol and decomposition]
  T2[T2 smoke + MANUAL]
```

### Interfaces

0012 consumes progress/poll; 0019 relaxes unknown side channels and peek; 0014 requires MANUAL to be synchronized when external behavior changes.

## Drawbacks

Envelope unwrapping is heuristic; progress and steps may duplicate information; interruption depends on nexau `force_stop` checkpoints.

## Rationale and alternatives

- Blind wall-clock kills can terminate legitimate long tasks.
- Appending progress to reply would contaminate the user experience.
- Reception of unknown side channels belongs to 0019; this group owns the seed emission contract.

## Prior art

CLAUDE.md black-box contract; stdio JSONL; long-task poll/heartbeat.

## Unresolved questions

Should the seed provide built-in “partial results” on timeout? What progress granularity and truncation should be used?

## Future possibilities

Seed behavior that “returns in-flight status on timeout”; reconstruct timelines from progress/steps in the observation layer.
