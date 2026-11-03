---
number: "0047"
title: "Parallel Experiment Runtime and Real-Model Authentication"
issue: 0
slug: parallel-experiment-runtime
summary: "Retain the current experiment identity, immutable manifest, isolated local infrastructure, and v2 lifecycle wiring; the old v1 commands, capacity protection, and authentication design have exited and been archived."
tasks:
  - id: T1
    title: "Current Experiment Identity and Isolation Contract"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0047-parallel-experiment-runtime.md
    scope: "Retain the current v2 experiment identity, resource ownership, immutable inputs, and auditable management boundary; the old v1 lifecycle, capacity leases, and authentication scheme have been retired by 0071."
    acceptance: "The current public workflow includes only check/prepare/run/status/logs/stop/resume/collect/destroy; the single-task limitation and differences between the two backends are explicit, and historical contracts are not current startup conditions."
  - id: T2
    title: "Immutable Manifest and Shared Identity Primitives"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/__init__.py
      - backend/ahe_beta/experiment/config.py
      - backend/ahe_beta/experiment/manifest.py
      - backend/tests/experiment/test_manifest.py
      - backend/tests/test_experiment_config_v2.py
    scope: "Retain the experiment ID, config hash, derived Compose project, and immutable manifest/journal primitives for use by the current v2 lifecycle; the old v1 configuration parser has exited."
    acceptance: "The manifest rejects overwrites and input drift; appended journal entries and recovered identities can be revalidated; current v2 configuration and manifest tests pass."
  - id: T3
    title: "Independent Local Infrastructure per Experiment"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/deploy/experiment/docker-compose.yml
      - backend/deploy/experiment/egress-proxy.conf
      - backend/ahe_beta/experiment/infrastructure.py
      - backend/tests/experiment/test_infrastructure.py
    scope: "Retain ownership checks for the Compose project, Gitea/egress network, and volumes for use by the v2 local backend; the current workflow does not start unregistered CI runners."
    acceptance: "Local resources are isolated by experiment, and incorrect labels are rejected; stop preserves data, while destroy affects only owned resources; infrastructure tests pass."
  - id: T4
    title: "Current v2 Lifecycle and Closed-Loop Wiring"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/runtime.py
      - backend/ahe_beta/experiment/cli.py
      - backend/scripts/experiment.py
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/experiment/controllers/swebench.py
      - backend/tests/test_run_vigil.py
      - backend/tests/test_run_swebench_closed_loop.py
      - backend/tests/test_experiment_cli_v2.py
      - backend/tests/test_experiment_lifecycle_v2.py
      - backend/scripts/e2e-spec-0047-parallel-experiment-runtime.sh
    scope: "Start the frozen controller through v2 check/prepare/run and management commands, reusing isolated infrastructure and recovered identity; the old create/plan/preflight/start/archive commands, singleton entry point, capacity protection, and authentication gate are no longer supported."
    acceptance: "Repeated startup does not create a second controller; stop and resume preserve the frozen identity; old commands are rejected before provider operations; current v2 CLI, lifecycle, and isolation tests pass."
---

# 0047 · Parallel Experiment Runtime and Real-Model Certification

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC overview in 9 sections. -->

## Summary

> Current contract after the 0071 cleanup: retain identity/manifest, local isolation infrastructure, and v2 lifecycle wiring; capacity lease/health implementation T5 and unimplemented real-model certification T6 have been removed from the living task list. Current entry points are constrained by 0069/0071 to check/prepare/run/status/logs/stop/resume/collect/destroy only, local+localhost or E2B+Gitea.com, with one session per task-package round. The v1 commands, shared model capacity, and mandatory certification gate in the original design below are historical context, not current support or acceptance commitments; the original implementation and records can be traced through research/inventory.json and Git.

Upgrade “running one closed loop” into a reusable experiment runtime. The operator submits only an experiment configuration containing no secrets, and the system derives
an independent directory, a pinned source worktree, a Harness starting point, Gitea/Runner/egress/Vigil containers, networks, volumes, dynamic ports,
model capacity leases, logs, telemetry, checkpoints, and an immutable manifest for that experiment, with a unified CLI for planning, preflight checks, startup,
observation, stopping, recovery, archiving, and explicit destruction. All writable resources use `experiment_id` as the naming and permission boundary; read-only images and seed
images may share layers by digest.

