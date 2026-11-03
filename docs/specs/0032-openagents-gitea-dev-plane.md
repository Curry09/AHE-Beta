---
number: "0032"
title: "Switch the developer side to OpenAgents: separate the requirements and delivery planes + adapt the Gitea forge"
issue: 0
slug: openagents-gitea-dev-plane
summary: "The current developer side is a transitional implementation (as described by spec-0025/T5): nexau dev picks up ready issues and pushes directly to main, with no branches/PRs/reviews/CI; bad commits can only be corrected through subsequent rounds of iteration, and multiple devs must run serially because pushes to the same repository are mutually exclusive. OpenAgents (an RFC-driven multi-agent delivery framework in a separate repository) has refined the delivery loop of “issue→branch/worktree→spec→PR→CI→review→merge” into a level-triggered watchkeeper (vigil). Its execution-plane entry point happens to have the same name and meaning as the endpoint of our three planes (spec-0029): both use the `ready` label as the sole work-queue allowlist. This spec places the seam at admission: ahe-beta retains the requirements plane (user simulation→evidence→proposal→Owner as the sole admission authority), while OpenAgents takes over the delivery plane (ready→PR→merge). The two systems interact only through issue labels and main SHAs, with zero code coupling. Responsibility decision: disable OpenAgents' triager/admitter (admission already belongs to Owner, `stages.triage=skip`); curator/drafter/implementer/reviewer/deliver/merger/replier take over the delivery plane; retire our AgenticDeveloper + developer_agent entirely, and remove the dev beat from the orchestrator (step c retains its semantics of feeding back the main SHA, naturally supporting the PR merge model). Platform constraint: this repository's infrastructure runs on local Gitea (spec-0002), while OpenAgents' utils/github.py is entirely tied to the gh CLI—so add a forge dispatch layer to the OpenAgents repository (alias-import with zero call-site changes) + a Gitea REST driver (semantic mappings such as checks→commit status, blocked_by→issue dependencies, draft→WIP prefix, merge/update→Gitea pulls API). Upgrading direct trunk pushes to a PR gate does not violate held-out constraints: CI/review is an engineering quality gate (smoke tests in the harness repository, never running the benchmark), user experience remains purely observational, and the benchmark remains held-out throughout. Retire the vK tag system; the observation anchor is the merge commit."
tasks:
  - id: T1
    title: "OpenAgents repository: forge dispatch layer—alias-import seam + configuration section + merger prompt parameterization"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - OpenAgents/openagents/utils/forge.py
      - OpenAgents/openagents/utils/agent_config.py
      - OpenAgents/openagents/recipes/vigil.py
      - OpenAgents/openagents/recipes/stages.py
      - OpenAgents/openagents/recipes/backfill.py
      - OpenAgents/openagents/runtime/gates.py
      - OpenAgents/openagents/runtime/context.py
      - OpenAgents/openagents/utils/identity.py
      - OpenAgents/openagents/utils/release.py
      - OpenAgents/openagents/cli.py
      - OpenAgents/openagents/agents/merger.py
      - OpenAgents/tests/test_forge.py
    scope: "Create the utils/forge.py dispatch module: read the new `forge=github|gitea` section in `.openagents/openagents.yml` (default to github, transparent to existing users), import the corresponding driver module according to configuration, and delegate all public names through `__getattr__`. Rewire using alias-import: in 8 consumer files (vigil/stages/backfill/gates/context/identity/release/cli), replace `from ..utils import github` with `from ..utils import forge as github`, with zero changes to all `github.xxx()` call sites. Add the `forge` section schema to agent_config.py (gitea requires four keys: base_url/owner/repo/token_env; the token itself is read only from environment variables—maintaining the “do not store tokens” discipline). Replace hardcoded `gh pr merge` / `gh pr view` in the merger prompt with `$merge_command` / `$verify_command` placeholders, injected by the dispatcher (vigil) using command text provided by forge (the github driver supplies gh commands; the gitea driver supplies equivalent REST/tea instructions, or the stage performs the merge mechanically instead; see §Unresolved in the main text for tradeoffs). Scan prompts across the repository for gh references and parameterize them as well. Implement this task in the OpenAgents repository under a separate corresponding spec following its spec process; this is a mirrored description."
    acceptance: "forge falls back to github by default, and all existing tests pass (zero regressions for existing users); when `forge=gitea`, forge.* resolves to the gitea driver; the merger PROMPT contains no gh literals; hermetic tests do not access the network."
  - id: T2
    title: "OpenAgents repository: Gitea REST driver—the same public interface as github.py, targeting Gitea /api/v1"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - OpenAgents/openagents/utils/gitea.py
      - OpenAgents/tests/test_gitea_driver.py
    scope: "Create utils/gitea.py, implementing the github.py public interface actually consumed by the new vigil stack (see §4.2 in the main text for the function list: approximately 28 functions + Issue/PR/Comment/CheckStatus/Mergeability/PRSnapshot/CheckSnapshot/Blocker dataclasses reused directly from github.py definitions), all targeting Gitea /api/v1 (stdlib urllib, without adding a requests dependency to OpenAgents; align the exponential-backoff framework for transient errors with github.py). Semantic mappings: checks→commit combined status (/commits/{ref}/status); mergeable→PR.mergeable bool (false→DIRTY; see the main text for the UNKNOWN convergence strategy during Gitea's asynchronous computation); draft→WIP title prefix (mark_ready=remove prefix via PATCH); blocked_by→issue dependencies API; merge_pr→POST /pulls/{index}/merge; update_branch→POST /pulls/{index}/update; linked closure→closing keywords in the PR body (natively supported by Gitea); ensure_prerequisites→preflight checks for token presence + API reachability + repository write access (replacing gh auth status). Wherever empirical behavior of 1.22 endpoints differs, apply minimal semantic degradation and document it in driver comments (see the empirical checklist in §Unresolved)."
    acceptance: "Hermetic tests with a fake HTTP layer cover request shapes and response parsing for all public-interface functions; every semantic mapping has tests (including three-state mergeable convergence, WIP prefix round trips, and zero-status equivalence to zero-check); run one round of manual smoke testing against real Gitea 1.22 started by this repository's deploy/gitea (create issue→apply label→open PR→merge→issue closes automatically)."
  - id: T3
    title: "Admission handoff: Owner switches to applying the openagents discovery label, and plane READY incorporates {ready, openagents}"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/demand/issue_schema.py
      - backend/ahe_beta/demand/owner.py
      - backend/tests/demand/test_issue_schema.py
      - backend/tests/demand/test_owner.py
    scope: "Add `OPENAGENTS = \"openagents\"` to issue_schema (delivery-plane discovery label and handoff token for Owner admission); consolidate the READY plane classification in plane() as `ready | openagents` (admission is decided; issues awaiting or already under delivery-plane handling both count as the work queue); is_ready takes effect automatically through plane (after this proposal, only metrics/web read-side consumers remain). Change owner.py `_ready_labels` to produce OPENAGENTS (no longer apply READY directly)—reason: vigil `_intake` directly skips issues already labeled ready, and curator dependency ordering triggers only when there are new admissions in the current round; Owner applying ready directly would prevent curator from ever running and remove blocked_by protection for parallel workers. Leave all covers cascade merge/decline/hold semantics unchanged (Owner remains the sole admission point). Backpressure READY_DEPTH_ALARM automatically covers both labels through plane."
    acceptance: "After admit, the issue has openagents and plane==READY; after vigil applies ready, plane remains READY (idempotent); covers cascade regression tests remain unchanged and pass; no regressions in legacy label mappings."
  - id: T4
    title: "Retire the dev side: remove AgenticDeveloper/developer_agent and remove the dev beat from the orchestrator"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/dev/agentic_developer.py
      - backend/agent_defs/developer_agent/agent.yaml
      - backend/agent_defs/developer_agent/systemprompt.md
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/loop/roster.py
      - backend/ahe_beta/loop/live_tracer.py
      - backend/tests/dev/test_agentic_developer.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/loop/test_parallel_sessions.py
      - backend/tests/loop/test_roster.py
    scope: "Delete dev/agentic_developer.py and the entire agent_defs/developer_agent/ directory (responsibilities move to OpenAgents implementer+deliver+merger). orchestrator: remove the developer_agents parameter from ctor and remove the serial dev beat from run_round; keep step c feedback unchanged as a purely observational cursor for the latest main HEAD SHA (spec-0007 semantics, compatible with any actor advancing main—after this proposal, that actor is vigil's merge). roster: change the meaning of the developer count to delivery-plane concurrency K (mapped to vigil --parallel, default 1); retain the developer key for compatibility with env N_DEVELOPERS. Update tests accordingly: delete test_agentic_developer, change orchestrator tests to assert that there is no dev beat and that step c reads the SHA, and update roster tests for the new semantics."
    acceptance: "All backend tests pass; orchestrator run_round contains only the two generation beats in a + Owner admission + step c; no remaining AgenticDeveloper references in the repository (zero grep matches)."
  - id: T5
    title: "Wire up vigil: run.py writes openagents.yml, manages the vigil subprocess lifecycle, and retires vK tags"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/experiment/controllers/swebench.py
      - backend/tests/test_run_vigil.py
    scope: "run.py: after pushing the seed, write `.openagents/openagents.yml` in HARNESS_REPO (forge=gitea + base_url/owner/repo/token_env from deploy/gitea, finalized stages triage=skip / rfc=skip(initially; an explicit warning is acceptable) / conflict=agent / ci=skip(change to agent once T6 is in place) / e2e=skip / review=agent / merge=agent, labels=[openagents], interval=30, release=manual); start `openagents vigil --parallel K` using subprocess.Popen (cwd=HARNESS_REPO, K=roster developer count, stdout/stderr written to data/vigil.log), and terminate+wait with kill as a fallback when run exits. Integrate openagents as a standalone CLI (pin the version with uv tool install, do not vendor or import it; see deployment model in body §4.3); before startup, run.py checks that the `openagents` command exists. vigil's local state (sqlite queue, claims flock, and runtime-state under .openagents/) naturally resets on every run through rmtree in _seed_harness_repo, leaving no dirty state across runs. Retire the entire vK tag chain: dev budget env (DEV_BUDGET_*), _next_version/ls-remote tags logic, and update banner text. Platform note: vigil depends on fcntl.flock, so the delivery plane runs only on Linux/macOS (the Linux production environment meets this requirement); on local Windows, run unit tests only. Credential note: the delivery-plane coding backend is claude CLI (OpenAgents claude_code backend); DEV_LLM_* is no longer consumed, and the host must be logged in to claude CLI; pass the Gitea token to the vigil subprocess through the GITEA_TOKEN env."
    acceptance: "Unit tests (mock Popen) assert that yml contents match the finalized stages, vigil startup/shutdown and log paths are correct, and abnormal exits have a fallback; no vK remnants in the banner/budget env; manually smoke-test one complete round in the Linux production environment (Owner admit → vigil opens PR → merge → step c cursor advances)."
  - id: T6
    title: "Minimal CI for the harness repository: Gitea Actions runner + smoke workflow"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: true
    files:
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/gitea/bootstrap.sh
      - backend/harness_template/.gitea/workflows/smoke.yml
    scope: "Enable GITEA__actions__ENABLED=true in docker-compose and add an act_runner service (registration token handled through bootstrap.sh); include .gitea/workflows/smoke.yml with the seed in harness_template—minimal smoke test: start the entry subprocess, send one fixed message, and assert that it returns one line containing a valid JSON reply (do not run benchmark or call a real LLM; use stub model env). Enable the ci gate through env `VIGIL_CI_STAGE=agent` (skip by default—rule ⑦ in the vigil decision table states that zero checks means waiting for CI forever; verify empirically in the deployment environment that act_runner is actually running before enabling it, with a prompt in bootstrap.sh; this adds an empirical verification step over switching directly to agent as part of the task, preventing all issues from getting stuck until the watchdog intervenes when the runner is not ready)."
    acceptance: "After pushing to Gitea, commit status is visible and smoke passes; vigil assigns an implementer to rework PRs with failing CI (manually verify the fix-ci path once); unit tests cover the VIGIL_CI_STAGE override; set to agent after empirical deployment verification."
  - id: T7
    title: "Delivery-plane observability: GiteaTracker PR read path + web API + frontend delivery-plane view"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/tracker/gitea.py
      - backend/ahe_beta/web/api.py
      - backend/tests/web/test_api.py
      - frontend/src/types.ts
      - frontend/src/api.ts
      - frontend/src/lib/issueMeta.ts
      - frontend/src/App.tsx
      - frontend/src/components/SidePanel.tsx
      - frontend/src/components/DeliveryPanel.tsx
    scope: "Add the observational read path list_pulls to GiteaTracker (number/title/state/linked issue/head branch/mergeable/labels, read-only). Add a delivery section to web/api overview (open PR list + needs-human issue-count alert). Frontend: retire the developer column and add a delivery-plane panel (PR cards: issue number→PR→status; highlight the needs-human backlog—in the unattended loop, this is the only queue of stuck issues that requires human clearing). funnel/plane displays automatically become correct through T3's READY consolidation."
    acceptance: "api tests cover the delivery section shape; frontend tsc+build pass; the panel shows an explicit alert state when needs-human>0."
  - id: T8
    title: "Documentation wrap-up: CLAUDE.md architecture section and spec artifact regeneration"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: true
    files:
      - CLAUDE.md
    scope: "Update the CLAUDE.md architecture section: change the developer-side description from a nexau agent with git tools pushing directly to main to the OpenAgents delivery plane (vigil): ready issues admitted by Owner are merged into main through branches/PRs/CI/review; CI/review serve as engineering quality gates, user experience remains purely observational, and benchmark remains held-out throughout; update the dev/ entry in the directory structure table. Regenerate OVERVIEW/ARCHITECTURE through spec render/graph."
    acceptance: "CLAUDE.md matches the actual state; spec validate/render/graph all pass with no drift."
