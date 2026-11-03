---
number: "0055"
title: "Goal-Aware Demand-Side Evidence Layers and Role Visibility"
issue: 0
slug: goal-aware-demand-evidence-boundaries
summary: "Without feeding complete user traces to demand-side roles, assemble user goal evolution, key interaction behaviors, and objective execution results into layered evidence with provenance; Triage receives bounded goal-aware evidence for the current report by default, the product PM retains a global view of user experience, and the Architect drills down only along proposal relationships, avoiding extra latency, cross-topic overfitting, and subjective accept being passed off as an objective pass."
tasks:
  - id: T1
    title: "Define goal-aware evidence packages and the layered reading contract"
    status: done
    priority: P0
    tags: []
    depends-on:
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/evidence_contract.py
      - backend/tests/demand/test_evidence_contract.py
    scope: "Define five evidence categories, report, user_goal, interaction, objective, and harness_source, and their provenance; define fields, character limits, invocation conditions, and role permissions for L0 report, L1 compact goal-aware summary, L2 timeline, L3 targeted beat, and L4 step/objective detail. L1 must be generated deterministically from persisted data, with no additional LLM calls."
    acceptance: "Every evidence field has a source, purpose, and maximum size; L1 contains no complete raw persona prompt, full stdout, target project source code, or benchmark oracle; missing fields are explicitly marked unavailable; contract unit tests cover compatibility with old sessions, empty goal ledgers, and truncation of overlong content."
  - id: T2
    title: "User feedback handoff and single-report input for Triage"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/triage.py
      - backend/ahe_beta/demand/role_contract.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/tools/get_session_timeline.tool.yaml
      - backend/tests/demand/test_triage.py
    scope: "Generate a handoff-ready user_feedback envelope at the end of the session; Triage's default input is the current report + L1 goal-aware summary + that session's feeling/termination reason. L2/L3 may be read on demand only to address evidence gaps in the current report. Preserve single-report isolation; do not expose other reports, global aggregates, or unrelated sessions to the same call."
    acceptance: "Triage can see B0's initial goal, current goals, revision before/after/reason, key target/action/effect, and explicit user feedback; each piece of evidence carries a session/turn source; it can return needs_info when evidence is unavailable; Triage does not treat goal met, user accept, or specific target project answers as an objective pass; the handoff can be consumed directly by triage without reparsing the entire chat."
  - id: T3
    title: "Product PM global experience input and product perspective boundaries"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/tools/get_session_timeline.tool.yaml
      - backend/tests/demand/test_divergent_gate.py
    scope: "The PM retains a cross-session experience index and global observation rights, but consumes L1/L2 summaries by default; the PM may reference sessions with or without reports and compare user goals, behaviors, experience tensions, and desired outcomes. The PM's artifact must not carry code locations, protocol fields, fixed thresholds, or implementation steps; the Owner decides whether something is a duplicate."
    acceptance: "PM input can express goal changes and user feedback rather than only feeling scores; the PM can reference multiple sessions, but every reference has an evidence source; artifact fields contain only user_goal, observed_behaviors, experience_tension, product_opportunity, desired_outcome, and evidence_sessions; sessions without reports are not rejected by novelty rules; the PM does not read L3/L4 by default because traces are too large."
  - id: T4
    title: "Architect proposal-relationship input and evidence drill-down constraints"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
      - 0054/T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/agent_defs/architect/systemprompt.md
      - backend/ahe_beta/demand/session_timeline.py
      - backend/tests/loop/test_architect.py
    scope: "By default, Architect takes ProposalView and proposal artifact relationships as input and performs L2/L3 verification only on session evidence for referenced proposals; it must not rediscover individual-issue requirements from raw sessions without provenance. The goal ledger serves as evidence of user intent for referenced proposals, not as an implementation specification or objective acceptance criteria."
    acceptance: "Each structural proposal must reference at least two proposals visible in the current round and explain their relationship; drill-down calls must include the source proposal and a rationale; unauthorized sessions, requirements without provenance, and specific implementation prescriptions must be rejected or converted into an observable revise; Architect's default token usage and tool call count must not grow linearly with the full trace volume."
  - id: T5
    title: "Role visibility, overfitting, and latency regression evaluation"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - tools/dev/audit/evaluate_role_traces.py
      - backend/tests/demand/test_role_contract_flow.py
    scope: "Add comparative replays using the old inputs and new layered inputs for the same batch of sessions, recording input tokens, tool call counts, wall-clock time, evidence citations, cross-task proper-noun leakage, and artifact semantic violations for each role separately; score users' subjective conclusions independently from objective evaluator results."
    acceptance: "The comparison report must demonstrate that Triage consumes evidence from only a single report, PM maintains a global product perspective, and Architect only synthesizes proposal relationships; the default L1 path must add no model calls; L2/L3 budget overruns or unauthorized reads must be observable and trigger degradation; target project filenames/answers in traces must not enter generic proposal fields; the combination of `accept` and objective failed/unverified must not be rated as an overall success."
