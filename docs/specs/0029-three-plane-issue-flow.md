---
number: "0029"
title: "Three-plane issue flow: evidence→proposal→work queue, with a single admission Owner (claimable whitelist, generators freely parallelized, gate special channel removed)"
issue: 0
slug: three-plane-issue-flow
summary: "Three root problems in the current issue flow: ① Three writers have authority to put work into the dev queue (triage accept, architect directly creating RFCs and superseding others, gate promote), with inconsistent admission rules—architect output enters the queue without review, while divergent output must pass gate, a product of historical evolution with no underlying principle; ② labels flatten \"work-item eligibility / workflow status / attributes\" into one plane, and dev claimability is determined by a blacklist that grows with every new state (each addition of divergent or gate-dropped requires remembering to update the dev exclusion set); ③ deduplication is placed on the generation side, which is meant to run in parallel (triage normalizes and deduplicates at the same time), inherently conflicting with parallelism—the root cause of the previous impasse in triage sharding discussions. This spec restructures the flow into a three-plane, single-admission model: plane 1 evidence (user reports/user experience/runtime, input) → plane 2 proposals (proposal, always unclaimable; triage/architect/divergent are all merely generators, producing non-binding proposals, so they can run freely in parallel and duplicates are harmless; they also split into two tracks by evidence source—architect consumes the normalized backlog to find structural root causes (delivery track), while divergent directly consumes raw session behavior to mine capability gaps not raised as issues (discovery track), achieving deduplication by construction rather than prompt instructions) → single admission Owner (one batch review per round: admit→ready / merge for deduplication / decline / hold; mechanical mode automatically admits a single fix proposal with complete fields without an LLM call) → plane 3 work queue (ready is the sole claimable whitelist; dev pulls by priority→age and closes only its own issues—covers cascading is completed by merge during Owner admission). Supporting changes: extract the shared agent runtime (eliminating triage/divergent dependencies on architect private symbols), retire the gate/divergent special channel and superseded/gate-dropped intermediate states, and add proposal/ready queue depth backpressure alerts (= implementing CLAUDE.md degradation signals). Do not change the pure trunk/direct push to main/benchmark held-out/submit-tool contracts (reuse 0027; Owner only adds submit_admission)."
tasks:
  - id: T1
    title: "Consolidate issue_schema three-plane labels: report/proposal/ready whitelist + read-side mapping of legacy labels"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/issue_schema.py
      - backend/tests/demand/test_issue_schema.py
    scope: "Add plane constants REPORT/PROPOSAL/READY, terminal-state labels DECLINED/MERGED, and provenance labels FROM_TRIAGE/FROM_ARCHITECT/FROM_DIVERGENT; add plane(labels) projection (report/proposal/ready plus None) and is_ready(labels,state) whitelist check (the sole entry point for dev); move covers machine-line parsing (parse_covers_line) and the merged-into machine-line helper into this module as the single source of truth (web/architect will subsequently reference it consistently). Retain constants for legacy labels (needs-triage/triaged/RFC/superseded/divergent/gate-dropped) and map them in the read-side projection to the new planes (needs-triage→report, triaged|RFC→ready, divergent→proposal, superseded/gate-dropped→closed terminal-state display), so old data remains displayable; the write side no longer produces legacy labels. Leave SCHEMAS/validate/render/PRIORITIES/round_label unchanged."
    acceptance: "plane/is_ready return correct values for combinations of new and legacy labels; unit tests for covers/merged-into parsing; coverage of legacy label mappings; no regressions in existing validate/render tests."
  - id: T2
    title: "Extract the shared agent_runtime: one implementation for running agents + reading submit"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/agent_runtime.py
      - backend/tests/demand/test_agent_runtime.py
    scope: "Create agent_runtime.py to consolidate common logic copied separately by the four drivers: run_with_timeout (contextvars.copy_context across threads), run_agent_def(agent_def_dir, message, *, store, repo, on_event, timeout, max_iterations=None) (set SANDBOX_WORK_DIR to an absolute path, AgentConfig.from_yaml, StepTracer, bind_session_store, dumps when the return value is not str), read_submit(text, key) (bounded layer-by-layer json.loads until a dict, extract the key array, return None on failure). read_submit transports nested payload dictionaries unchanged: no label normalization, key aliases, or value coercion; drivers enforce canonical English field contracts before persistence. Only add the new module; do not modify existing files—each driver switches imports in its own task (T3/T4/T5/T6), and the old copy in architect.py is deleted in T4 after all switches."
    acceptance: "read_submit handles all four cases correctly: normal, re-encoded one additional layer, prose, and submit not called; unit test for run_with_timeout passing contextvars across threads (reuse the existing assertion style); read_submit preserves canonical field keys and nested values exactly; there is no norm_label helper or alias conversion, and drivers retain strict per-kind validation."
  - id: T3
    title: "Change triage into a pure normalization generator: accept→promote in place to proposal, move deduplication responsibility out"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/triage.py
      - backend/agent_defs/triage_agent/agent.yaml
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/agent_defs/triage_agent/tools/submit_triage.tool.yaml
      - backend/tests/demand/test_triage.py
    scope: "Converge disposition to three values, accept/reject/needs_info—retire duplicate (transfer full responsibility for deduplication to Owner; triage returns to a single-item view and is no longer fed \"already-triaged deduplication references,\" reducing input size). accept→promote in place to proposal: remove REPORT, add PROPOSAL+FROM_TRIAGE+confirmed kind+suggested priority (P0-P3 labels, which Owner may change), render TRIAGE fields in a comment; reject/needs_info→DECLINED+reason+close. Update agent_contract.dispositions_input_schema accordingly (three-value enum), regenerate submit_triage.tool.yaml (drift-guard remains unchanged); remove the deduplication section from systemprompt and change it to the three-value contract. Switch the driver to agent_runtime imports and remove its dependency on architect.py."
    acceptance: "After accept, the issue is in the proposal plane (not ready, not claimable by dev); all three paths are correct; no duplicate path remains; deduplication references are no longer supplied; test_triage is rewritten with three-value+proposal assertions and passes."
  - id: T4
    title: "Narrow architect to a pure generator: produce proposal(from-architect), retire gate_once"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/agent_defs/architect/agent.yaml
      - backend/agent_defs/architect/systemprompt.md
      - backend/agent_defs/architect/tools/submit_rfcs.tool.yaml
      - backend/agent_defs/architect/tools/submit_gate.tool.yaml
      - backend/tests/loop/test_architect.py
    scope: "Change propose_once output to PROPOSAL+FROM_ARCHITECT (no longer create RFC labels directly or apply superseded; the covers relationship remains a machine-readable line in the body and is only a **suggestion**, with merge decisions transferred to Owner); change its inputs to the ready backlog + compact proposal index + user experience + runtime (orchestration ensures it runs after this round's triage, and the compact index includes from-triage proposals newly promoted in this round). Retire gate_once/GateOutcome/_gate_from_submit/submit_gate entirely (admission responsibility belongs to Owner/T6): remove submit_gate from architect agent.yaml, restore stop_tools to [submit_rfcs], and delete submit_gate.tool.yaml; remove the gate mode note from systemprompt. Switch the driver to import from agent_runtime, and delete the old local copies of run_with_timeout/_unwrap_result. Retain the submit_rfcs tool name (the colloquial “RFC” means a structural proposal); only the persisted labels change."
    acceptance: "Output is on the proposal plane, with from-architect and covers lines, and without superseded; zero remaining gate symbols; test_architect is rewritten for the new persistence assertions and passes."
  - id: T5
    title: "Align divergent as a pure generator: produce proposal(from-divergent), retire the dedicated channel"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/divergent.py
      - backend/agent_defs/divergent_pm/agent.yaml
      - backend/agent_defs/divergent_pm/systemprompt.md
      - backend/agent_defs/divergent_pm/tools/submit_divergent.tool.yaml
      - backend/tests/demand/test_divergent_gate.py
    scope: "Redefine the input as “firsthand session evidence” (review revision, two-track differentiation): use the user experience curve (score + reason + session handle) as an index, and drill down into raw session behavior on demand via get_session_timeline/beat/step; the compact index of open proposals/ready issues serves only as a “do not duplicate” reference; **no longer feed it triaged backlog or runtime_agg** (those are convergence signals for architect). Responsibility = identify “procedures/capabilities users repeatedly devise themselves that have not been raised as issues” from user conversation behavior; align systemprompt (its original text already called for attention to such signals, and the inputs now finally provide them). Change output to PROPOSAL+FROM_DIVERGENT (retire the old DIVERGENT label to a read-side mapping); retain the hard cap of 3 items per round. Switch the driver to import from agent_runtime and remove its dependencies on Architect internals (_proposals_from_submit/_DESIGN_TIMEOUT). Split test_divergent_gate.py: retain and rewrite the divergent generation portion here, and delete the three-way gate tests (Owner-side T6 rebuilds equivalent coverage)."
    acceptance: "Inputs exclude triaged backlog/runtime_agg and include the user experience index and session drill-down; candidates are on the proposal plane with from-divergent and cannot be claimed by dev; zero imports from architect.py; divergent tests pass."
  - id: T6
    title: "Owner as the sole admission authority: batch decisions in mechanical + review modes (admit/merge/decline/hold)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/owner.py
      - backend/ahe_beta/demand/agent_contract.py
      - backend/ahe_beta/demand/submit_tools.py
      - backend/agent_defs/owner/
      - backend/tests/demand/test_owner.py
    scope: "Create an Owner driver (owner.py): admit_once() performs batch admission once per round. Inputs = all open proposals (compact index: number/title/kind/provenance/suggested priority/covers, with bodies drilled into on demand via get_session_timeline) + ready backlog + user experience curve. Two-level decision process: ① mechanical stage (zero LLM calls): a single-issue fix proposal from-triage, with complete TRIAGE fields and no near-title conflict with existing ready issues or proposals in the current batch (simple similarity after norm) → automatic admit; ② review stage (one batch LLM call): the rest (structural/product proposals, conflict groups, and cases the mechanical stage cannot decide) go through the owner agent, ending with submit_admission. Persist decisions: admit → remove PROPOSAL and add READY + final priority; merge → close + a merged-into machine-readable line linking to the primary issue; decline → DECLINED + close with reason; hold → keep as proposal. The **only place covers cascading occurs is here** (replacing the old “_close_covered when dev completes an RFC”): decision precedence = **explicit decision > covers default merge > global default hold**. First apply all explicit decisions, then for each admitted structural proposal, default-merge report/proposal issues in its covers that are still open and have not been explicitly decided in this batch (close immediately + link to the primary issue via merged-into; leave ready/closed issues untouched). If Owner explicitly admits a covered urgent fix (e.g. P0), retain it as an independent ready issue to proceed in parallel with the structural proposal; if the structural proposal is held/declined, its covers triggers no cascade. When multiple structural proposals in the same batch cover the same issue, process them deterministically in issue-number order (first wins). Do not rewrite covers machine-readable lines after creation; record decision outcomes in the state of each covered issue itself. Add admission_input_schema() to agent_contract (four-value decision enum, into/priority/reason), and delete gate_input_schema; add submit_admission to submit_tools and delete submit_gate. Create agent_defs/owner/ (read-only tools + timeline drill-down + submit_admission, systemprompt = admission responsibilities and criteria)."
    acceptance: "The mechanical stage admits qualifying single-issue proposals with zero LLM calls; all four review-stage outcomes (admit/merge/decline/hold) are persisted correctly, with unlisted items defaulting to hold; merge links to the primary issue, and covers converges consistently; drift-guard (yaml==admission_input_schema); skip the LLM when there are no candidates; test_owner covers the above."
  - id: T7
    title: "dev whitelist-based claiming: ready-only + priority→age ordering + cascading closure"
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
    scope: "Change _eligible from a blacklist to the is_ready whitelist (issue_schema is the single source of truth); change ordering from pure issue-number FIFO to priority (P0>P1>P2>P3>none) → issue number (FIFO within the same priority to prevent starvation); retain budget tiers by kind (structural proposals from-architect get the highest tier, replacing the original RFC tier criterion); resolved → close+comment, **closing only its own issue**. The covers cascade has moved earlier to merge at Owner admission (covered issues are closed and linked to the primary issue upon admit); retire dev-side _close_covered, reducing coupling between dev and tracker to “claim an issue + close its own issue”."
    acceptance: "Claim only ready issues; P0 jumps the queue, FIFO within the same priority; budget tiers follow the new criteria; zero remaining _close_covered references; tests rewritten and passing."
  - id: T8
    title: "Orchestration/roster/run wiring: generation stage fully parallel (triage can be sharded) → Owner → dev + backpressure alerts"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
      - T4
      - T5
      - T6
      - T7
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/loop/roster.py
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_roster.py
    scope: "Reorder run_round as a → generation stage in **two beats**: first beat triage shards × N_TRIAGERS ∥ divergent (parallel in a thread pool: triage consumes reports, divergent consumes session evidence; both depend only on stage a output and not on each other; deduplication has moved to Owner, so sharding is unconstrained), second beat architect (runs after all triage work finishes, with inputs including from-triage proposals newly promoted **this round**, so structural synthesis does not lag by one round) → Owner.admit_once (always 1) → b dev → c; delete the gate stage. Add owner to roster (default 1; 0 = mechanical admission only, no LLM review stage), and retire gate semantics. Wire Owner into run.py and add backpressure alerts: proposal depth and ready depth exceeding their thresholds (env PROPOSAL_DEPTH_ALARM/READY_DEPTH_ALARM, both default to 20) → status callback + stdout alert (no automatic scaling; signal for manual intervention = implementation of “an issue count that does not decline over time indicates degradation” in CLAUDE.md). As before, log and skip individual agent crashes."
    acceptance: "Assert stage order (triage∥divergent all finish → architect → owner → dev); triage shards each process non-overlapping subsets; architect input includes proposals newly promoted in this round; when owner=0, skip the review stage but still perform mechanical admission; exceeding a backpressure threshold triggers the alert callback; test_orchestrator/test_roster are rewritten and pass (git-dependent cases run in CI)."
  - id: T9
    title: "Observability backend adaptation: plane field + ready depth curve + funnel counts"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T6
      - T7
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/web/api.py
      - backend/ahe_beta/loop/metrics.py
      - backend/tests/web/test_api.py
      - backend/tests/loop/test_metrics.py
    scope: "Attach plane (report/proposal/ready/closed terminal state), provenance, and merged_into to each item in /api/issues; change covers parsing to use issue_schema as the single source of truth; data with old labels displays correctly through the T1 read-side mapping. metrics: change issue_curve to represent ready depth over time (accumulated open/close events, excluding proposal/report); add endpoint data for funnel counts (current counts for the four stages report/proposal/ready/done + backpressure threshold status)."
    acceptance: "plane/provenance/merged_into fields are correct (for both new and old labels); the curve counts only ready; funnel counts and threshold status are readable; test_api/test_metrics cover these."
  - id: T10
    title: "Frontend adaptation: three-plane grouping + Owner room + funnel and backpressure display"
    status: done
    priority: P3
    tags: []
    depends-on:
      - T9
    relates-to: []
    parallel: false
    files:
      - frontend/src/types.ts
      - frontend/src/lib/issueMeta.ts
      - frontend/src/components/SidePanel.tsx
      - frontend/src/components/detail/IssueDetail.tsx
      - frontend/src/App.tsx
      - frontend/src/api.ts
    scope: "Add owner to AgentRole, insert an “Admission” room into App ROLES (distinct from the generation-stage rooms); change SidePanel issue grouping to three planes (Reports/Proposals [with provenance badges]/Ready/Closed), and display merged-into links; show four-stage funnel counts + a backpressure alert bar (highlight when thresholds are exceeded); rewrite issueMeta projection by plane (fallback mapping for old labels consistent with the backend); add plane/provenance/merged_into to IssueDetail. Degrade gracefully without crashing when an old backend lacks the fields."
    acceptance: "Under mocks, three-plane grouping is correct, the Owner room is visible, and the funnel and alert bar render; missing fields degrade gracefully; npm build passes."
