---
number: "0054"
title: "User simulation goal-driven and revisable goal ledger"
issue: 0
slug: user-goal-driven-simulation
summary: "Add an explicit, revisable, and auditable goal ledger to user simulation: retain the original task identity in an undeletable B0, allow users to reformulate goals based on interaction and record the reasons; each round uses goal awareness, goal targeting, expected progress, and goal-effect impact to make action decisions, without treating goal state or subjective accept as objective acceptance."
tasks:
  - id: T1
    title: "Goal ledger and revision event model"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/goals.py
      - backend/tests/user/sim/test_goals.py
    scope: "Define Goal, GoalLedger, GoalEvent, GoalStatus, and GoalKind, as well as B0 initialization and the add/status/focus/revise/relax/withdraw operations; B0 must not be deleted or withdrawn, but its text/done_if may be revised with a reason; each revision stores before/after, the version, and evidence_refs."
    acceptance: "Initialize a B0 for every task; B0's initial_text/initial_done_if must be retained permanently; a revise without a reason or without an actual change has no effect; relax/withdraw must include a reason and cannot operate on B0; event seq values are continuous; snapshot and audit can independently restore the current state and the original state."
  - id: T2
    title: "Goal perception and action decisions"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/persona_client.py
      - backend/tests/user/sim/test_loop.py
      - backend/tests/user/sim/test_persona_client_agentic.py
    scope: "Inject the current goal snapshot into the judge/intent/act/waiting decision context; each round outputs goal_reading, target_goal_ids, expected_progress, goal_updates, and goal_effect; when goals change, reconstruct the subsequent decision context through a structured revise, without using keywords to infer whether the user should accept."
    acceptance: "Each round, the user can choose actions such as send_message, keep_waiting, interrupt, and accept based on the current goals; goal updates affect subsequent prompts; target_goal_ids may reference only known goals; abnormal action/goal fields produce only auditable warnings and do not turn ordinary formatting noise into evaluator_invalid; changes to B0 must not lose the original task."
  - id: T3
    title: "Separate goal outcomes from subjective and objective conclusions"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/models.py
      - backend/ahe_beta/user/session_store.py
      - backend/tests/test_models.py
      - backend/tests/user/test_session_store.py
    scope: "Store the goal ledger, goal acceptance, and per-round goal fields in Session/SimTrace/SimTurn; the goal terminal check reports only whether the user's subjective goal is closed and does not override interaction_status, objective_status, or lifecycle_status."
    acceptance: "New fields support JSON round-trip serialization; when fields are missing from an old session, read them safely as empty/unavailable; accept combined with an unclosed goal produces subjective_accept_unverified without forcibly preventing the user's action; objective failed/unverified and user accepted may coexist and remain distinguishable."
  - id: T4
    title: "Timeline projection and complete goal ledger auditing"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/demand/test_session_timeline.py
    scope: "Project goal summaries, goal-change events, per-round target/effect, and goal_audit into the design-facing timeline; retain the complete sim_trace as the authoritative persisted record, while the default projection provides only bounded, readable, source-attributed goal evidence and does not provide the complete persona raw."
    acceptance: "The timeline can distinguish B0's initial text, current text, and the revision reason for each revision; each round's goal targeting and actions are traceable to the turn; goal audit can report unknown goals, effect mismatches, missing reasons, and other issues; old timelines without goal fields remain compatible and are marked unavailable."
---

# 0054 · Goal-Driven User Simulation and a Revisable Goal Ledger

<!-- This file is the foundational contract for the user goal mechanism; 0055 defines how demand-side roles consume this evidence. -->

## Summary

User simulation previously determined its next action primarily from the current chat content and harness responses. This mechanism has two shortcomings:

1. What the user actually wants to accomplish can only be inferred from natural language after the fact;
2. There is no stable basis for decisions when the user changes a request, waits, interrupts, or accepts.

This spec makes “goals” explicit internal state in user simulation, but does not turn them into a rigid task list. Each session initializes a non-deletable goal identity `B0` from the original task; B0's text and completion criteria may be revised as the user's understanding changes, but every revision must record a reason and before/after.
In each turn, the user first forms perceptions and intent in light of the current goals, then decides on an action; action outcomes and goal state are persisted independently.

```text
Original task
  ↓ initialize B0
Current goal snapshot
  ↓ perceive / intent
target_goal_ids + expected_progress
  ↓ act / wait / interrupt / accept
goal_effect + optional goal_update
  ↓ append-only audit
```

This mechanism is a control layer for explaining and recording user behavior, not an objective acceptance checker or a state machine that forces the user to reach implementation or accept.

## Motivation

The old mechanism's `issue_artifact`, `verdict`, and `action` can record what the user said and ultimately did, but cannot consistently express “what progress the user considers valuable.” As a result, the same `accept` can mean either “the core requirement is genuinely satisfied” or merely “I don't want to wait anymore”; designers and auditors can only guess from long conversations.