---

# 0032: Developer-Side Track Switch to OpenAgents: Requirements/Delivery Split + Gitea Forge Adapter

## Summary

Split the closed loop into two halves: the **requirements side** and the **delivery side**: ahe-beta retains the requirements side (user simulation → evidence → proposals → Owner-only admission), while OpenAgents takes over the delivery side (ready issue → branch/worktree → PR → CI → review → merge). The two systems interact **only through issue labels and the main SHA**, with zero code coupling. The platform remains local Gitea: the OpenAgents repository adds a forge dispatch layer and a Gitea REST driver (alias-import with zero call-site changes). Our nexau developers (AgenticDeveloper + developer_agent) are retired as a whole, direct pushes to main are upgraded to PR-gated delivery, and the orchestrator's c-step feedback loop (a pure-observation cursor for the latest main SHA) retains its existing semantics.

## Motivation

**The current dev is an explicitly transitional implementation** (spec-0025/T5: “the dev side is a transitional implementation; it will be improved when a repository-switching agent is integrated”): claim the issue, checkout main → modify files → commit → tag → push, all in one direct-push flow. It has three structural shortcomings:

1. **No quality gate**: a bad commit lands directly on main and can only be corrected through subsequent rounds of iteration (gradient-descent style). This is workable with small step sizes, but there is no mechanism to prevent a single major breakage (for example, breaking the entry point); after that, every user session runs uselessly on a broken harness.
2. **No real parallelism**: multiple devs pushing to main in the same repository conflict with one another and can only run serially (the orchestrator calls dev work_one one beat at a time).
3. **No engineering closed loop**: there are no concepts of branches, PRs, reviews, CI, or conflict handling, so the intermediate states from issue to delivery are invisible and cannot be intervened in.

