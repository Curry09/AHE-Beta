---
number: "0028"
title: "divergent PM + gate: parallel product candidate channel and promotion review"
issue: 0
slug: divergent-pm-gate
summary: "Add a parallel product candidate channel alongside the 0025 triage funnel: divergent PM and architect use the same signals in parallel to persist unclaimable divergent candidates; Architect.gate_once performs semantic promotion (promote→feature+triaged / hold / drop). Disabled by default with N_DIVERGENTS=0; dev claiming strictly excludes divergent."
tasks:
  - id: T1
    title: "issue_schema: divergent/gate-dropped labels and executable backlog criteria"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/issue_schema.py
      - backend/tests/demand/test_issue_schema.py
    scope: "Add DIVERGENT / GATE_DROPPED constants. Insert GATE_DROPPED (terminal state) and DIVERGENT (unclaimable candidate) into the triage_status priority order. is_backlog_by_labels / is_executable_backlog exclude divergent and gate-dropped to prevent candidates from flooding the executable backlog curve."
    acceptance: "Constants are importable; triage_status returns the correct single value for labels containing divergent/gate-dropped; executable backlog determination is correct for divergent and for feature+triaged after promotion; unit tests cover these cases."
  - id: T2
    title: "Divergent driver + agent_defs/divergent_pm: persist unclaimable product candidates"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/agent_defs/divergent_pm/
      - backend/scripts/preview_divergent_pm_rounds.py
      - backend/scripts/preview_gate_on_divergent.py
      - backend/tests/demand/test_divergent_gate.py
    scope: "Create Divergent.propose_once: use inputs analogous to architect (triaged/RFC/backlog candidates/user experience/runtime_agg), run the divergent_pm agent, validate RFC fields, then create_issue(labels=[divergent, round-N]), with a hard cap of 3 per round. Do not apply triaged/RFC labels. agent_defs includes jail+timeline tools; the prompt emphasizes product opportunity discovery and prohibits overfitting to the task description. Include a preview script (FakeTracker / real LLM) to facilitate offline gate verification."
    acceptance: "Candidates carry divergent and not triaged; entries exceeding the cap are truncated; entries with invalid fields are not persisted; dev cannot claim them; stub unit tests cover creation/truncation/unclaimability."
  - id: T3
    title: "Architect.gate_once: promote/hold/drop semantic promotion"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/architect.py
    scope: "Add gate_once to Architect: skip when there are no candidates; otherwise run a promotion task with a short budget (candidates + RFCs + user experience, with timeline as needed). Parse disposition: promote→remove divergent and add feature+triaged; hold→leave unchanged; drop→close with gate-dropped. Candidates absent from the decisions default to hold. Reuse the same agent_defs/architect; do not create a fourth role definition."
    acceptance: "promote enters the claimable set; hold remains divergent; drop closes with gate-dropped; do not call the LLM when there are no candidates; default to hold on parse failure; unit tests (see the T2 test file) cover all three paths."
  - id: T4
    title: "Orchestration wiring: d2 architect∥divergent → d3 gate; roster/run disabled by default"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/loop/roster.py
      - backend/ahe_beta/loop/live.py
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/experiment/controllers/swebench.py
      - backend/tests/loop/test_roster.py
    scope: "orchestrator: after triage, run architect∥divergent in parallel using ThreadPool, then call gate_once for each architect (if there is no architect, candidates accumulate). Add the divergent key to roster, DEFAULT=0, overridden by N_DIVERGENTS. run.py and the SWE script construct and inject Divergent according to the roster. Insert divergent into live ROLE_ORDER. Disabled by default, preserving existing closed-loop costs."
    acceptance: "Order: triage→(architect∥divergent)→gate→dev; N_DIVERGENTS=0 creates no divergent instance; =1 injects and runs it; roster unit tests cover this; live ordering includes divergent."
  - id: T5
    title: "Hard-exclude divergent candidates from dev claiming"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/dev/agentic_developer.py
      - backend/tests/dev/test_agentic_developer.py
    scope: "Add DIVERGENT not in labels to AgenticDeveloper._eligible so candidates are not claimed even if mistakenly labeled triaged. This provides a second safeguard alongside the schema's eligibility rules."
    acceptance: "An open issue labeled only divergent does not enter eligible; after promotion, feature+triaged makes it claimable; unit tests assert the exclusion."
---

# 0028 · divergent PM + gate: parallel product candidate channel and promotion review

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level nine-section rust-RFC overview. -->

## Summary

Alongside the 0025 triage→architect→dev funnel, add an **optional** product candidate channel:

1. **divergent PM** (new agent definition): runs **in parallel with architect on the same signals**, mines interactions for product opportunities that are perceptible to users, and creates open candidates labeled `divergent` (**not claimable**).
2. **gate** (logical Promoter, implemented as `Architect.gate_once`): performs semantic promotion on open divergent candidates: `promote`→remove `divergent`, add `feature`+`triaged`; `hold` remains backlogged; `drop`→close with `gate-dropped`.

The default is `N_DIVERGENTS=0` (zero additional cost); divergence and promotion run only when enabled. The dev claimable set hard-excludes `divergent` to prevent unreviewed candidates from going directly into trunk changes.

