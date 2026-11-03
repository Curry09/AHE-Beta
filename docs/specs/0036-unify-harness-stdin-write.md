---
number: "0036"
title: "Unified stdin write entry point in the seam layer: remove the begin/emit split, use reply as a soft wake-up"
issue: 0
slug: unify-harness-stdin-write
summary: "The seam layer's begin/emit_message split leaks “formal turn vs. interjection” semantics and ties stdout reads to in_flight, causing keep_waiting to spin without doing work after reply. This group changes the model to: a single write entry point for user messages (always writing to stdin, like the CC input box); the harness decides blocking/queuing; the platform uses type=reply as a soft wake-up (waiting for the next reply or timeout), and poll does not depend on write-path flags; interrupt remains an out-of-band channel. Changes are concentrated in launcher/loop/connector and tests, without changing the shape of the harness wire protocol."
tasks:
  - id: T1
    title: "Write the 0036 live snapshot"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0036-unify-harness-stdin-write.md
    scope: "Clearly document the motivation: the begin/emit split and in_flight blocking reads; select a unified write entry point + reply soft wake-up; define the boundaries with 0022/0035; explicitly state that the utterance FIFO ledger is not a design constraint."
    acceptance: "spec validate passes; the body includes Summary/Motivation/Reference-level explanation/Rationale and alternatives; the DAG and file assignments are clear."
  - id: T2
    title: "launcher: unified write entry point + poll independent of write flags"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/harness/launcher.py
      - backend/tests/harness/test_launcher.py
    scope: "Unify user messages under write_message (or an equivalent single API): always write stdin message frames, without distinguishing begin/emit; remove branches that require or prohibit in_flight for writes. poll(timeout) only reads stdout to wait for the next type=reply (recording progress/status and continuing to wait), without requiring a write flag; return pending on timeout. Retain the interrupt/shutdown out-of-band channels. Change blocking send() to “write + poll until reply.” Remove experimental parallel-wait APIs (if any)."
    acceptance: "Unit tests: two consecutive message writes require no fabricated turn lock between them; polling again after reply can receive a subsequent reply; idle poll times out with pending; progress/status are recorded while waiting for reply; no regressions in the interrupt path."
  - id: T3
    title: "loop: main/heartbeat message sends use unified writes; keep_waiting→poll"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/tests/user/sim/test_loop.py
      - backend/tests/user/sim/test_heartbeat.py
    scope: "send_message in both the main loop and heartbeat uses the unified write entry point; the wait loop uses reply as a soft wake-up (after writing, poll until reply or the heartbeat timer fires). Main-loop keep_waiting: poll for the next reply, return None on timeout, and still drain side-channel events when there is no reply. Do not make the utterance FIFO ledger a prerequisite for wake-ups or the write path. Adding accept to the heartbeat menu is not mandatory in this round (it may be listed under Unresolved)."
    acceptance: "Route/integration tests: keep_waiting after reply can receive a subsequent reply; heartbeat interjections and main message sends both use the same write entry point; idle keep_waiting is a safe no-op; existing heartbeat paths pass."
  - id: T4
    title: "Align connector and INTERFACE with unified writes"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/harness/connector.py
      - backend/ahe_beta/harness/INTERFACE.md
      - backend/tests/harness/test_connector.py
    scope: "connector exposes unified writes and poll/drain; documentation states: stdin messages are unified, reply is a soft wake-up label, and interrupt is out-of-band; the compatibility layer may retain old method names as aliases, but their semantics point to unified writes."
    acceptance: "connector unit tests cover unified writes and poll; INTERFACE.md matches the implementation; no descriptions of a begin/emit semantic split remain (or they are explicitly marked as deprecated aliases)."
---

# 0036 · Unified stdin write entry point in the seam layer: remove the begin/emit split, use reply as a soft wake-up

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in 9 rust-RFC sections. -->

## Summary

This group consolidates the seam layer's I/O model for the harness, bringing it closer to a human-operated CLI (the input box is always available): **a single stdin write entry point for user messages**; **the harness decides blocking/queuing**; the platform uses `type=reply` on stdout as a **soft wake-up** (the user decides again), without constraining the harness through platform-private “formal turn / interjection” semantics.

It also closes a concrete gap in the current implementation: after `reply`, main-loop `keep_waiting` spins without doing work because of a write-path flag—reading stdout (`poll`) no longer depends on that flag. The shape of the harness wire protocol remains unchanged (still message / progress / status / reply / interrupt), and the TurnLog utterance ledger is not treated as a design constraint.

## Motivation

### Split write entry points leak product semantics

The current launcher provides `begin` and `emit_message`:

- `begin`: the platform “formally starts a turn,” sets an internal flag, and subsequently uses `poll` to wait for the corresponding `reply`
- `emit_message`: allows another write only when the flag is true, called an “in-turn interjection”