Before startup, the complete closed loop must also consume real-model certification bound to the exact OpenAgents SHA, Vigil image digest, Claude Code version, and model profile.
Certification is not a simple API smoke test, but behavioral acceptance testing of role protocols, real Git changes, and isolated Gitea
`issue → RFC → implement → test → review → PR → merge`. This allows multiple evolutionary lineages to run concurrently,
without requiring operators to repeatedly modify `run.py` global constants, Gitea `.env`, repository names, container names, or configuration mounts.

## Motivation

The current closed-loop implementation assumes “only one experiment on the machine at a time”: runtime data is fixed at `backend/data`, Harness at
`data/harness_sandbox/harness_repo`, Vigil configuration at `data/vigil_config`, and the default Vigil container name at
`ahe-beta-vigil`. If startup logic finds a running container with the same name, it reuses it directly. Gitea Compose also uses fixed container names, networks,
volumes, and host ports. These conventions are simple and effective for a single run; when two experiments run concurrently, they create risks of configuration overwrites, mixed logs, attachment
to the wrong container, shared OpenAgents runtime state, accidental claiming of another repository's issues, and stopping one experiment affecting another.

Previously, experiment scripts repeatedly overwrote module globals, copied runners, and temporarily changed repository and container names to avoid collisions. Every experiment required rechecking
which resources needed renaming, and recovery depended on the operator remembering a particular set of directories and processes. This operational knowledge never became a machine-enforced contract, making environment preparation
more expensive than experiment design itself and making “recoverable aggregation” easy to confuse with a “unified batch.”

Directory isolation alone is insufficient. Vigil holds a Gitea token; if multiple experiments share the same Gitea user, even when their configurations point to different repositories,
a real model may still cross the target repository boundary through the API. Shared Runners, queues, volumes, and fixed container names also create a common failure domain.
Formal evolution experiments therefore require strong project-level isolation by default, rather than merely separate repository names. Image layers can be safely reused, but writable state, credentials, and
lifecycles must be independent.

Another problem comes from the nondeterminism of real LLMs. Existing OpenAgents offline tests can demonstrate that the state machine, schemas, Gitea driver,
worktrees, and gate code work under a mock backend, but cannot demonstrate that the specified GLM will consistently return parseable structures, use tools correctly,
respect role boundaries, complete commits and pushes, or continue converging after a Reviewer requests rework. Historical runs have already shown discrepancies between expectations and actual behavior, such as “semantically correct but protocol-unparseable,”
“code pushed but misclassified by the wrapper,” and “the model did not use the markers required by the design.” Real models are part of the system,
and their critical behavior must undergo pre-release certification for formal experiments, rather than being discovered incidentally during a long run.

## Guide-level explanation

The operator creates a configuration for a new lineage, for example (source and asset pins must contain the actual values used in this verification):

```yaml
schema_version: 1
experiment_id: glm-evolution-e0
mode: full-evolution
source:
  ahe_beta_sha: <verified-controller-sha>
  openagents_sha: <verified-openagents-sha>
  nexau_sha: <verified-nexau-sha>
  harness:
    kind: git
    revision: <verified-harness-sha>
images:
  vigil: sha256:<immutable-digest>
  seed: sha256:<immutable-digest>
models:
  profile: glm-5.2-fp8-local
  user: glm-5-2-fp8-wangyiding-mlcoding
  harness: glm-5-2-fp8-wangyiding-mlcoding
  architect: glm-5-2-fp8-wangyiding-mlcoding
  delivery: glm-5-2-fp8-wangyiding-mlcoding
capacity:
  endpoint: glm-local
  user_parallel: 2
  delivery_parallel: 1
infrastructure:
  isolation: dedicated
retention:
  keep_on_stop: true
```

The configuration stores only identifiers, pins, and policies; endpoint URLs, tokens, and API keys are resolved at runtime through named secret profiles and must never
be copied into configuration, manifests, command lines, logs, or certification evidence. Formal experiments prohibit floating Git branches, `latest` images, or dirty host
worktrees. Typical CLI operations are:

```text
experiment create  --config glm-evolution-e0.yaml
experiment plan    glm-evolution-e0
experiment preflight glm-evolution-e0
experiment start   glm-evolution-e0
experiment status  glm-evolution-e0
experiment stop    glm-evolution-e0
experiment resume  glm-evolution-e0
experiment archive glm-evolution-e0
experiment destroy glm-evolution-e0 --confirm glm-evolution-e0
```

`create` only creates a fresh experiment root and an immutable initial manifest; it refuses if the target already exists. `plan` provides a read-only view of the directories,
Compose project, containers, networks, volumes, port policy, model capacity, and certification requirements to be created. Before any paid model call, `preflight` checks
source/image/seed pins, Docker capabilities, resource collisions, secret profiles, capacity leases, OpenAgents certification, and the Harness starting point.
`start` advances idempotently according to the journal; `stop` only stops processes and retains Gitea volumes, repositories, checkpoints, and telemetry;
`resume` resumes from this experiment's last completed stage. `archive` generates a read-only evidence package without destroying runtime state. Only `destroy`, confirmed with the full experiment ID,
can delete resources, and selectors must match both Docker labels and the specific resource IDs in the manifest.

By default, `dedicated` infrastructure starts independent Gitea, Actions Runner, egress proxy, and Vigil instances for each experiment. Docker image
read-only layers may be shared; the following writable or permission-bearing resources must not be shared:

| Resource | Parallel experiment policy |
|---|---|
| Experiment root, session, telemetry, checkpoint | Independent directories per experiment |
| Auto Architect/OpenAgents/NexAU | Read-only worktrees or images at exact SHAs |
| Harness repository and per-task workspace | Independent per experiment and per task |
| Gitea data, users, tokens, repos | Independent instance and volume per experiment |
| Runner data and job containers | Independent Runner and network per experiment |
| Vigil clone and `.openagents` state | Independent container filesystem per experiment |
| egress proxy | Independent container and allowlist configuration per experiment |
| Images and SWE-bench seed images | Read-only layers may be shared by digest |
| Model endpoint | May be shared, but a global capacity lease must be acquired first |

Docker dynamically allocates the Gitea host HTTP port, which is resolved and written to the runtime journal; containers always use the service alias within that Compose project.
Every Docker resource carries `io.openagents.experiment_id`, manifest SHA, and role labels. The system never reuses resources merely because
“the names match”; idempotent commands may continue operating on existing resources only when labels, image digests, configuration hashes, and manifest resource IDs all match.

The complete closed loop also requires an `certification.json`. It binds:

```text
OpenAgents SHA
+ Vigil image digest
+ Claude Code version
+ model profile hash / protocol
+ certification suite version
```

A change to any item invalidates certification. User-interaction-only mode may omit OpenAgents certification; whenever real delivery
stages after Triage are enabled, preflight must verify certification. Certification uses a tiny synthetic code repository and must not use SWE-bench or formal evolution tasks, to avoid turning
benchmarks into delivery test material.

## Reference-level explanation

### Exact Egress Authorization for the Model Gateway

In addition to default-deny behavior, T3's independent proxy retains the existing model service domains and the user-specified Boyue gateway
`35.220.164.252/32` on HTTP port `3888`. New authorization must match both address and port, without opening arbitrary external access or arbitrary ports.
Secrets still pass only through private profiles/process environments and are not written into Squid templates. A successful direct API call cannot replace verification through the proxy from the development container;
the current gateway uses plaintext HTTP, so the network link provides no TLS confidentiality, and this authorization does not constitute a production-grade network security commitment.

### 1. Experiment Identity and Directories

`ExperimentConfig` is user input, while `ExperimentManifest` is the system-frozen result; the two are separate. `experiment_id` permits only
lowercase letters, digits, and single hyphens, and must retain a short configuration hash suffix after normalization to avoid collisions caused by Docker length truncation.
The default experiment root is specified by `EXPERIMENTS_ROOT` and defaults to `../ahe-beta-experiments` outside the repository. Every resolved writable path
must lie within that experiment root; symbolic links, `..`, empty paths, the workspace root, and other experiment roots all fail closed.