OpenAgents (an independent repository and RFC-driven multi-agent delivery framework) has refined this delivery chain across 60+ specs: level-triggered reconcile scheduling (a pure-function decision table that self-heals when any round is lost), true parallelism through worktree isolation, deterministic hard gates for head-advanced/evidence-stamp/round-cap to prevent agents from idling or lying, and a first-class needs-human exit. **Rebuilding this chain would be the greatest waste; connecting to it is the correct solution.**

The two prerequisite integration questions also happen to have clean answers:

- **How should overlapping responsibilities be divided**: OpenAgents includes an admission surface (triager triage / admitter human gate / curator dependency ordering), overlapping with our three planes' (spec-0029) triager/Owner. The ruling principle is: **admission responsibility already belongs to Owner (the three-plane single-admission rule remains unchanged), so disable the OpenAgents admission surface (`stages.triage: skip`) and retain only the non-overlapping curator** (dependency ordering, which we do not have and which is required for parallel delivery).
- **How should the platform be integrated**: OpenAgents' `utils/github.py` (all gh CLI wrappers) is the sole platform coupling point, and all consumers call module functions—one forge dispatch layer plus a Gitea driver is enough to switch platforms; none of the 195KB of orchestration logic in vigil needs to change.

## Guide-level explanation

### Split model

