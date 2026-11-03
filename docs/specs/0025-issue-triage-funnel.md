---
number: "0025"
title: "Issue triage funnel: user submits issue → triage agent classifies and locates the problem → architect agent produces RFC → dev"
issue: 0
slug: issue-triage-funnel
summary: "Build the issue flow into a triage funnel modeled on a real software team, and split the existing single architect into two agents. User sim produces raw issues (the user-side template fills user-visible fields, applies type labels and needs-triage, and stamps the round number); the triage agent classifies (confirms type) + locates the problem (reads harness code + get_session_timeline traces) + deduplicates + rejects/marks needs-info in place; the architect agent (the original architect with a narrower scope) only synthesizes structure across issues and produces RFCs (a separate label that takes precedence over type, consolidates/supersedes individual issues, and receives the highest dev budget). Each round, devs sequentially claim triaged issues + RFCs up to capacity (N devs), with any uncleared backlog carried into the next round (backlog = previous round carryover + newly triaged issues this round). Budgets are tiered by kind; remove the 0020 pool partitioning/retry/stuck mechanisms. Product/direction layer = distill persona/seed card library (humans via CLI, layer ⓪, no agent); PM responsibilities = priority derived through an experience + frequency mechanism."
tasks:
  - id: T1
    title: "Platform-layer issue schema: canonical English keys + display labels + validate/render"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/issue_schema.py
      - backend/tests/demand/test_issue_schema.py
    scope: "Define normalized issue fields in SCHEMAS, owned by the platform. Field.key is the canonical English wire/parser key; Field.label is an English display heading only. bug={root_cause,boundary,acceptance}; feature={boundary,deliverable,acceptance}; chore={boundary optional,acceptance}; document={acceptance optional}; RFC={problem,root_cause,related,direction,acceptance}. validate(kind,fields) enforces the selected kind, required fields and string values, rejecting unknown keys and all display-label aliases. render reads values by Field.key and emits ### Field.label sections in declaration order. Generated tool schemas derive normalized field properties from the same SCHEMAS keys; changing labels cannot change the wire contract. Priority remains a P0-P3 label, not a normalized body field. The unused USER template was retired by Spec-0027; user reports remain free text."
    acceptance: "Each kind exposes only its declared canonical English keys with the existing required/optional rules. Validation rejects unknown kinds, missing required values, unknown or display-label keys, and nonstring normalized values. Rendered headings use English labels. Changing a Field.label changes only presentation, leaving generated schema keys and parser acceptance unchanged. Tests cover per-kind fields, rendering, strict failures, and label/key independence."
  - id: T2
    title: "User sim produces structured raw issues: provisional type + needs-triage + round number"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/sim_user.py
      - backend/tests/loop/test_sim_user.py
    scope: "Structure raw issues created by sim_user—labels=[provisional type(bug/feature, roughly inferred by _infer_kind, to be confirmed by triage), needs-triage, round-N] (round passed through by round_provider); body=original persona user-visible report (users cannot see code→only user-perspective symptoms, naturally constituting USER section content); leave TRIAGE section fields empty for the triage agent to fill after reading code + traces. No longer apply only ['bug']. Add round_provider to make_sim_run_session_fn (None preserves compatibility with old callers). Note: Splitting persona reports into structured USER section fields requires changing the user-side prompt(user/sim), beyond this task's file scope; defer to follow-up work."
    acceptance: "Issues produced by sim carry provisional type + needs-triage + round-N (when round_provider is supplied) labels; body=original user report; omit the round number when round_provider is absent (compatible with old tests); _infer_kind defaults to bug, matching request keywords→feature; unit tests assert labels and round pass-through."
  - id: T3
    title: "Triage agent (new role): classify + locate + deduplicate + reject/mark needs-info in place"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3a
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/triage.py
      - backend/tests/demand/test_triage.py
    scope: "Create a Triager driver + agent_defs/triage_agent/ (agent.yaml+systemprompt+tools, including read_file for read-only harness code access + get_session_timeline; reuse workspace_jail with read-only access to the harness repository). Process issues labeled needs-triage one by one (including still-untriaged issues in the previous round's carryover): ① Classify (confirm/change the type label); ② Locate (read harness code + call get_session_timeline by issue number to retrieve god-view traces, fill the corresponding TRIAGE section fields by kind: bug=root_cause/boundary/acceptance, feature=boundary/deliverable/acceptance, validated through issue_schema.validate); ③ Set priority (triage assigns P0-P3 labels based on severity×experience impact; do not apply an invalid label); ④ Deduplicate (compare with existing triaged issues; duplicate→close and link to the primary issue); ⑤ Reject/mark needs-info (insufficient information or out of scope/platform-related→apply rejected/needs-info label + write reason + close). Augment in place (remove needs-triage label, add triaged + kind + priority), without creating a new design issue. Incomplete TRIAGE fields→downgrade to needs_info."
    acceptance: "After triage, needs-triage issues have confirmed type + triaged + priority labels and completed TRIAGE sections (correct fields by kind, validated through validate); feature uses boundary/deliverable/acceptance; duplicate→close and link to the primary issue; rejected/needs-info→close + reason + corresponding label; invalid priority is not labeled but the issue is still accepted; unit tests cover all five paths + field validation + per-kind fields + priority."
  - id: T4
    title: "Architect agent (original architect with narrower scope): structural synthesis across issues → RFC"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/architect.py
      - backend/tests/loop/test_architect.py
    scope: "Narrow Architect to a pure architect role: input=already groomed(triaged) backlog (including backlog across rounds) + experience curve (with session_id) + runtime_agg + read-only harness code + get_session_timeline. Produce 0..n RFCs (separate RFC label, taking precedence over type): fields follow the issue_schema RFC fields (problem/root_cause/related/direction/acceptance); the body uses a covers machine-readable line to declare the individual triaged issues it synthesizes (reuse 0020), and synthesized issues receive a superseded label (record the primary RFC number and exclude them from the set devs can claim). No splitting across rounds (even large requirements use a single RFC). Do not touch git or close raw issues. Prefer no output over low-quality output (no theme→[])."
    acceptance: "RFCs carry the RFC label + structured fields + covers links to related triaged issues; synthesized issues are marked superseded-by; produce [] when there is no cross-issue theme; can still call get_session_timeline/read_file to locate problems; unit tests cover RFC output, supersede marking, empty output, and covers."
  - id: T5
    title: "Simplify dev: claim triaged/RFC issues up to capacity, carry uncleared backlog forward, tier budgets by kind, remove pool partitioning/retry/stuck"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/dev/agentic_developer.py
      - backend/tests/dev/test_agentic_developer.py
    scope: "Remove pick_policy/pool partitioning, attempt/tier escalation, and stuck/bottom placement from 0020/T2. Claiming=list_open_issues filtered (claimable=triaged or RFC label; exclude needs-triage/rejected/needs-info/superseded)→take one sequentially in ascending issue number order (fair, oldest first), with attempted preventing collisions. Each dev claims one issue per round (N devs = N issues/round); when backlog exceeds capacity, unclaimed issues naturally carry into the next round (unresolved/unclaimed issues remain open and can be claimed next round, with no attempt marker or stuck bottom placement). Budgets are tiered by kind: separate tiers for bug/feature/chore/document + highest tier for RFC (env overrides, increased relative to 0020), without retry escalation. Reuse cascading closure from 0020: issue advances → close the raw issues it covers (resolved by default); RFC advances → also close its covered triaged issues (two levels)."
    acceptance: "Devs claim only triaged/RFC issues, skipping needs-triage/rejected/superseded; take one in ascending issue number order; attempted prevents collisions across devs; budgets tiered by kind, RFC highest; when backlog exceeds capacity, unclaimed issues remain open (claimable next round); no remaining pick_policy/attempt/stuck mechanisms; advancing an RFC triggers two-level cascading closure; unit tests cover filtering/order/backlog/budgets/two-level closure."
  - id: T6
    title: "Orchestration wiring: two agents in phase d, triage→architect + round pass-through + mechanism-derived priority + roster"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/loop/roster.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_roster.py
    scope: "Split orchestrator phase d into two steps—run triager first (all triagers), then architect (all architects), both before b. Pass round_no through to sim (to stamp the round number) and both agents. Add triager staffing to the roster (N_TRIAGERS defaults to 1), remove load_dev_pick_policies(0020/T3). run.py constructs Triager + Architect(architect) and injects them into the orchestrator; change budget env vars to be kind-based (DEV_BUDGET_BUG/FEATURE/…/RFC). (Priority has moved to the triage agent assigning P0-P3 labels; see T3. This task no longer derives it through a mechanism.)"
    acceptance: "Phase d runs triage before architect, both before b; both agents receive round; roster provides the triager count, with no pick_policy; budgets tiered by kind + RFC highest; tests cover ordering/round/roster/budget tiers."
  - id: T7
    title: "web+metrics: attach kind/round/status/priority to issues + curve tracks actionable backlog (including carryover)"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/web/api.py
      - backend/ahe_beta/loop/metrics.py
      - backend/tests/web/test_api.py
      - backend/tests/loop/test_metrics.py
    scope: "api: Each issue includes kind(type/RFC), round, triage status(needs-triage/triaged/rejected/needs-info/superseded), priority, covers/covered_by(single value), and rejection reason; /api/issues supports frontend grouping. metrics: issue curve definition=open triaged issues + RFCs (actionable backlog, including carryover across rounds), excluding needs-triage(unprocessed) and rejected/needs-info(already declined). The curve's \"backlog not decreasing\" is exactly what the CLAUDE.md observation metrics should track (a degradation signal)."
    acceptance: "Issues include all new fields; the curve counts only actionable backlog (including carryover); rejected issues include reasons; covered_by is a single value; test_api/test_metrics cover the new fields and counting definition."
  - id: T8
    title: "Frontend: issue list by type/status + RFC section + coverage/supersession/backlog display"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T7
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/SidePanel.tsx
      - frontend/src/components/detail/IssueDetail.tsx
      - frontend/src/lib/issueMeta.ts
      - frontend/src/types.ts
      - frontend/src/api.ts
    scope: "Refactor the SidePanel issue section: display issues grouped by status/type (untriaged / triaged backlog / rejected), with a separate, prominent RFC section showing the issues it covers/replaces; display kind/priority/round badges for issues, plus a coverage chain (covered by a design issue), rejection reason, or superseded marker. IssueDetail displays all fields. Add kind/round/status/priority/covers to types/api."
    acceptance: "In mock mode, group issues by status/type, highlight the RFC section, mark superseded issues, show the age of backlog items, and include all badges; gracefully degrade without crashing when fields are absent (legacy backend); `npm build` passes."
  - id: T3a
    title: "Add `set_labels` to tracker: replace an issue's labels as a complete set."
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/tracker/base.py
      - backend/ahe_beta/tracker/gitea.py
      - backend/ahe_beta/tracker/fake.py
      - backend/tests/tracker/test_fake.py
      - backend/tests/tracker/test_gitea.py
    scope: "Add `set_labels(number, labels)` to the IssueTracker protocol to replace an issue's labels as a complete set (triage needs to remove `needs-triage` and add `triaged`). GiteaTracker: ensure the labels exist and obtain their IDs, then `PUT /repos/{o}/{r}/issues/{n}/labels {labels:[id…]}`. FakeTracker: replace the labels on the in-memory issue. Align with Gitea semantics (replacement rather than incremental updates; callers compute the target label set themselves)."
    acceptance: "After `set_labels`, the issue's labels equal the specified set (old labels are removed and new ones are added); unknown labels are ensured first; a nonexistent number raises `KeyError` (Fake); Gitea uses `PUT labels`; unit tests cover replacement semantics and `FakeTracker`."