## Motivation

In actual SWE closed-loop runs, users almost never proactively report `feature`, and architect and dev are occupied by reliability debt (soft timeout closure, continuation, BrokenPipe). Even when product opportunities repeatedly appear in conversations as "user-devised procedures," they do not enter the claimable backlog. Binding product candidate discovery to architect would undermine its responsibility for selective root-cause synthesis. A **parallel channel that is disabled by default and claimable only after gating** is needed: divergence may extrapolate from "repeatedly devised procedures→product contract"; promotion handles deduplication and bandwidth filtering.

## Guide-level explanation

The d phase of a round becomes:

```
a(user) → d1 triage → d2 (architect ∥ divergent) → d3 gate → b(dev) → c
```

- Off (default): `N_DIVERGENTS=0`, behavior equivalent to 0025 (gate still runs, but skips immediately if there are no candidates).
- On: `N_DIVERGENTS=1` (usually paired with `N_ARCHITECTS≥1`; otherwise candidates can only accumulate until a gate with an architect runs in a later round).

For observability: `divergent` is excluded from the actionable backlog curve; after promotion, it enters the same claimable set as an ordinary feature.

## Reference-level explanation

### Labels and semantics (T1)

| Label | Meaning |
|------|------|
| `divergent` | Product candidate, open but not claimable |
| `gate-dropped` | Dropped by gate (closed) |
| After promote | Remove `divergent`, add `feature` + `triaged` (retain `round-*`) |

`triage_status` priority: `rejected` / `needs-info` / `gate-dropped` / `superseded` / `divergent` / `triaged` / `needs-triage`.
`is_backlog_by_labels` excludes `DIVERGENT` and `GATE_DROPPED`.

### Divergent (T2)

- Driver: `backend/ahe_beta/demand/divergent.py`
- Definition: `backend/agent_defs/divergent_pm/` (jail + timeline/beat/step, same tool surface as architect)
- Hard limit of 3 per round; body undergoes RFC five-gate field validation; labels only `[divergent, round-N?]`
- Offline preview: `preview_divergent_pm_rounds.py` / `preview_gate_on_divergent.py`

### Gate (T3)

- `Architect.gate_once`: inject full candidate text + open RFCs + experience score curve; prompt that `get_session_timeline` can be used as needed
- `complete_task` goes to `[{issue, disposition, note}]`; unlisted candidates default to hold
- Short `max_iterations` (≤80); no LLM call when there are no candidates

### Orchestration (T4)

- `Orchestrator`: `ThreadPoolExecutor` runs `propose_once` in parallel (architect∥divergent), then `gate_once` serially
- `roster`: `divergent` key, env `N_DIVERGENTS`
- `live._ROLE_ORDER`: user < triager < architect < divergent < developer

### Dev (T5)

- `_eligible`: `DIVERGENT not in labels` (a second safeguard alongside the schema)

### DAG

```
T1 → T2 ─┐
T1 → T3 ─┼→ T4
T1 → T5 ─┘
```

## Drawbacks

- One additional LLM call (divergent) + one gate per architect; disabled by default to avoid this cost.
- architect∥divergent write to the same Fake/Gitea tracker in parallel, relying on tracker thread safety (the existing Fake/Gitea call surface is small; accepted).
- gate reuses the architect definition, and systemprompt remains architect-oriented; the task message overrides the role, but in extreme cases the model may confuse responsibilities.

## Rationale and alternatives

| Approach | Tradeoffs |
|------|------|
| **This approach: parallel divergent + Architect.gate_once** | Does not dilute architect; promotion does not require a new full agent definition (Occam's razor); can be disabled by default |
| Put product discovery into architect | Undermines its selective approach; in practice, product opportunities are still drowned out by reliability |
| A fourth full Promoter agent_defs | Another set of prompt/tools/roster configuration; disproportionate to the benefit over gate's "same tool surface, different task" |
| divergent directly adds triaged | No deduplication or bandwidth gate; issues can easily flood and occupy N_DEVELOPERS |
| Mechanistic rule-based promotion (keywords/frequency) | Cannot distinguish "pure runtime overlap" from "user-perceptible product opportunities" |

## Prior art

- 0025: triage funnel and RFC claimable set—the present group extends it via a side channel without changing the semantics of the raw→triage→RFC main path.
- 0024: god-view timeline—divergent/gate gather evidence as needed; jail still prohibits direct reads of sessions/.
- Real software teams: PM proposal board → Promoter/TL review into sprint backlog.

## Unresolved questions

- Should gate require at least one timeline sample (currently "as needed")?
- With multiple architects, should gate run only once (currently: each architect runs it once; unambiguous when N_ARCHITECTS=1)?
- Should the frontend AgentBoard have a separate room color for divergent (roster already has the key; UI can follow later)?

## Future possibilities

- Project gate decision notes onto the observability dashboard.
- Evolve the divergent output kind from the RFC five gates to a lighter "product opportunity" field set.
- Integrate with the 0026 frontend: divergent / gate-dropped badges.