---

# 0055 · Goal-Aware Evidence Levels and Role Visibility on the Demand Side

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG). The body contains first principles, role boundaries, and implementation contracts. -->

## Summary

The user goal mechanism solves an existing problem: traces reveal why users wait, interrupt, modify requests, or accept results. But feeding the complete
`sim_trace` directly to every demand-side role has two adverse effects: more context and tool calls slow down Triage; filenames,
commands, and test answers from the target project enter the model's context, causing roles to overfit to individual tasks.

This spec interprets “reading traces” as an input contract with sourced, layered user evidence read on demand, rather than “reading all logs”:

```text
raw report
  + L1 Goal-awareness summary (default, deterministically generated)
  + L2 Timeline relevant to the current issue (on demand)
  + L3 Activity for a particular beat (on demand)
  + L4 Single-step/objective details (strictly on demand)
```

Triage, the product PM, and Architect use different levels and scopes of visibility. This brings the goal mechanism into the demand side without turning all three roles back into the same
Agent that “reads all logs and then provides a technical solution.”

## First principles

### 1. Triage asks, “What exactly does this report describe?”

Triage must turn user observations into factual boundaries, user impact, and uncertainties, and determine whether the problem belongs to the harness. To answer this question,
it needs to know at least:

- What the user originally wanted to accomplish;
- What the user actually did during the interaction;
- Whether the goal was revised, and why;
- Why the user continued waiting, interrupted, provided feedback, or accepted;
- Which statements are subjective user judgments and which are objective execution evidence.

Therefore, denying Triage all visibility into user traces is wrong; it would degrade into a language editor for issue bodies, prone to producing generic prompt
suggestions or incorrectly treating user misunderstandings as harness defects.

But Triage does not need the full trace. It is responsible neither for product synthesis across issues nor for replaying every tool step. The default L1 summary is sufficient to determine
whether further investigation is needed; drilling down into L2/L3 is permitted only when there is an explicit evidence gap.

### 2. The product PM asks, “What product opportunities does the user experience imply?”

The PM needs a broader observation scope than Triage: it must be able to compare multiple sessions and see recurring behaviors without formal issues; otherwise, it can only
make local fixes based on existing reports. The PM therefore needs to retain a global session index and experience evidence across sessions.

The PM's boundary is not “no trace visibility,” but “even when traces are visible, express findings only in product language”: user goals, observed behavior, experience tensions,
product opportunities, and desired outcomes. Filenames, protocols, fixed timeouts, keyword thresholds, and implementation steps do not belong in PM artifacts.

### 3. Architect asks, “What common mechanisms exist among existing proposals?”

Architect is neither a second PM nor a larger Triage. It should first use ProposalView as its object of analysis, then drill down into sessions along the evidence references
already declared by proposals. If it can freely read all raw sessions, it will bypass the intermediate outputs of Triage/PM and rediscover requirements without
sources, undermining both role separation and the audit chain.

Architect therefore retains visibility across proposals, but raw traces are gated by references: sessions without a source proposal must remain
invisible and cannot directly serve as the basis for from-architect proposals.

## Motivation

Past demand-side inputs had two opposing problems. Without any user behavior evidence, Triage could only rewrite free-text reports as generic
“please improve the prompt” requests; giving roles the complete `sim_trace`, tool stdout, and target project details instead slowed calls and encouraged
implementations tailored to individual tasks. The new user goal mechanism turns intent into structured facts, but without visibility boundaries, it can still be incorrectly
treated as an acceptance result, or cause all roles to read the same large evidence bundle and become homogeneous again.

This spec therefore addresses three root causes together:

1. User intent is absent from demand-side handoffs, leaving “why the user waited/interrupted/changed their request” unexplained;
2. Trace visibility is not layered by role responsibility, causing latency, context contamination, and overfitting;
3. Subjective user accept, goal status, and the objective evaluator are not kept separate by source in the inputs.

The approach of “giving Triage no traces at all” is rejected because it would reduce factual investigation to textual guesswork; the approach of “letting every role see all raw
traces” is also rejected because it violates the three distinct cognitive boundaries of individual-report triage, a product-wide view, and proposal relationships.

### 4. Goal status is not an acceptance conclusion