---

# 0025 · Issue Triage Funnel: User Submits an Issue → Triage Agent Classifies and Localizes It → Architect Agent Produces an RFC → Dev

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is the group-level, nine-section rust-RFC overview. -->

## Summary

Build the issue flow into a real software team’s **triage funnel**, and split the existing **single architect into two agents**—corresponding to the two distinct hats of support/triage and architect in the real world.

- **⓪ Product/direction layer = distill card library (human, not an agent)**: the persona×seed distribution determines “what usage the harness should optimize for.”
  Already present in the code (`run.py` layer ⓪ loads `persona_library.json` / `seeds.json`).
- **a · User sim**: fills in **user-visible fields** according to the user-side template to produce raw issues (type label + `needs-triage` + round number),
  and stores experience + god-view traces.
- **d1 · Triage agent (new)**: handles each issue by **classifying** (confirming the type) + **localizing** (reading harness code + using `get_session_timeline`
  to retrieve the real trace, then filling in TRIAGE section fields) + **deduplicating** + **rejecting/requesting more info**. Augments in place; does not create another issue.
- **d2 · Architect agent (the original architect, with a narrower scope)**: only performs **cross-issue structural synthesis**, producing an **RFC** (a separate label that supersedes type, consolidates/supersedes local issues, and gets the highest dev budget).
- **b · Dev**: each round, devs claim triaged issues + RFCs according to capacity (N devs, each claims one); **if the backlog exceeds capacity, unclaimed items carry over to the next round**.
  Budgets are tiered by kind; remove 0020’s pool separation/retry/stuck mechanisms.