---

> Historical specification note: This file preserves the decisions and terminology from the implementation of 0029. The current role contract, Owner review method, Triage persistence semantics, and covers lifecycle are governed by Spec 0042; do not restore mechanical admission or old state migration from this document.

# 0029 · Three-Plane Issue Flow: Evidence → Proposal → Work Queue, with a Single Admission Owner

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a nine-section group-level rust-RFC overview. -->

## Summary

Refactor the issue flow from “multiple writers, a blacklist, and tone-based role separation” into **three-plane single admission**: evidence (user reports/experience/runtime) → **proposal** (proposal, never claimable; triage / architect / divergent are all demoted to generators whose output is a non-binding proposal, so they can run freely in parallel and duplicates are harmless) → **single admission Owner** (one batch decision per round: admit / merge / decline / hold; a single fully specified fix proposal follows zero-LLM mechanical admission) → **work queue** (`ready` is the only claimable whitelist; dev pulls by priority → issue age and only closes its own issues—covers cascading is completed by merge during Owner admission, and dev-side _close_covered is retired). Also extract a shared agent runtime to eliminate private dependencies between drivers, retire the gate special channel and the superseded/gate-dropped/divergent intermediate labels, and add proposal/ready queue-depth backpressure alerts.

## Motivation

The root causes of the current flow (all supported by code evidence) are:

1. **The dev queue has three writers with inconsistent entry rules**. triage accept → `triaged`, architect directly creates `RFC` (and can mark someone else’s triaged issue as `superseded`), and gate promote → `feature+triaged`—three paths with different standards. The starkest asymmetry: **architect output enters the queue without review, while divergent output must pass through gate**, with no principled reason; this is purely historical evolution (divergent was added later and was not trusted).
2. **Labels are mixed together, and dev eligibility is an expanding blacklist**. `(TRIAGED or RFC) and not SUPERSEDED and not NEEDS_TRIAGE and not DIVERGENT`—every time a workflow state is added (this time divergent/gate-dropped), the dev exclusion set must be updated; missing one causes an incident. Eligibility, state, and attribute semantics are compressed into one plane.
3. **Deduplication is in the wrong place**. Deduplication is pushed onto triage (the generation side), while generation naturally wants parallelism and deduplication inherently requires a global view—previous triage sharding discussions repeatedly stalled (polling misses duplicates, hash partitioning is half-baked, and sorting by partition still feels awkward). The root cause is a responsibility mismatch.
4. **The three “work-seeking” agents are distinguished by prompt tone**: architect/divergent/gate consume the same signals and emit the same shape; the only difference is the system-prompt posture. gate also reuses the architect agent with a different task message, so `Architect` is one class with two personalities.
5. **The modules are genuinely coupled**: triage.py and divergent.py each import private symbols from architect.py (`_run_with_timeout`/`_norm_label`/`_proposals_from_submit`/`_DESIGN_TIMEOUT`), while the shared “run agent + read submit” logic is copied into three variants.