`goal_ledger`, `target_goal_ids`, `expected_progress`, and `goal_effect` provide evidence of user intent and behavior;
`goal_acceptance` is a subjective user conclusion; the objective evaluator provides an objective technical conclusion. These three categories must be partitioned in the evidence bundle and carry provenance:

```text
user_goal_status = met
user_verdict = accepted
objective_status = failed | unverified
```

This is a valid and important outcome and must not be flattened into “overall success.” The goal mechanism explains user behavior; it does not replace tests or add
unsupported facts to proposals.

## Evidence envelope

The input to each role invocation is represented by a logical `EvidenceEnvelope`. It may be persisted as a handoff or projected into the prompt,
but roles must not be allowed to discover unauthorized data through relative paths or unrestricted shell access.

```json
{
  "report": {"issue_id": "...", "title": "...", "body": "...", "labels": [...]},
  "user_evidence": {
    "session_id": "...",
    "goal_summary": {
      "baseline_id": "B0",
      "initial": "...",
      "current": "...",
      "revisions": [{"before": "...", "after": "...", "reason": "..."}],
      "unresolved": ["..."]
    },
    "key_events": [
      {"turn": 0, "action": "send_message", "target_goal_ids": ["B0"], "effect": "advance"},
      {"turn": 4, "action": "interrupt", "target_goal_ids": ["B0"], "effect": "wait"}
    ],
    "feedback": "...",
    "user_outcome": "accepted"
  },
  "objective_evidence": {"status": "unverified", "source": "evaluator"},
  "harness_source": {"repo": "read-only", "ref": "..."}
}
```

Field meanings must remain partitioned: `user_evidence` describes the user's goals and experience, `objective_evidence` describes executable results,
and `harness_source` describes only the scope of harness source code readable by the role. No role may rewrite one category of evidence as another.

## Evidence levels and budgets

### L0 · raw report

The current issue's title/body/labels. These are the user's subjective report and context, not a confirmed root cause.

### L1 · compact goal-aware summary

Projected deterministically from SessionStore and the sim trace, without additional model calls. Includes:

- B0 initial goal, current goal, and revision summary;
- The before/after/reason for each revision;
- Key user actions, their target goals, and effects;
- Explicit user feedback and reasons for interrupt/waiting/termination;
- feeling, final request state, and existing objective summaries (if already produced at that stage).

L1 has fixed limits on characters and event counts, excluding complete persona prompts, raw LLM output, full stdout, complete tool bodies, and target project source code.

### L2 · projected timeline

User-visible interactions, harness responses, and activity summaries for the session associated with the current report. Triage may read this when it needs to confirm factual boundaries;
the PM uses it to explain experiences across sessions; Architect drills down only through referenced proposals.

### L3 · targeted beat

Harness activity and stop kind for a particular turn. Calls must specify the turn and reason, and their results must be recorded. This level distinguishes local causes such as “the assistant is exploring,”
“the request is queued,” and “a tool reported an error”; it is not default context.

### L4 · step/objective detail

The body of an individual step, test results, or evaluator details. Allowed only when L2/L3 cannot explain the current evidence gap, and must retain the source, reason for the call, and
truncation status. L4 must not put target project answers, patches, or proprietary paths into general proposal fields.

## Role visibility matrix

| Role | Default input | Readable on demand | Explicitly prohibited | Output focus |
|---|---|---|---|---|
| Triage | Current report + current session L1 + feeling/termination reason | Current session L2/L3; necessary L4 objective summaries | Other reports, global aggregates, complete target project source code, raw steps without justification | Facts, user impact, boundaries, evidence, uncertainties |
| Product PM / Divergent | Global experience index + multi-session L1/L2 + report/proposal index | Relevant session L3; L4 results when necessary | Code locations, protocol prescriptions, fixed thresholds, implementation steps | User goals, behavior, experience tensions, product opportunities, desired outcomes |
| Architect | ProposalView + proposal artifact relationships | Session L2/L3/L4 for referenced proposals | Raw sessions without sources, rewriting individual issues, discovering new requirements independently of proposals | Source relationships, shared tensions, structural directions, expected leverage |
| Owner | Role artifacts, ready queue, evidence references, and experience summaries | No unrestricted searching of source code or raw sessions | Rediagnosis, supplying facts on behalf of roles, treating accept as a pass | User value, evidence strength, scope cohesion, risk, adjudication |

“Default input” does not mean concatenating data into an infinitely long prompt; it means projecting permitted envelope fields into a role-specific schema. Tool calls
should be explicit, countable, and replayable.

## Reference-level explanation

### Architect's single protocol completion attempt