- **No agent for the PM function**: priority is derived mechanically from **experience impact + runtime_agg frequency**.

**Carryover is the norm**: one round = newly triaged issues this round + uncleared backlog from the previous round. The observed curve (actionable backlog) rises and falls as items accumulate and are resolved—that is exactly what the metrics observed in CLAUDE.md should track (a long-term rise indicates degradation).

## Motivation

**Testing exposed gaps at two levels.** ① “Issue” is used incorrectly: user sim outputs and architect proposals are both called issues, distinguished only by label, and displayed side by side in the frontend—conflating **raw user feedback** with **actionable work items**. ② One “architect” agent handles both **item-by-item grooming**
(triage) and **finding root causes across items** (architect); these two cognitive tasks are bundled into one prompt, and the triage half is barely done—the user’s
issues go straight into the backlog as free text, so devs work directly from raw reports, making overfitting likely and implementation difficult.

**Real teams have two distinct hats**: support/triage clears the inbox item by item (classification, localization, deduplication, rejection); the architect writes RFCs across items (structural root causes). This is an industry-recognized practice (Kubernetes needs-triage→accepted + KEP; GitHub triage + RFC). This group **splits the architect into these two agents**, with distinct responsibilities and clear data boundaries (also allowing room to scale triage horizontally in the future).