```text
<experiments-root>/<experiment-id>/
├── config.yaml                 # User input snapshot without secrets
├── manifest.json               # Atomically created by create; cannot be overwritten afterward
├── journal.jsonl               # append-only lifecycle facts
├── checkpoints/
├── telemetry/
├── logs/
├── sessions/
├── workspaces/
├── source/
│   ├── ahe-beta/
│   ├── harness/
│   └── pins.json
├── infrastructure/
│   ├── compose.env             # No model/Gitea secret values
│   ├── runtime.json            # Dynamic ports and resource IDs
│   └── vigil-config/
├── secrets/                    # 0600, never included in archive/, logs, or manifest
└── archive/
```

The manifest records the configuration hash, Git SHA, proof of tree dirty=false, image digests, task/Persona/seed artifact SHAs, model
profiles, role-model matrix, sampling configuration, capacity budget, Compose project, isolation level, and certification hash. Dynamic facts are appended only to the journal;
the manifest must not be “updated” to pretend the starting point has not changed. Journal entries carry a monotonically increasing sequence, UTC timestamp, previous state, next state, action, resource ID, and
error classification; writes use temporary files/append locks, and when two processes concurrently create/start the same ID, only one succeeds.

### 2. Lifecycle State Machine

```text
ABSENT
  └─ create ─► CREATED
                 └─ provision ─► PROVISIONED
                                     └─ preflight ─► READY
                                                          └─ start ─► RUNNING
RUNNING ── stop ─► STOPPED ── resume ─► RUNNING
RUNNING/STOPPED ── archive ─► ARCHIVED
Any in-progress state ── failure ─► FAILED (completed stages retained; resume after inspection)
CREATED..ARCHIVED ── destroy --confirm <id> ─► DESTROYED
```

States are observed facts, not inferred from the existence of a single process. Each stage first writes intent, then creates resources, then writes
completion with objective resource IDs; if a process dies midway, the next command performs reconciliation using labels, inspect, and Gitea health. If resource ownership
cannot be proven, stop and request manual intervention; guessing or cleaning up by broad names is prohibited.

`stop` is a recoverable operation: it stops the demand side, log followers, and Vigil, but by default does not delete container volumes, remote branches, Gitea data,
workspaces, or capacity history. `archive` copies sanitized manifest/journal, session, usage, state, Git bundle/refs, Gitea
issues/PRs/comments, and container/image provenance, excluding secrets and credentials in working directories. `destroy` is the sole deletion entry point,
requires explicit confirmation, and must report each object deleted; recursive deletion by prefix or glob is not provided.

### 3. Infrastructure Isolation

Experiment Compose templates must not use `container_name`, explicit global network names, or shared named volumes. The Compose project
is fixed by the manifest; Gitea, Runner, proxy, and Vigil all reside in project-scoped networks. Gitea data and Runner data use
project-scoped volumes. The Gitea host HTTP port requests a random Docker mapping, and SSH is not exposed by default; when required, it also uses a random mapping.

Each instance bootstraps an independent owner and token. The token can access only that independent Gitea instance and is passed through a 0600 secret file or process
env; Vigil has only that instance's token, model credentials, and access to the project internal network. Vigil continues to run as a non-root user, with no host code
mounts, and clones the Harness repository itself; it mounts only the experiment's own OpenAgents configuration and entrypoint read-only. The egress proxy permits only domains declared by that model
profile, and its configuration hash is included in the manifest. Runner jobs may join only this project's CI network and must not join another experiment's network.

Shared images must be referenced by digest; tags are for human-readable display only. After startup, record the container's actual image ID and compare it with the manifest.
Source code uses a detached clean worktree created from an exact commit; the host repository's dirty state does not enter the experiment. Harness starting points such as v0/v1/v2
are explicit seed pins and must not be guessed from the host's current `backend/data/harness_repo`.

### 4. CLI and Closed-Loop Wiring