To the harness, both are the same kind of stdin message. The split was invented by the seam layer for wait-loop bookkeeping, leaking “formal turn vs. interjection” into the platform API and hindering the harness from evolving toward the CC-style model where “the input box is always available.”

### The read path is tied to a write flag

The flag is cleared upon receiving `reply`; if main-loop `keep_waiting` requires the flag to be true before `poll`, then **it cannot wait for the next reply after a reply** (for example, subsequent output from queued work). 0035 already specifies reply ≠ idle and the semantics of `keep_waiting`, but does not firmly require decoupling the read path from the write flag; this group implements that as well.

## Guide-level explanation

For user simulation:

```text
Send message → uniformly write to stdin
             → poll / heartbeat: progress and status visible, continue waiting
             → see type=reply → soft wake-up, main loop calls decide again
             → can send another message / keep_waiting (poll again) / interrupt / terminate
```

For the harness: it sees only a sequence of messages and optional interrupts; it decides how to queue and when to emit replies.

## Reference-level explanation

### Writing

- A single API (possibly named `write_message`; the old `begin`/`emit_message` may remain as deprecated aliases, both meaning to write a stdin message frame).
- **No longer** require “no turn in progress to write” or “a turn must be in progress to write.”
- Multiple consecutive writes are valid; queuing/discarding/parallel processing is harness behavior, expressed through stdout-visible events.

### Reading and soft wake-up

- `poll(timeout)`: read stdout; record `progress`/`status` and similar items as visible events and continue waiting; `type=reply` (and the legacy `reply` field) → return that text; timeout → `pending`.
- Do **not** make a write-path flag a prerequisite for `poll`.
- Main-loop `keep_waiting`: call `poll`; reply received → use it as `harness_output` for the next turn; timeout → `None`, with `drain_visible_events` still available.
- The wait loop (from writing until the next reply): timed heartbeats remain available; `send_message` within a heartbeat uses the same write entry point.

### Out-of-band channels

- `interrupt` / `shutdown` remain out-of-band channels (0022), not ordinary messages.

### Non-goals

- Do not change to “wake the main decide on every progress event” (too costly).
- Adding `accept` to the heartbeat menu is not mandatory in this round (a subsequent group may address it).
- Do not require deleting TurnLog observation fields; do not make them prerequisites for writing/reading either.
- Do not change the queued/status product behavior of the v0 harness (0035/T4 is already implemented).

### DAG and file assignments

```text
T1 Live snapshot
 ├→ T2 launcher: unified write + poll
 │    ├→ T3 loop wiring
 │    └→ T4 connector / INTERFACE
```

| Task | Files |
|---|---|
| T1 | `docs/specs/0036-unify-harness-stdin-write.md` |
| T2 | `harness/launcher.py`, `tests/harness/test_launcher.py` |
| T3 | `user/sim/loop.py`, `tests/user/sim/test_loop.py`, `test_heartbeat.py` |
| T4 | `harness/connector.py`, `INTERFACE.md`, `tests/harness/test_connector.py` |

## Drawbacks

- After removing “a single begin in flight,” the platform no longer uses a flag to prevent “logical double turns”; if a caller mistakenly writes consecutively, handling relies on harness and user behavior (consistent with a human-operated CLI).
- Old tests/probes asserting “concurrent begin is prohibited” or “emit requires in_flight” must be rewritten.
- While compatibility aliases exist in the short term, documentation must avoid continuing to propagate the split semantics.

## Rationale and alternatives

### Why unify writes instead of only relaxing poll

Relaxing `poll` alone can fix `keep_waiting` spinning without doing work, but leaves the begin/emit split and the need to explain “interjections” during evolution. Unified writes remove the leaked semantics in one step and naturally include read-path decoupling.

### Why choose type=reply for soft wake-up

It matches the current harness wire protocol and controls decide frequency; progress/status still enter perception, but do not trigger a full main decision each time. If “wake on any visible event” is needed in the future, extend `poll` to return kind rather than introducing a third write API.

### Why retain interrupt as an out-of-band channel

In a human-operated CLI, Ctrl+C and typing are not the same channel; the internal/external windows in 0022 still apply.

## Prior art

- 0022: internal/external channels; this group retains interrupt and tightens the ordinary message write path.
- 0035: stdout-visible events, `keep_waiting`, reply ≠ idle; this group implements the read path and removes the write split.
- Claude Code / Codex: the input box is always available; input while busy receives product-side feedback, rather than a client-fabricated “interjection type.”

## Unresolved questions

- Whether to add `accept` to the heartbeat wait menu / fully align it with the main loop's action space.
- Whether to retain an internal read-only counter of “expectations since the last reply” for observation, or completely delete the write flag.
- The minimal surface of a Fake/Scripted harness: whether to implement only unified writes + blocking `send`.

## Future possibilities

- Event coalescing window: combine multiple progress events over a short interval before deciding, further reducing costs.
- When the harness voluntarily outputs `reply_to`, use it only for display, not platform inference.
- Further merge the main/heartbeat loops into a single event loop (not required by this group).