**Triage can now localize issues**: main has just landed `session_timeline`—triage/architect agents can call `get_session_timeline` by issue number
 to retrieve the **real god-view trace** (`architect/session_timeline.py`). Triage’s “localization” is therefore grounded in three sources: user-reported symptoms + read-only harness code + real traces. The previous concern that “triage can’t see traces and has to make things up” is resolved.

**The product layer already exists in code and should remain human-operated**: the persona/seed card library in `run.py` layer ⓪ is the product judgment about “which usage distribution to optimize for,”
provided by a person through the CLI. It sets the goals and value, which cannot be derived from experience internally (experience is measured relative to the current distribution), so **there is no agent for it**.

## Guide-level explanation

One closed-loop round (compare spec-0007 a→d→b→c; the d stage now has two agents):

- **⓪**: Load the persona×seed distribution from the distill card library (by a person through the CLI).
- **a · User sim**: A persona fills in the user-visible fields in the **USER section** according to `issue_schema` (bug: reproduction/expected/actual;
  feature: background/goal/scenario), with quality varying by persona (experts provide details, blind users are perfunctory). The sim creates an issue: body=rendered USER section,
  label `[<type>, needs-triage, round-N]`. It also stores experience + sim_trace (god-view) in the store.
- **d1 · Triage agent** processes each `needs-triage` issue (including issues from the previous round’s backlog that are still untriaged):
  1. **Classify**: confirm or correct the type label.
  2. **Localize**: read harness code + `get_session_timeline(issue_number=…)` to retrieve the real trace → fill in the **TRIAGE section**
     (root-cause area/boundary/acceptance criteria), through `issue_schema.validate`.
  3. **Deduplicate**: compare with existing triaged issues; if duplicate → close it and link it to the primary issue.
  4. **Reject/request more info**: insufficient information / out of scope / platform issue (such as one requiring changes to the launcher) → apply the `rejected`/`needs-info`
     labels + provide a reason + close; **do not create zombie tracking issues**.
  After processing, remove `needs-triage` and add `triaged` (**augment in place; do not create a separate design issue**).