Simply adding hard rules is not a solution either. If we require that “the user cannot accept without evidence for the goal,” acceptance logic will shape user simulation in reverse, bringing back excessive conservatism, toy-only operations, and frequent early exits. The goal mechanism should make user decisions more explainable, not make technical judgments on the user's behalf.

This spec therefore adopts three principles:

- **Original goals are traceable**: B0 cannot be deleted as an identity, preventing the user's original intent from becoming obscured by rewritten history;
- **Current goals can evolve**: users can reinterpret and revise goals during real interactions, but must record their reasons;
- **Subjective and objective are separate**: user goal closure and subjective accept are user evidence; an independent evaluator determines whether the code passes.

## Guide-level explanation

### B0 is not an immutable task lock

B0's “non-deletable” property applies only to its identity and history, not its text. The initial task is:

```json
{"goal_id": "B0", "text": "Fix the issue with apply_voi_lut", "status": "open"}
```

During interaction, the user discovers that the original issue is too vague and can revise it to:

```json
{
  "op": "revise",
  "goal_id": "B0",
  "text": "Fix the two bugs involving empty Rescale metadata and a corrupted LUTDescriptor, and add tests",
  "reason": "The original report mixed a question about the issue with an implementation request; it is now clear that a patch should be delivered"
}
```

The old text remains in the revision event. Revision does not automatically relax acceptance criteria; it merely clarifies the goal the user currently wants to advance.

### How each turn affects actions

The minimum decision chain for each turn is:

1. `goal_reading`: based on current observations, the user judges the goal to be unchanged, advancing, blocked, unclear, or complete, and explains why;
2. `target_goal_ids`: the user declares which goals they want to advance in this turn;
3. `expected_progress`: what kind of progress the user believes would improve these goals;
4. `goal_updates`: if understanding changes, revise/add/relax/withdraw goals with a reason;
5. `goal_effect`: the effect of this turn's action on the goal is advance, wait, close, close_with_reservations, abandon, or abandon_and_report.

These fields affect the persona's context and action selection in the next turn, but do not replace the action contract. `keep_waiting` remains waiting, `interrupt` remains interruption, and `accept` remains the user's subjective acceptance; goal fields cannot disguise one action as another.

### Multiple goals and anchoring risk

B0 is the original task anchor, but it is not the only content that always takes priority. Users can create request/core/optional goals such as `G1/G2` through `add` and use `focus` to indicate their current focus; they can `relax` or `withdraw` non-B0 goals with a reason. This expresses natural shifts such as “clarify the problem first, then fix the bug, and finally add tests.”

To prevent B0 anchoring:

- The prompt repeatedly includes only the current goal snapshot, not the full original text;
- The original B0 and revision history are retained in full only for audit/replay;
- `focus_goal_id` and `target_goal_ids` can temporarily point to new goals;
- B0 revisions must record a reason; silent overwrites are not allowed.

## Reference-level explanation

### Data model

`GoalLedger` stores the current goal set and append-only `GoalEvent`:

```text
Goal
  goal_id / text / kind / done_if / status / evidence_refs / version

GoalEvent
  seq / turn / op / goal_id / actor / reason / before / after / evidence_refs

GoalLedger
  baseline_id / focus_goal_id / goals / events
```

Goal states are `open`, `partial`, `met`, and `dropped`; goal types are `baseline`, `core`, `request`, and `optional`.
The goal check for a normal accept lists only baseline/core/request goals that have not yet closed as unresolved; optional goals do not prevent the user from completing.

### Update operations

| Operation | Effect | Constraints |
|---|---|---|
| `add` | Add a goal | Must have non-empty text; duplicate ids are ignored |
| `status` | Update open/partial/met | Save before/after and evidence |
| `focus` | Change the current focus goal | The goal must exist |
| `revise` | Change the meaning of text/done_if | Requires a reason and an actual change; allowed for B0 |
| `relax` | Lower requirements for a non-B0 goal | Requires a reason; may change done_if |
| `withdraw` | Abandon a non-B0 goal | Requires a reason; changes status to dropped |

`relax` and `withdraw` are observable user trade-offs, not the framework lowering the acceptance threshold on the user's behalf. `B0` always exists and can only be revised when necessary.

### Integration with user simulation stages

The goal snapshot enters the judge/intent/act and waiting paths, but fields in different stages still follow their stage-local schemas:

```text
judge: read the current goal and output goal_reading
intent: output the goal targets and expected_progress, proposing goal_update when necessary
act: output action, target_goal_ids, and goal_effect, submitting goal_update when necessary
waiting: decide whether to wait, interrupt, or continue communicating based on the current goal
terminal: record goal_acceptance, but do not modify the objective evaluator
```

Missing goal annotations in model output should not automatically produce a “completed” conclusion. The framework may record a warning or use empty values for compatibility with older models, but issues such as unauthorized actions, unknown goal ids, and revisions without reasons must be auditable.

### Goal acceptance and objective acceptance

The goal ledger provides `terminal_check`, which answers “does the user believe the goals have closed under their own current goals,” not “is the code correct.”
The following combinations are therefore all valid:

```text
user_goal_status = met
user_verdict = accepted
objective_status = failed
```

