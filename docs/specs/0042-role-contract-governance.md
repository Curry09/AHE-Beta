---
number: "0042"
title: "Requirements-side role contract governance: unified terminology, normalized proposal projections, and reliable state transitions"
issue: 0
slug: role-contract-governance
summary: "Eliminate the coexistence of multiple generations of requirements-side workflow semantics, use formal terminology and the role responsibility matrix as authoritative definitions, establish a unified ProposalView, fix Triage/Architect/Owner state transitions and handoff boundaries, unify System Prompt, runtime message, and submit-tool contracts, and verify through cross-role tests and historical session replay."
tasks:
  - id: T1
    title: "Authoritative glossary, role responsibility matrix, and current workflow baseline"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0042-role-contract-governance.md
      - docs/specs/OVERVIEW.md
    scope: "Define formal terms including report/proposal/ready item, Triage/Divergent/Architect/Owner, progressive evidence retrieval, merge target, and covers; clarify each role's inputs, outputs, permissions, and prohibitions; this Spec explicitly supersedes the mechanical admission, old Triage persistence, old Owner input, and dev-stage descriptions in 0029 without rewriting historical decision records. 0052 further specifies Architect's authority to absorb covers."
    acceptance: "Each active concept has exactly one formal name and machine identifier; the role matrix covers the five requirements-side roles; superseded clauses of 0029 are listed; OVERVIEW points to this Spec as the current supplementary specification."
  - id: T2
    title: "Canonical ProposalView and normalized proposal versions"
    status: done
    priority: P0
    tags: []
    depends-on: [T1]
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/proposal_view.py
      - backend/ahe_beta/demand/architect.py
      - backend/ahe_beta/demand/divergent.py
      - backend/tests/demand/test_proposal_view.py
    scope: "Establish a single source of truth for task-independent normalized proposal projections, unifying titles, fields, labels, priorities, sources, and covers formats; Architect, Divergent, and Owner no longer independently concatenate and truncate bodies; raw reports and execution details are available only through comment audits or progressive timeline/beat/step retrieval."
    acceptance: "The three roles generate explicit projections suited to their responsibilities from the same ProposalView data model; Divergent references omit bodies, while Architect and Owner receive normalized bodies; default projections exclude raw reports and old workflow labels; the truncation policy exists in only one place; relevant unit tests pass."
  - id: T3
    title: "Reliable Triage normalization transitions and structured failure results"
    status: done
    priority: P0
    tags: []
    depends-on: [T1, T2]
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/triage.py
      - backend/ahe_beta/tracker/base.py
      - backend/ahe_beta/tracker/fake.py
      - backend/ahe_beta/tracker/gitea.py
      - backend/tests/demand/test_triage.py
      - backend/tests/tracker/test_fake.py
      - backend/tests/tracker/test_gitea.py
    scope: "Consolidate normalization updates to title/body/labels into a single retryable semantic tracker operation; Gitea executes steps through its EditIssue and labels endpoints, validates post-write state, and performs compensating rollback when a subsequent step fails observably; add failed to TriageOutcome, and never silently swallow core write exceptions; failure of the raw-report audit comment may degrade gracefully but must produce an observable warning; repeated execution must not nest content or damage original evidence."
    acceptance: "Fake implements this with a single in-memory update; Gitea uses Swagger-compliant stepwise calls, post-write validation, and compensating rollback; transition failures surface as dedicated errors containing the issue number, primary failure, rollback result, and observed state; comment failure does not change proposal state but is observable; relevant tests pass."
  - id: T4
    title: "Owner decision graph validation and reliable batch persistence"
    status: done
    priority: P0
    tags: []
    depends-on: [T1, T2]
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/owner.py
      - backend/tests/demand/test_owner.py
    scope: "Owner remains a lightweight delivery router; execute existing handoff state transitions, and do not extend the historical exact duplicate compatibility path into semantic deduplication; core persistence failures enter failed/held and are observable, and handoffs must not be silently lost."
    acceptance: "All open proposals enter handoff by default; invalid/failed handoff actions are observable; Owner does not close covers sources already handled by Architect again; relevant tests pass."
  - id: T5
    title: "Specialized Prompts for five roles and unified Tool contracts"
    status: done
    priority: P1
    tags: []
    depends-on: [T1, T2, T3, T4]
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/user_agent/prompt.md
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/triage_agent/tools/submit_triage.tool.yaml
      - backend/agent_defs/divergent_pm/tools/submit_divergent.tool.yaml
      - backend/agent_defs/architect/tools/submit_rfcs.tool.yaml
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
    scope: "System Prompt declares only role invariants, runtime messages carry only the current round's context, and Tool description describes only the invocation contract; unify formal terminology and remove retired workflow semantics; machine enums remain in English, with a fixed Chinese definition at first occurrence. Review user_agent file definitions and production simulator runtime assembly separately, without claiming they are the same active path."
    acceptance: "Requirements-side role definitions express only current responsibilities, input boundaries, and output contracts; System Prompt, runtime messages, and Tool description do not alter one another's workflow state; tool schema drift-guard and cross-role behavior tests pass."
  - id: T6
    title: "Cross-role contract tests, specification index, and historical session replay"
    status: done
    priority: P1
    tags: []
    depends-on: [T3, T4, T5]
    relates-to: []
    parallel: false
    files:
      - backend/tests/demand/test_role_contract_flow.py
      - tools/dev/replay/replay_roles_from_sessions.py
    scope: "Add cross-role behavior tests for report→Triage→Architect/Divergent projections→Owner; run design/loop/tracker regressions, and replay the existing 16 sessions through Owner, then stop without starting OpenAgents."
    acceptance: "Tests without API access verify that the exact set of issue numbers produced by Triage reaches Owner through Divergent references and Architect inputs; original problem statements do not enter default downstream context; invalid state graphs cannot be persisted; relevant tests, ruff, and diff-check all pass; real replays freeze the model, adjudications, and artifact checksums, verify that OpenAgents was not started, and explicitly state that they validate only the requirements direction rather than implementation readiness."
