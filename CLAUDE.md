Pull updates from the remote repository before starting local work.

## Project Design

### Foundation

1. New experiments use the unified local/E2B lifecycle. `harbor` is used only by independent held-out evaluation adapters and historical research.
2. Agents are implemented with `nexau`; Claude Code and Codex integrations are also supported.

### Project Documentation

Start with README.md. The unified entry for new experiments is backend/scripts/experiment.py (`schema_version=2`). Local Docker + localhost Gitea and E2B + Gitea.com share materials and lifecycle management. QuickStart, configuration, and the U1 tutorial have English and Chinese editions. Public `examples/experiments/` contains only validatable v2 definitions, including frozen task lists, multiple users on the same task, and mixed ordinary/SWE plans. Public U1/U4 examples cover both backends. A complete archive with the current continuation export can be inherited into a new run to add rounds through the same entry; see docs/tutorials/experiment-continuation.md and its Chinese edition. tools/dev/ contains diagnostics and replay tools, not experiment entry points. The shared credential template is examples/experiment.env.example. See docs/ARCHITECTURE.md for the current architecture and docs/specs/ for design contracts.

The Spec-0081 examples examples/experiments/u8-mixed-e2b.json, u8-direct-e2b.json, u16-mixed-e2b.json, and u32-mixed-e2b.json use the first 8, first 16, or all 32 tasks from the original task set. Experiments remain schema 2; container task packages use schema 3. All four groups start from the current builtin seed and run six rounds: R1–R5 include feedback and delivery; R6 is usage only. Simulated/direct counts are 6/2, 0/8, 12/4, and 25/7; Triager counts are 4/4/8/16; Architect and Divergent each have 1 instance. Owner is mechanical, grouping=false, user and Developer concurrency are each 4, E2B resources are 4 CPU/8192 MiB, and per-round official grading is disabled by default. Original personas are reused, with 5/5/8/15 distinct profiles. Each round, interaction_plan rotates the selected subset as a whole by 1; do not rotate all 32 tasks and then truncate. The U8 comparison differs only in six interaction overrides and the derived names/identities; all other conditions must match by deep comparison. Public model IDs are glm-5.3-flash for User/Harness and glm-5.3 for demand/delivery. The initial output allowance for User/builtin Harness/demand roles is 32768; the Claude Code client controls delivery output. Do not inject a 128k allowance or an internal endpoint. examples/tasks/evolution32/manifest.json and each task.json bind public image digests, input hashes, and recipes; never reconstruct initial states from completed work. See docs/tutorials/evolution32.md and its Chinese edition; the batch is examples/batches/evolution-four-e2b.json. Record materials, real environment/tool checks, the two-round model pipeline, and the four full six-round experiments separately.

After a single run starts, its cloud supervisor/controller runs independently, with a separate background collector on the management host. The collector handles status, collection, and successful-terminal cleanup only; it currently does not refresh E2B leases. 86400 seconds is the creation lease, not an unlimited lifetime. CLI resume requires the original VM to remain running; paused VMs require explicit provider recovery, and expired/deleted VMs are LOST. Do not silently replace a VM and call it lossless recovery. A batch uses a foreground supervisor rather than a detached monitor per member. Model limits are static capacity declarations; reserved_output_tokens does not change actual max_tokens. User/Harness input thresholds can be overridden; demand roles currently use fixed YAML thresholds. Do not describe static checks as dynamic token guarantees for every role.

Manage experiment lists through batch check/prepare/run/status/stop/resume/collect under the same entry. Members retain single-run identities and frozen configurations. Post-run objective session grading uses grade RUN_ID --plan PATH; SWE, Terminal, TUA, NL2Repo, and custom tasks are dispatched by independent plans. The old dataset argument is retired. For both backends, complete collect before grading in local Docker; --offline only validates inputs. Direct and simulated sessions share artifact collection. New sessions atomically save complete patches, artifacts, and receipts; do not fabricate missing artifacts or full predictions for frozen controllers that saved hashes only. Spec-0081 provides container sources, managed-service finalization, and original measurement collection. Official grader support for a task remains governed by its independent plan/adapter contract. Post-run grading writes an independent evaluation attempt without modifying Session, manifest, checkpoint, seal, or archive, and never feeds grading reports back into evolution. evaluation.official_grading remains false. These user-task results are separate from independent held-out Harness generalization evaluation. See docs/tutorials/post-run-grading.md and its Chinese edition.

