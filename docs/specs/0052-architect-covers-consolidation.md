---
number: "0052"
title: "Architect Proposal Coverage and Duplicate Consolidation Responsibilities"
issue: 0
slug: architect-covers-consolidation
summary: "The Architect determines which triage/proposals are absorbed by structural proposals based on the complete ProposalView; covers is the sole simplification directive, directly merging and closing covered sources after the target proposal is created. The Owner is responsible only for delivery routing."
tasks:
  - id: T1
    title: "Architect covers merge semantics and state transitions"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/ahe_beta/demand/issue_schema.py
      - backend/ahe_beta/demand/role_contract.py
    scope: "Define covers produced by the Architect as an absorption directive. After a structural proposal is successfully created, merge and close covered sources still on the report/proposal plane and record merged-into; proposals not covered by covers remain independent. Do not add Owner semantic review or acceptance mapping validation."
    acceptance: "After Architect creates a structural proposal with covers, covered triage/proposal items transition to closed+merged, while the structural proposal remains proposal; proposals without covers or not covered remain open; covers still references only open sources visible in the current round."
  - id: T2
    title: "Return Owner to delivery-only routing"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/owner.py
      - backend/ahe_beta/demand/agent_contract.py
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
    scope: "Remove Owner's responsibility for covers and semantic merging; Owner handles only handoff admission, retaining the existing exact-duplicate compatibility path without taking responsibility for cross-proposal deduplication. Synchronize model-visible semantics."
    acceptance: "The Owner prompt no longer claims that covers only represents relationships or that Owner performs merges; the Architect prompt makes clear that covers absorbs and closes sources; Owner does not close sources based on covers relationships."
  - id: T3
    title: "Coverage merging regression tests and specification verification"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/tests/loop/test_architect.py
      - backend/tests/demand/test_owner.py
      - backend/tests/demand/test_role_contract.py
      - backend/tests/demand/test_agent_contract.py
      - docs/specs/0052-architect-covers-consolidation.md
    scope: "Update Architect/Owner behavior tests and tool/schema drift checks, and complete spec validate/render/graph and Python static checks."
    acceptance: "Tests for coverage merging, retention of uncovered items, Owner-only routing, and prompt/schema semantics pass; pytest, ruff, spec validate/render/graph, and git diff --check pass."
---

# 0052 · Architect Proposal Coverage and Duplicate Merging Responsibilities

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a nine-section rust-RFC overview for the group. -->

## Summary

On the requirements side, Owner no longer re-adjudicates semantic duplication between proposals. Architect/Architect reads the unified
ProposalView and already has context across triage, Divergent, and existing structural proposals, so it uses
`covers` to specify which open reports/proposals the current structural proposal absorbs. After the structural proposal is successfully created, the driver
directly merges and closes the open sources in `covers` and writes an `merged-into` audit line. Owner is responsible only for handing
still-open proposals off to OpenAgents; no second semantic review, acceptance mapping, or manual confirmation is added.

## Motivation

The current uncommitted role-governance changes turn Owner into a Delivery Router while downgrading `covers` to relationship metadata
used only for planning displays. This leaves a practical gap: even when a proposal produced by Triage and a structural proposal produced
by Architect clearly duplicate each other, no role is responsible for removing them from the set of independent deliveries; Owner also
hands off unlisted proposals by default. The result is duplicate work entering OpenAgents, with decision-making authority misaligned with the role that has the most context.

This group restores only the necessary merging loop, without restoring Owner's product-review responsibilities. The goal is to make “whether a source is absorbed by a structural proposal”
a semantic decision owned solely by Architect, while preserving existing platform capabilities such as issue state transitions, audit relationships, and failure isolation.

## Guide-level explanation

A round on the requirements side follows these rules:

1. Triage, Divergent, and Architect generate proposals; Architect uses the ProposalView visible in the current round
   to form structural proposals.
2. When Architect submits a structural proposal, `covers` lists the open source issue numbers it has decided to absorb. `covers` is no longer
   a suggestion for “Owner to consider,” but a merge decision Architect has already made.
3. The driver first creates the structural proposal and obtains its target issue number, then applies the existing `MERGED` state transition to
   sources in `covers` that are still on the report/proposal planes, and appends `merged-into: #target-issue-number`.
4. Sources not included in `covers` remain open; Owner subsequently hands these proposals (including the new structural proposal)
   off directly. Owner does not reassess value direction, root causes, or implementation approaches.

