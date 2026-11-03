---
number: "0043"
title: "Demand-side role cognitive contracts: role-specific artifact language and behavioral quality gates"
issue: 0
slug: role-cognitive-contracts
summary: "Establish distinct cognitive tasks, role-specific artifact contracts, and executable quality gates for Triage, product PM, Architect, and Owner on top of shared evidence, preventing multiple roles from degenerating into the same kind of technical analysis Agent."
tasks:
  - id: T1
    title: "Role artifact models and shared quality gate contracts"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/role_contract.py
      - backend/ahe_beta/demand/agent_contract.py
      - backend/ahe_beta/demand/submit_tools.py
      - backend/tests/demand/test_role_contract.py
      - backend/tests/demand/test_agent_contract.py
    scope: "Define role-specific artifact schemas for the four roles, source references, deterministic invariants, and structured revise/hold violations; retain the canonical proposal storage projection, but no longer have all four roles share the same cognitive form."
    acceptance: "The four role schemas are explicitly distinct in their fields and semantic purposes; machine-checkable invariants cover Triage's single-report source, PM's user/product perspective, Architect's multi-proposal relationships, and Owner's investment adjudication; invalid sources, unauthorized issue numbers, and missing relationships are rejected with structured violations; contract and submit binding unit tests pass."
  - id: T2
    title: "Triage single-report cognitive isolation and factual proposals"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/triage.py
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/tools/submit_triage.tool.yaml
      - backend/tests/demand/test_triage.py
    scope: "Change Triage scheduling to give each report an independent context; processing may run in parallel, but other reports/proposals must not be exposed in the same model call; artifacts define only reported facts, user impact, boundaries, evidence, and uncertainties, then project them into canonical proposals."
    acceptance: "The model input and tool scope for processing report A exclude B; Triage cannot submit fields for cross-issue duplicate detection, product opportunities, or implementation plans; batch execution remains concurrent, with outcomes precisely attributed to each issue; positive and negative behavioral tests and existing state transition tests pass."
  - id: T3
    title: "Product PM holistic insight contract"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/tools/submit_divergent.tool.yaml
      - backend/tests/demand/test_divergent_gate.py
    scope: "Retain PM's visibility into all experiences, existing reports/proposals, and on-demand session evidence, while changing its task to explaining user goals, behavior, experience contradictions, product opportunities, and desired outcomes; do not define PM as a scanner for unreported items or a deduplicator."
    acceptance: "PM may reference sessions with or without reports and may reframe existing problems; output must include user goals, observed behavior, experience contradictions, product opportunities, desired outcomes, and evidence references; it must not contain code locations, protocols, thresholds, or implementation steps; duplication is not grounds for rejection by the PM driver and is instead adjudicated by Owner; behavioral tests cover these positive and negative examples."
  - id: T4
    title: "Architect proposal relationship synthesis contract"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/agent_defs/architect/agent.yaml
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/architect/tools/submit_rfcs.tool.yaml
      - backend/tests/loop/test_architect.py
    scope: "Constrain Architect's cognitive focus to ProposalView relationships: declare source proposals, relationship types, shared contradictions, structural direction, and expected leverage; evidence drill-down may only validate relationships among already referenced proposals and must not independently discover new requirements outside proposals."
    acceptance: "Each structural artifact references at least two proposals visible in the current round and explains their relationship; nonexistent or unauthorized sources are rejected; single-proposal rewrites, derivations from sessions without source proposals, and concrete implementation prescriptions cannot be stored as from-architect; covers remains only a nonbinding recommendation to Owner; behavioral and persistence tests pass."
  - id: T5
    title: "Owner investment judgment and portfolio quality gates"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/owner.py
      - backend/agent_defs/owner/agent.yaml
      - backend/agent_defs/owner/systemprompt.md
      - backend/agent_defs/owner/tools/submit_admission.tool.yaml
      - backend/tests/demand/test_owner.py
    scope: "Owner judges user value, evidence strength, scope cohesion, overlap relationships, investment risk, and priority based only on role artifacts, the ready queue, experience summaries, and evidence references; remove unrestricted source code investigation and rediagnosis paths, while retaining admit/merge/decline/hold."
    acceptance: "Owner may adjudicate only inputs in the current batch and must provide a rationale for each item's value, evidence, scope, and overlap/risk; insufficient evidence, incohesive scope, or premature implementation detail must support observable hold/revise outcomes, and blanket approval without justification is prohibited; Owner does not invoke source code search or unrestricted timeline access for rediagnosis; decision graph and state transition regression tests pass."
  - id: T6
    title: "Cross-role behavioral evaluation and real replay acceptance"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/tests/demand/test_role_contract_flow.py
      - tools/dev/replay/replay_roles_from_sessions.py
      - tools/dev/audit/evaluate_role_traces.py
    scope: "Establish positive, negative, and boundary-violation examples for each role to verify that the same evidence produces different artifacts through four cognitive tasks; real replays freeze complete inputs, role artifacts, adjudications, and per-role compliance scores, without substituting valid JSON or successful state transitions for behavioral acceptance."
    acceptance: "Tests demonstrate that Triage does not mix issues, PM maintains a product perspective without novelty restrictions, Architect explains multi-proposal relationships, and Owner adjudicates the investment portfolio and blocks artifacts that exceed role boundaries; the trace evaluator outputs per-role contract violations and evidence locations; real replays run without OpenAgents and complete artifacts can be independently audited; ruff, relevant pytest tests, and spec validate/render/graph pass."
