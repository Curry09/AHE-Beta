---
number: "0056"
title: "Align terminal acceptance's atomic goal-ledger commit with Persona evidence"
issue: 0
slug: terminal-acceptance-alignment
summary: "Preserve the freedom of subjective user acceptance while keeping the goal ledger, Persona acceptance basis, and objective evaluation as three non-overlapping, auditable result surfaces; the close of a terminal action must be atomically committed to the goal ledger, but it does not replace the objective evaluator."
tasks:
  - id: T1
    title: "Atomic commit of terminal action and goal ledger"
    status: done
    priority: P0
    files:
      - backend/ahe_beta/user/sim/goals.py
      - backend/tests/user/sim/test_goals.py
    depends-on:
      - 0054/T4
    scope: "When accept/accept_with_reservations carries close/close_with_reservations, the framework commits the declared closed goals as met through status events with actor=terminal; it preserves the user action and does not forcibly change it to give_up because some goals remain open."
    acceptance: "The terminal TurnLog's goal_after is consistent with the final goal_ledger; B0 does not remain open merely because the model forgot an additional status update; unknown goals, action/effect mismatches, and empty goal_ids each produce an auditable warning."
  - id: T2
    title: "Align Persona acceptance basis with capability"
    status: done
    priority: P0
    files:
      - backend/ahe_beta/user/sim/prompt.py
      - backend/ahe_beta/user/sim/persona_client.py
    depends-on:
      - 0053/T4
    scope: "A terminal act can output acceptance_basis(mode, evidence_refs, reason). mode expresses subjective, independent, delegated, or waived; the framework generates expected/alignment observation fields according to D1/D3. This check does not block user acceptance or forcibly turn a strong Persona into a test bot."
    acceptance: "Subjective acceptance by blind/RUNS can be marked aligned; competent/expert or idiomatic/rigorous is marked weak without independent/delegated basis; missing fields cannot be fabricated as verified."
  - id: T3
    title: "Separate visible initial completion conditions from objective results"
    status: done
    priority: P0
    files:
      - backend/ahe_beta/models.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/demand/evidence_contract.py
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/demand/test_terminal_evidence.py
    depends-on:
      - 0051/T4
      - 0054/T2
    scope: "During B0 initialization, generate low-resolution done_if using only the user-visible task/reproduction, allowing the Persona to revise it later with a reason; the objective evaluator continues to run independently and derives accept_validity."
    acceptance: "The initial done_if does not read benchmark gold; user_outcome, goal_acceptance, terminal_audit, objective_evaluation, and accept_validity are persisted separately; evaluator skipped/unavailable remains unverified_accept."
  - id: T4
    title: "Terminal consistency regression"
    status: done
    priority: P0
    files:
      - backend/ahe_beta/user/sim/loop.py
      - backend/tests/user/sim/test_loop.py
      - backend/scripts/e2e-spec-0056-0057-user-semantics.sh
    depends-on:
      - T1
      - T2
      - T3
    scope: "Cover close commits, residual B0, strong Personas without evidence, objective skipped/failed, and compatibility with old sessions; do not add an automatic test gate."
    acceptance: "The same trace can simultaneously express persona accepted, persona_alignment weak, and objective unverified/failed; downstream consumers must not project any subjective field into objective pass."
---

## Summary

Subjective user acceptance, the goal ledger, the Persona acceptance basis, and independent technical verification are recorded on separate tracks. Explicit terminal closure is written to the goal event history, and default completion conditions use only the user-visible task statement; the framework audits the self-consistency of its fields without deciding for the user whether to accept or continue.

## Motivation

“ The user is willing to finish” and “the code is objectively correct” are two different facts; “whether this Persona made a judgment according to its own capabilities and acceptance criteria” is a third fact. The system must not allow any one of these fields to override either of the other two.

Therefore, `accept` remains a free action for the Persona. The framework only atomically commits explicit `goal_effect=close` as a subjective goal-ledger update and records terminal consistency and the acceptance basis; the independent evaluator continues to determine the technical result. Missing evidence can only reduce auditability or Persona alignment; it cannot forcibly make the user continue, nor can it fabricate a pass.

## Guide-level explanation

In `accept` or `accept_with_reservations`, the user declares the closure of `goal_effect` and may explain `acceptance_basis`. Subjective belief, self-checking, harness-delegated checking, and explicit waiver respectively express `subjective / independent / delegated / waived`; when none is declared, record `unreported`, and do not fabricate evidence.

For example, if the user explicitly closes B0 but does not send a separate `status=met` update, the framework should still preserve this closure declaration in the final trace rather than leaving contradictory action and goal states. Closing a goal does not mean that the code is necessarily correct.

## Reference-level explanation

```text
user_outcome         = whether the Persona chooses to end
goal_acceptance      = whether the Persona subjectively declares the current goal closed
terminal_audit       = whether actions, goal submissions, and acceptance rationale are consistent
objective_evaluation = technical result from the fresh evaluator
accept_validity      = derived relationship between user_outcome and objective_evaluation
```

`terminal_audit` is observational auditing; its warning does not change the action. `accept_validity` continues to fail closed: when objective evaluation has not run, has failed, timed out, or is stale, it must not be `valid_accept`.

The initial `done_if` is a low-resolution heuristic: select generic completion conditions based only on reproduction steps, expected behavior, or test descriptions in the task statement; do not read the gold patch or hidden tests. The user may revise it with a reason; it is not a formal acceptance specification covering every meaning of the task.

`GoalLedger.commit_terminal_effect` appends an `actor=terminal` event for an explicit close and records the before and after states.
Action/effect mismatches, empty goal lists, and unknown goals only produce warnings; the final turn's `goal_after` is synchronized with the ledger. `audit_acceptance_basis` records expected, alignment, references, and warnings according to capability/acceptance thresholds; these are observation fields at the declaration layer and do not verify reference authenticity. Serialization and design-side evidence projection preserve these fields, and old sessions remain readable when fields are missing.

File ownership and DAG: T1 handles ledger/audit primitives; T2 handles prompts and input contracts; T3 handles persistence and evidence projection; T4 integrates the main loop and performs regression. See the frontmatter for specific files; T4 depends on T1–T3. Offline validation entry point:
`backend/scripts/e2e-spec-0056-0057-user-semantics.sh`, without starting the model, container, or benchmark evaluator.

## Drawbacks

Explicit fields add a small amount of context; heuristic completion conditions may be overly general; the existence of evidence references does not mean that the evidence has been verified.
Consumers must read warnings and objective status together and must not calculate technical success solely from `met` or alignment.

## Rationale and alternatives

Reject the approach of “forbid accept when evidence is missing”: it would change the user's intent and turn the goal ledger into an engineering gate.
We also do not adopt an approach that modifies B0 only in the final summary, because it cannot reconstruct each terminal declaration.
Appending events and performing independent audits preserve subjective choices while exposing evidence gaps.

## Prior art

Continue the existing approach of revisable goal ledgers, semantic action catalogs, and independent recording of fresh evaluator results.

## Unresolved questions

There are no open items requiring a decision for this submission; acceptance quality from real models still requires trace review and cannot be inferred from unit tests alone.

## Future possibilities

The expression of completion conditions and the readability of evidence references can be studied further, but subjective acceptance must not be converted into an objective pass.