## Guide-level explanation

The life of an issue after refactoring (advance one issue in place without duplicating it):

```
User sim files a report (free text + round-N)
  │ triage (generator, single-issue view): investigate → promote in place to proposal (kind+fields+suggested priority)
  │                                                   or decline (reject/needs_info, close with reason)
  ▼
proposal plane (not claimable) ←──── architect / divergent also create structural/product proposals here
  │                                  (with provenance and covers machine-readable lines)
  │ Owner (sole admission authority, one batch per round):
  │   admit → ready (set final priority)    merge → close, link to primary issue via merged-into (deduplication happens here!)
  │   decline → close with reason          hold → defer to next round (unlisted items default to hold)
  ▼
ready plane (sole allowlist for claimable issues)
  │ dev pulls by priority→issue age, pushes directly to main
  ▼
done (close only its own issue—covered issues were already closed by merge and linked back to the primary issue during Owner admission)
```

Role charter (one sentence each):

| Role | Responsibility | Count | Parallelism |
|---|---|---|---|
| user sim | Use the harness to produce evidence | N | Already parallel |
| triager | Investigate reports one by one → fix proposals; **does not deduplicate** | N | **Freely sharded** (output is non-binding, so duplicates are harmless) |
| architect | Find structural root causes across items on the **normalized backlog** → structural proposals (delivery track) | 0..1 | Second beat (after triage winds down) |
| divergent | Mine **raw session behavior** for capability gaps that were not proposed as issues → capability proposals (discovery track) | 0..N | First beat (parallel with triage, consuming only section-a evidence) |
| **Owner** | **Single admission authority**: deduplicate and merge, resolve conflicts, set priority, admit/decline/hold | **Always 1** | Single point (global view; compact index + backpressure keep context bounded) |
| dev | Pull work from ready and push directly to main | N | Already parallel |