---

# 0043 · Demand-side Role Cognitive Contracts: Dedicated Artifact Languages and Behavioral Quality Gates

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in 9 rust-RFC sections. -->

## Summary

Before role-specific artifacts, demand-side roles shared similar evidence, tools, and `problem`/`root_cause`/`direction`/`acceptance` fields, so in real replays they repeatedly collapsed into
the same kind of Agent that “reads large volumes of sessions, repeats technical diagnosis, and proposes implementation plans.” This group elevates role distinctions from Prompt descriptions into three layers of
verifiable contracts: each role answers a different cognitive question, submits a different structured artifact, and passes a quality gate matched to its responsibilities.

The formal division of responsibilities is: Triage accurately defines a single report; the product PM comprehensively observes user behavior and explains product problems and opportunities; Architect
explains structural relationships and common mechanisms among existing proposals; Owner decides which directions merit investment and whether to admit, merge, decline, or
hold. PM is not reduced to an “unreported-item scanner,” nor are duplicates forcibly eliminated during generation; Owner retains authority over global portfolio decisions.

## Motivation

Spec 0042 unified report/proposal/ready states, ProposalView, migration reliability, and role names, but replays show that “correct data flow”
does not mean “correct role behavior.” In early replays, the product PM's proposals for a direct operation layer, raw output trustworthiness, and change reconciliation were close to expressions of product
capabilities; later replays gradually shifted toward technical prescriptions such as command fingerprints, fixed timeouts, and keyword triggers. Triage oscillated between preserving the original user task text and
designing solutions on behalf of the product; Architect sometimes produced structural judgments such as “exploration/execution separation,” but at other times bypassed proposals to
rediscover requirements from sessions; Owner degraded from selective admit/hold/decline decisions to admitting everything and merging everything with covers.

These deviations stem from homogeneous contracts: multiple roles see similar evidence, use similar investigation tools, and submit the same fields, while tests primarily assert JSON, labels, and
state transitions. Although Prompts state “what the role is not responsible for,” the runtime has no dedicated artifacts, provenance relationships, or consequences for crossing boundaries, so the model only needs to switch
submission buttons to continue using the same technical analysis paradigm. This group's goal is not to narrow PM's observation scope, but to ensure that comprehensive evidence produces genuinely different, reviewable intermediate artifacts
through different cognitive tasks.

## Guide-level explanation

Each role contract fixes three components: the cognitive question it must answer, the artifact language it may use, and the conditions under which its artifact fails.