`ExperimentContext` replaces module-global singletons for experiment paths and container resources, providing at least `data_root`, `harness_repo`,
`harness_runs_root`, `sessions_root`, `vigil_config_root`, `vigil_container`, `compose_project`, Gitea host/internal
connections, model profiles, and telemetry context. `run.py` and the SWE-bench runner read these values from the context; when legacy entry points are not given
context, they retain the default single-experiment behavior and print a deprecation warning, but must not attach to resources managed by Experiment Runtime, or vice versa.

All CLI commands that change state first output a plan; `--json` provides machine-readable results. `status` displays experiment state, each container's health,
Gitea reachability, queues/PRs, current Harness main, model leases, error protection, and the latest checkpoint. `start` may start
`user-only`, `design-only`, `delivery-only`, or `full-evolution` by scope, but the scope must be declared in the initial configuration and must not be silently changed during resume.
Stage completion writes a checkpoint; task-level salvage must save each task under the same manifest/pins, and aggregate reports must explicitly identify a unified
batch or recoverable aggregation, without conflating the two.

### 5. Shared Model Capacity and Failure Protection

Docker isolation cannot isolate throughput on a shared GLM endpoint. `capacity.py` maintains a capacity lease
registry protected by an experiments-root-level lock. The endpoint profile declares total capacity units; experiment preflight requests the maximum budget based on user concurrency, design-role concurrency, Vigil concurrency, and protocol
overhead. Only lease holders may enter model stages. Leases contain the owner experiment, process/container identity, heartbeat,
requested amount, and expiration time; reclaiming expired leases must first verify that the corresponding process/container is no longer running, rather than deleting active leases based solely on the clock.

The first version reserves capacity based on each experiment's peak usage and does not build an intermediary proxy that rewrites OpenAI/Anthropic payloads. Each entry point mechanically maps the allocated budget to
`MAX_PARALLEL_USERS`, design shards, and `VIGIL_PARALLEL`; code must not bypass configuration to increase it on its own. When capacity is insufficient, `start` queues
or fails closed, as configured, rather than competing through retry storms.

`health.py` tracks rolling success rates, HTTP/transport categories, latency, consecutive empty responses, and records with no tokens per experiment; when protection is triggered, it pauses only
the current experiment and writes a checkpoint, without stopping the shared endpoint or other experiments. usage events must include experiment/run/round/task/role/
model/protocol, with queue time and API latency recorded separately. Shared failures of the model service itself remain an experimental limitation; reports must disclose whether other experiments shared the endpoint
during the same time window.

### 6. OpenAgents real-model certification

OpenAgents implements the live suite in its own repository under the corresponding Spec; this repository defines only the consumption contract. The live suite is excluded from default pytest,
requires explicit opt-in, and must use a dedicated temporary Gitea. It consists of three layers:

1. **Role protocol canary**: Drafter, Architect, Refiner, Implementer, Tester, Reviewer, and Merger each return real structured results for bounded inputs;
   each role must parse successfully on the first attempt three consecutive times, with correct required fields/schema/terminal states, without asserting specific wording.
2. **Real tools and Git canary**: In a tiny repository, have the model read an issue, modify designated files, run real tests, commit, and push;
   objectively assert the scope of changes, tests changing from red to green, HEAD advancing, remote head consistency, and the absence of fabricated results.
3. **Complete isolated Gitea loop**: A small synthetic bug must pass through real RFC, architecture, implementation, testing, review, PR, and merge twice consecutively
   without human intervention; at least one run must cover Reviewer REWORK or small-scale conflict recovery. Official experiment tasks or benchmarks must not be used.

Certification output retains only redacted objective evidence: the bound tuple, call counts, parsing results, tool names, commit/PR/merge SHA, test command exit
statuses, tokens/duration, and failure categories; it does not retain prompts, file contents, credentials in command arguments, or ordinary model reasoning text.
The content hash of `certification.json` is written to the experiment manifest. If any element of the certification tuple changes, the real suite fails to meet the threshold, evidence is missing, or
the model endpoint protocol does not match, experiments with delivery enabled are refused startup before any API call.

### 7. Parallel end-to-end verification