User-visible benefits: the dev filter becomes one word (`ready`); triage can parallelize however it wants; architect and divergent have symmetrical status (both pass through the same gate); deduplication is concentrated at the only point with a global view; the number of LLM decision calls per round remains roughly unchanged (Owner replaces gate and also absorbs scattered deduplication/supersede decisions).

## Reference-level explanation

**Planes and labels (T1)**: Eligibility looks only at three words `report / proposal / ready`; terminal states are `declined / merged` (+ closed); attributes (kind, P0-P3, round-N, provenance `from-triage/from-architect/from-divergent`) do not participate in eligibility checks. `plane(labels)` and `is_ready(labels,state)` are the only projections; machine-readable covers and merged-into lines are consolidated into issue_schema as the single source of truth. Old labels are retired on the write side and mapped on the read side (old data remains displayable): needs-triage→report, triaged|RFC→ready, divergent→proposal, superseded/gate-dropped→closed terminal state.

**Shared runtime (T2)**: `agent_runtime.py` consolidates run_with_timeout (contextvars across threads), run_agent_def (SANDBOX_WORK_DIR/AgentConfig/StepTracer/bind_session_store/timeout), and read_submit (bounded, layer-by-layer json.loads to extract the submit array). Nested dictionaries retain their canonical English keys and values unchanged; the runtime never normalizes display labels or coerces field values. Drivers perform strict per-kind validation before tracker mutations: “assemble prompt → run_agent_def → read_submit → validate canonical fields → write tracker.”