or:

```text
user_goal_status = partial
user_verdict = accepted_with_reservations
objective_status = passed
```

Downstream triage/PM may use these combinations to explain the user experience, but must not treat `goal_acceptance` as an evaluator result.

### Persistence and audit

`SimTurn` records at least:

```text
goal_before
goal_reading
target_goal_ids
expected_progress
goal_updates
goal_after
goal_effect
goal_field_audit
```

`SimTrace` and `Session` save the final `goal_ledger`, `goal_acceptance`, and `goal_audit`. `goal_audit` is an observational integrity check that reports problems such as a missing B0, illegal focus, non-contiguous seq, unknown goals, inconsistencies between effect and target, and revisions missing a reason; except for unauthorized actions, these annotation warnings are not directly converted into `evaluator_invalid`.

The complete raw persona trace remains the authority for post-hoc debugging, but the timeline used by subsequent design roles should project only limited goal evidence. Layered visibility and handoff for demand-side roles are constrained by Spec-0055.

## Rationale and alternatives

### Why B0 must be non-deletable

If only current goals are saved, the original task disappears when the user changes their request, leaving auditors unable to determine whether this was reasonable requirement clarification, user influence by the system, or the persona lowering its goals to finish. B0 retains its identity and initial snapshot, making “goal changes” inspectable events.

### Why B0 must be revisable

Real users often understand the original problem only after seeing the repository structure or assistant feedback. Prohibiting revisions would misclassify genuine clarification as deviation, forcing the persona to continue acting around text that is no longer accurate. Revisable does not mean unconstrained: a reason, before/after, and version are required.

### Why goals should not directly become a hard acceptance gate

A hard gate would turn user simulation into a test script that “requires fields to be satisfied before accept,” recreating artificial conservatism and premature abandonment. Goals are an explicit basis for decisions, not an objective quality judgment; the objective evaluator remains responsible for code results.

### Why not save only the final goals

Final goals can explain current actions, but not why the user changed goals. Append-only revision events preserve the user's current freedom while letting the design side determine whether goal drift came from genuinely new information, assistant behavior, or the persona relaxing its own requirements.

### Alternatives

- **Put goals only in the prompt without persisting them**: not auditable; rejected.
- **Copy the full goal history into the prompt every turn**: context grows linearly and anchors the user; rejected. The prompt contains only the current snapshot, while history stays in the trace.
- **Make B0 permanently immutable**: cannot express natural requirement clarification; rejected.
- **Have the framework automatically determine goal completion from chat keywords**: would hard-code semantic guesses as acceptance criteria; rejected.
- **Use goal state to override objective status**: would disguise subjective accept as a technical pass; rejected.

## Drawbacks

Goal fields increase structured output per turn and trace size; the model may produce vague `expected_progress` or invalid revisions. Mitigations are stage-local schemas, deterministic field audits, fixed-length projections, and offline replay, not keyword rules that forcibly perform cognition on the model's behalf.

B0 and its revisions may also cause users to focus excessively on the original task, especially in long-running tasks. Keeping only the current snapshot in the prompt, allowing focus/add/relax for non-baseline goals, and exposing revisions in the audit reduces anchoring without claiming to eliminate it entirely.

## Prior art

This mechanism reuses the existing user-sim judge → intent → act stages and Session.sim_trace persistence; action semantics and the independence of the objective evaluator and lifecycle follow Spec-0053; role-specific artifacts and evidence boundaries are governed by Spec-0043/0055. What is added here is the semantics and event model of user goal state, not a new execution runtime or acceptance checker.

## Validation plan

Offline replay and a small real end-to-end loop must verify at least:

1. The original task always initializes B0, and initial_text remains recoverable after a B0 revision;
2. Users can move from a vague goal to a clear request, or keep the goal unchanged when there is no new information;
3. wait/interrupt/accept choices can reference goals and expected progress, but goal fields do not force a particular action;
4. User accept does not override objective failed/unverified;
5. Reasons and before/after for revision, focus, relax, and withdraw are all traceable;
6. Old sessions without goal fields can be read compatibly and are explicitly marked unavailable;
7. Goal traces handed to demand-side roles do not carry complete persona raw or target project answers.

## Unresolved questions

- Whether to split long-term and current goals into two entities in the future or continue expressing them as B0 + subgoals; the first version keeps a single ledger to avoid adding hierarchy prematurely;
- Whether `goal_reading` should continue to be self-reported by the persona or an independent observer should be added in offline evaluation; the first version retains self-reporting but grants it no objective acceptance authority;
- The L1 summary limit for goal fields is calibrated against the real session distribution of Spec-0055; revision reasons cannot be deleted to save tokens.

## Future possibilities

After accumulating enough goal revisions and user behavior, it will be possible to measure the convergence rate from “vague issue → clear request,” triggers for goal changes, goal advancement rates for wait/interrupt, and a separation matrix for subjective accept versus the objective evaluator. These metrics are for evaluating user simulation and demand-side quality and should not in turn become fixed counts or hard-coded acceptance rules in the prompt.