```
┌─ Demand plane (ahe-beta, round-based) ──────────────────────────────────┐
│ user sim ──report──▶ report plane                                       │
│ triager/architect/divergent ──proposal──▶ proposal plane                │
│ Owner sole admission (admit/merge/decline/hold + covers cascade)        │
│        │ admit = apply the `openagents` discovery label                 │
└────────┼────────────────────────────────────────────────────────────────┘
         ▼  Interface ①: issue labels (Gitea issue as the bus)
┌─ Delivery plane (OpenAgents vigil, level-triggered resident) ───────────┐
│ _intake: discover openagents issues → triage:skip directly marks ready  │
│          → curator arranges blocked_by dependency edges                 │
│ Execution plane: worktree/branch → (rfc) → implement → review loop      │
│          → deliver push → PR → conflict/CI/review gates                 │
│          → merger merges (Closes #N automatically closes the issue)     │
└────────┼────────────────────────────────────────────────────────────────┘
         ▼  Interface ②: latest SHA on main
  orchestrator step c backfill (pure observation cursor, spec-0007 semantics unchanged)
```

### Role ruling table

| Role | Ownership | Ruling |
|---|---|---|
| user sim / triager / architect / divergent / **Owner** | Requirements side (ours) | Retain as-is; leave spec-0029 unchanged |
| OpenAgents triager (single-issue contradiction self-check) | Delivery-side admission | **Disable** (`triage: skip`)—admission has already been completed upstream by Owner, so the benefit of double checking is negligible |
| OpenAgents admitter (reads whether a human has approved) | Delivery-side admission | Enable only for `triage: human`; in an unattended loop it is **naturally idle** |
| OpenAgents curator (dependency ordering for ready issues) | Delivery-side admission | **Adopt**—a capability we do not have, providing blocked_by protection for parallel workers |
| drafter / implementer / reviewer / deliver / merger / replier / tester | Delivery-side execution | Take over; tester (e2e) starts as skip |
| **AgenticDeveloper + developer_agent** | Legacy dev | **Retire as a whole** |

