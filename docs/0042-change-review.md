# Spec 0042 change-set review

Date: 2026-08-22

Experiment evidence is frozen in `/root/src/auto-designer-experiments/20260822-contract42-experiment-freeze.md`.
This review separates the current worktree changes into five independently reviewable boundaries. It does not treat the unrelated Spec 0041 usage-monitoring, frontend, or seed-image changes as part of Spec 0042.

## 1. Spec

Disposition: revise before merge.

Keep:

- Canonical flow: report → proposal → Owner → ready item.
- Role responsibility matrix and explicit supersession note for Spec 0029.
- ProposalView, progressive evidence retrieval, observable failures, and decision-graph validation as normative concepts.
- T6 remains in progress because mechanical replay passed but quality acceptance failed.

Required revisions:

- Do not claim five active prompt paths without distinguishing the shipped `agent_defs/user_agent/prompt.md` definition from the current simulator prompt assembly used by the production loop.
- Replace quality claims that are only prompt requirements with measurable behavioral acceptance. The replay demonstrated that task-independent wording alone does not prevent case-derived product rules or implementation-level prescriptions.
- Record that Gitea offers no transaction spanning EditIssue and label replacement. The current compensation logic reduces ordinary request failures but cannot make a process crash atomic.
- `OVERVIEW.md` is generated from every local Spec. Its current diff includes unrelated Spec 0041 content and must be coordinated rather than presented as an isolated 0042 change.

## 2. Tracker

Disposition: retain the API correction; harden recovery before merge.

Keep:

- Gitea EditIssue no longer sends the unsupported `labels` property.
- Label replacement uses `PUT /issues/{number}/labels`.
- Request failures are observable and ordinary second-step failures trigger compensation.
- The mock Gitea now follows the local 1.22.6 Swagger contract.

Required revisions:

- Remove `set_title` and `set_body` from the public protocol unless a real caller is identified; they currently increase API surface without production use.
- Add postcondition verification for critical migrations instead of assuming every 2xx response applied the intended state.
- Define reconciliation for process termination between the two HTTP calls. `update_issue` can otherwise leave normalized content on the report plane; `transition_issue` can leave a terminal label with the old state.
- Document or guard the snapshot race: compensation can overwrite a concurrent human edit made after the initial GET.
- Use a dedicated migration error carrying primary failure, rollback result, issue number, and observed post-state rather than a generic RuntimeError when rollback also fails.

## 3. Role contract and runtime

Disposition: data contract is useful; quality contract is not yet sufficient.

Keep:

- One ProposalView implementation shared by Synthesize, Divergent, and Owner.
- Raw report evidence stored outside the default proposal body.
- Triage failures/warnings and Owner invalid/failed outcomes.
- Owner validation that merge targets are existing ready items or successfully admitted proposals in the same batch.
- No mechanical admission bypass; `owner=0` means hold.

Required revisions:

- ProposalView currently forwards raw label names, including possible legacy workflow labels. Canonicalize metadata before it becomes model-visible.
- A single full-body projection is used for all three consumers. Divergent only needs a compact duplicate-reference view; Synthesize and Owner have different evidence needs. Preserve one canonical data model but add explicit projections rather than making every consumer read the same 3000-character body.
- The rewritten prompts are substantially shorter, but the replay shows that Synthesize still emits implementation details, case-derived trigger rules, and mixed abstraction layers. Define proposal invariants in the structured contract or a separate validation stage; do not add incident-specific wording or keyword blacklists.
- Owner admitted every structural proposal despite overlap and boundary violations. Its decision contract needs explicit, general rejection/hold dimensions for non-cohesive scope, implementation prescription, unsupported generalization, and duplicated leverage points.
- Keep System Prompt, runtime batch data, and tool description separate. Avoid reintroducing the same policy independently in all three locations.

## 4. Tests

Disposition: current regression suite is valuable but acceptance coverage is overstated.

Keep:

- Realistic Gitea mock behavior and rollback fault injection.
- Owner decision-graph tests and observable failure outcomes.
- ProposalView raw-evidence exclusion tests.
- Report → Triage → Owner behavioral test using opaque sentinels rather than incident vocabulary.

Required revisions:

- `test_role_contract_flow.py` does not execute Synthesize or Divergent, despite the Spec describing a full cross-role flow. Add a real stubbed flow through both projections and Owner.
- Add process-interruption/reconciliation tests, not only exceptions returned by the second request.
- Add exact-set assertions showing that all Triage proposal numbers reach Synthesize and Owner; count-only assertions can pass with the wrong issues.
- Add tests for canonical removal of legacy labels from model-visible ProposalView.
- Do not encode style governance as a list of prohibited incident words. Tests should assert data flow, authority, state, and validation outcomes.

## 5. Experiment tooling

Disposition: keep full replay after hardening; do not merge the recovery script as a general tool in its current form.

Keep:

- Fresh target repository refusal and explicit stop before OpenAgents.
- Reuse of saved sessions so user-simulation calls are not repeated.
- Structured summaries and agent event logs.

Required revisions:

- Validate that copied source issues are raw reports. The current full replay forcibly relabels any referenced source issue as report, even if its source body was already normalized.
- Record code revision, prompt hashes, source issue snapshot, model endpoint identity, and usage totals in the summary so a run is reproducible.
- Protect concurrent event logging with a lock or a single writer.
- Exclude generated `__pycache__` and `.pyc` files when seeding the harness repository.
- Create the output directory only after all preflight checks succeed, or write a failure manifest when setup stops partway.
- `replay_synthesize_owner_from_repo.py` mutates an existing repository, accepts arbitrary issue ranges, and does not persist a complete pre-mutation snapshot. It was appropriate as incident recovery but is unsafe as a reusable production script. Move it to experiment-local evidence or redesign it around an immutable source snapshot and a fresh target repository.
- The recovery summary lacks the final issue snapshot and lost the original Triage priority suggestions; it must not be used as a complete scientific record without the freeze note and Gitea state.

## Proposed review units

1. Spec-only: 0042 source, 0029 supersession note, generated Overview coordination.
2. Tracker-only: semantic migration API, Gitea-compliant implementation, recovery model, tracker tests.
3. Role-contract-only: ProposalView, Triage/Owner outcomes, role drivers, prompts, tool descriptions.
4. Tests-only: cross-role behavior, decision graph, legacy projection, recovery and real-contract fixtures.
5. Experiment-only: replay runner, immutable manifests, frozen results; incident recovery kept outside production tooling.

## Resolution status

The review findings were resolved as follows:

- The Spec now defines direction-level demand acceptance and leaves implementation readiness to downstream design and delivery review.
- ProposalView filters legacy workflow labels and exposes an explicit compact Divergent reference projection while retaining normalized detail for Synthesize and Owner.
- The public tracker protocol no longer includes unused single-field title/body mutations. Gitea migrations verify postconditions, avoid overwriting observed concurrent edits during compensation, and raise a structured `IssueMigrationError` containing the issue, primary failure, rollback result, and observed state.
- The cross-role test now executes Triage, Divergent, Synthesize, and Owner with exact issue-set assertions and no external model call.
- The full replay runner validates raw source reports before creating the target, serializes event writes, excludes generated bytecode, and records revision, prompt hashes, endpoint identity, source snapshots, and run-scoped usage totals.
- The incident recovery script remains untracked experiment evidence and is not part of the reusable Spec 0042 tool boundary.

Gitea still cannot provide an atomic transaction across issue-edit and label endpoints. The Spec now states this platform limitation explicitly and requires idempotent retry rather than claiming process-crash atomicity. This is a documented operational constraint, not a hidden correctness guarantee.