Spec-0084 adds explicitly optional evaluation.session_grading. After each round's user artifacts are sealed and before feedback processing, an independent assessment-worker grades them with a private plan and Docker; this also runs in the final round. Only signed safe summaries with fixed fields enter demand and delivery. Hidden assertions, reference answers, and raw verifier logs remain with the external grader. This path shares the post-run grade implementation. Wait for missing workers; infrastructure failures are not scored 0; task failures do not eliminate or roll back candidates. Tasks and feedback used for evolution cannot also be claimed as held-out results. Configuration and real acceptance boundaries are documented in docs/tutorials/evolution-feedback.md; current reproducible checks are in docs/VERIFICATION.md.

Dual-mode feedback separately records task judgments, experience scores, issue attribution, and improvement opportunities. Missing observations remain null; accept does not mean task success, and successful sessions may produce zero Issues. During interaction, simulated users access the live workspace according to their persona. Competent/expert users may write tests, run commands, and modify code according to their collaboration style. main_final_check remains limited to four tool calls followed by a fresh judgment. Stop the Actor and writing processes and freeze artifacts only before terminal review; the terminal Reviewer reads a snapshot. Preserve user operations in sim_trace. Passing the final collaborative artifact does not automatically mean the Harness passed independently. Report plans and publication receipts support recovery without repeating the Actor/Reviewer. Execution contracts carry the initial objective through every role: Direct must not depend on a second user message; control messages do not renew the overall deadline; a declared 7200-second budget must not be truncated by an internal 1800-second fallback. Preflight model capacity from explicit configuration, without guessing unknown capacity; deterministic context overflow must not repeat an identical outer call. These boundaries do not preimplement context compression or a new early-stop strategy.

Convert old seed-card libraries and operator text to ordinary v1 packages through task import-seeds LIBRARY --output DIR [--seed ID ...] or task from-text --instruction PATH --id ID --output DIR --not-in-benchmark. Both support --interaction direct|simulated_user and the parent --json flag. Conversion makes no network calls, reads no model/provider credentials, and runs no setup. JSON output provides an absolute task_packages array: remove old workload.kind/task_package/interaction_plan fields before setting workload.task_packages. tasks.json is only an output-directory-relative index, not a new runtime entry. Inputs without a repo use scratch with an initial README, without answers. Do not copy oracle, env.test_cmd, gates, or provenance into the package or a sidecar. Old setup commands do not automatically lock dependencies; old images and external services are not automatically reproduced. Public examples/seed-inputs/ contains only small synthetic cards and user instructions explicitly outside benchmarks; the historical seven cards remain in the research archive. See docs/tutorials/seed-task-import.md and its Chinese edition; experiments still use check/prepare/run. Seed conversion and archive continuation are separate input features. Conversion and offline validation do not prove a real experiment on both providers or task success; see docs/VERIFICATION.md for current reproducible checks.

Engineering CI for local + localhost is opt-in through runtime.local.ci_enabled=true, disabled by default, and does not change old frozen runs. E2B CI is unsupported. runner_image and ci_job_image are optional and allowed only when CI is enabled; require explicit versions or digests, never :latest. Pin default images and actual image IDs per run; also pin the actual image ID of the internal docker:27.5.1-dind daemon recipe. The frozen Harness must contain an ubuntu-latest PR workflow. The backend verifies the dedicated runner identity and a real PR checkout/Python smoke before issuing a readiness receipt. context accepts only a matching verified receipt to set OpenAgents ci:agent; failure must not downgrade to skip. status/collect preserve CI readiness and the current main/PR SHA state, never reusing a green result for an older head. Each run owns a privileged Docker daemon, job storage, and tool cache. The runner connects through internal DOCKER_HOST, without mounting the host Docker socket or exposing a daemon host port; a job's host network belongs to the private daemon's network namespace. stop handles owned runners/jobs and stops the daemon while retaining recovery data. resume reuses the daemon/storage/registration and revalidates them. destroy removes execution resources and CI job storage only with ownership evidence, explicitly preserving Gitea and private runner-registration volumes. Registration credentials never enter ordinary archives. This configuration is for trusted Harness engineering code, not hostile-code isolation. CI calls no models and runs no benchmarks; it is separate from post-run SWE grade and held-out Harness evaluation. See docs/tutorials/local-engineering-ci.md and its Chinese edition, and docs/VERIFICATION.md for reproducible checks. Manual red/green comparisons are not evidence of automatic model repair.