- **d2 · Architect agent** (the original architect): finds root causes across issues using the **groomed (triaged) backlog (including carryover)** + experience curve +
  runtime_agg + traces, and produces an **RFC** (label `RFC`, superseding type): RFC fields go in the RFC section; `covers` the
  local triaged issues it synthesizes, and those synthesized are marked `superseded-by #RFC` (excluded from the set dev can claim). Better to produce none than to produce a weak one (no theme →
  `[]`). **Do not split work across rounds** (one RFC for a large requirement; assume an individual item can be fixed in one round, without splitting it across rounds).
- **b · Dev**: each round, N devs each claim **one** claimable issue (`triaged` or `RFC`, excluding needs-triage/rejected/
  needs-info/superseded), in ascending issue-number order (older first); `attempted` prevents collisions. After a fix → also close the issues it covers
  (two RFC levels: RFC→triaged→raw). **If the backlog exceeds N, unclaimed items remain open and carry over to be claimed next round** (no attempt/
  stuck mechanism—carryover is simply a collection of open issues that remain claimable next round).
- **c**: Refeed the main SHA.
- **Priority**: mechanically derive P0–P3 from **experience impact (issues from low-scoring sessions rank higher) + runtime_agg frequency**; it is not assigned by an agent.
- **Frontend**: group the issue list by status/type (untriaged / triaged backlog / rejected), show RFCs in a separate prominent section, and mark backlog age.
- **Observability**: track the issue curve for the **actionable backlog (triaged + RFC, including carryover)**—a decrease means dev is resolving items; an increase means new root causes or growing backlog.

**Distinguish the two meanings of “fixed in one round”**: **individual issue size** is assumed to be fixable in one round (increase the budget + rely on 0014; do not split across rounds); **backlog
quantity** is limited by dev capacity (N devs/round), so anything over capacity **carries over**—the two are not contradictory.

## Reference-level explanation

### Roles and I/O (all based on existing code anchors)

| Role | Input (source anchor) | Output | agent? |
|---|---|---|---|
| ⓪ Product layer distill | persona_library.json / seeds.json (`run.py:316,321`, supplied by a person through the CLI) | persona×seed distribution | No (human) |
| a User sim | persona + scenario + harness+manual + workspace (`sim_user.py:150-190`) | experience+raw issue+trace (`:196-203`) | Yes |
| d1 Triage (**issue normalization only**, single-item scope) | needs-triage issue (including carryover) + read-only harness code + `get_session_timeline` (single-session trace, **including that session’s experience score**) | in-place triaged issue (confirmed type + TRIAGE fields + priority) / close duplicate / reject | Yes (new) |
| d2 Architect (**PM + architect**, global scope) | all triaged backlog (including carryover) + **experience curve** (scores + reasons, with session_id,`architect.py:272`) + **runtime_agg** (`:184`) + traces | RFC (in-depth requirements analysis → structural/framework improvements) + supersede markers | Yes (original architect, narrowed scope) |
| b Dev | claimable set (triaged/RFC) + issue body + writable harness repo | git commit/tag/push + close related issues | Yes |

**Division of responsibility**: triage sees only **individual issues** (report + code + that session’s trace, **without** aggregate runtime_agg / global experience curve)—
priority is anchored to that session’s experience score. The architect alone has the **global view** (all normalized issues + full experience picture + runtime_agg) and performs the PM function of
in-depth user-requirements analysis, driving structural/framework improvements (producing RFCs). Priority has already been assigned to triage (see T3), rather than being derived mechanically.

### Canonical issue fields (T1)