| Role | Cognitive question | Dedicated artifact language | Quality gate |
|---|---|---|---|
| Triage | What problem does this report accurately describe? | Report facts, user impact, boundaries, evidence, uncertainties | Remain faithful to a single report; do not deduplicate across issues or prematurely provide product/implementation solutions |
| Product PM | What product problems and opportunities does user behavior imply? | User goals, observed behavior, experience tensions, product opportunities, desired outcomes | Express user value and product capabilities; technical implementation is not a PM artifact |
| Architect | What structural relationships and common mechanisms exist among existing proposals? | Source proposals, relationship types, common tensions, structural directions, expected leverage | Must explain relationships among multiple proposals; must not rewrite a single issue or discover new requirements independently of proposals |
| Owner | Which directions merit investment, and how should they form a queue? | User value, evidence strength, scope cohesion, overlap, risk, priority, decisions | May decide only on inputs; hold/revise when evidence is insufficient, boundaries are confused, or solutions are proposed prematurely |

PM continues to receive the full experience index, existing report/proposal references, and session evidence on demand. It may reinterpret existing reports or discover opportunities in
unreported behavior; the system does not require every PM insight to prove it is “unprecedented.” Overlap between PM and other generators is valid input, and
Owner decides whether to merge it. The boundary is product perspective rather than novelty: outputs answer questions about user goals, experience tensions, and desired outcomes, rather than specifying code locations,
protocols, thresholds, or implementation steps.

Quality gates fall into two categories. Machine-provable invariants trigger hard rejection before persistence, such as nonexistent source issues, Triage referencing multiple reports at once,
Architect having fewer than two sources, or Owner making decisions beyond its authority. Semantic qualities such as product perspective, abstraction level, and scope cohesion cannot be reliably judged with keyword blacklists;
they are verified using positive and negative role examples, structured revise reasons, and replay scores. An initial failure permits revision within the same round; continued failure produces
an observable hold/revise rather than masquerading as a qualified proposal.

## Reference-level explanation

### Artifacts and canonical proposals

Add a role artifact contract layer. An artifact preserves the role's original cognitive output and its sources, then a deterministic projection generates the existing canonical
proposal, maintaining compatibility with the report/proposal/ready workflows in tracker, the frontend, and OpenAgents. The four submit tools no longer share
the same RFC item schema:

- Triage artifact: `source_report`, `reported_problem`, `user_impact`, `scope_boundary`,
  `evidence`, `uncertainties`.
- PM artifact: `user_goal`, `observed_behaviors`, `experience_tension`, `product_opportunity`,
  `desired_outcome`, `evidence_sessions`; optional `related_proposals` serves only as a reference and does not express a merge.
- Architect artifact: `source_proposals`, `relationship`, `common_tension`,
  `structural_direction`, `expected_leverage`; optional `covers` remains only a recommendation to Owner.
- Owner decision: in addition to the existing `decision/into/priority/reason`, add `user_value`, `evidence_strength`,
  `scope_cohesion`, `overlap`, and `delivery_risk` to make investment judgments observable.

All submit properties use canonical English identifiers. Normalized issue/RFC projections read `Field.key` directly; the English `Field.label` controls display headings only and is never a parser alias.
Unknown or nonstring normalized fields are rejected by per-kind validation. The PM and Architect artifact keys listed above remain unchanged.

`role_contract.py` handles collection and provenance invariants beyond the schema and returns stable violation codes, such as
`foreign-source`, `not-cross-proposal`, and `decision-out-of-batch`. Incident vocabulary blacklists must not be used to infer role quality.

### Role execution boundaries

Triage may process multiple reports concurrently, but each model invocation includes only the current report, its associated session evidence, and read-only harness
context; results are attributed independently by issue number. The product PM retains panoramic input without generation-side deduplication. Architect first reads the full ProposalView;
timeline/beat drill-down must originate from evidence references in currently visible proposals and may only verify relationships; it must not become the basis for new proposals
without provenance. Owner receives role artifacts, ProposalView, the ready queue, experience summaries, and evidence summaries, without unrestricted source code search;
it evaluates investment value rather than regenerating root causes and solutions.

### Quality gates and behavioral evaluation

At runtime, execute schema validation first, then hard provenance/collection invariants, and finally record semantic self-review results. The semantic gate uses stable dimensions rather than banned words:
`evidence_fidelity`, `product_orientation`, `cross_proposal_reasoning`, `investment_judgment`,
`abstraction_level`. It may be implemented through structured self-review by the same role or an independent evaluator, but evaluation inputs, results, and evidence locations must be recorded in the trace;
no automated model evaluation may directly change tracker state. State remains controlled by the driver's deterministic rules and Owner decisions.