### Current Archive Continuation

Create a new run using harness.source=continuation, workload.source=parent, and archive/sha256 provenance declarations. Do not edit the parent configuration and resume it. Inherit the parent's final-round pairings, materials, personas, and full sessions by frozen hashes; count means additional user rounds only. First handle parent feedback and delivery in the separate checkpoints/continuation-bootstrap recovery domain, then run this experiment's 1..N user rounds. Both stages share loop/feedback_pipeline. The final added round runs users and configured independent grading, without further demand or delivery. Parent sessions do not enter the child SessionStore index or new metrics. Reports enter the new repository through a source namespace/issue map; observations retain their identities and receive access grants again. Parent commit and child seed commit SHAs differ, but inventory reconstructs exactly the same tree. The collector must not infer final code from the working tree HEAD. The current export/schema and source validator are the sole contract; add no old-format adapter, forwarding script, or second supervisor. A child collect can be inherited again; logical round numbers accumulate, while grade/batch continue to use local round numbers. See docs/VERIFICATION.md for current checks. Zero admissions or offline contract tests are not evidence of real code delivery.

### Problem

Evolving directly from trajectories imports their specific features into the Harness, encouraging local fixes to individual failures rather than structural improvements. Optimizing benchmark scores directly creates overfitting.

### Core Idea: Separate Training Signals from Testing

- Evolution feedback comes from task judgments, experience, attribution, and improvement opportunities during use. Explicitly enabled per-round grading adds independent safe summaries. Optimize over a distribution of simulated real usage.
- Keep benchmarks held out; use them afterward to test whether experience-driven evolution improves actual capability.
- Held-out tasks and results never enter evolution. Materials already used as usage tasks with feedback cannot be called held out. Developer agents may make substantial changes; independent evaluation determines generalization.

### Method: Simulate the User Usage → Developer Iteration Loop

- **Distillation**: distill persona and seed-scenario libraries from real usage data: CC/Codex/NexAU logs, issue trackers, and community feedback. Derive personas from real data, not benchmarks, to ground experience signals and prevent training/test contamination.
- **a | User side**: use the Harness under each persona and the task's direct/simulated_user condition. Preserve actual trajectories, execution contracts, and four-axis feedback. Experience uses a shared 1–4 scale, with missing observations null. Issues come from frozen report plans and may be absent. Record independent grading and Reviewer judgments separately; filing a bug is not a substitute for determining task completion.

  SWE-bench scenarios use **one temporary container per session** under spec-0051, started from the same runnable seed image. Persona `read_file`/`run_shell` and the Harness operate only on the in-container repo; never `docker cp` it to the host. There is no 240-second whole-turn Harness timeout. A 90-second persona heartbeat decides whether to keep waiting or interrupt slow requests. Only actual crashes/infrastructure hard limits fail closed. Sessions retain subjective experience and acceptance decisions, but technical success requires objective results from the official SWE-bench harness in a fresh instance container afterward. Keep sessions and minimal audit events in session JSON, and objective results and acceptance relationships in independent grading reports. When per-round grading is explicitly enabled, only signed safe summaries enter subsequent feedback.