This group does not allow an issue to be “partially closed”: an individual source is either merged in full and closed or retained as an independent delivery item.
Parts requiring independent acceptance should not be included in `covers`; if splitting is needed later, first split the source into multiple issues.

## Reference-level explanation

### Responsibilities

| Role | Merging responsibilities |
|---|---|
| Triage | Normalizes only the current report; does not deduplicate across issues |
| Divergent | Discovers capability proposals; does not close existing issues |
| Architect/Architect | Decides on structural proposals and their `covers` sources based on the full ProposalView |
| Owner | Only packages open proposals for handoff; does not consume `covers` for semantic merging |
| driver/tracker | Executes post-creation state transitions and audit recording according to `covers` submitted by Architect |

### `covers` and State

`covers: #n #m` is the only machine-readable line in the structural proposal body. The Architect driver continues to filter out issue numbers that do not exist, are already
closed, or are not on the report/proposal planes, preventing new proposals from referencing objects that can no longer be merged. After the target
is created, valid sources use the existing `transition_issue(state="closed", labels=...)` to transition to `MERGED`; the target
proposal itself remains on the `PROPOSAL` plane, awaiting Owner handoff. The merge relationship is preserved through
`merged-into: #target` in source comments; existing issue bodies and historical comments are not deleted.

Merge operations should execute deterministically by source issue number and allow repeated runs to skip issues that are no longer open sources; failure of an individual transition
must not affect the target proposal or other sources, and failures should be recorded in Architect outcomes/events rather than silently swallowed.
This is reliable state transition handling in the existing tracker, not a new semantic validation layer.

### Owner Boundaries

Owner's model input and submit schema do not need new merge fields. Owner does not read `covers` to close sources;
proposals not listed by the model are still handed off directly under the existing fail-open rules. If the existing exact-duplicate
compatibility path is retained, it is merely mechanical compatibility for historical data and does not grant Owner semantic deduplication authority; new cross-issue semantic merges
are triggered exclusively by Architect's `covers`.

## Drawbacks

Incorrect Architect judgments directly affect which issues continue as independent deliveries; this is the accepted cost of returning decision-making authority to the role
with global context. To keep the workflow simple, this group adds neither acceptance mapping nor a second model review, so structural proposals must
fully express the goals of the covered sources. `covers` can only close sources in full; it cannot express that only part of the acceptance requirements
of a single issue have been taken over.

## Rationale and alternatives

Architect is chosen over Owner because Architect sees open triage/proposal items, ready references,
experience trends, and run aggregates together, making it best suited to judge common mechanisms and duplication relationships; Owner's context and responsibilities have already narrowed to delivery
routing. Reusing `covers` instead of adding an `consolidates` field reduces the synchronization surface across schemas, prompts,
state parsing, and frontend fields.

“Owner continues semantic deduplication” is rejected: it would reintroduce overlapping responsibilities and give both the generator and delivery router
product-level merge authority. Automatic text deduplication is rejected as the primary path: exact title/body matches identify only a narrow class of mechanical duplicates
and cannot address semantic coverage between triage and structural proposals. A new “partially closed” state is rejected: it would spread into planes,
Owner filtering, OpenAgents intake, and the UI, and obscure the delivery boundary of an issue.

## Prior art

Spec-0029 previously placed `covers` cascading merges at Owner admission; Spec-0042 later turned Owner into a lightweight
router and temporarily defined `covers` as a relationship. 0052 restores the behavior in which “structural proposals can absorb sources,” but moves the semantic
decision point earlier to Architect, retaining the three-plane labels and the existing machine representations `MERGED`/`merged-into`.

## Unresolved questions

This group does not yet address how to arbitrate conflicting structural proposals targeting the same source when multiple Architects run in parallel; whether merged
sources should be collapsed by default in the frontend; or how to display priorities across multiple structural proposals. These questions do not change
this group's minimal semantics: `covers` in a single Architect output is the basis for closure.

## Future possibilities

If partial acceptance needs to be retained in the future, or a single issue needs to be jointly taken over by multiple structural proposals, an explicit issue-splitting/sub-acceptance model can be added
without changing Architect's semantic responsibilities. Any new state or machine-readable line must first update issue_schema,
OpenAgents intake, web projections, and the corresponding spec; “partial closure” must not remain implicit in `covers`.
