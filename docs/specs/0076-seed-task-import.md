---
number: "0076"
title: "Import legacy seed card libraries and plain-text tasks"
issue: 0
slug: seed-task-import
summary: "Convert explicitly provided seed cards or text instructions into existing ordinary task packages, executed through the same freezing and local/E2B lifecycle, without restoring old entry points or carrying hidden evaluation fields."
tasks:
  - id: T1
    title: "Convert legacy cards and text materials"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/task_import.py
      - backend/tests/test_experiment_task_import.py
    scope: "Strictly convert inputs and publish existing task packages and provenance summaries in stages without overwriting"
    acceptance: "Seed-card libraries can be imported; Git pin and setup semantics are correct; hidden fields are not output; errors and overwrite attempts produce no successful artifacts"
  - id: T2
    title: "Unified task CLI and public command checks"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/cli.py
      - backend/tests/test_experiment_cli_v2.py
      - backend/scripts/check_experiment_repository.py
      - backend/tests/test_experiment_repository.py
    scope: "Wire up task import-seeds/from-text and an accurate public command allowlist"
    acceptance: "help/arguments/exit codes/JSON are valid; conversion does not read credentials or enter the lifecycle"
  - id: T3
    title: "Bilingual input tutorials and current examples"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/tutorials/seed-task-import.md
      - docs/tutorials/seed-task-import.zh-CN.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - README.md
      - README.zh-CN.md
      - examples/seed-inputs/library.json
      - examples/seed-inputs/instruction.md
      - CLAUDE.md
    scope: "Explain conversion and integration through array paths, provide current small examples, and update the migration status of historical capabilities"
    acceptance: "English and Chinese commands are consistent; no claims that hidden sidecars or legacy environments have been reproduced; current examples can be converted and checked"
  - id: T4
    title: "Verification from conversion through freezing and real workspaces"
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
      - backend/tests/test_experiment_task_import_e2e.py
      - backend/scripts/e2e-spec-0076-seed-task-import.sh
      - .github/workflows/experiment-contract.yml
    scope: "Verify freezing of real materials and conversion without side effects, real Docker preparation, local model runs, and workspace export"
    acceptance: "Actual artifacts enter the existing hash contract; repository-wide regression checks; a real local model experiment completes collection and cleanup, with explicit cloud and evolution boundaries"
---

# 0076 · Legacy Seed Card Library and Plain-Text Task Import

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is the group-level rust-RFC nine-section overview. -->

## Summary

Add `task import-seeds LIBRARY --output DIR [--seed ID ...]` and `task from-text --instruction PATH --id ID --output DIR --not-in-benchmark` to the unified entry point. Both only prepare materials and do not start experiments: they generate the current v1 ordinary task package, description, setup, requirements files, and path index, then hand them to the existing workload.task_packages, check/prepare/run, and local/E2B lifecycles. Text tasks from legacy cards use the initial scratch source directory; do not restore legacy scripts or add a new controller.

## Motivation

The legacy flow could read the seed card library directly, with the card's task.prompt serving as the actual requirement; when no repository existed, it used an empty scratch workspace. The unified entry point currently requires a complete task package, so users can only migrate the old input flow by manually adding source/setup. Directly restoring the legacy seed runner would duplicate freezing, authentication, and resource governance. This feature converts at the material boundary while preserving the same execution contract; successful import does not prove that the old environment has been fully reproduced or that the task passes.