- **b | Developer side (delivery, current spec-0032)**: OpenAgents vigil runs as an independent persistent CLI process. Under spec-0063, coordination=soft by default; failures return to the ordinary queue. VIGIL_COORDINATION=off disables the prerequisite step. Owner-admitted issues carry the `openagents` handoff token. vigil discovers them and follows: apply ready → bounded lightweight prerequisites (shared mechanisms/soft ordering, without automatically setting blocked_by) → worktree/branch → RFC/architecture → draft PR → implementation → conflict/configured CI/e2e/review gates → merge to main. CI/review are **engineering quality gates**, using Harness-repository structure smoke tests and never benchmarks. They differ from the removed experience-based admission gate. Experience and per-round grading do not eliminate candidates, and held-out evaluation never enters evolution. PR gates reject bad changes before they reach main.

- **c | Closed loop (spec-0050/0062/0084)**: after Owner admission in a nonfinal round, **wait for this round's admitted issues to reach terminal states**: merged to main or explicitly blocked. Only then start the next user round. The final round still runs users and configured independent grading, without proposals or delivery. Attribute round N+1's experience relative to N to round N's sealed artifact. Any automation-failed issue, historical needs-human state, or timeout stops the experiment in that round; closing an issue does not erase failure. User sessions and delivery of multiple issues may still run concurrently within their respective round stages.

### Constraints

1. Held-out benchmarks never participate in training or release gates. Keep per-round feedback tasks separate from held-out evaluation.
2. Personas come from real data, not benchmarks or trajectories.
3. Experience and benchmark scores are observations. Delivery uses configured engineering quality gates; experience scores do not determine merges.

### Observation Metrics

Track issue counts over time to assess the balance between new reports and resolved issues. A persistently nondecreasing count suggests Harness degradation; reaching zero too early suggests insufficient persona diversity and stopped exploration.

### Open Questions

1. Calibrate the shared 1–4 experience scale across persona and task distributions.
2. Inventory real data sources for distillation.
3. Define sample sizes and regression analysis for experience observations: single-point versus distribution comparisons.

## Current Architecture

### Runtime: NexAU Demand and OpenAgents Delivery (spec-0032)

Demand roles share one NexAU runtime with different agent definitions (prompts + tools) under `agent_defs/`:

- **User agent**: plays a user, interacts with the Harness over multiple turns, and produces experience feedback and issues in the report plane.
- **triager / architect / divergent**: generators producing unclaimable proposals (the three planes in spec-0029).
- **Dual paths (spec-0060)**: PM goes independently to Owner; Triage goes through Architect to Owner. Architect's proposal/ready inputs exclude PM. Evidence grants derive only from filtered visible proposals. The paths meet only at Owner.
- **Owner / Delivery Router**: admits by default and applies `openagents`. delivery_overlaps coordinates shared work between the paths while preserving separate handoffs and acceptance; delivery decides implementation reuse. Only historical exact-deduplication compatibility remains. Owner does not choose implementation layers or collapse independent capabilities and acceptance goals.

Delivery is OpenAgents vigil, integrated as an independent CLI rather than vendored or imported, with the claude CLI coding backend. Gitea access uses its forge/Gitea driver (OpenAgents spec-0074). The two sides communicate only through issue labels (openagents/ready) and main SHA. Under spec-0033, **container containment is the default**: vigil runs in a dedicated deploy/vigil image, clones the Harness repository inside the container, and has no host mounts. It joins only the internal vigil-net; external access goes through an egress allowlist proxy for the Anthropic API. Claude credentials (ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN) and the Gitea token enter only through container environment variables. `VIGIL_MODE=subprocess` is for supervised host debugging or a whole-experiment E2B sandbox whose identity was verified by the unified entry. E2B delivery workers are in-sandbox processes. Spec-0081 container user tasks separately create Docker containers/service networks per attempt; do not confuse delivery processes with task environments.

> There is no experience-based gatekeeper role. Experience and per-round grading may inform corrections in later rounds, but do not automatically eliminate or roll back candidates. Held-out evaluation never enters evolution.

Independent held-out evaluation uses `evaluation.yaml` and `python -m evaluation`, supporting Harbor Index tasks, direct and simulated_user modes, and frozen Harnesses or native Agents. Environments live under evaluation/environments/, Harness integration under evaluation/harness/, and Index-specific helpers under evaluation/benchmarks/harbor_index/. See evaluation/README.md for installation and use. Backend session-artifact grading under backend/ahe_beta/evaluation/ remains independent.