The final script is `backend/scripts/e2e-spec-0047-parallel-experiment-runtime.sh`. The offline layer creates two fake/model-free
experiments simultaneously and asserts that all paths, Compose projects, container labels, networks, volumes, dynamic ports, Gitea repos/tokens, Vigil state,
logs, and checkpoints differ; stopping, resuming, or archiving one leaves the other's state unchanged; incorrect labels and cross-experiment resource IDs are rejected.
After certification passes, the live layer starts two minimal complete loops, deliberately interleaves issues, PRs, logs, and stop/resume operations, and asserts that there is no cross-repository issue claiming, cross-volume
state, cross-log writing, or capacity oversubscription. Failed test environments are retained by default; only explicit test cleanup performs
precise destruction for the two recorded experiment IDs.

Task DAG and file ownership:

| Task | Responsibility | Main deliverables |
|---|---|---|
| T1 | Complete runtime and certification contracts | This Spec |
| T2 | Configuration, naming, manifest, and journal | `experiment/config.py`, `manifest.py` |
| T3 | project-scoped Gitea/Runner/proxy/Vigil | experiment Compose, `infrastructure.py` |
| T4 | Lifecycle CLI and contextualization of the existing loop | `runtime.py`, CLI, `run.py` wiring |
| T5 | Cross-experiment model capacity and experiment-level failure protection | `capacity.py`, `health.py` |
| T6 | Real-model certification consumption and dual-stack E2E | certification, live/e2e scripts and migration notes |

```text
T1 ─► T2 ─┬─► T3 ─► T4 ─┐
          └─► T5 ────────┼─► T6
               T3 ───────┘
```

## Drawbacks

A separate Gitea, Runner, and proxy for each experiment by default increases container counts, startup time, disk volumes, and the maintenance surface; although image layers are shared,
retaining multiple experiments for long periods still consumes substantial storage. Dynamic ports reduce collisions, but manual access addresses must be obtained from status/manifest; users can
no longer rely on remembering a fixed `localhost:3000`.

Experiment Runtime itself becomes a new infrastructure component. If manifest, journal, Docker reconciliation, capacity leases, and archiving
are not implemented rigorously, they turn previously explicit manual risks into hidden platform risks, requiring stronger fault injection and
dual-stack verification than an ordinary runner. Retaining legacy entry points also creates two paths for a time, requiring clear deprecated boundaries.

Real-model certification costs money and time, and models themselves are nondeterministic; three consecutive role canaries and two complete deliveries cannot prove that future
failures will never occur, only that the exact combination meets the minimum engineering contract. Certification tasks that are too simple may miss long-horizon problems, while overly complex ones become another expensive
benchmark. The first version accepts this limitation, using a minimal integration contract in place of capability evaluation.

Peak capacity reservation is conservative, so two low-load experiments may be unable to start simultaneously because the total budget is insufficient; however, it avoids request storms caused by relying on instantaneous averages.
The model endpoint remains a shared external failure domain; unless separate model replicas are deployed, parallel results cannot claim complete infrastructure independence.

## Rationale and alternatives

A separate infrastructure stack per experiment is chosen as the default for official experiments, rather than sharing Gitea and only changing repo names. Shared Gitea costs less,
but token permissions, Runner queues, volumes, service restarts, and out-of-bounds model access remain shared failure domains; it may serve as an explicit
`isolation: shared-dev` local short smoke mode, but cannot be used for papers or long-term evolution results.

Declarative ExperimentConfig + immutable manifest + append-only journal is chosen instead of continuing to maintain per-batch `run_*.py`
wrappers. Wrappers can override constants, but cannot provide unified collision checks, recovery, archiving, destruction, and provenance; configuration/manifest turns these
requirements into verifiable interfaces. A direct refactor into a Kubernetes operator was not chosen: the current scale uses single-machine Docker, and Compose projects
already provide sufficient naming and network boundaries; Kubernetes would introduce a control plane far beyond the requirements.

Dynamic host ports are chosen instead of computing fixed ports from experiment ID hashes. Hashes can still collide with existing non-experiment services and require central registration;
letting Docker allocate ports and writing the actual ports to the journal is more reliable. Stable service aliases are used inside containers, so application configuration does not depend on host ports.