---

# 0042 · Demand-side Role Contract Governance

## Summary

Consolidate demand-side prompts and state semantics accumulated across multiple historical versions into a testable role contract system. The formal workflow is:
`report (raw report) → proposal (normalized proposal) → Owner → ready item (admitted work item)`. Triage handles individual
normalization, Divergent handles capability discovery based on session behavior, Architect handles cross-proposal structural synthesis and covers absorption decisions,
and Owner handles only batch handoff and prioritization. All roles read a unified ProposalView by default, with specific cases obtained through progressive evidence retrieval;
the detailed semantics of coverage merging are governed by Spec-0052.

## Motivation

The current Spec, System Prompt, runtime messages, Tool descriptions, Schema, and driver validation each retain different versions of
the role rules. Tests can prove that individual fields and labels work, but cannot prove that information actually reaches the next role, nor prevent legacy mechanical admission,
superseded, or post-development covers cascading semantics from reentering active prompts. Repeated local fixes have also produced three sets of proposal
formatting logic and risks of partial migration across multiple requests, requiring unified governance across contracts, state, and validation.

## Canonical terminology

| Formal term | Machine identifier | Definition |
|---|---|---|
| Raw report | `report` | Raw evidence produced by users, with no requirement for product abstraction |
| Normalized proposal | `proposal` | A task-independent requirement description that has not yet been admitted |
| Admitted work item | `ready` / `openagents` | Has passed Owner adjudication and may enter the delivery side |
| Report normalization | Triage | Classification, localization, title normalization, and field normalization for a single report |
| Capability discovery | Divergent | Identify gaps in product capabilities from session behavior that has not explicitly become a report |
| Structural synthesis | Architect | Identify cross-proposal structural root causes in the normalized backlog |
| Delivery routing | Owner | Batch admit/hold and prioritization; retain exact duplicate compatibility |
| Progressive evidence retrieval | timeline→beat→step | On-demand evidence access from summaries to execution details |