**Generators (T3/T4/T5)**:
- triage: disposition converges to three values (accept/reject/needs_info); **duplicate is retired**—no deduplication references are supplied, the input becomes smaller, and the per-item view is purer. accept upgrades the issue in place to proposal (not ready).
- architect: produces proposal(from-architect)+covers lines; **no longer marks superseded** (supersede is an admission decision and belongs to Owner).
- divergent: **switches evidence tracks**—it no longer consumes triaged backlog/runtime_agg (those are architect’s convergence signals), but instead consumes an experience index plus on-demand drilling into raw session behavior to find “ways of working that users did not report as issues but repeatedly devised themselves”; it produces proposal(from-divergent), and the dedicated gate channel disappears. The two generators change from “same material, different tone” to “different material on two tracks”; overlap is eliminated by construction, and occasional collisions are merged by Owner as a fallback.
- All three continue to use the existing agent_contract generation + drift-guard submit contract (reusing the 0027 mechanism).

**Owner (T6)**: `admit_once()` has two decision levels—① mechanical stage (zero LLM): a single from-triage proposal with complete fields and no near-title conflict is automatically admitted (conservative: when uncertain, send it to the review stage); ② review stage (one batch LLM call): structural/product proposals and conflict groups. Contract `submit_admission`: `[{issue, decision: admit|merge|decline|hold, into?, priority?, reason?}]`; anything not listed defaults to hold. When admitting a structural proposal, all proposals it covers are merged consistently (the only place where covers decisions are made).

**dev (T7)**: Whitelist `is_ready`; sort by priority → issue number; done closes only its own issue (covers cascading has already been completed by Owner merge at admission, and `_close_covered` is retired). **covers lifecycle**: write machine lines at creation (filter to issue numbers that exist and are open, then do not rewrite them) → cascade at admission according to “explicit > default merge > hold” → no cascade on done → if the fix is unsuccessful, a new report corrects itself in the next round (no reopen mechanism; gradient-descent-style correction).