The boundary in one sentence: **the requirements side decides “what to do and what to do first,” while the delivery side decides “how to finish it and when it counts as finished”; Owner is the only admission decision-maker, and vigil is the only main advancement mechanism.**

### Admission handoff protocol (key details)

Owner admission does **not directly apply `ready`**; instead, it applies the `openagents` discovery label. The reason is that vigil's `_intake` directly skips issues that already have `ready`, while curator triggers only when “new admissions occurred in this round”—if Owner directly applied ready, curator would never run and parallel delivery would lose dependency protection. The flow is:

```
Owner admit ─▶ +openagents (-proposal, priority retained)
vigil _intake ─▶ discover (labels=[openagents]) → triage:skip → +ready → curator arranges edges
vigil execution plane ─▶ list_issues(labels=[ready]) claim work → … → merge (Closes #N closes the issue)
```

Our `plane()` READY-plane determination is incorporated into `{ready, openagents}`: as soon as admission lands, it is counted in the work queue (the metrics funnel, backpressure alerts, and frontend grouping consequently become correct automatically), and vigil subsequently applies ready idempotently with no visible effect. The covers-level joint merge still occurs in full at Owner admission; the delivery side only closes its own `Closes #N` issues, consistent with spec-0029's boundary that “dev only closes its own issues.”

### One-round walkthrough (after integration)

1. The requirements side proceeds as before: two beats of a generate → Owner batch-admits, with N issues receiving `openagents`;
2. On the next tick, the resident vigil discovers the new issues: applies `ready` and has curator add the blocked_by edges;
3. K workers claim unblocked issues: create worktree branches `openagents/issue-<N>`, implement, run the review loop, deliver and push, and open PRs;
4. Merge pipeline: conflict → CI (skip before T6) → review → merge; if any gate fails, dispatch implementer for another iteration; if it cannot proceed, apply `needs-human` and exit with a comment (a human clears it periodically);
5. The merge lands on main, `Closes #N` automatically closes the issue; in the next round, the orchestrator's c step reads the new SHA and feeds it back to the user side through the new harness.

## Reference-level explanation

### §4.1 OpenAgents forge seam (T1)

- **Dispatch module** `utils/forge.py`: read the configuration once, select the corresponding driver (github/gitea) using `import`, and delegate all public names through `__getattr__`.
- **Zero call-site changes**: the eight consumer files (vigil/stages/backfill/gates/context/identity/release/cli) only change their import behavior through `from ..utils import forge as github`; hundreds of `github.xxx()` call sites remain unchanged.
- **Configuration**: add a top-level `forge` section to `openagents.yml`; `gitea` requires `base_url/owner/repo/token_env`, and the token itself is read only from an environment variable (continuing the “OpenAgents does not store tokens” discipline, with gh delegation changed to env delegation). The default is `github`, so existing users experience no change.
- **Prompt parameterization**: the merger's PROMPT hard-codes `gh pr merge $pr_number --merge` and `gh pr view` (agents/merger.py); replace them with placeholders and inject the forge-specific commands at dispatch time; audit the entire repository for literal gh strings.
- Data classes (Issue/PR/Comment/CheckStatus/Mergeability/PRSnapshot/CheckSnapshot/Blocker) remain in github.py, and the Gitea driver imports and reuses them directly (imports do not trigger gh calls and are safe).