## Role boundaries

| Role | Default input | Output | Not responsible for |
|---|---|---|---|
| User Simulator | Scenarios, persona, harness responses | Raw reports and experience evaluations | Product abstraction and admission |
| Triage | A single report, corresponding session evidence, read-only harness | A normalized proposal or reject/needs_info | Cross-proposal duplicate detection |
| Divergent | Experience index, on-demand session evidence, ProposalView references | Capability proposals | Structural mechanism synthesis and admission |
| Architect | Full ProposalView, ready references, experience and run aggregates | Structural proposals and covers absorption decisions | Implementation design and downstream handoff |
| Owner | ProposalView, ready queue, experience index | admit/hold handoff (and exact duplicate compatibility) | Semantic deduplication, rediagnosis, architectural design, and code implementation |

## Superseded behavior

This Spec supersedes the following current descriptions in 0029: mechanical admission by Owner, mechanical demotion of `owner=0`, Triage writing normalized fields only in comments,
Owner not reading normalized bodies, Architect using the old triaged/superseded lifecycle, and the in-process dev phase. 0052 further
supersedes this Spec's old description that “covers is only a relationship/Owner handles semantic merging.” 0029 remains a historical decision record; active implementations and
the Overview follow 0032, 0042, and 0052.

## Reliability requirements

Core state transitions must not use silent `except Exception: pass`. Observability and audit comments may be best effort, but failures must be recorded in
an event or outcome. Multi-field issue updates must use retryable semantic operations provided by the tracker; when the backend cannot commit atomically, post-write verification is required, along with compensating rollback for observable failures in subsequent steps. These semantics are not equivalent to a transaction across HTTP requests; process termination between requests may leave an identifiable intermediate state, which callers must recover through idempotent retries, without claiming atomicity. Owner must validate the entire batch decision graph before performing
individual state transitions; failures must not produce dangling merge relationships.

## Reference-level explanation

The normalization boundary is at Triage: reports remain audit evidence, while the active backlog exposes only ProposalView. ProposalView is
the shared read-only data model for Architect, Divergent, and Owner, unifying body extraction, normalized metadata, and length limits; Divergent uses a compact deduplication projection without bodies, while Architect and Owner use the normalized body projection. At the write boundary, the tracker
provides two types of semantic operations: `update_issue` transitions title/body/labels, and `transition_issue` transitions state/labels. The Fake backend
can complete them atomically; Gitea 1.22 calls EditIssue and the labels endpoint separately, verifies the final state, and restores the pre-operation snapshot upon observable failures in subsequent steps. Gitea provides no transaction spanning the two endpoints, so the process termination window is handled through idempotent retries.
After Architect creates a structural proposal, the driver merges and closes report/proposal sources that are still open according to `covers` and writes
`merged-into`. Owner processes only proposals that remain open after merging; its own exact duplicate compatibility operations do not change
the state already established by `covers`.

## Compatibility

Legacy labels may be converted to the canonical model only at compatibility entry points in the tracker/issue projection and must not enter active role prompts.
Retain existing class names, environment variables, and submit tool names as API compatibility identifiers, while documentation and model-visible semantics consistently use the formal terminology.

## Rationale and alternatives

A prompt word blacklist was not adopted: vocabulary blacklists cover only known incidents and cannot prove that role responsibilities are correct. Professional wording is reviewed against authoritative terminology and responsibility boundaries,
while automated tests verify behavioral outcomes such as data isolation, state transitions, and decision graphs. Raw reports are no longer embedded in proposal bodies because
downstream batch reads increase case leakage and Token consumption; audit comments and progressive evidence tools still preserve full traceability. Per-field
tracker writes were not adopted because failures midway would produce partially migrated states that cannot be reliably retried.

## Validation

Validation has four layers: static contracts, unit state machines, cross-role closed loops, and real replays. Real replays reuse existing sessions and reports without consuming additional user
simulation calls; execution stops after Owner, and OpenAgents is not started.