**Orchestration and backpressure (T8)**: `a → two-beat generation stage[first triage×N shards in parallel; then architect ∥ divergent] → Owner(1) → dev → c`; the gate stage is deleted. Two beats instead of full parallelism: architect must see the **newly promoted from-triage proposals from the current round** (otherwise structural synthesis lags by one round and dev first fixes symptoms one by one), while waiting for triage to wind down adds only one wall-clock beat—worth it. The genuinely valuable parallelism (between triage shards and between architect∥divergent) is preserved. Add owner to the roster (1; 0 = purely mechanical admission). Backpressure: when proposal/ready depth exceeds the threshold (env, default 20) → alert callback + stdout, **no automatic scaling**—this makes the CLAUDE.md “issue count not declining over time = degradation” observation metric actionable.

**Observability (T9/T10)**: Issues include plane/provenance/merged_into; the curve is ready depth; the funnel has four-stage counts (report/proposal/ready/done) + backpressure status; the frontend groups the three planes + Owner room + alert bar.

**DAG**: T1 and T2 start in parallel → T3/T4/T5/T6 in parallel (files do not overlap) → T7 (depends only on T1) → T8 convergence → T9 → T10.

**Non-goal**: Do not change pure trunk/dev direct push to main/no-gate behavior (0007); do not change benchmark held-out or experience as the sole training signal; do not change the submit-tool contract mechanism (0027); do not implement embedding-based semantic deduplication (Owner first uses batch LLM judgment + mechanical near-title matching, which is sufficient for now); do not implement triage sorting by mechanism area (free sharding followed by polling is sufficient, while area-based sorting is reserved for a later optimization).

## Drawbacks

- **The Owner review stage adds one batch LLM call**—but it replaces gate (which already required one) and removes triage’s deduplication burden (so its input becomes smaller); net cost is approximately unchanged. The mechanical stage lets the “plain majority” (single fix proposals with complete fields) pass with zero LLM calls.
- **Owner is a single point of failure**: if it fails, the entire round has no admission (proposals accumulate and dev gets no new work). Mitigation: log the crash and skip it (proposals remain for review in the next round) + a pure mechanical fallback mode with owner=0.
- **Old and new labels coexist during migration**: read-side mapping preserves display, but historical curves will have a step at the metric-definition switch (old triaged depth vs. new ready depth); accept this and mark the switch point on the dashboard.
- The change surface is large (10 tasks); control risk through single-file ownership + behavioral assertions per task + mechanical mode first (establish behavioral equivalence before tightening).

## Rationale and alternatives