## Guide-level explanation

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json task import-seeds examples/seed-inputs/library.json --output /absolute/path/to/imported-tasks
uv run --locked --extra experiments python backend/scripts/experiment.py --json task from-text --instruction examples/seed-inputs/instruction.md --id text-example --output /absolute/path/to/text-task --not-in-benchmark
```

The card library supports either a bare array or an object containing a seeds array; cards are imported in input order, and an explicit --seed may be repeated but the same ID must not be specified twice. The selected cards must be valid. Missing input files, an empty library, duplicate IDs, no not_in_benchmark declaration, a missing prompt, an invalid Git revision, or an invalid setup type are rejected, and no usable partial batch of materials is produced. The output directory must not exist, including as an empty directory or symbolic link; existing artifacts are not overwritten. The command does not read model/provider credentials, access the network, or run setup.

The result provides an absolute task_packages array that can be written directly to workload.task_packages in the experiment JSON. The output tasks.json stores paths relative to the output directory, ordering, and an input summary; it is not a new experiment definition and cannot replace the array as an entry point. When paths are moved elsewhere, they must be adjusted relative to the experiment JSON's directory. Persona, rounds, and model remain configured by the experiment definition.

## Reference-level explanation

### Material conversion contract

Add experiment/task_import.py with two public functions, import_seed_tasks and import_text_task. Selected cards must be objects, their IDs must satisfy the existing task package ID rules and be unique within the library; source.not_in_benchmark must be true, and task.prompt must be a non-empty string. Reuse the field and vocabulary constraints from distill.seed_library.validate_card, while adding the required fields that it does not enforce; do not retain SeedLibrary's fallback that treats a missing file as an empty library. The original prompt bytes are written to instruction.md, without appending task.context. Rejected cards, benchmark cards, and envelopes adapted from SeedScenario must not be mixed into real seed input.

When source.repo is absent or n/a, generate scratch source/README.md explaining that this is the initial directory for a task yet to be implemented; do not add a solution. The existing freezer rejects an empty source directory, so the explanation file establishes hashable initial materials; legacy text tasks likewise ultimately run in scratch, and users/tools continue to access them through the current isolated workspace. Cards with a repo require credential-free HTTPS and an owner/repo identifier; env.repo_at must be a fixed 40-character lowercase SHA. The existing load_task_package validates the generated result. task.source continues to contain only local/git, with kind=ordinary and not_in_benchmark=true.

setup uses the current TASK_ROOT/TASK_PYTHON/VIRTUAL_ENV/UV_BIN contract to create the task venv. After the environment is fixed, each original env.setup string is executed in an independent bash subprocess, preserving quotation, newlines, and list order; do not split/join the text, and do not actually execute the commands. Generate requirements.lock explicitly stating that legacy setup does not automatically lock dependencies; text tasks without setup have no external dependencies. base_image, external_deps, budget, and pairing metadata have no corresponding automatic migration. The conversion must not be described as having passed reproduction gates for the original environment.

### Hidden fields and publication

Only the permitted prompt/source/setup are mapped. Do not copy oracle, env.test_cmd, gates, or provenance into the task or any sidecar, and do not generate descriptions, dependencies, or feedback from their contents. The input source in tasks.json retains only the byte digest, ID, and source type, and does not store the original card content; gold standards and hidden tests do not enter the frozen materials. Plain-text import requires an explicit --not-in-benchmark and must not infer the source automatically from text content.

First write and validate everything in temporary staging under the same parent directory using the existing package checks, then create the target with an exclusive mkdir and move in the generated files; reject any existing target. On failure, clean up only the directory and staging created by this operation; do not delete the original input or other outputs. Do not promise strong cross-platform atomic directory visibility. On success, the materials are complete; on failure, there is no success index that could be misused. Do not use a bare rename that might overwrite an existing empty directory.

### Task DAG and file allocation

T1 conversion core, T2 CLI, and T3 bilingual documentation are implemented independently according to this document's stable interface; T4 integrated acceptance depends on all three. The frontmatter is the sole file ownership table, with at most four items in the group. The new task command must update the public command allowlist; do not expand the task schema or copy historical entry points. The dedicated script backend/scripts/e2e-spec-0076-seed-task-import.sh covers seed-card conversion using synthetic examples, mixed Git/text inputs, UTF-8/quoting, no network/model/setup execution, forbidden-field sentinels, overwrite rejection, options, and frozen-production integration. Real Docker scratch setup/file modification/prediction export are accepted separately; when E2B is not tested, record that explicitly and do not present an offline substitute as evidence.

## Drawbacks

Legacy cards do not generate a complete experiment in one step: persona, model, and round count still require user configuration. Legacy setup may contain unlocked dependencies; conversion does not determine versions or download code for verification. Scratch contains an initial README, adding one explanatory file compared with the historical bare empty directory, but it does not contain the task solution. Generated tasks require a separate output directory and consume a small amount of space; the initial release does not promise strong atomic directory visibility.

## Rationale and alternatives

Restoring the old --seed-library runner would duplicate execution paths and bypass the unified material contract, so it is rejected. Carrying a new source.kind=none or legacy.seed DSL through both backends and the orchestration layer would require a larger fork while solving only the lack of initial code, so it is not selected. Converting to the existing task package reuses the validated single/multi-task, batch, isolation, and recovery behavior, allowing source adaptation and execution to retain single responsibilities.

## Prior art

The legacy distill.seed_adapter mapped task.prompt to the instructions, generated a Git workspace when a repo existed, and used workspace=None when no repo existed; however, it did not strictly restrict SHA values and rewrote setup quoting, so it cannot directly serve as the new importer. The current ordinary task package has fixed source, setup, instructions, and a non-benchmark declaration; the frozen catalog/plan binds these to each session. The importer only connects the two and does not change the evolution or feedback contracts.

## Unresolved questions

This authorization scope contains no implementation questions requiring a user decision. Whether legacy card images, external services, and environments are reproducible is verified by the generated package's actual check/prepare/run; the importer does not guess or access the network during conversion.

## Future possibilities

Later additions may include dependency locks and migration-difference reports explicitly provided by the user, or references to the task package index in the unified experiment editing flow; do not add automatic model guessing, implicit searches for private materials, or arbitrary host env passthrough. Appending rounds to historical artifacts and runner governance for engineering CI remain separate features.
