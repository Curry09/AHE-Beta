---
number: "0012"
title: "Making the user's waiting experience realistic: heartbeat-driven initiative · visible progress · task-dependent patience"
issue: 0
slug: user-wait-realism
summary: "Upgrade the user agent's “idle waiting” when facing a slow/stalled harness to a perceptible, realistic user experience: after a heartbeat wakes it during a wait, it decides through judge→intent→act; the waiting bar displays live progress and prior_activity; keep_waiting consumes patience only when there is no new progress; WAIT_GAP and ATTRIBUTION. Initial patience varies with task load. Waiting menus and internal/external IO semantics follow 0022 (this group no longer defines invoke_control)."
tasks:
  - id: T1
    title: "Initiative while waiting: heartbeat wake-ups + visible progress + consistent waiting decay rules"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0022/T1
        type: note
    parallel: false
    files:
      - backend/tests/user/sim/test_loop.py
    scope: "Real subprocesses wake via begin/poll heartbeats; waiting context is supplied with progress/prior_activity; keep_waiting consumes patience according to patience_decay only when there is no new_progress; _MAX_HEARTBEATS provides a fallback limit; scoring ATTRIBUTION. See 0022 for current definitions of menu structure, emit_message, open intent/gap, and interrupt attribution wording (this group no longer maintains invoke_control). This Task's file list retains only test_loop, which is not claimed exclusively by 0022; the main implementation is in 0022/T1 and this group's T2."
    acceptance: "Only real subprocesses are supervised; keep_waiting deducts patience when there is no new progress and does not deduct it when there is progress; patience exhaustion/the heartbeat limit can lead to give_up; the waiting prompt includes progress/prior_activity; scoring includes ATTRIBUTION. Cover these together with the 0022 menu unit tests."
  - id: T2
    title: "State patience model: task-load-based initial variation + personality-based decay coefficient"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/state.py
      - backend/tests/user/sim/test_state.py
    scope: "Upgrade patience across turns from a fixed baseline to two levels: “personality tier + slight task-load variation”: init_state obtains the patience baseline from D4.3; during the initial OPENING, apply_task_load adds TASK_LOAD_DELTA based on task_load, clamped to >=1. Coef.patience_decay is derived from personality and shared by apply_verdict and heartbeat keep_waiting."
    acceptance: "For the same persona, initial patience for quick is strictly lower than for epic; the variation is applied only once during OPENING and clamped to >=1; patience_decay is 2 for impatient personalities and otherwise 1; apply_verdict rules are covered by unit tests."
---

# 0012 · Realistic User Waiting Experience: Heartbeat Agency · Visible Progress · Task-Dependent Patience

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level nine-section rust-RFC overview. -->

## Summary

Upgrade the user agent's behavior when facing a slow/stalled harness from “silently waiting until timeout” to realistic mechanisms:

1. **Agency while waiting**—follow **judge → intent → act** after a heartbeat wake-up.
2. **Visible progress**—feed `last_progress` and cross-turn `prior_activity` into the waiting prompt.
3. **Conditional patience depletion**—`keep_waiting` reduces patience **only when this heartbeat has no new_progress**.
4. **WAIT_GAP + ATTRIBUTION**—record a gap when intent is not fulfilled; do not blame the harness for user-initiated interruption.
5. **Task-dependent initial patience**—personality level + slight variation based on task size.

**See 0022 for the current definitions of the waiting menu, internal/external channels, open intent, `emit_message`, and interrupt attribution** (this group no longer describes `invoke_control` / closed intent enums).

## Motivation

The turn-based approach in 0005 compresses a slow harness into “one final judgment,” losing the user experience during the wait; initial patience is unrelated to task size. This group introduces heartbeats, visible progress, conditional patience depletion, and task-size variation. 0022 handles the replacement of the menu and IO boundaries.

## Guide-level explanation

- Heartbeats apply only to real subprocesses; not Fake/Scripted.
- Three decision hops; context includes elapsed seconds, history, MANUAL, progress, and prior_activity.
- `keep_waiting`: deplete patience only when there is no new progress; reaching the cap or exhausting patience → give up (see 0022 for specific action IDs).
- Initial patience: slight OPENING `task_load` variation.
- ATTRIBUTION: do not blame the harness for self-initiated interrupt.

## Reference-level explanation

### Anchors

- Current heartbeat orchestration and menu code: see **0022/T1** (`loop.py` / `prompt.py` / `launcher.py`).
- Patience model: `state.py` (T2 in this group).

### DAG

```mermaid
graph LR
  T1[T1 Heartbeat and decay definitions]
  T2[T2 Patience model]
```

### Adjacent groups

- **0022**: internal/external windows, waiting menu, open intent, `report_issue`, slash.
- **0013 / 0019/T1**: progress emission and side-channel reception.

## Drawbacks

Applies only to real subprocesses; three mode makes more LLM calls; constants are empirical values.

## Rationale and alternatives

Heartbeats + conditional patience depletion are preferable to “give up immediately on timeout” or “deduct patience on every keep.” Menu replacement is delegated to 0022 rather than redesigned in this group.

## Prior art

0005; long-running agent heartbeat; 0022 IO boundaries.

## Unresolved questions

Whether to recalibrate the thresholds and `TASK_LOAD_DELTA`.

## Future possibilities

Feed structured waiting sequences into 0016; adjust heartbeat frequency based on emotion.
