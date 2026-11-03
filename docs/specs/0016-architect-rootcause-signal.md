---
number: "0016"
title: "Architect root-cause signals + code-reading efficiency + runtime aggregation"
issue: 0
slug: architect-rootcause-signal
summary: "Add the Architect's missing \"why is it bad\" root-cause signal, mechanism-level comparison numbers, and code-reading efficiency: ① feed the experience reason to the Architect alongside the score; ② search_file_content + search before reading; ③ runtime_agg scans the most recent N Session sessions after the fact, aggregates the proportions of 0-step/timeouts/interruptions/errors and the budget knobs, and injects them into propose_once (observation only, no attribution). Locations: architect/ + user/session_store.py + agent_defs/architect/."
tasks:
  - id: T1
    title: "Use the experience reason as a root-cause signal for the Architect"
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/ahe_beta/user/session_store.py
      - backend/tests/loop/test_architect.py
    scope: "Add the qualitative signal missing from the Architect's root-cause diagnosis. SessionStore: when save() writes index.json, persist FeelingScore.reason (the \"why\" behind the user's score) alongside score/created_at. architect: _feeling_trend reads (created_at, score, reason) triples from the index, and _format_trend incorporates reason into the experience trend for the Architect—scores only say \"bad,\" while reason says where it is bad. In particular, pain points such as \"latency/waiting itself\" (waiting a long time before failure / nothing happening for ages / waiting until abandonment) are experience killers and appear only in reason, never in the score level; the Architect must use reason to first determine whether the issue is a bug or a feature, then send the requirement action to dev, rather than misreading \"latency\" as \"not delivered\" and adding recovery logic (negative example). The Architect's position is product + architecture: starting from the premise of solving the user's problem, inspect experience (score + reason) → analyze the root cause → submit requirements to dev."
    acceptance: "After SessionStore.save, every index.json entry includes a reason field; _feeling_trend returns triples containing reason, and _format_trend outputs each score together with its reason; the Architect's input shows the corresponding \"why\" for each round's score. Unit tests cover: reason persisted in the index, triples read back by trend, reason included in formatting, and compatibility with a missing default reason."
  - id: T2
    title: "Architect grep + search before reading to reduce code-reading overhead"
    status: pending
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/architect/agent.yaml
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/architect/tools/search_file_content.tool.yaml
    scope: "Previously, the Architect had no shell and could only read entire large files with read_file (entry.py is hundreds of lines), immediately exhausting the iteration budget (once reaching max-iter). Give it the search_file_content(grep) tool and establish a \"search before reading\" rule in the system prompt: for large files such as entry.py, first use search_file_content with keywords such as timeout|retry|_CALL_TIMEOUT|_RUN_RETRIES|max_iter to jump to relevant locations, then read only that section with read_file (using offset/limit) for close inspection; agents/main.md is usually short and can be read directly. When reading the system, first determine whether the root cause lies at the behavior layer (main.md) or the mechanism layer (entry.py/agent.yaml); do not assert a mechanism root cause without reading the mechanism source. Reuse the search_file_content.tool.yaml from the dev tool definition."
    acceptance: "architect/agent.yaml mounts read_file/list_directory/search_file_content; the system prompt includes the \"search before reading; do not read the entire file\" rule and keyword examples; search_file_content.tool.yaml has a valid schema and can be loaded. In simulation, the Architect uses grep → focused reading for large files instead of reading them in full, and no longer exhausts iterations through full-file reading."
  - id: T3
    title: "Runtime behavior aggregation runtime_agg: feed mechanism-level observation numbers to the Architect"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/runtime_agg.py
      - backend/tests/loop/test_runtime_agg.py
    scope: "Add the mechanism-level comparison numbers claimed by the Architect prompt but never injected. Add architect/runtime_agg.py: after the fact, scan the harness rounds from the most recent N sessions in SessionStore (default 50), aggregating task-independent metrics—the proportion of 0-step rounds, the proportion of timeout/interrupted/harness_error replies, the proportion of tool_error steps, median steps, and the Harness repository budget knobs (_CALL_TIMEOUT/_RUN_RETRIES/max_iterations, read-only constants/configuration; do not import harness). format_runtime_agg renders RuntimeAgg as a readable block; architect.propose_once (owned by T1's architect.py) injects it alongside the experience trend. This performs observation aggregation only and no attribution (attribution remains for the Architect to infer from reason). Do not change the Session schema or protocol, and do not touch the user-side simulation path."
    acceptance: "aggregate_runtime returns zero counts for an empty repository; when sessions exist, it correctly counts 0-step/timeout/interrupted/error/tool_error and median_steps; it can read the budget knobs from the Harness repository (None if absent). format_runtime_agg outputs proportions and a budget line. propose_once input includes this block. Unit tests cover: empty repository, mixed reply classification, budget parsing, and formatting."