- **In-place upgrade vs. creating a separate proposal issue**: A three-plane purist design would create an additional proposal issue for every report (doubling issue count and making the chain more convoluted). Advance in place instead (report→proposal→ready completes on the same issue); only cross-item structural/product proposals create new issues—this does not simplify the state machine, but halves the cost.
- **Single admission vs. the current three writers**: This follows common practice in real organizations (Kanban backlog grooming, Scrum Definition of Ready, and K8s triage/accepted+milestone admission)—anyone can propose, but only the owner decides what enters Ready. Deduplication/priority/coverage decisions are concentrated at the sole point with a global view, fully decoupling the generation side for free parallelism.
- **Owner always 1 vs. scalable**: Admission requires a global view, while the input is bounded three ways by “compact index + on-demand drilling + backpressure,” keeping a single instance’s context manageable (earlier discussions established that architect can be single-instance; the same applies to Owner). The scaling signal is a backpressure alert; the response is manual adjustment of B/addition of dev capacity, not running multiple Owners.
- **Whitelist vs. blacklist**: A blacklist grows with the number of states and requires “remembering to update dev every time a new state is added”; a whitelist has one word, and new states are safe by default (fail-closed).
- **Alternative: retain gate and only fix the asymmetry** (make RFC also pass through gate)—this fixes the asymmetry, but deduplication remains in triage, the blacklist remains, and coupling remains; converging on one Owner is preferable.
- **Alternative: Owner entirely LLM-based (no mechanical stage)**—even ordinary single-item proposals would consume review capacity every round, which is wasteful and slow; the mechanical stage acknowledges that “most proposals should pass anyway.”
- **Two beats for the generation stage vs. full parallelism** (review revision): Under full parallelism, architect cannot see newly promoted triage proposals from the current round. Structural synthesis either lags by one round (dev fixes symptoms individually before being superseded by the structural proposal, wasting dev budget) or falls back to consuming raw reports. Waiting for triage to finish adds only one wall-clock beat, so use two beats. “Triage proposals being covered by structural proposals” is not waste: the individual root-cause region/priority/evidence are precisely the basis for clustering and merge decisions (in K8s, issues are likewise triaged before being absorbed by an umbrella/KEP). Also, in 0029 coverage changes from architect unilaterally marking superseded to a covers recommendation + Owner decision (allowing an urgent fix to be partially retained).
- **Divergent switching evidence sources vs. same material with different tone** (review revision): In the original design, architect/divergent consumed the same signal and were distinguished by prompt posture—structurally, that is duplication. Moreover, the “ways of working that users did not report as issues but repeatedly filled in through conversational behavior” that divergent must find are **mostly absent from the issue backlog** (users tolerated or worked around them, leaving traces only in trajectories and experience rationales), so its system-prompt intent conflicted with its input design. Split by evidence source instead: architect consumes the normalized backlog (explicit complaints → structural convergence), while divergent consumes raw session behavior (implicit coping → capability discovery). Deduplication changes from prompt instruction to construction; divergent no longer depends on triage and moves into first-beat parallelism. Occasional collisions (the same coping behavior is also proposed as an issue) are merged by Owner as a fallback.

## Prior art

- Kanban / Scrum: backlog grooming and Definition of Ready—free proposal generation and single admission are the direct prototypes for this spec.
- Dual-track agile / continuous discovery: the delivery track consumes the backlog (engineering convergence), while the discovery track conducts user research (looking at sessions/interviews for opportunities)—the prototype for architect/divergent splitting by evidence source; PMs perform product discovery by observing how users work, not by browsing the bug tracker.
- K8s issue triage: needs-triage → SIG sorting → `triage/accepted`, with milestone admission governed separately—the sorting step (normalization) and admission (deciding what to do) are two gates.
- Competitive consumers/partition discussions (the group’s preceding discussions): the conflict between parallelism and deduplication has no solution on the generation side, but resolves naturally on the admission side—generators can produce non-binding proposals with at-least-once semantics, and admission provides idempotent convergence.
- 0025 established the triage funnel, 0027 established the submit-tool contract, and 0028 introduced divergent/gate—this spec converges and corrects all three: it retains triage’s investigative value, 0027’s contract mechanism, and divergent’s discovery function, while rearranging their power boundaries.

## Unresolved questions

- **Hold lifecycle limit**: After a proposal is held for K consecutive rounds (K=3?), should it be automatically declined or escalated as an alert? For now, only count it and show its age on the dashboard; do not take automatic action.
- **Mechanical-stage “no conflict” criterion**: What normalized title-similarity threshold counts as a conflict (and therefore enters the review stage)? Start conservatively (prefer review over accidental admission) and tune after measurement.
- **Old-data migration**: Read-side mapping or a one-time migration script to rewrite labels? For now, use read-side mapping only (do not modify historical issues); add a script later if the metrics become confusing.
- **Owner agent definition**: Create a completely new agent_defs/owner/ or reuse the architect definition? For now, create a minimal new definition (the responsibility charter differs); merge them later if the prompts are highly overlapping.

## Future possibilities

- Upgrade triage sharding from polling to mechanism-area sorting (SIG-style): keep context resident within an area and move part of deduplication earlier; Owner still covers the global view.
- Add embedding similarity to Owner’s mechanical stage to assist deduplication (replacing near-title matching).
- Make the backpressure threshold adaptive (estimate it on a rolling basis from dev throughput), and upgrade alerts to automatically adjust the number of sessions B per round.
- Use funnel conversion rates (report→proposal→ready→done conversion at each stage) as a secondary observability metric for harness evolution quality.