Capacity leases + existing client concurrency wiring is chosen instead of implementing a transparent model proxy in the first version. A transparent proxy supporting both OpenAI-compatible
and Anthropic-compatible streaming protocols, usage, and retry semantics could easily alter the requests under test. Although peak leases are conservative, they do not touch payloads,
making them more suitable for establishing experiment isolation first. If finer-grained scheduling is needed later, a proxy can be added once request bytes and call ordering can be proven unchanged.

Real behavioral certification is chosen instead of expanding mock tests. Mocks still provide fast, deterministic default regression coverage; the live suite runs only when images/models/
protocols change and before official experiments start. Assertions target objective results such as schema, Git, tests, PRs, and merges, without requiring fixed
model output text, reducing false failures caused by random wording.

## Prior art

Docker Compose projects natively isolate default networks, containers, and named volumes by project name; this design adds manifest resource IDs
and custom labels to avoid inferring ownership solely from Compose naming. CI systems commonly use ephemeral environments/preview environments
to create separate service stacks for each change; the experiment runtime adopts the same lifecycle approach, but retains failed environments and evidence by default.

Experiment orchestration systems generally distinguish declarative configuration, immutable run manifests, and event logs; job schedulers also use resource reservation/admission
control to prevent parallel jobs from oversubscribing shared accelerators. The certification tuple resembles build provenance/attestation: only when the exact source, image, tool,
and dependency combination passes the prescribed tests can the artifact enter the next environment.

The repository's existing isolated Vigil verification scripts have already demonstrated the feasibility of separate container names, fresh Gitea targets, and read-only configuration mounts; the existing approach still shares
the Gitea service, network, and runtime directory. This design elevates those one-off verification techniques into a platform contract covering the full lifecycle with strong isolation by default, and adds
dual-stack concurrency and real-model stability gates.

## Unresolved questions

The first version commits only to Linux/WSL Docker Engine; file locking, dynamic ports, and permission semantics on native Windows Docker Desktop are outside the supported scope for official
experiments. Whether Runner job image caches are shared at the host level affects only performance; regardless of the choice, job writable layers and networks must remain
project-scoped.

Model endpoint capacity units must be explicitly calibrated by the deployment profile. The first version does not infer capacity automatically from historical latency or allow runtime
adaptive budget increases; after sufficient telemetry is collected, a decision can be made on introducing dynamic admission based on queues and latency. If separate GLM replicas are provided for each experiment
in the future, the endpoint profile can be marked dedicated to bypass global contention while retaining concurrency limits within each experiment.

The specific synthetic repository contents for the OpenAgents live suite are determined by its corresponding Spec, but must remain small, public, non-benchmark, free of historical experiment
answers, and version-pinned. Initial certification has no date-based expiration; any change to the exact tuple or suite version invalidates it. Whether to add periodic
recertification later will be determined by actual drift data.

## Future possibilities

Once the runtime is stable, a Web experiment console can be added to display all experiments' status, resources, model leases, costs, error protection,
Harness lineage, and certification through the same read-only API; all mutations still go through the same runtime commands, without duplicating lifecycle logic in the frontend.

Resource quotas and retention policies can be added: set CPU, memory, and disk budgets per experiment, automatically compress Git/Gitea evidence after archive, and reclaim
volumes after human approval. The manifest and certification can be combined into signable provenance to verify the origins of paper results or experiments reproduced
across machines.

If single-machine concurrency becomes a bottleneck, ExperimentConfig, manifest, labels, and the state machine can be mapped to remote Docker hosts or Kubernetes
namespaces; because experiment identity and resource interfaces are already independent of the current Compose implementation, migration need not change experiment semantics. Model capacity leases can also evolve
into a true global streaming scheduling proxy, but must retain protocol transparency and per-experiment auditing.

In the longer term, lineage-level controllers could be supported: create multiple model/Prompt/delivery-strategy branches from the same Harness v0, automatically compare user experience,
merge quality, tokens, and wall-clock time for each round, and use independent holdout evaluation; each branch would still be isolated by the experiment runtime in this Spec, preventing
lineage control logic from interacting with Docker/Gitea details again.