If the model returns text without structurally submitting proposals, the driver invokes the same role at most once more, reusing this round's
ready, proposal, trend, and runtime inputs, and appending a completion prompt to call only `submit_rfcs` to submit 0..n results.
A valid empty array also counts as successful completion, with no further retries; if submission is still absent, the result remains empty, and no artifact is inferred from prose.
This is a new role invocation and does not restore the model's internal reasoning from the previous invocation; “submit only” is an instruction constraint, not a hard restriction on tool permissions.
Retry exceptions still propagate upward, and temporary prompt state is reset in finally. This behavior belongs to T4, with tests covering no retry in the normal case,
successful recovery, at most two invocations, and reset after exceptions; it does not change evidence access scope or proposal admission criteria.

### Input construction and permission enforcement

SessionStore is the authoritative source of user evidence. At session completion, a deterministic projector first generates L1 and writes goal ledger revisions, key
actions, and feedback events into the handoff; it does not call a model or infer goals from target project source code. At runtime, roles obtain the envelope through the bound evidence store,
and the workspace jail continues to allow demand-side roles to read only the harness repository, preventing discovery of sessions,
harness_runs, or host directories through relative paths.

Triage still processes only one report at a time. Its initial message contains only the report and an explanation that “evidence for the current report can be accessed through tools”; L1
may be injected with the handoff as a short deterministic summary, while L2/L3/L4 must be retrieved on demand through tools. If call arguments point to another report, an unrelated session,
or an unreferenced proposal, the tool returns an unauthorized-access violation rather than silently providing data.

The PM's panoramic view does not mean full raw text: the global index uses L1, and L2 is retrieved only for relevant sessions when comparing experiences; it must not put specific
files or commands from the target project into product artifacts. Architect first receives ProposalView; evidence drill-down must carry a source proposal, separating
“broad visibility” from “the ability to invent new requirements without a basis.”

### Artifact and state projection

Triage, PM, and Architect continue to use the dedicated artifact schemas from Spec-0043. This spec does not add a shortcut field stating “the goal is satisfied, so
this proposal qualifies”: goal fields serve only as evidence references or user goal context. The user handoff's `user_outcome`,
`goal_acceptance`, and objective evaluator results are projected separately, and no role may overwrite them.

### Observability metrics

Each role invocation records input evidence levels, input character/token estimates, tool call counts, the level of each drill-down, elapsed time, evidence references, truncation, and
unauthorized-access denials. The evaluator also outputs artifact semantic violations, proprietary-term leakage, and conflicts between subjective and objective conclusions. Metrics are used only for regression testing and tuning;
model-reported numbers do not determine whether a check passes.

## Triage artifact and handoff

The handoff generated at the end of a user session is the formal handoff interface for the subsequent closed loop; Triage is not required to infer user intent again from session files. It
contains at least:

```text
source_report
session_id
goal_summary
feedback_events
user_outcome
objective_evidence (if already produced)
evidence_refs
```

Triage artifacts continue to use the factual language of Spec-0043:

```text
reported_problem
user_impact
scope_boundary
evidence
uncertainties
implementation_target
```

Here, `goal_summary` is evidence, not a new implementation field; `implementation_target` may only be harness, outside_harness, or
uncertain. Target project issue identifiers, filenames, and proprietary parameters may appear in `evidence_refs`, but must not enter task-independent
`proposal_title`, general boundaries, or implementation plans.

Triage follows a fixed investigation order:

```text
L0/L1 → Assess evidence gaps → L2 → L3 when necessary → L4 in very rare cases
```

When evidence is insufficient, produce `needs_info`; adding more logs must not be used to force a definitive conclusion.

## Latency and overfitting safeguards

### Latency control

- L1 is generated deterministically by code, without additional persona/triage LLM calls;
- Triage does not automatically call the full timeline for every report;
- Each L2/L3/L4 call writes an `evidence_access` event recording level, turn, reason, character count, and elapsed time;
- Each role has input token, tool call count, and wall-clock budgets; once a limit is reached, return the existing evidence or `needs_info`;
- The PM's cross-session index uses short summaries rather than concatenating L2 from all sessions;
- Architect deduplicates evidence drill-down by the set of proposal references, avoiding repeated retrieval of the same trace as proposal counts grow.

### Overfitting control

