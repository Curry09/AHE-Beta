---
number: "0044"
title: "Reusable SWE-bench Seed Workspace Provisioning"
issue: 0
slug: swebench-seed-workspace-supply
summary: "Provide isolated, auditable prebuilt workspaces for concurrent user sessions through explicit manifests, resumable build state, prebuilt workspaces, and storage-only Docker images; maintain per-task attribution in the closed loop and retain a git fallback path."
tasks:
  - id: T1
    title: "Manifest and Provisioning Contract"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0044-swebench-seed-workspace-supply.md
    scope: "Define explicit task pool manifests, instance_id uniqueness, storage boundaries, and instance ownership; the fixed medium_hard_16 task pool is archived and is not the default for current public experiments."
    acceptance: "The Spec defines replaceable task pools and the current v2 single-task boundary; the manifest format is verified by current build and provisioning tests, without depending on the archived task pool for startup."
  - id: T2
    title: "Isolated Prebuilt Copying and Virtual Environment Relocation"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/sources/prebuilt.py
      - backend/tests/user/sim/test_prebuilt_source.py
    scope: "Copy an independent workspace for each session from an explicit directory, skip stale virtual environment backups, and relocate safely identifiable venv text metadata from the build path to the session path."
    acceptance: "Missing sources fail explicitly; two provisioning runs do not contaminate each other; the original workspace is not modified; venv text references are relocated; relevant pytest and ruff checks pass."
  - id: T3
    title: "Storage-only Docker Seed Provisioning"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/user/sim/sources/docker_seed.py
      - backend/deploy/swebench-seed/Dockerfile
      - backend/deploy/swebench-seed/build.sh
      - backend/tests/user/sim/test_docker_seed_source.py
    scope: "Build storage-only images without an execution entry point; each provision uses a temporary container to copy only the specified instance workspace and build state, validates safe instance ids, and cleans up containers on all paths."
    acceptance: "Missing image/instance parameters, invalid path segments, and missing images/instances all fail explicitly; relocate the venv after a successful copy; temporary containers must be cleaned up; tests, ruff, and image structure verification pass."
  - id: T4
    title: "Resumable Batch Builds and Image Validation"
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
      - backend/scripts/build_swebench_seed_workspaces.py
      - backend/scripts/validate_swebench_seed_image.py
      - backend/tests/test_swebench_seed_builder.py
    scope: "Incrementally prepare workspaces in source/dependency stages according to the manifest, atomically write build state, and support single-instance recovery; parquet paths must be explicitly supplied through arguments or the environment; the validator extracts each instance and performs structure, venv, and import checks."
    acceptance: "validate-only does not build; completed stages can be skipped on resumption; failure states are auditable; no default local absolute paths; all manifest instances in the image pass validation; script tests and ruff pass."
  - id: T5
    title: "Closed-loop Task Pool Selection and Stable Instance Attribution"
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
      - backend/ahe_beta/experiment/controllers/swebench.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/tests/loop/test_sim_user.py
      - backend/tests/test_run_swebench_closed_loop.py
    scope: "The closed loop supports manifests, single-task smoke tests, and running every task once per round; a fixed seed produces reproducible plans; all three paths, prebuilt/docker-seed/git, carry instance_id into session and usage contexts, retaining git provisioning when no seed is available."
    acceptance: "Invalid single-task selections are rejected; in all-task mode, each instance appears exactly once per round and personas rotate deterministically; all three sources retain instance_id; concurrent sessions do not mix tasks; relevant pytest and ruff checks pass."
---

# 0044 · Reusable SWE-bench Seed Workspace Provisioning

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level, nine-section rust-RFC overview. -->

## Summary

> Current mapping after the 0071 cleanup: provisioning, build, and instance attribution logic remain in use by the controller and workspace source in the current package; the fixed medium_hard_16 task pool has been archived. The batch task pool capabilities below are underlying provisioning interfaces and do not enable multi-task support in the current public v2 task-package entry point; the public entry point still accepts only one session per round.

Prebuild workspaces for user simulations that require real historical repositories and dependency environments, and provide them to each session through two interchangeable provisioning methods:
`prebuilt` copies from the host cache, and `docker-seed` extracts from a file-only image. Each provisioning operation still produces an independent directory. Recognizable old absolute paths in the virtual environment
are migrated after copying; multiple sessions must not share a writable workspace.

The task pool is defined by an explicit manifest and checked against the authoritative SWE-bench Verified parquet; the parquet, output directory, and image name are all explicitly specified through the CLI
or environment, with no hardcoded personal directories. The builder saves resumable state in two stages, source and dependency, and the image validator extracts and verifies
each task. The closed loop can select a manifest, a single-task smoke test, or full coverage in every round, and preserves `instance_id` across all provisioning paths for
auditing sessions, usage, and experiment results. The specific set of 16 tasks is only the current experiment configuration and does not enter role Prompts or product decision rules.

## Motivation

Cloning historical repositories and installing dependencies directly within every user session repeatedly consumes network bandwidth, time, and storage write amplification, and also blocks concurrent sessions
while environments are prepared. Historical SWE-bench snapshots may also depend on build tools that have since changed; live installation results drift with package indexes and release dates,
making experiments difficult to reproduce.