`issue_schema.SCHEMAS` defines normalized fields in the platform layer. The unused USER template is retired; user reports remain free text.
`Field.key` is the only wire/parser identifier. `Field.label` is an English display heading and is never an accepted alias.

| Kind | Required keys | Optional keys |
|---|---|---|
| `bug` | `root_cause`, `boundary`, `acceptance` | — |
| `feature` | `boundary`, `deliverable`, `acceptance` | — |
| `chore` | `acceptance` | `boundary` |
| `document` | — | `acceptance` |
| `rfc` | `problem`, `root_cause`, `related`, `direction`, `acceptance` | — |

| Key | Display label |
|---|---|
| `root_cause` | Root cause |
| `boundary` | Boundary |
| `acceptance` | Acceptance criteria |
| `deliverable` | Deliverable |
| `problem` | Problem |
| `related` | Related issues |
| `direction` | Direction |

`validate(kind, fields)` checks the selected kind's allowed and required keys and rejects unknown keys and nonstring values.
Parsers consume the canonical dictionary directly, without Chinese or display-label aliases. `render` reads each `Field.key` and emits `### Field.label` headings in declaration order.
Tool `fields` properties are generated from the same declarations; changing a display label cannot change schema keys or accepted payloads.
Current PM and Architect role-specific submit payloads remain unchanged; their canonical projections use these normalized keys.

### Splitting the two agents (T3/T4)

- Triage: new `architect/triage.py` (driven by Triager) + `agent_defs/triage_agent/` (tools include read_file +
  get_session_timeline; workspace_jail has read-only access to the harness repo).
- Architect: narrow the Architect in `architect/architect.py`—remove “check for duplicates item by item and create issues”; focus on cross-issue RFCs; reuse
  existing backlog/trend/runtime/trace inputs (already available in `architect.py:180-270`).

### Carryover (backlog across rounds)

No retry/stuck mechanism—carryover is a collection of open issues that have not been claimed. Each round, devs claim N issues (N = number of devs) in ascending issue-number order; unclaimed items
naturally remain for the next round. Triage handles only issues with `needs-triage` (incremental); already-triaged carryover is not triaged again. The architect consumes the
**entire** triaged backlog (the accumulation of carryover is precisely the material it uses to find cross-round themes).

### Existing anchors

- `run.py:316,321`: loading the distill card library (product layer). `run.py:406,450,486`: sim/dev/architect construction point (make wiring changes here).
- `sim_user.py:114`: raw issues currently use `['bug']` free text — T2 changes this to structured fields + type + needs-triage + round.
- `architect.py:180-270`: propose_once/_run_agent (currently mixes triage and architect work in one agent) — split in T3/T4.
- `architect/session_timeline.py`: `get_session_timeline` (trace tool, used for localization in T3/T4).
- `agentic_developer.py`: 0020/T2 pool separation/retry/stuck — remove in T5.
- `loop/roster.py`: remove `load_dev_pick_policies`(0020/T3); add triager staffing.
- `web/api.py` `_annotate_covers`; `loop/metrics.py` issue curve — adjust in T7.

### DAG

```mermaid
graph LR
  T1[T1 schema]
  T2[T2 user sim structured issue]
  T3[T3 triage agent]
  T4[T4 architect agent RFC]
  T5[T5 dev simplification + backlog]
  T6[T6 orchestration: two agents+round+priority]
  T7[T7 web+metrics]
  T8[T8 frontend]
  T1 --> T2
  T1 --> T3
  T2 --> T3
  T3 --> T4
  T4 --> T5
  T5 --> T6
  T4 --> T7
  T7 --> T8
```

### File assignments (non-overlapping) are in each Task frontmatter `files`.

## Drawbacks

- **One more agent = one more LLM call + one more agent_def**: triage and architect each run once, making the d stage longer. Acceptable
  (triage can be parallelized later).
- **Triage is the sole interpreter + SPOF**: all raw issues depend on it for grooming. Mitigation: all triage actions are traceable, rejections include reasons, and raw issues are retained.
- **Carryover has no upper-bound protection**: a hard issue that dev repeatedly claims and fails to fix will consume one dev slot every round (0020’s stuck-
  sink has been removed). This group accepts that decision by the user (assuming an individual issue can be fixed in one round); truly hard cases are left for implementation by dev on a different repo (see Future).
