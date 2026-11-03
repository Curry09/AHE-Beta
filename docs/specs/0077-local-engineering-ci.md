---
number: "0077"
title: "Local engineering CI runner lifecycle"
issue: 0
slug: local-engineering-ci
summary: "Optionally enable a local experiment-specific Gitea Actions runner, enable the OpenAgents CI gate only after readiness verification, and include resource ownership and cleanup."
tasks:
  - id: T1
    title: "Configuration materials and environment gating"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/schemas/experiment-v2.json
      - backend/ahe_beta/experiment/config.py
      - backend/ahe_beta/experiment/materials.py
      - backend/ahe_beta/experiment/context.py
      - backend/tests/test_experiment_ci_config.py
    scope: "Optional local CI configuration, workflow prechecks, and a CI environment that accepts only verified receipts"
    acceptance: "Disabled by default with legacy-hash compatibility; rejected on E2B; missing workflows or invalid receipts cannot start the CI gate"
  - id: T2
    title: "Dedicated runner and execution lifecycle"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/backends/local_ci.py
      - backend/ahe_beta/experiment/backends/local.py
      - backend/ahe_beta/experiment/infrastructure.py
      - backend/deploy/experiment/docker-compose.yml
      - backend/tests/test_experiment_local_ci.py
    scope: "Fixed images, Compose, registration, real PR probe, identity verification, and stop/resume cleanup"
    acceptance: "Ready only after the real current head succeeds; preserve diagnostics on failure; do not clean up other experiment resources; resume does not re-register"
  - id: T3
    title: "Bilingual engineering CI documentation"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/tutorials/local-engineering-ci.md
      - docs/tutorials/local-engineering-ci.zh-CN.md
      - docs/tutorials/seed-task-import.md
      - docs/tutorials/seed-task-import.zh-CN.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - README.md
      - README.zh-CN.md
      - CLAUDE.md
    scope: "Describe enablement, trusted code, and local scope, and update the capability audit"
    acceptance: "Chinese and English commands are consistent; clearly distinguish engineering CI from post-hoc scoring; do not overstate acceptance facts"
  - id: T4
    title: "Engineering status collection and end-to-end evidence"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/collection.py
      - backend/tests/test_experiment_ci_collection.py
      - backend/ahe_beta/user/sim/runtime.py
      - backend/tests/user/sim/test_process_cleanup.py
      - backend/scripts/e2e-spec-0077-local-engineering-ci.sh
      - .github/workflows/experiment-contract.yml
    scope: "Collect current commit status and CI receipts, offline regression, and real Docker PR red/green and lifecycle acceptance"
    acceptance: "A new head does not reuse the old green status; registration secrets do not enter the archive; real PR red/green, resume, and cleanup are recorded"
---

# 0077 · Local Engineering CI Runner Lifecycle

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is the group-level rust-RFC nine-section overview. -->

## Summary

Add optional engineering CI for local + localhost experiments. It remains disabled by default; when enabled, prepare fixed runner/job images, register a dedicated Gitea Actions runner, execute a real PR smoke test, and set the OpenAgents CI stage to agent only after identity and readiness receipts are verified. CI checks only Harness engineering structure; it does not call models or run benchmarks. CI remains unsupported on E2B + Gitea.com in this release.

## Motivation

The historical local Gitea deployment included act_runner and Harness's .gitea/workflows/smoke.yml, but the unified entry point only creates Gitea and the proxy with Actions disabled, so ci_enabled can only be false. When the CI gate is open, fixed OpenAgents reads combined commit statuses for the PR's current head SHA; zero checks or pending checks wait continuously, while failure enters fix-ci. Neither allowing true nor merely starting the runner process proves that checkout, the Node action, networking, and status reporting work. The old services also used a global network and container names, which do not fit the current per-run resource ownership, collection, stop, or resume requirements.

## Guide-level explanation

Set runtime.local.ci_enabled=true in the local configuration and continue using the existing check/prepare/run/status/stop/resume/collect/destroy lifecycle. Optional runner_image and ci_job_image must have a tag or digest, and the actual image_id is fixed during preparation. Existing configurations without this setting and frozen runs retain their original semantics. Preparation and run preflight add real Actions verification; failure preserves diagnostics and a clear error rather than degrading to skip. status reports CI state, registration identity, and execution evidence separately. stop pauses the runner and handles owned jobs; resume reuses the same identity and probes again; destroy removes execution resources while retaining explicitly listed Gitea and runner private volumes.

## Reference-level explanation

Configuration and freezing: ci_enabled is an optional boolean; E2B continues to prohibit local settings. When enabled, verify that the frozen Harness has an ubuntu-latest workflow capable of covering PRs. When disabled, do not introduce new default fields that would break old hashes. The default runner is gitea/act_runner:0.2.11, and the job image uses a fixed digest of catthehacker/ubuntu; preparation records the actual IDs.