Simply reusing the same directory breaks isolation: writes by users or the harness affect subsequent tasks, and editable virtualenvs also carry build-machine
absolute paths into new sessions. Baking the entire executable service into a task image expands the trust boundary and couples runtime orchestration to experiment data.
Therefore, this group prebuilds only file assets; running processes are still created by the existing harness launcher. Seeds are a provisioning optimization and do not change
the consumption contract of `WorkspaceSpec -> directory` or replace the git source fallback path.

## Guide-level explanation

Operators first select a manifest and the corresponding Verified parquet, run source-only to check downloads and storage, and then enable dependency builds as needed:

```text
manifest + verified parquet
          │ verify instance / difficulty
          ▼
build_swebench_seed_workspaces.py
          ├─ source prepared
          ├─ dependencies prepared
          └─ build-state.json (per-instance, resumable)
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       host prebuilt cache    storage-only image
              │                     │ docker create/cp/rm
              └──────────┬──────────┘
                         ▼
                 independent repo directory per session
                         │
                 relocate editable venv
```

`SWEBENCH_SEED_ROOT` selects host prebuilt assets, and `SWEBENCH_SEED_IMAGE` selects an image; when neither is set, the git source remains in use.
`SWEBENCH_INSTANCE_FILE` specifies the task pool, `SWEBENCH_INSTANCE` selects a single task, and `SWEBENCH_ALL_ONCE` runs every task in the pool
once per round. With `SESSION_SEED` fixed, task order and persona rotation are reproducible. Regardless of the source used,
`workspace.params.instance_id` enters the session usage context.

## Reference-level explanation

The manifest must contain at least nonempty, unique `instances[].instance_id` values and retain experiment stratification metadata such as difficulty and optional topics. The builder
reads repo, base commit, problem statement, and difficulty from the parquet; if the manifest difficulty differs from the dataset,
it fails closed. The parquet path can only be supplied through `--parquet` or `SWEBENCH_PARQUET`.

Build outputs are `workspace/<instance_id>/repo` and `build-state.json`. State records the source/dependency stages,
original build path, repository, and space information per instance, and is updated atomically by replacing a temporary file. Failures do not delete successful stages; reruns only continue unfinished
work. Dependency compatibility parameters belong to the current manifest's build profile and do not enter the user, design, or delivery role context.

`PrebuiltSource` uses `copytree` to create a new directory, skips `.venv.stale-*`, and
replaces the old root path only in known venv text metadata and scripts. It does not modify the source cache or scan arbitrary files in the product repository. `DockerSeedSource` requires an image and a safe, single-path-segment
instance id; it creates a temporary container with `docker create`, reads `/build-state.json` to verify the instance, then copies
`/workspace/<instance>/repo`, and removes the container in `finally`. The image `FROM scratch` has no entry point or execution tools and serves only as
an addressable file carrier.

Task pool selection for the closed loop occurs at process startup. A single task must belong to the current pool; all-once copies and shuffles the instance list each round, and personas
are assigned deterministically using a round-based offset. Normal mode retains sampling with replacement. A session generates its id before running and reads the
instance id from WorkspaceSpec; user and harness usage therefore share task attribution, while different concurrent sessions remain isolated by independent contexts.

## Drawbacks

Prebuilt dependencies consume substantial storage, and storage-only images do not automatically deduplicate all file content; build profiles also require maintenance as the base Python,
package indexes, and historical project compatibility change. Copying a complete virtualenv is slower than sharing read-only layers, but provides session write isolation and explicit cleanup.
Docker provisioning depends on the local daemon; when Docker is unavailable, only host prebuilt assets or the git fallback can be used.

## Rationale and alternatives

The choice is “file asset images + copying per session,” rather than running the harness inside the image: the latter would change the existing launcher, sandbox, and stdio
protocol and elevate the task environment into a new execution trust boundary. Resumable per-instance state is chosen over a one-shot monolithic script: building dependencies for 16 tasks
takes a long time, and network or single-task failures should not invalidate completed assets.

A shared writable cache was rejected because it would cause cross-session contamination; storing the parquet in the repository was rejected because it is large and constitutes external
authoritative data; inferring difficulty from text or instance ids was rejected because the manifest must be checked against dataset fields. Specific dependency pins remain in the seed
builder and do not enter the general SeedSource interface.

## Prior art

Spec 0008/0009 established `WorkspaceSpec`, SeedSource registration, and per-session materialized directories; this group adds two sources without changing the consumption
port. Spec 0017 already requires workspace isolation for concurrent sessions. Spec 0041 uses `workspace.params.instance_id` for Token
attribution; this group is responsible for consistently providing that metadata across the three SWE-bench sources. Using container images as offline file carriers is similar to Docker
multi-stage/cache export, but this group deliberately does not execute the target project inside the image.

## Unresolved questions

There is currently no unified content-addressed deduplication layer; whether large wheels or site-packages shared by different tasks should be extracted into a read-only base layer must be evaluated against
actual storage savings and copying costs. Dependency build profiles are currently maintained by scripts; whether to split them into versioned profile
files external to the manifest will also need to be decided after the task pool expands. This group does not promise reuse of built virtualenvs across CPU architectures.

## Future possibilities

Future work could add complete provenance for source commits, build tools, and image digests to build-state, provide read-only layers with copy-on-
write workspaces, or integrate seed validation into offline CI. The task pool can be replaced with another benchmark manifest as long as it continues to satisfy the contracts for unique instance ids,
authoritative metadata verification, and independent workspaces; role Prompts and product design workflows should not be aware of benchmark names or task content.