- **Static product layer**: persona/seed do not expand automatically; exploration depends on people (an “issues reach zero” signal prompts people to expand the distribution). See Future.
- **Schema evolution cost**: adding a kind/field requires changes in the platform layer + frontend. Start with bug/feature + RFC.

## Rationale and alternatives

- **Single architect with two internal stages (previous proposal, rejected by the user)**: Change to **two separate agents**—triage and architect are two distinct roles;
  separating them clarifies responsibilities and allows triage to scale through sharding.
- **dev clears the entire backlog in one round (previous proposal, rejected by the user)**: Unrealistic—dev capacity is limited; uncleared work **accumulates** into the next round.
  Change to claiming work according to capacity, with carryover as the norm.
- **Retain dev retry/stuck/separate pools + splitting across rounds (0020/previous proposal, rejected by the user)**: Assume each item can be fixed in one round + increase the budget +
  use 0014 as a fallback; accumulated work is claimed again next round (open issues naturally carry over), without building retry/stuck.
- **dev reads raw issues directly (current behavior, rejected)**: Raw issues lack localization/acceptance criteria, making implementation difficult for dev and prone to overfitting.
- **Create tracking issues for platform/needs-information cases (rejected)**: Zombies with no one driving them forward. Change to rejection/needs-info + a reason.
- **Rely on Gitea ISSUE_TEMPLATE validation (rejected)**: Issues are created through the API throughout; Gitea forms only govern the Web UI. Change to a platform-level schema
  + separate sections filled by the user/triage + rendering in code.
- **Create a PM/product agent (rejected)**: The PM function = user experience signals (already the training objective); the mechanism can simply derive priorities. Product direction is a value
  judgment that cannot be derived from within user experience; leave it to humans (distill layer ⓪).

## Prior art

- **support/triage vs architect as two distinct roles**: Kubernetes needs-triage→triage/accepted + KEP; GitHub triage
  + RFC; Scrum refinement / Definition of Ready.
- **RFC / tracking-issue consolidation**: Structural proposals cover/supersede local issues.
- **spec-0020**: covers/dispatch — evolution in this group (mandatory coverage + simplified dispatch + RFC supersede + removal of retry).
- **spec-0016/0018**: architect root cause/envelope — retained by the architect agent.
- **spec-0024(godview-timeline)**: `get_session_timeline` — used by triage/architect for localization.
- **spec-0014**: Incremental commits — the dev-side fallback for "fix each item within one round".

## Unresolved questions

- **Priority derivation formula**: How user experience impact × frequency maps to P0–P3; start with simple rules and calibrate against actual measurements next round.
- **Whether triage and architect share the agent_def toolset**: Both need read_file + get_session_timeline; tool
  declarations can be reused, with only systemprompt differing.
- **Protection for difficult carryover issues**: Is a lightweight "reduce weight/flag after being claimed for N rounds without completion" mechanism needed (a minimal version of 0020 stuck)? This group will
  defer it and decide after observing the backlog curve.
- **Body representation of RFC supersede and covers**: RFC body `covers: #..` reuses the 0020 machine-readable lines + local issues receive the
  `superseded-by` label; consistency between the two is enforced by T4/T5.

## Future possibilities

- **Scale triage through sharding**: Large user volumes overwhelm triage context → map(batch triage)+reduce(deduplication); architect consumes only a bounded
  groomed set. The two-agent split already provides a boundary for this.
- **Product-level exploration mechanism**: The "zero issues = exploration has stopped" signal triggers humans (or a semiautomated process) to expand the persona/seed distribution, pushing the harness
  into new territory.
- **Integrate a developer agent for repository switching**: Replace the transitional dev-side implementation; address fine-grained collaboration for "large requirements/difficult issues carried over across rounds" at that point.
- **Automatic priority/budget calibration**: Use the next round's runtime_agg budget-limit hit rate as feedback to adjust budget tiers and the priority formula.
- **Extend the schema with chore/document + more fields**: Expand as needed.