---

# 0016 · Architect Root-Cause Signals + Code-Reading Efficiency + Runtime Aggregation

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a nine-section group-level rust-RFC overview. -->

## Summary

Add the signals and code-reading efficiency required for the Architect's diagnosis:

1. **Experience reason**—persist it in the index alongside the score and feed it into the trend (latency-related pain points appear only in reason);
2. **Search before reading**—`search_file_content` + discipline, avoiding iteration burn from reading entire files;
3. **runtime_agg**—after the fact, scan the most recent N Session sessions, aggregate the proportions of 0-step rounds/timeouts/interruptions/errors, median steps, and budget knobs, and inject them into `propose_once` (**observation only, no attribution**).

Locations: `architect/` + `session_store` + `agent_defs/architect/`.

## Motivation

Looking only at scores misses latency root causes and leads to incorrect recovery requirements; without grep, reading entire files burns the budget; the prompt claims to have "0-step proportion/timeout proportion" but never injects the numbers, and when reason is compressed to "timed out again," it is impossible to distinguish forgetting from a budget that is too tight—hence runtime_agg.

## Guide-level explanation

- The trend includes reason; determine the root cause of latency before submitting requirements.
- Search large files first, then read the relevant sections closely.
- Add a side-channel block of **mechanism-level comparison numbers** (runtime_agg); the Architect performs attribution itself.

## Reference-level explanation

### Code anchors

- `session_store`: the index includes reason; `architect.py`: trend + injection into `format_runtime_agg(aggregate_runtime(...))`.
- `runtime_agg.py`: `RuntimeAgg`, most recent N=50, coarse reply labels, and reading `_CALL_TIMEOUT`/`_RUN_RETRIES`/`max_iterations` from the repository.
- architect agent.yaml / systemprompt / search_file_content.

### Signal flow

```
FeelingScore{score,reason} → index
Turn.steps + reply + budget controls → runtime_agg
        ↓
propose_once: curve(reason) + runtime block → classify as bug/feature → propose requirements
```

### DAG

```mermaid
graph LR
  T1[T1 Feed reason to the architect]
  T2[T2 grep + search before reading]
  T3[T3 runtime_agg]
  T1 --> T3
```

### File allocation

- **T1**: `architect.py`, `session_store.py`, `test_architect.py` (including the propose injection call site)
- **T2**: architect agent definition and grep tool
- **T3**: `runtime_agg.py`, `test_runtime_agg.py`

## Drawbacks

reason noise; runtime_agg uses coarse labels rather than task semantics; grep still depends on keyword selection.

## Rationale and alternatives

- Scores only: latency is invisible.
- Structured reason labels: the MVP feeds the raw text first.
- Do not inject numbers and rely on the prompt to pretend that metrics exist: disproven.

## Prior art

0005 FeelingScore; 0012/0013 latency and steps side channels.

## Unresolved questions

Whether reason should be labeled; whether to structure waiting sequences and include them in agg.

## Future possibilities

Display agg in a dashboard; aggregate pain points by label.