Positive and negative example tests use task-independent synthetic evidence: the same set of sessions passes through all four roles, asserting that Triage produces factual boundaries, PM produces product opportunities,
Architect produces relationship explanations, and Owner produces investment decisions. Tests reject assertions that “field presence means qualification” and must cover typical artifacts produced by roles straying into other roles' responsibilities.

### DAG and file allocation

| Task | Content | Dependencies |
|---|---|---|
| T1 | Artifact schemas, shared invariants, and violations | — |
| T2 | Triage single-report isolation | T1 |
| T3 | Product PM panoramic insights | T1 |
| T4 | Architect relationship synthesis | T1, T2, T3 |
| T5 | Owner investment quality gate | T1, T4 |
| T6 | Cross-role behavioral evaluation and real replays | T2, T3, T4, T5 |

Files are exclusively owned through Task `files` in the frontmatter. The end-to-end entry point is
`tools/dev/audit/evaluate_role_traces.py` together with `replay_roles_from_sessions.py`: replay runs until Owner stops,
outputs complete artifacts, provenance relationships, violations, decisions, and per-role scores, and does not launch OpenAgents.

## Drawbacks

Role-specific schemas increase migration costs; historical proposals can participate in new Owner reviews only through compatibility projections. Changing Triage from one invocation per batch to
per-issue isolation increases request counts, but concurrency can maintain wall-clock time. Architect's provenance constraints may miss important
structural signals represented by only one proposal; PM should first turn such signals into product proposals before they enter the next round of synthesis. Semantic quality cannot be fully judged by deterministic code,
and introducing evaluators adds cost and uncertainty, so semantic scores are used by default for revise/hold and observation, without direct state write permissions.

## Rationale and alternatives

We did not adopt “add more prohibitions to the four Prompts”: existing replays have already demonstrated that when roles share inputs and forms, Prompt identities are easily overridden by a generic
investigation paradigm. We did not adopt “strictly isolate PM and allow it to view only sessions without reports”: the product PM needs a comprehensive understanding of the user experience and should also be able to reconstruct
the product significance of existing reports; constraining the perspective of its submissions fits its responsibilities better than constraining its observation scope. We did not adopt mandatory generation-side novelty/deduplication:
similar proposals may express different product opportunities, and premature deduplication loses information; Owner holds the portfolio perspective and merge authority.

We chose “dedicated artifacts + provable invariants + semantic behavioral evaluation” because the three layers address homogeneous expression, provenance boundary violations, and abstraction-level drift, respectively;
canonical proposals are retained as the downstream compatibility layer to avoid rewriting tracker and delivery-side protocols.

## Prior art

The existing ProposalView has demonstrated that a unified read-only data model can eliminate format drift; this group adds role-specific projections and artifacts on top of it. The existing Owner
decision graph has demonstrated the feasibility of validating an entire batch before transitioning states; this group extends the same approach to source collections and investment decision fields. Compiler
typed intermediate representations provide a similar principle: stages may share underlying facts, but must hand off through distinct, verifiable
intermediate representations rather than relying solely on stage names to constrain behavior.

## Unresolved questions

Whether the first semantic quality gate uses role self-review, independent low-cost model evaluation, or scoring only in offline replays must be decided before implementing T1 based on invocation cost and
false rejection rates; regardless of the choice, automated evaluation has no tracker write permissions. When historical canonical proposals lack role artifacts,
whether Owner reviews them directly as compatible low-confidence inputs or first routes them through a migration/restatement queue also remains to be decided before implementation.

## Future possibilities

After enough traces accumulate, long-term metrics stratified by role can be established: Triage factual fidelity, PM product perspective scores, Architect cross-proposal
leverage rates, and Owner hold/merge calibration. Role artifacts can also support division of work across models, manual sample calibration, and improvements to
upstream contracts based on Owner feedback, but must not turn a single Owner preference into an incident vocabulary rule.