Resources: each run has a dedicated runner service/data volume and ci network; do not introduce container_name or a global network. When disabled, do not create a runner. Runner shared cache is disabled; job containers receive run_id, config_hash, and CI role labels, with default capacity limited to one and the job image fixed for this run. The runner uses a run-specific docker:27.5.1-dind executor; that daemon does not expose host ports and is accessible only through the current dedicated ci network. The runner does not mount the host Docker socket. The job image is streamed from the fixed host image into the private daemon. The job's host network refers to the isolated daemon's network namespace, not the host network, and therefore can still access the same run's Gitea. act_runner's global task container names and act-toolcache names are isolated in their respective daemons and are not shared across experiments. The daemon image and containers/volumes are also verified by the current run label and image_id. The registration token is supplied only as a temporary secret input and must not enter ordinary compose.env, logs, public receipts, or the archive; the registration file is stored in a dedicated private volume, and receipts contain only non-sensitive registration ID/name/instance/labels.

Readiness: verify container labels, images, project network, registration identity, and independent daemon identity. Submit a minimal workflow to a dedicated technical probe repository and create a PR; real execution must show count>0 and success for the PR's current head before readiness is issued. The probe does not impersonate user feedback; deletion is limited to temporary probe repositories created by the current run. Registration/workflow/API failures or bounded timeouts fail closed. build_controller_environment outputs agent only when ci_enabled matches the verified resource receipt; otherwise enabled configuration errors and disabled configuration continues to skip.

Lifecycle: stop first terminates controller/Vigil, then boundedly stops the runner and handles CI jobs with dual ownership labels, after which it saves final forge/status/CI evidence and stops infrastructure. Resume does not re-register, change the image/network/runner identity, or omit readiness verification. destroy does not clean up by act-* name, global network, or containers from another run; it cannot declare DESTROYED until owned jobs are deleted. The reason and name for retaining the runner registration volume are written explicitly to the receipt; destroy removes its dedicated Docker data volume and all inner task/cache data after confirming that the daemon has stopped, while stop retains the volume for resume. If ownership cannot be verified or stopping fails, retain the resources and report an error. collect saves main-branch and PR-current-SHA status plus readiness for CI-enabled runs, does not make extra CI endpoint requests when disabled, and does not copy the runner's private registration file.

Work breakdown: T1 configuration/material prechecks/environment gating and corresponding tests; T2 image preparation, Compose, dedicated CI helper, backend lifecycle, and tests; T3 bilingual tutorial/configuration/migration audit; T4 forge status collection, end-to-end scripts, real acceptance, and CI workflow. T1/T2/T3 proceed in parallel against fixed interfaces, and T4 depends on the first three. Specific files are allocated separately by the frontmatter; the group-level spec and generated index are maintained by the coordinator. The end-to-end script is backend/scripts/e2e-spec-0077-local-engineering-ci.sh.

## Drawbacks

Enabling this adds image download, registration, and real Actions probe time. The dedicated daemon requires local Docker support for privileged containers and is intended for user-trusted Harness code; it isolates task names/cache between experiments but does not claim to be a secure sandbox against malicious PRs. Retaining the runner volume retains private registration credentials and it must not be uploaded as a public artifact. Current single-runner capacity is limited and does not provide cross-experiment capacity scheduling.

## Rationale and alternatives

Do not directly reuse the old global gitea/act_runner services because they would share account, network, and cleanup boundaries. Do not merely add ci_enabled=true because an OpenAgents gate with zero checks would wait continuously. Do not merge engineering CI into post-hoc SWE grade because engineering tests and benchmark/gold results serve different purposes. First migrate the local path with host Docker; E2B + Gitea.com has no equivalent hosted-runner contract, so it remains explicitly disabled. Keep runner logic in a helper to avoid placing registration, probes, and the complete state machine into the existing large backend.

## Prior art

The registration and fixed-workflow work in historical backend/deploy/gitea proves that the required building blocks exist, but global ownership is unsuitable for public runs. The current local toolchain's actual image_id, Compose labels, private provider.env, final forge evidence, and resume identity verification provide reuse boundaries. Fixed OpenAgents ci:agent is a status gate and red-light repair orchestration, not an executor.

## Unresolved questions

Regression acceptance found that existing attempt-timeout cleanup directly calls an optional Python pidfd API; it fails when the locked Python lacks that interface. T4 adds Linux x86_64/aarch64 native pidfd syscall compatibility, continues to obtain stable handles and reverify the nonce, and does not fall back to PID signals without handle protection. Unknown platforms or unsupported kernels retain failure diagnostics and do not claim cleanup success. This correction is a prerequisite for passing the existing required regression and does not change the workspace model.

There are no blocking product choices; this group's scope is fixed to local+localhost, disabled by default, and trusted user-owned code. Real acceptance distinguishes manually produced red/green technical controls from model automatic repair and does not claim the former as the latter.

## Future possibilities

E2B CI can be designed separately once an explicit hosted-runner service and identity contract exist. Appending rounds to historical artifact imports remains an independent migration; this group does not change the same-run identity or frozen controller during resume. Future work may add stricter CI execution isolation, multi-runner capacity, and custom labels, but must not restore the old global wrapper.