### §4.2 Gitea driver public surface and semantic mapping (T2)

The function surface actually consumed by the new stack (verified by grep; the remaining functions in github.py are outside the first batch):

Issue side `ensure_label / create_issue / get_issue / list_issues / issue_comment / list_issue_comments / issue_add_label / issue_remove_label / close_issue / list_blocked_by / add_blocked_by`; PR side `create_pr / pr_for_branch / list_open_prs / pr_head_branch / pr_snapshot / check_snapshot / check_status / check_logs / list_comments / post_comment / add_label / remove_label / has_label / mark_ready / update_branch / merge_pr / branch_ci_green / code_fingerprint`; preflight `ensure_prerequisites`.

| GitHub semantics | Gitea 1.22 mapping | Notes |
|---|---|---|
| checks API (check runs) | Commit combined status `GET /commits/{ref}/status` | The success/failure/pending/error status set converges to CheckStatus; **zero statuses and zero checks are equivalent** (decision-table item ⑦ “waiting for CI” → watchdog), so `ci: skip` is mandatory before T6 |
| Three-state mergeability (MERGEABLE/CONFLICTING/UNKNOWN) | PR `mergeable: bool` | false → DIRTY; the empty window while Gitea calculates in the background converges to UNKNOWN (conservatively wait; the next level-triggered tick self-heals) |
| Draft PR | Title `WIP:` prefix | `is_draft` = prefix detection, `mark_ready` = PATCH prefix removal |
| Native blocked_by dependencies | Issue dependencies API `GET/POST /issues/{index}/dependencies` | Curator edge creation/`deps_done` verification use this |
| `gh pr merge` | `POST /pulls/{index}/merge` | Merger placeholder injection (§4.1) |
| Update branch | `POST /pulls/{index}/update` | Advance a BEHIND branch |
| PR body `Closes #N` automatically closes the issue on merge | Gitea native closing keywords | The delivery-side issue-closing mechanism remains unchanged |
| `gh auth status` preflight | Non-empty token + API reachable + repository push-permission probe | Rewrite ensure_prerequisites |

The implementation uses stdlib urllib (keeping the OpenAgents dependency surface minimal at ruamel.yaml+jsonschema), with a retry skeleton (exponential backoff for transient errors) aligned with github.py. Whenever empirical behavior in 1.22 differs from the table above, implement the minimum semantic degradation in the driver and record it in a comment (see Unresolved for the empirical checklist).

### §4.3 Process model and lifecycle (T5)

**Two processes, two cadences**: the requirements-side orchestrator remains round-based; the delivery-side `openagents vigil --parallel K` is a **resident child process** (managed by run.py Popen, with cwd=HARNESS_REPO, terminate fallback to kill on exit, and logs written to data/vigil.log). The two sides do not need synchronization—vigil is level-triggered and accepts an issue whenever it appears; the c-step cursor always reads live main.

**World resets are clean by construction**: all of vigil's local state (SQLite work_queue, claims flock, runtime-state) is stored under `<repo>/.openagents/` and is zeroed on every run together with the rmtree of `_seed_harness_repo`; the Gitea repository is rebuilt by bootstrap. This is a practical advantage of local Gitea over the GitHub solution (GitHub issues cannot be batch-deleted, so a new repository must be created for every run).

**Platform/credential constraints**: vigil uses `fcntl.flock` for fatal-recovery cleanup—the delivery side can run only on Linux/macOS (production Linux satisfies this; Windows locally runs unit tests only). The coding backend is the claude CLI (the OpenAgents claude_code backend; the nexau backend is not implemented and will be added in phase two), and the host must be logged into the claude CLI; `DEV_LLM_*` is retired. The Gitea token is passed to the vigil child process through the environment.