- Roles may obtain evidence only through EvidenceEnvelope and registered tools; they cannot read `data/sessions`, `harness_runs`, or host paths;
- Target project source code is not an implementation workspace for demand-side roles; harness source code remains a separate, read-only object of evolution;
- General proposal fields prohibit target project names, issue numbers, proprietary filenames, answers, fixed timeouts, and keyword thresholds;
- Specific cases remain only in original reports and evidence with sources;
- Triage must explicitly record uncertainties; PM/Architect semantic artifacts are checked against role-specific contracts, not judged by an incident keyword blacklist;
- `user accept`, `goal met`, private pytest, and evaluator results are always recorded separately.

## Rationale and alternatives

### Why Triage must see traces

Triage's responsibility is to frame user observations as facts, impact, boundaries, and uncertainties. With only a raw report, it cannot distinguish “unclear user goals,”
“the harness lacks the capability,” “the harness responds slowly,” and “the target project itself failed.” User behavior and goal revisions in the current session are
firsthand evidence for these judgments, so completely hiding traces directly harms Triage accuracy.

### Why Triage cannot receive complete traces

Triage is not responsible for architecture design across tasks. Complete tool bodies, target project paths, and test answers increase both token cost and overfitting probability, and encourage
it to turn case-specific fixes into general harness proposals. The progressive L1/L2/L3/L4 levels give it enough evidence to explain behavior first, then allow justified
drill-down; this is more auditable than repeating a large log in the prompt.

### Why PM and Architect Cannot Share the Same Input

PM's value comes from comparing the overall experience and observing unreported behavior, so it needs a broader view than Triage; Architect's value comes from the structural relationships among existing proposals, so it must be constrained by source proposals. Giving both access to the full trace would turn PM into a technical investigator and allow Architect to bypass Triage/PM and rediscover requirements. The role distinction must be reflected in input scope and artifacts, not merely written into the system prompt.

### Alternatives

- **Attach only the goal summary to the raw issue**: Low cost, but without user actions and harness activity it cannot explain the reasons for waiting or interruption; retain it as part of L1, but it cannot be the complete solution.
- **Let all roles read the complete `sim_trace`**: Simple to implement, but the context, leakage, and overfitting risks are unacceptable; rejected.
- **Let only PM see the trace**: Preserves product observation, but forces Triage back to guessing from text; rejected.
- **Let the model decide whether to read any trace**: Permissions and invocation costs cannot be audited; rejected. Use a role matrix, tool-parameter validation, and budgets instead.

## Interaction with existing specs

- Spec-0024 provides god-view persistence and progressive timeline/beat/step drill-down; this spec adds goal-aware L1 and a role permission matrix;
- Spec-0025 defines the raw report → Triage → Architect funnel; this spec adds user feedback handoff without changing role responsibilities;
- Spec-0029 preserves one report per Triage, different views for PM/Architect, and unique Owner admission; this spec makes “different views” concrete as machine-checkable input levels;
- Spec-0043 defines role-specific artifacts; this spec does not rewrite artifact semantics, but only specifies their evidence sources and visibility;
- Spec-0053 defines independent lifecycles for user actions, goals, and objective outcomes; this spec projects those outcomes into the demand-facing evidence package without allowing the demand side to reassess lifecycle state.

## Validation plan

Validation is not successful merely because the JSON is valid. At minimum, compare the following results:

1. **Input boundaries**: Triage does not mix reports; PM can reference unreported sessions; Architect does not accept sessions without sources; Owner cannot freely read code.
2. **Goal utilization**: The goal revision can explain interrupts, waiting, and explicit feedback; roles do not treat goal status as objective acceptance.
3. **Latency**: The default L1 path adds no model calls; L2/L3 call counts and character volumes are bounded; wall-clock time and token usage for sessions in the same batch do not grow linearly without bound.
4. **Generalization**: Task-specific files, commands, and answers may appear only in evidence references and must not appear in generic proposal fields.
5. **Conclusion separation**: `accepted + objective_failed`, `accepted + objective_unverified`, and `abandoned + objective_passed` can each be audited independently and are not compressed into one overall status.

Offline replay should use the same frozen session set to compare the old input with the new envelope, and output each role's input tokens, tool calls, duration, artifact, evidence refs, and violations. Only when both behavioral quality and evidence boundaries are satisfied may the system enter the complete closed-loop experiment.

## Unresolved questions

- The event count and character limit for L1 need to be calibrated against the existing session distribution, but the reason for the goal revision must not be removed to save tokens;
- Whether L4 allows Triage to read the evaluator's single-step body should be decided according to the target project's leakage risk; by default, it should receive only structured results;
- Sessions without a historical goal ledger use `goal_evidence=unavailable`; B0 must not be backfilled or fabricated by guessing;
- Whether the user feedback envelope is submitted directly as a Gitea comment or used only as role invocation input must be fixed during T2 implementation; both must retain the original session reference.