### Evolution Target: Harness as a Launchable Program

Model the Harness as a launchable program with a black-box conversation contract, not as a single agent definition. It receives user messages and returns replies. Its own entry script determines whether it uses one or N NexAU agents and how they are orchestrated, allowing multi-agent Harnesses.

- The user side interacts only through `HarnessInterface` (send/reset/close), without knowing the internal structure.
- Each Harness supplies an `entry` and depends on NexAU independently of this repository's nexau_runtime; it may later be replaced by CC/Codex.
- Harness source is an **independent Git repository hosted in Gitea**, with main and per-issue delivery branches/PRs managed by vigil. Merge commits are observation anchors; the vK tag scheme is retired. `harness_template/` is the v0 seed, including `.gitea/workflows/smoke.yml` structural smoke CI, used to initialize that repository.

### State Storage

- **Issues/PRs → Gitea**: user agents submit through IssueTracker; Gitea owns numbering, states, labels, and comments. vigil takes over through openagents→ready, with PRs in the same repository and read-only observation through /api/delivery.
- **Experience + sessions → local storage**: data/sessions/ supplies experience curves and regression baselines.

### Closed Loop

loop/orchestrator runs demand processing. Each round runs users against the current origin/main snapshot, then configured independent grading. Only nonfinal rounds run the two demand stages, Owner admission, and a wait for this round's admitted issues to close without automation-failed/needs-human, before resolving the sealed SHA. The final round runs users and configured independent grading only. A blocked round raises RoundDeliveryBlocked and does not advance. vigil remains a persistent executor but does not overlap with the next user round. An ordinary TOTAL_ROUNDS=1 run does not start vigil. Continuation bootstrap uses shared delivery_required semantics, including when adding only one user round. loop/metrics records issue curves and the three-plane funnel. Reconstructable experiment slices are stored in backend/data/role_runs/<run_id>/ (spec-0049); _reset_to_initial must not delete them. Manage new and existing v2 experiments only through backend/scripts/experiment.py (spec-0069/0071). For new workload contract 1, the supervisor launches ahe_beta.experiment.controllers.unified. Old schema-2 module/script runs use their original archive recipes; do not add compatibility scripts forwarding to old entries. Prepared v2 runs must continue with frozen source; never replace their identities, hashes, or controllers.

### Directory Layout

All backend code is under backend/. Observations are available through the CLI and read-only JSON API; the frontend application and GitHub Pages deployment are retired. Project documentation, tools, and configuration stay at the root.

```text
backend/                 # Orchestration backend
  ahe_beta/              # Framework package
    experiment/          # v2 config, material freezing, local/E2B lifecycle and supervisor
      controllers/       # unified.py + feedback.py + runtime.py: shared assembly, not public entry points
    models.py            # Shared data structures
    nexau_runtime.py     # Shared role adapter: load and run one agent definition
    harness/             # Black-box interface and versioned Harness entry launcher
    user/                # user_agent, sim/WorkspaceRuntime, local fixtures, per-session Docker, session_store
    evaluation/          # Shared artifact collection, independent grading contracts, benchmark/custom adapters
    tracker/             # IssueTracker, Gitea/PR observation and fake tracker
    demand/              # Triage, Architect, PM, Owner and shared demand processing
    guards/              # workspace_jail + repo_guard + harness_boundary; no built-in developer role
    loop/                # Orchestrator, stage recovery, and experiment metrics
    web/                 # Read-only FastAPI observations: /api/overview, /api/delivery, /api/sessions
  tests/                 # Backend tests; root pyproject also includes evaluation/tests
  agent_defs/            # NexAU definitions: user_agent/, triage_agent/, architect/, divergent_pm/, owner/
  harness_template/      # v0 seed program: entry.py, agents/, params.yaml, smoke workflow
  deploy/gitea/          # Gitea + act_runner + egress proxy + dual networks and bootstrap
  deploy/vigil/          # Container containment: Dockerfile, self-cloning entrypoint and build script
  scripts/               # Unified experiment entry, offline demo, exports, CI and build checks
docs/specs/             # Project-level spec-driven-development source
examples/                # Current experiment definitions, task packages, persona library, credential template
evaluation/              # python -m evaluation; shared harbor/harness/environments and benchmark sources
tools/dev/               # Maintained probes, audits, replay and delivery verification
tools/spec-driven-development/ # Vendored Spec CLI
.experiments/            # Ignored experiment identities, frozen inputs and outputs
backend/data/            # Ignored runtime artifacts: sessions/ and harness_runs/
```