**Deployment form**: OpenAgents is integrated as an **independent CLI tool** (`uv tool install --from <OpenAgents repository>@<pin> openagents`, pinned to a commit/tag containing the forge/Gitea driver), without vendoring its source into this repository or importing it as a Python package—the entirety of ahe-beta's dependency on it is the `openagents` command on the host PATH plus the Gitea label contract, with the process boundary naturally isolating crashes on both sides. Before starting, run.py performs an existence preflight for `openagents --help` and reports an error if it is missing (alongside the claude CLI preflight). The OpenAgents/ directory in this repository's workspace is only a local development copy (T1/T2 are implemented there according to that repository's spec workflow) and remains untracked; development iterations use `uv tool install --force --from ./OpenAgents` for immediate effect (uv tool uses a snapshot, so running without reinstalling would execute old code).

### §4.4 Finalized stages and gate semantics

```yaml
forge: gitea
gitea: { base_url: <deploy/gitea>, owner: <bootstrap>, repo: <harness>, token_env: GITEA_TOKEN }
stages:
  triage: skip      # Admission belongs to Owner (sole admission across the three planes)
  rfc: skip         # Initial phase: the harness repository has no spec toolchain (explicit warning acceptable; evaluate introduction in phase two)
  conflict: agent
  ci: skip          # Change to agent after T6 lands (zero checks would wait forever; see §4.2)
  e2e: skip         # Phase two
  review: agent     # Engineering quality gate (OpenAgents rejects review:skip+merge:agent—zero gates are not allowed)
  merge: agent
release: manual     # Unused; vK tags retired, observation anchor = merge commit
defaults: { interval: 30, base: main, labels: [openagents] }
```

**Relationship to held-out constraints**: spec-0005/0007 remove the **experience gate** (preventing the training signal from becoming a release gate); the CI/review brought back by this spec are **engineering quality gates** (preventing the harness repository from being broken), which are different dimensions. Harness-repository CI performs smoke tests only (with a stub model and no real LLM calls), **and must never run the benchmark**; experience remains pure observation, the benchmark remains held-out throughout, and the three constraints in CLAUDE.md remain unchanged. “Correct bad commits through multiple rounds of iteration” is upgraded to “reject bad PRs at CI/reviewer, so they do not land on main.”

### §4.5 Containment (in comparison with spec-0021/0022)

- **Credential surface does not expand**: All delivery-surface credentials = local Gitea token + claude CLI login. The blast radius remains this machine and local Gitea (the “no external credentials” posture from 0022 is preserved; this is one of the main reasons for rejecting the GitHub migration proposal).
- **The weakened jail must be acknowledged**: The claude_code backend is `claude -p` + acceptEdits, relying on prompt constraints (do not modify .claude/), and is weaker than the three-layer nexau workspace_jail defense in depth. Mitigation: worktree isolation naturally limits the change surface; the harness repository’s pre-commit boundary hook is installed with the seed (worktrees share hooks) and continues to guard against boundary violations such as “writing the tested project’s code into the harness repository”; network egress allowlisting remains an environment-level recommendation (left over from 0022 and out of scope for this spec).
- **The hard gates remain in force**: head-advanced/evidence-stamp/round-cap are OpenAgents deterministic hard gates, and `skip` cannot disable them. “The agent claims it is done but has not committed” is mechanically blocked on the delivery surface as well (consistent with our existing principle that “repository state is the ground truth”).

## Drawbacks

1. **Maintaining two repositories**: The forge layer and Gitea driver live in the OpenAgents repository (with a separate spec created according to its spec process), so CI in our repository cannot cover them; contract drift is guarded by OpenAgents’ own tests plus this repository’s T5 smoke tests.
2. **Reduced delivery-surface observability**: The dev step-by-step timeline (the StepTracer stream) is gone, replaced by PR-granularity observation (T7) plus vigil logs; needs-human dead issues require periodic human cleanup.
3. **Heterogeneous backends**: The harness being evolved uses nexau, while the delivery surface evolving it uses the claude CLI. This adds an environment dependency (claude login), and dev behavior is no longer controlled by DEV_LLM_* configuration.
4. **Latency**: Direct pushes (main advanced within seconds) become a PR pipeline (minutes, with multiple rounds of rejection potentially spanning several ticks); an issue admitted within one round may not be merged in that round. However, the c-step cursor semantics do not inherently require synchronization, so the loop remains unaffected.
5. **The delivery surface cannot run locally on Windows** (flock).

## Rationale and alternatives

- **Why cut at admission**: The two models naturally align at the `ready` label (the endpoint of our three planes = the entry point to the vigil execution surface, with identical names, meanings, and allowlists). Moreover, “issues/labels as the bus, with no centralized messaging mechanism” is precisely OpenAgents’ decentralized design philosophy, so no interface is invented.
- **Rejected alternative 1: Move the harness repository to GitHub (zero OpenAgents changes)** — rejected due to platform constraints: this repository’s infrastructure is on Gitea (spec-0002); migration would introduce external credentials (violating the 0022 containment posture), GitHub issues cannot be deleted in bulk, per-run repository creation adds operational burden, and it would introduce an external-network dependency. The user decided to retain Gitea.
- **Rejected alternative 2: Thin integration (reuse only prompts+engine+backend+worktree and implement Gitea PR orchestration ourselves)** — this would amount to recreating a mini-vigil in our repository, overlapping with the responsibilities of the OpenAgents orchestration layer (the very problem this change is intended to eliminate), while losing the resilience accumulated across 60+ specs (anti-spin fingerprints, watchdog, hard gates, rejection loops) in exchange for reusing only about 10 prompt files.
- **Why alias-import instead of a major forge Protocol refactor**: vigil is 195KB with hundreds of call sites; changing import lines is the only O(file count), rather than O(call count), solution. The distribution module `__getattr__` delegates to keeping the github.py public surface as the factual interface contract, without prebuilding an abstraction (Occam’s razor: do not pay for a “third forge”).
- **Why Owner opens openagents rather than ready**: See §Guide admission handoff. Preserving curator liveness is the sole reason; otherwise, merging the two labels would be simpler.

## Prior art

- OpenAgents’ own 60+ specs (the level-triggered reconcile architecture derived from Kubernetes’ first principle; the overall principle that “judgment belongs to the agent, mechanics belong to code”) — all delivery-surface semantics in this spec follow the current implementation and do not repeat its details.
- spec-0029 (single admission across three planes): this spec changes the route consumed by its “plane 3 work queue”; the admission model is unchanged.
- spec-0007 (pure trunk direct push): this spec acknowledges its self-described “transitional implementation” and upgrades the delivery channel, inheriting the cursor semantics unchanged.
- Gitea /api/v1 (1.22): commit status, pulls merge/update, issue dependencies, and closing keywords are all capabilities of the official API (T2 evidence).

## Unresolved questions

1. **Gitea 1.22 endpoint evidence checklist** (the first task when T2 starts): the shape of the issue dependencies API endpoint; whether the PR response has a draft field (otherwise use the WIP prefix approach); `/pulls/{index}/update` availability; and the mapping of combined status error/warning states. The actual deploy/gitea instance is authoritative, and the spec mapping table will be adjusted slightly based on the evidence.
2. **Mechanical merger vs prompt parameterization**: Whether the merge action under Gitea should simply be executed mechanically by stage code (more consistent with “mechanics belong to code”, but diverging from OpenAgents’ 0017/T3 tradeoff of “lifecycle actions belong to the agent layer + needs-human is the final exit”) — this will be decided together with the OpenAgents repository during T1 implementation. This spec defaults to parameterization (the smallest change).
3. **Whether to enable phase two of the rfc stage**: introducing a lightweight spec system into the harness repository (the drafter requires the spec CLI) — beneficial to the “structural improvement” objective, but it adds institutional overhead to the object being evolved; decide after observing delivery quality during the first month.
4. **needs-human cleanup cadence**: the handling interface for accumulated dead issues in unattended operation (T7 only provides alerts); whether to give Owner a recovery path to “read the needs-human reason → decline or rewrite and resubmit” will be deferred until runtime data is available.
5. **nexau backend**: The AgentBackend protocol is very thin (run(work_dir, task, context)→AgentResult), but OpenAgents’ “last-line JSON” output contract must be honored by the nexau agent. In phase two, add an adapter in the OpenAgents repository so that dev behavior can again be controlled by DEV_LLM_*-style configuration.

## Future possibilities

- nexau AgentBackend adapter (return the delivery surface to a runtime structurally identical to the requirements surface, supporting mixed-runtime comparison experiments).
- Connect the e2e gate: have the tester run a real conversation round against the harness for evidence collection (the evidence-stamp hard gate is already in place).
- Upstream the forge layer: if the Gitea driver proves stable, it can become OpenAgents’ official multi-forge capability (GitLab and others can be extended in the same way).
- Add delivery-surface metrics to metrics: PR rejection rounds, merge lead time, and needs-human rate — new observability dimensions for harness evolution health (alongside the issue curves).