Root configuration includes pyproject.toml (covering backend), .github/, .gitignore, .commitlintrc.yml, and CLAUDE.md.

### Spec Roadmap

- **spec-0001, user side**: models, HarnessInterface + Fake, UserAgent, IssueTracker + Fake, local SessionStore, and run_session; independently testable without real Gitea or a Harness.
- **spec-0002, Gitea integration/infrastructure**: Docker/SQLite, tokens, labels, GiteaTracker, and Harness repository initialization.
- **spec-0003, initial developer side/loop, superseded by 0005/0007**: Harness launcher, developer_agent, test_agent experience gate, merge/tag release, orchestrator, and metrics.
- **spec-0004, Harbor execution and resumable checkpoints**: all agents run in one sandbox (plan A: an entire run is one Harbor task). Emit incremental checkpoints at round boundaries and resume idempotently from them. Preserve user/developer/orchestration intermediate state. Harbor wraps the outer rollout lifecycle; round-by-round conversations still use spec-0001's independent protocol.
- **spec-0005 / spec-0007, trunk-only developer side, superseded by 0032**: a NexAU agent with Git tools pushes directly to main. Remove fix branches, merge/release stages, and experience gating. Experience becomes observational; benchmarks remain held out. The latest main SHA becomes the observation cursor, a meaning retained today.
- **spec-0032, current OpenAgents delivery**: separate demand and delivery. Owner applies openagents; persistent vigil uses its forge/Gitea driver (OpenAgents spec-0074) for ready→branch/PR→CI/review→merge. Retire direct-push NexAU development. PR gates cover engineering quality; held-out constraints remain.
- **spec-0033, current delivery containment**: dedicated container, no host mounts, self-cloning Harness source; Gitea is the sole medium between the two sides. Internal networking and an egress allowlist implement spec-0021/0022's no-credentials/allowlisted-egress boundaries. Observe origin/main, because local main does not represent a server-side merge.

## Design Principles

1. **Occam's razor**: add no entities without need. Keep code and architecture minimal; build an MVP and iterate.
2. **Module separation**: give modules clear responsibilities and boundaries.
3. **Structured organization**: organize files into directories with a clear hierarchy.
4. **Evidence-driven work**: ground concepts, data, and conclusions in real, verifiable sources. Read the source and cite it where used; do not invent evidence.
5. **Outcome-focused work**: test and accept deliverables rather than stopping at code details.
6. **User-focused design**: confirm unclear requirements with the user during design.

## Technology Stack

- Python

## Code Conventions

- **Commit messages**: Conventional Commits, `<type>(<scope>): <description>`.
  - Types: feat / fix / refactor / chore / docs / test / ci / style / perf / build / spec (Spec authoring/revision).
- **Code checks**: Ruff, line length 100.
- **Git hooks**: lefthook, with pre-commit lint and commit-msg commitlint.
- **Git pushes**: set upstream on the first push with `git push -u origin <branch>`.
- **Automatic commits**: after each completed change, git add + git commit + git push without seeking confirmation, under the user's standing authorization. Explicit session instructions take precedence.
- **CI**: fix and push repeatedly until all checks pass.
- **Comments and docstrings**: write in English. Chinese editions and original source data follow their explicit preservation rules.
- **Python parameters**: positional-only parameters (`/`) are prohibited. Private functions (names starting with `_`, excluding dunders) must not have default parameter values; callers supply all arguments explicitly.
