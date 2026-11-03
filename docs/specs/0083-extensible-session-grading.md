---
number: '0083'
title: "Extensible session artifacts and independent objective acceptance verification"
issue: 0
slug: extensible-session-grading
summary: "Unify acceptance artifacts for direct and simulated interactions, retain existing SWE grading, and add benchmark and custom grading adapters; grading reads frozen archives and is stored independently, without fabricating missing evidence."
tasks:
- id: T1
  title: "Unified grading contracts, registration, and result semantics"
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/evaluation/contracts.py
  - backend/ahe_beta/evaluation/registry.py
  - backend/ahe_beta/evaluation/results.py
  - backend/ahe_beta/evaluation/acceptance.py
  - backend/tests/evaluation/test_grading_contracts.py
  scope: "Define read-only grading requests, fixed adapter registration, execution contracts, and public results; extract acceptance relations and distinguish continuous scores from infrastructure failures."
  acceptance: "Explicitly reject unknown adapters or versions; only completed results may count as technical success or failure; non-fresh contracts must support strict verification; unverified results or continuous scores do not automatically become valid_accept."
- id: T2
  title: "Task sources, public artifact declarations, and compatible identity"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/config.py
  - backend/ahe_beta/experiment/schemas/task-package-v2.json
  - backend/ahe_beta/experiment/materials.py
  - backend/ahe_beta/experiment/workload.py
  - backend/ahe_beta/models.py
  - backend/tests/test_experiment_grading_task_config.py
  - backend/tests/test_experiment_grading_task_materials.py
  scope: "Add generic benchmark sources in task package v2 and artifact v1 declarations; freeze content, validate paths and backend capabilities, and preserve original schema1 identities."
  acceptance: "Old configurations, catalogs, and task digests must not drift; custom sources must not pose as benchmarks; managed handles must not accept forged user paths; reject unsupported required collection before resource or model operations."
- id: T3
  title: "Shared session collection, archiving, and resume boundaries"
  status: pending
  priority: P1
  tags: []
  depends-on:
  - T1
  - T2
  - 0081/T3
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/evaluation/artifacts.py
  - backend/ahe_beta/loop/sim_user.py
  - backend/ahe_beta/user/sim/runtime.py
  - backend/ahe_beta/experiment/context.py
  - backend/ahe_beta/experiment/controllers/unified.py
  - backend/ahe_beta/experiment/collection.py
  - backend/ahe_beta/experiment/continuation/source.py
  - backend/ahe_beta/experiment/continuation/export.py
  - backend/tests/evaluation/test_session_artifacts.py
  - backend/tests/user/test_direct_session.py
  - backend/tests/loop/test_sim_user.py
  - backend/tests/test_experiment_grading_artifact_lifecycle.py
  - backend/ahe_beta/loop/orchestrator.py
  - backend/tests/test_experiment_engine.py
  - backend/tests/user/test_prediction_artifacts.py
  scope: "Both runners share collection before cleanup and reuse the complete prediction; save session/attempt receipts, integrate managed-environment collection, and isolate private materials, recovery evidence, and parent-round evidence."
  acceptance: "Use the same contract for direct/simulated; bind the actual user_sha; ensure file and measurement sources are verifiable; do not upgrade missing, over-limit, or tampered evidence; parent-round records must not serve as child-round results; do not write back to old Sessions; do not mark done until managed-measurement prerequisites are complete."
- id: T4
  title: "Official and custom grading adapters"
  status: pending
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/evaluation/adapters/swebench.py
  - backend/ahe_beta/evaluation/adapters/__init__.py
  - backend/ahe_beta/evaluation/adapters/terminal_bench.py
  - backend/ahe_beta/evaluation/adapters/tua_bench.py
  - backend/ahe_beta/evaluation/adapters/nl2repo.py
  - backend/ahe_beta/evaluation/adapters/custom.py
  - backend/tests/evaluation/test_grading_adapters.py
  - backend/tests/evaluation/test_swebench_runner.py
  - backend/ahe_beta/evaluation/adapters/container.py
  - backend/ahe_beta/evaluation/adapters/profiles.py
  - backend/ahe_beta/evaluation/__init__.py
  scope: "Wrap the existing SWE evaluator; verify Terminal/TUA/NL2Repo artifacts against pinned official contracts, execute fixed custom scripts in independent containers, and remove the old online grading entry point and compatibility exports for acceptance functions."
  acceptance: "Do not rewrite official graders; pin tasks, executors, images, and external grading materials; retain official SWE reports; read official rewards for Terminal/TUA; retain official NL2Repo pass rates without inventing binary rules; replay SQL using the production plan; KV consumes only trusted original measurements; environments that cannot be reconstructed cannot be graded; custom grading and operator thresholds must not pose as official."
- id: T5
  title: "Unified post-hoc grade command and binding to the original session"
  status: done
  priority: P1
  tags: []
  depends-on:
  - T2
  - T3
  - T4
  relates-to: []
  parallel: false
  files:
  - backend/ahe_beta/experiment/grading.py
  - backend/ahe_beta/experiment/grading_inputs.py
  - backend/ahe_beta/experiment/cli.py
  - backend/ahe_beta/experiment/schemas/grading-plan-v1.json
  - backend/tests/test_experiment_grading.py
  - backend/tests/test_experiment_grading_e2e.py
  - backend/tests/test_experiment_grading_plan.py
  - backend/tests/test_experiment_cli_v2.py
  scope: "Reuse archive/round/baseline/Session/generation validation before dispatching to the adapter; grade accepts only the required private --plan, removes old dataset arguments and compatibility conversions, retains offline mode, and stores grading results and acceptance relations independently."
  acceptance: "All adapters share --plan; a missing plan or use of old dataset arguments must produce an explicit error before grading execution and point to the new usage; direct SWE plans can be graded; hidden materials are not uploaded; grading does not invoke models/providers/Issue; original experiment bytes and identities remain unchanged; interruptions and regrading use independent attempts; the new interface must not bypass existing bindings."
- id: T6
  title: "Real acceptance verification, migration instructions, and bilingual tutorials"
  status: pending
  priority: P1
  tags: []
  depends-on:
  - T5
  - 0081/T4
  relates-to: []
  parallel: false
  files:
  - docs/tutorials/post-run-grading.md
  - docs/tutorials/post-run-grading.zh-CN.md
  - docs/specs/0051-session-container-objective-evidence.md
  - docs/specs/0075-post-run-swe-grading.md
  - docs/specs/0081-e2b-task-environments.md
  - examples/grading/swebench.json
  - examples/grading/mixed-benchmarks.json
  - examples/grading/custom.json
  - backend/scripts/e2e-spec-0083-session-grading.sh
  - backend/tests/test_experiment_grading_compatibility.py
  - README.md
  - README.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - CLAUDE.md
  - backend/tests/test_experiment_public_examples.py
  - backend/scripts/e2e-spec-0051-session-container.sh
  - backend/scripts/e2e-spec-0056-0057-user-semantics.sh
  - backend/scripts/e2e-spec-0075-post-run-grading.sh
  scope: "Provide unified post-hoc acceptance materials, commands, and extension methods for both backends; verify official positive and negative controls and managed measurements, update the boundaries of old specifications, and complete regression verification."
  acceptance: "Report real grading results item by item for SWE/production planning/Excel/TinyDB/custom; verify KV using managed measurements from the actual original run; substitutes must not masquerade as official results; do not modify old runs; retain pending when prerequisites or materials are incomplete, and do not describe complete N8 support in the documentation."
---

# 0083 · Extensible Session Artifacts and Independent Objective Verification

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC nine-section overview. -->

## Summary

Add extensible **objective verification of existing sessions** to the unified experiment entry point: direct and simulated-user share an artifact collection contract, and grading reads only stopped, fully collected runs and invokes SWE, Terminal-Bench, TUA, NL2Repo, or custom adapters according to an independent grading plan. Task source, interaction mode, runtime environment, and verification method are modeled separately; adding a benchmark does not add session runner branches.

Retain the official SWE evaluator, but retire the old `--dataset`/`--dataset-sha256` parameters from the public grade interface. All tasks use only the required `--plan`, with no aliases, automatic conversion, or parallel compatibility paths. Do not change subjective user conclusions, original Sessions, feedback, delivery gates, or historical archives. Each grading attempt generates an independent report distinguishing actual passes, actual failures, not configured, unsupported, missing materials, and verification environment failures. Independent Harness benchmark evaluation remains responsible for rerunning a specified Harness on new tasks and is not replaced by this group.

This group has received review approval and implemented the first version: the public contracts, task package v2, shared regular-file collection, initial adapters, and unified plan command are integrated. T3's managed-environment branch, T4's complete official verification, and T6's complete acceptance verification remain pending. Some real Docker controls have been completed; historical itemized records are available in Git history, and currently reproducible checks are listed in docs/VERIFICATION.zh-CN.md. Offline regression does not indicate successful real grading. Do not rerun N8 or modify old experiment results within this group.

## Motivation

The old SWE simulated sessions exported patches after completion, invoked `SWEbenchEvaluator`, and saved `objective_evaluation` and `accept_validity`. This path was introduced by 0051's session isolation and dual-conclusion design and already included actual official CLI calls; it runs only when the dataset and execution environment are configured. The direct path added later did not invoke this evaluator, and its `accept_validity` was directly set to `not_applicable`.

The current public entry point explicitly disables official grading during evolution. The post hoc `grade` implemented in 0075 validates the frozen archive, complete patch, and original session identity, then invokes the official SWE evaluator in local Docker; it can already grade direct SWE sessions, but routes by `kind == swebench`, requires an SWE dataset for all grading, and has no adapters for other tasks. Generic determination of the acceptance relationship still resides in the SWE module, and `fresh=true` represents all verification isolation, which cannot directly cover TUA verification in the original task environment or KV verification that depends on independent measurements.

The old mixed-task executor prepared agent/grader packages, and the documentation required running the official grader, but package preparation, users' own checks, role-based delivery, and official verification are distinct facts. Terminal, Excel, TinyDB, and service tasks require different artifacts; a Git diff alone is insufficient. R6 archives saved workbooks and databases but lacked formal KV measurement records; adding a grader cannot recover facts that were not saved at the time.

0081's complete E2B task environment remains pending: it plans to provide management-side services, companions, readiness and finalize, collection, and isolation. This group defines the verification artifact interface it must deliver, does not implement another E2B environment broker, and does not repackage old shared snapshots as a current public environment with trustworthy measurement isolation already in place.

## Guide-level explanation

### Operator workflow

1. Configure experiment tasks and interaction mode. Existing schema 1 SWE/ordinary task packages remain usable; tasks requiring new benchmark sources or additional artifacts use task package schema 2.
2. Task packages declare only public task sources and artifacts to preserve; they contain no hidden tests, reference answers, grading outputs, or private grading paths. prepare validates whether the current backend can preserve these materials; if it cannot provide the required capabilities, reject before allocating resources or invoking models.
3. Run the experiment normally. Both interaction modes invoke the same collection function after the session ends and task finalize completes, but before workspace cleanup. Record capture failure reasons and continue necessary cleanup; do not equate experiment success with material completeness.
4. Stop and collect. The operator supplies an independent grading plan and the required official materials; the grading plan is copied, validated, and frozen into an independent attempt before verification executes, and is not uploaded to the evolution runtime environment.
5. Invoke the same `experiment.py grade` to view each session's technical result, original user conclusion, and the derived relationship between them. This command does not start a Harness, invoke models, restore E2B, or create a Gitea Issue.

The new functionality uniformly uses the following invocation. SWE, other benchmarks, and custom tasks all use `--plan`; SWE does not require a separate entry point:

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py grade RUN_ID \
  --plan /path/grading-plan.json --round 6
```

The plan here is grading configuration, not a new benchmark dataset: it specifies which adapters apply to which original tasks and where the official materials required by each adapter are located. The official SWE dataset is one material referenced by the plan; Terminal/TUA test packages, NL2Repo task images, and custom scripts serve as inputs to their respective adapters, without forcing them to share the SWE dataset structure.

An illustrative SWE plan configuration follows. Placeholder hashes must be replaced with actual values; this format is already validated by the current plan loader:

```json
{
  "schema_version": 1,
  "materials": {
    "swe_dataset": {
      "path": "/path/official.json",
      "sha256": "<64-character SHA256 of the official dataset file>"
    }
  },
  "graders": [
    {
      "adapter": "swebench",
      "contract_version": 1,
      "task_ids": ["pvlib__pvlib-python-1478"],
      "inputs": {"dataset": "swe_dataset"},
      "timeout_seconds": 1800
    }
  ]
}
```

This configuration means: select the original sessions for the specified tasks from round 6 of `RUN_ID`, read the saved complete patches, and perform SWE verification using this official dataset. The operator does not reenter patch paths, persona, Harness SHA, or the original source baseline; these facts are resolved from the archive and validated. The official SWE evaluator version remains pinned to 4.1.0, and the official adapter determines the passing rules.

The same plan can add Terminal, TUA, NL2Repo, or custom entries in `graders`, each referencing its own materials. Multiple SWE tasks can share `swe_dataset` without copying the dataset file; the generic grading entry point dispatches mixed sessions item by item and marks unselected items not_configured. Each task may match at most one entry; duplicate matches are rejected before execution.

The old `--dataset`/`--dataset-sha256` parameters are removed outright, with no compatibility shorthand or automatic plan conversion. Using old parameters or omitting `--plan` produces an argument error before running a verifier or writing a grading attempt, and points to `grade RUN_ID --plan PATH`. To migrate old SWE usage, place the original dataset path and SHA in the plan's materials, then explicitly select the SWE task_ids from the original run; there is no need to change dataset files or rerun the experiment.

The `--plan` path supports `--offline`: it validates only available input identities, contracts, and materials, without allocating containers, running grading scripts, writing grading attempts, or marking unknown environments as ready. Missing materials are explicitly listed in the offline report. New examples and official tutorials show only plan invocations; old parameters appear only in retirement notes, not as executable examples.

### Task sources and grading selection

task package schema 2 retains the existing `ordinary` and `swebench` and adds the generic `benchmark`, in which `benchmark={suite,instance_id,revision}` identifies the actual source. ordinary remains an explicitly non-benchmark scenario and can configure custom verification. Grading adapters are selected by an independent plan; source validation cannot be bypassed by changing a standard task to ordinary, and a new kind is not added for every new suite.

The same grading adapter handles both interaction modes; for example, direct and simulated-user deliveries for the same TinyDB task are verified in the same official environment. A source identifier does not automatically enable grading, interaction mode does not determine the grader, and the grader does not change the task runtime environment.

### Compatibility scope

| Input | Behavior after implementation |
| --- | --- |
| Existing schema 1 SWE tasks | Original identities and official verification rules remain unchanged; grade using the new --plan |
| Dataset parameters of the original grade interface | Retired outright; replaced with plan, with no aliases or automatic conversion |
| Existing ordinary tasks with no verification declared | May continue running; reports explicitly state not_configured, with no default pass |
| Old complete archives of current schema 2 experiments | May be graded independently when native binding validation passes and materials are sufficient; no old receipt is added |
| Private old schema 1 experiments, missing baselines, or truncated traces only | Remain explicitly unsupported or insufficient in materials; not automatically converted into current runs |
| New benchmarks without registered adapters | May run when task environment capabilities permit; explicit grading records unsupported |
| KV sessions missing original-run measurements | missing_artifact or ungradable; a newly run workload must not masquerade as verification of the original session |

New grading does not backfill the original `accept_validity`; grading reports use `acceptance_assessment` to show the derived relationship while preserving the original fields and user experience as independent facts.

## Reference-level explanation

### 1. Layers and minimal interfaces

Execution dependencies are fixed as:

```text
Public task-package artifact declarations → Shared session collection → Immutable archive
                                                                                ↓
Original run/round/session binding checks →                              Grading adapter → Independent results and acceptance relations
                                                                                ↑
                                                          Operator-private grading plan/test materials
```

Create small contract, registry, and result modules within `ahe_beta.evaluation`. Adding an adapter adds only a module and an explicit registry entry, without modifying the orchestration flows of direct, simulated-user, triage, OpenAgents, or providers. The registry uses fixed identifiers and contract versions; configuration files may not arbitrarily import Python classes, and no third-party plugin discovery system unneeded by this group is introduced.

Adapters provide only `validate_inputs(request)` and `evaluate(request, attempt_dir)`. Inputs include validated task/session identities, a read-only artifact collection, frozen grading configuration, and grading resource locations. Adapters must not infer artifacts anew from live workspaces and are not responsible for experiment restoration, Session persistence, Issue operations, or subjective review. The common layer owns original-run binding, grading locks, attempt lifecycles, and unified reports; adapters own official-material validation, environment preparation, verification commands, and result parsing.

Official SWE CLI execution details are consolidated into the private `_SWEbenchRunner` class within `evaluation/adapters/swebench.py`, sharing a single file with the public `SWEbenchAdapter`; there is no separate runner module or compatibility alias. Remove the old `evaluation/swebench.py`, package-level evaluator exports, `from_env()`, runner evaluator injection, and the `derive_accept_validity` compatibility interface; grading will not be started within user sessions through host configuration. Historical Sessions' objective/acceptance fields remain available for reading existing records; new sessions retain only interactions and artifacts, with acceptance relationships determined in independent grade reports. Determination in new reports explicitly receives the execution contracts validated by each adapter, rather than using a global `fresh` boolean to substitute for every benchmark's isolation requirements.

### 2. Versioned public tasks and private grading plans

Add `task-package-v2.json`; schema 1 parsing, field defaults, serialization, and digests remain unchanged, and old frozen packages must not be rewritten to reuse a parser. Only new packages may add actual benchmark sources and `artifacts` declarations; these enter the task catalog and content identity unchanged. New provenance kinds are explicitly supported in model and catalog validation.

`artifacts` uses an independent version 1 and an explicit export list. Each entry includes at least a stable id, source `workspace`/`managed_service`, a path within the task root or a management-side handle, content type, requiredness, and byte limit; restrict path traversal, duplicate targets, unbounded globs, and non-regular files. Managed services may reference only handles already created by the controller and belonging to the current session/attempt; tasks cannot specify host absolute paths themselves or pass off files they write as independent measurements.

Existing environment declarations are responsible for inputs and service deployment; this group's artifact declarations describe only verification outputs. The two connect through artifact ids and must not create two sources of truth. Implementation of 0081 should reuse task package v2 and this group's public collection entry point; environment or grading default fields must no longer be implicitly injected into old schema 1.

Private grading plan version 1 uses `materials` to define material paths and hashes, and `graders` to define adapters/contract versions, task_ids, material references, time limits, and adapter-specific configuration. `task_ids` selects only tasks in the original run; task digests, sessions, and Harness identities are resolved from the validated archive and frozen into the attempt, rather than allowing operators to transcribe or override them. Each selected task has at most one adapter; duplicate matches, missing material references, unknown tasks, and mappings inconsistent with actual sources are prohibited. Official/custom identity is jointly validated by the adapter and frozen task source, without trusting arbitrary string labels.

Official materials pin revisions and file hashes; required environments are determined by adapter-specific configuration or fixed rules of the pinned adapter. Resolved container image digests are frozen before verification executes, and mutable tags must not be resolved again during verification. Custom scripts and dependencies have fixed hashes. Datasets, test files, and commands are validated by adapter-specific schemas; the SWE dataset is not forced to be a parameter for all adapters.

Official binary tasks retain their original passing rules; continuous-score tasks report the original score and its definition. Custom thresholds must be declared and frozen before grading starts; when there is no binary rule, `passed=null`, and only the score may be reported. A threshold or test-version change must create a new attempt, and reports must not merge different plan digests as identical experimental conditions. If a grading plan is specified only after an experiment ends, record that fact and do not claim it was a standard preregistered before the experiment.

Private grading files are written only to independent local evaluation attempts. Subsequent collect explicitly excludes the evaluation directory under the run root to prevent private tests, reference answers, and grading plans from entering new evolution archives. Only public artifact declarations needed for task execution are passed to the controller; grader files, grading conclusions, and private managed-measurement content are not included in observation authorizations for users, the requirements surface, or the delivery surface. Grading reads only local materials and container images; private image login is handled by the operator's existing container tools, and credentials are not written to plans, Sessions, or grading summaries.

### 3. Shared collection and lifecycle

Implement a single collection function in `evaluation/artifacts.py`, invoked by both runners at the same lifecycle boundary. Reuse the existing complete prediction export rather than creating a second patch implementation. New artifact receipts are placed in `workspace_evidence.evaluation_artifacts`, with data persisted separately by session/attempt; receipts record the contract version, task digest, run/round/session/slot, trial Harness SHA, file hashes/bytes, collection time, source, and completion status. Grading binds to the `user_sha` actually tried by the user, not the `sealed_sha` after delivery in that round.

The following sequence is mandatory: end the Harness and user review → complete the task-prescribed finalize → stop or seal companion measurements → collect → save the receipt → reclaim resources. Necessary cleanup still runs on failure; missing files, truncation, limit overruns, loss of service ownership, and other failures are recorded separately, and failure of a required artifact must not produce a complete receipt. User-written outputs and controller-collected managed measurements are marked separately; trustworthy KV provenance requires not only correct hashes but also management-side identity, isolation, and sealing evidence.

Workspace files are collected through the existing runtime's read/write/export capabilities; managed services are collected through the environment management interface in 0081, without reading management directories through the user shell. If the existing backend does not support managed_service, prepare explicitly rejects that declaration. The shared collection module can first implement and verify ordinary files and SWE predictions; the complete KV path must wait for the managed environment capabilities in 0081. A local fixture or shared writable E2B directory must not be described as full support.

collect validates receipts against actual bytes and provides explicit collection paths for grading materials. Hidden or management-side materials retain operator access boundaries and must not automatically acquire demand-side observation grants through archiving or continuation imports. New child runs inherit only the task's public collection declarations and regenerate receipts for the current round; parent-round acceptance records may only be referenced and cannot substitute for child-round execution. Completed recovery units must not rerun user sessions because acceptance materials are missing.

### 4. Initial Adapters and Extension Contracts

| adapter | Inputs and execution method | Boundaries required for actual grading |
| --- | --- | --- |
| swebench | Baseline, complete prediction, pinned dataset; invokes the existing official 4.1.0 CLI | Official fresh instance container; reads resolved and official report classifications, without using the shell exit code to determine success for the entire task |
| terminal-bench | Pinned Harbor task package, task.toml, environment build materials, and tests; executes the official tests/test.sh | Respects verifier.environment_mode, artifact sources/destinations, user, and budget; reads formal reward and diagnostics, without universally assuming fresh |
| tua-bench | Pinned official task.toml/tests, environment, and reference-answer materials; saves task outputs | Performs acceptance after the Agent exits according to the pinned executor semantics; reads official reward/metric, without substituting pytest or process exit codes; ungradable if the environment contract cannot be met |
| nl2repo | Pinned test_commands/test_files/count, official task image, and generated repository; follows the overwrite and parsing semantics of the official post_process_task | Removes officially declared tests and package configuration from the generated copy before overlaying it onto the official environment, preserving the original tests and pass rate; does not describe Agent self-tests or arbitrary thresholds as official binary success |
| custom | Independent scripts, inputs, and pass rules with versions fixed by the operator | Executes argv in a restricted acceptance container; container isolation is a contract of this system, results are labeled custom, and there is no unified “official custom” grader |

The table above specifies alignment requirements that implementation and acceptance must satisfy; it must not be used to claim that actual grading verification is complete or that an entire benchmark is supported. The initial non-SWE alignment samples are restricted to the fixed task sources below; adapter identifiers do not promise compatibility with “all historical/latest versions.” During implementation, pin the actual acceptance executor and its dependency versions; pinning only the task repository while arbitrarily choosing the current Harbor is not permitted. New tasks are added to the support list only after their metadata, environment, and grading semantics have been verified; unknown versions or uncovered execution modes are explicitly unsupported.

| Source | Fixed revision / version | Initial verification scope |
| --- | --- | --- |
| SWE-bench official evaluator | 4.1.0 | Currently supported official SWE instances and their dataset identities |
| harbor-framework/terminal-bench-1 | 452bf305c6daa62fc59061d22133a7cbc7c1572e | Harbor-format tasks production-planning and kv-live-surgery |
| facebookresearch/TUA-Bench | 3497fd320abcafaf4797424192c891a593fd7964 | 010-pivot-product-revenue |
| multimodal-art-projection/NL2RepoBench | 781a1da1ee41fb8edb0bed22f586d69111610edf | tinydb |

The Terminal production-planning task explicitly uses a separate verifier and declares three SQL artifacts; the official test.sh restores a clean database, replays the SQL, then executes tests and writes reward. KV also uses a separate verifier, but its artifacts come from the loadgen service: results.json, measure.log, and the diagnostic loadgen.log, which must be placed back into the acceptance environment at the official paths; the six gates and 5-fold threshold under valid measurements remain unchanged. For official prerequisite failures such as missing records or an invalid baseline, preserve the original reward/logs while separately classifying evidence or environment issues in this system; reward=0 alone must not be taken to mean code failure. [Production-planning contract](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/production-planning/task.toml), [official replay and reward](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/production-planning/tests/test.sh), [KV artifact contract](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/kv-live-surgery/task.toml), [KV official gates](https://github.com/harbor-framework/terminal-bench-1/blob/452bf305c6daa62fc59061d22133a7cbc7c1572e/tasks/kv-live-surgery/tests/test_score.py).

The official script for the initial TUA Excel task runs test_outputs.py and writes the numeric value to reward.txt; this task's compare_table produces 0/1, but that does not imply that all other TUA tasks are binary tasks. Acceptance preserves the combination rules of the official metrics and the original score, without running --sanity/oracle to repair submissions. Content hashes must also be recorded and frozen for reference answers, sidecars, and external files downloaded within tests; pinning only the tests revision is insufficient to pin the contents of remote URLs. [Official acceptance script](https://github.com/facebookresearch/TUA-Bench/blob/3497fd320abcafaf4797424192c891a593fd7964/tasks/010-pivot-product-revenue/tests/test.sh), [official metrics and material references](https://github.com/facebookresearch/TUA-Bench/blob/3497fd320abcafaf4797424192c891a593fd7964/tasks/010-pivot-product-revenue/tests/test_outputs.py).

The initial NL2Repo implementation follows the official post_processor's package configuration cleanup, test path cleanup, image overlay, command execution, and output parsing; it modifies only the generated copy used for grading, not the original archive. Official parsing uses a fixed test count as the denominator, success_rate=min(passed/total,1), which is not a ready-made rule for passing the entire task; a more convenient pytest statistics formula must not be written and passed off as official. When no formal binary rule is provided, passed=null; operators may declare a derived threshold in the plan, but it must be listed separately as operator policy and cannot be labeled official success. [Official post_processor](https://github.com/multimodal-art-projection/NL2RepoBench/blob/781a1da1ee41fb8edb0bed22f586d69111610edf/openhands/post_processor.py).

The Terminal adapter selects the verifier mode according to the task declaration; if the required environment or original measurements are missing, it reports the task as ungradable without silently falling back. Production planning replays submitted SQL in a clean database according to the official contract; database snapshots do not automatically substitute for SQL. The KV verifier consumes records from the original run's independent load generator and does not start a new load to fabricate replacement measurements. If TUA acceptance can only occur in the original task environment, its verifier-only materials must enter through managed environment operations after the user process exits, and the results must be sealed as a separate acceptance receipt; this behavior, which must be captured online, must not be put into the generic persona runner. Current runs that do not provide this capability can only grade tasks after the fact whose environments can be fully reconstructed.

NL2Repo's grader package usually contains only file lists, commands, and test counts; the actual official tests come from the pinned task image. The presence of these three text files alone must not be treated as a complete test suite. Both the pass rate and binary success use fixed grading rules; passing an arbitrary pytest subset must not be interpreted as passing all official tests.

Do not copy the planning, interaction, or scheduler from `evaluation/harness_bench`. Existing budget/official metadata parsing can be reused through narrow functions; reusable grading rules have a single implementation, and independent Harness evaluation may call the same adapters later, but this change does not require merging the two sets of entry points or manifests.

### 5. Unified Results and Acceptance Relationships

Each result includes the adapter/version, plan digest, input and output hashes, execution environment identity, raw report path, time limit, status, score/definition, passed, error reason, and execution contract evidence. Each attempt also preserves content hashes for the modules of the current grading code, separately from the original experiment's controller_sha, to avoid treating the experiment code version as the post hoc grader version. Execution contracts must distinguish at least `fresh_official_instance`, `agent_stopped_task_environment`, `trusted_recorded_measurement`, and `isolated_custom_verifier`, and must be validated by the adapter; callers cannot arbitrarily supply a true value.

| Status | Meaning | passed |
| --- | --- | --- |
| completed | Formal acceptance ran successfully and produced a valid conclusion | true/false; null for continuous scoring only with no binary rule |
| not_configured / unsupported | No rules specified / no corresponding adapter | null |
| missing_artifact / ungradable | Missing artifacts / identity, provenance, or environment cannot satisfy the contract | null |
| unavailable / crashed / timed_out | Acceptance infrastructure, parsing, or execution failed | null |
| not_evaluated | Official evaluator explicitly skipped evaluation, such as an empty SWE prediction | null |

Count passed=false as a normal task failure only when the status is completed, contract validation passes, and the raw report is valid; list other statuses separately, without including them in success or failure denominators. Existing SWE JSON outputs retain their original meanings and fields; when the old evaluator internally uses passed=false to indicate a fault, normalize it to null according to status only in the new public result, preserving the raw output and leaving the behavior of old calls unchanged.

The denominator above refers only to this system's diagnostic statistics for “sessions with valid acceptance” and does not replace official benchmark aggregation. Preserve the official report's task totals, empty predictions, incomplete tasks, errors, and denominator definitions unchanged; do not remove these items and call a higher conditional pass rate the official resolved rate. Reports display official metrics separately from this system's coverage/status/acceptance diagnostics. Exceptions that the grading script itself specifies should become zero are still preserved as raw official output; add this system's classifications only for verifiable external environment or material failures, without rewriting the official script's result rules. [SWE 4.1.0 official aggregation](https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py).

`acceptance_assessment` is written only in new grading reports. Simulated interaction reads the original accepted conclusion; direct reads the original review_verdict=accept and requires review_status to be completed; user acceptance must not be inferred from feeling, Harness self-reports, or code diffs. Derive valid_accept only when the interaction is valid, the user accepts, formal passed=true, and execution contract validation passes; objective failure or request timeout/crash yields false_accept; incomplete technical acceptance or no binary conclusion yields unverified_accept; no acceptance yields not_applicable. This relationship does not override the original Session.accept_validity.

### 6. Public Commands and Archive Binding

`experiment/grading.py` preserves 0075's archive integrity, RecoveryIdentity, round seals, session provenance, baseline and prediction hashes, current generation, and lock validation; adapter dispatch occurs only after extracting common input validation, and new modes must not bypass any of these checks. `--plan` is the sole configuration method for all adapters; the CLI has removed the old dataset parameters and provides no conversion logic. The public grade function also changes to accept a grading plan, with dataset serving only as material for the SWE adapter. Given the same fixed archive, task selection, official dataset, and evaluator, SWE technical conclusions still follow the original official rules; this is a regression check of grading behavior, not old CLI compatibility.

Each grading invocation uses a separate `run_dir/evaluation/<attempt>/`, recording the plan snapshot/material manifest, per-session official logs and normalized results, and summary. Experiment and grading completion statuses are separate; an interrupted grading attempt does not cause the experiment to fail or overwrite existing grading, and the next invocation creates a new attempt. Batch child runs still invoke the same single-run command individually. The new task schema and grading records must not change existing continuation/recovery identities; frozen controllers are not automatically replaced because the host is upgraded.

### 7. Task Breakdown and Acceptance

| Task | Implementation scope | Primary verification |
| --- | --- | --- |
| T1 | Grading contracts, registration, and public results | Reject unknown versions, do not count faults as failures, and do not universally impose fresh |
| T2 | schema 2 task provenance and public collection declarations | schema 1 identities remain unchanged, provenance is authentic, and backend capabilities are checked before execution |
| T3 | Shared collection, archiving, and continuation boundaries for both session types | Same receipt contract, persistence before cleanup, no mixing of provenance/slot/attempt, and no escalation when evidence is missing |
| T4 | Five types of grading adapters and reuse of the official SWE implementation | Official rules are fixed, custom does not pose as official, and KV/TUA are explicitly ungradable when runtime materials are missing |
| T5 | Original run binding, sole plan CLI, and independent reports | Old parameters are rejected, SWE grading works with the new plan, original bytes remain unchanged, and no model/provider/Issue calls occur |
| T6 | Bilingual documentation, actual acceptance, and full regression | Actual official positive and negative cases, classification of environment failures and missing evidence, and itemized reporting of current support scope |

The DAG within the group is T1 → T2 → T3, T1 → T4, T2/T3/T4 → T5 → T6. The managed_service branch of T3 depends on 0081/T3; complete E2B/managed measurement testing in T6 depends on 0081/T4. While these prerequisites remain incomplete, available file collection and post hoc adapters may be implemented, but T3/T6 as a whole must not be marked done, nor may the complete N8 public path be advertised. The sole file ownership for each Task is determined by the frontmatter; adapters, runtime, and grading binding each have a single maintenance location.

The production acceptance script is `backend/scripts/e2e-spec-0083-session-grading.sh`. Offline regression covers equivalent collection in direct/simulated modes; limit overruns, tampering, duplication, and cleanup races; recovery idempotency; different generations; private material access boundaries; grading result classification; official SWE plan behavior; and rejection of the old dataset parameter and missing plans. The acceptance environment enforces a 256 MiB limit for each material or artifact and for the total bytes extracted from a tar archive, a limit of 10000 tar files, and a 16 MiB limit for verifier logs; these are resource limits of the current container executor, not official benchmark limits, and do not replace an explicit max_bytes in a task package. Limit overruns are explicitly rejected or failed, not truncated and then marked successful. Real tests invoke the fixed official grader and cover, at minimum, verifiable positive and negative controls for SWE, production planning, Excel, and TinyDB, plus one custom file task. Test control materials are used only within the acceptance boundary and are not claimed to demonstrate success on real Harness tasks. KV is tested end to end only after collection of the managed workload's original run records is complete; ordinary JSON fixture tests do not replace it. Model-driven task execution, actual grader execution, and offline substitute verification are reported separately.

During implementation, run the relevant pytest, ruff, spec validate/render/graph, and existing 0075/continuation/two-backend regressions. When required real materials or environments are unavailable, retain a pending/blocking explanation; do not fabricate an official pass, rewrite the grader, or restart historical experiments on your own to obtain evidence.

## Drawbacks

Non-patch artifacts increase storage requirements, and retention budgets for workbooks, databases, and service measurements must be explicit; required materials exceeding limits will make a session ineligible for acceptance. Test images and environment locks add optional dependencies and download costs, and ordinary tasks without acceptance requirements should not be forced to install every benchmark environment.

An interface is added between private graders and public artifacts, and managed_service and acceptance in the original environment require actual runtime support. 0081 has not yet been implemented, so this group cannot independently deliver a complete N8 scenario run or trustworthy collection of original KV measurements. Retiring the old CLI will require existing scripts and callers to switch to plan; updating in-repository documentation, examples, and acceptance scripts is required work for this group, while historical frozen records remain unchanged.

## Rationale and alternatives

The choice is “a unified artifact contract + an independent grading plan + small adapters” because interaction, runtime environments, and grading rules change independently. Isolating grading from evolution preserves real user conclusions while enabling independent review when materials are complete; official task-specific environments and rules are maintained in dedicated modules.

The first alternative is to copy the SWE evaluate invocation into the direct runner, then add if/else branches for each benchmark. It cannot preserve different deliverables and would also couple cleanup, timeouts, configuration, and acceptance into two session flows; each subsequent task would require runner changes, so it is not adopted.

The second alternative is to wrap every task as a SWE patch or host pytest. It loses Excel outputs, database replay, and original KV measurements, changes official rules, and cannot support correct attribution of results, so it is not adopted.

The third alternative is to embed the entire 0065 Harness evaluation scheduler in self-evolution experiments. It would rerun tasks and evaluate the capabilities of the specified Harness, rather than accepting a user session that has already occurred; the integration would also introduce a second run/provider lifecycle, so it is not adopted. Only pure metadata parsing and grading adaptation are reused.

The fourth alternative is to first implement an arbitrary dynamic plugin platform and automatic policy generation. Currently, only explicit adapter registration and versioned data are needed, with no requirement for third-party installation or remote code loading, so it is not adopted.

## Prior art

0051 stores user acceptance alongside fresh official SWE execution results and defines false acceptance and unverified acceptance; this group retains its dual-conclusion principle and internal evaluator interface, but not the old public grade parameter. 0056 makes clear that the goal ledger, Persona judgments, and technical results cannot override one another; this group follows the same principle in independent reports.

0075 already provides strict archive binding, complete predictions, official SWE execution, and post-hoc read-only grading, and serves as the direct foundation for this group. The independent Harness evaluation in 0065 already parses official budgets and grader metadata, but does not bind artifacts from current experiment sessions. This group does not rebuild either of these existing capabilities.

0081 plans to provide task environment readiness, service ownership, finalize, managed companions, and output collection; this group defines only the acceptance-side consumption contract, with the complete managed path contingent on the corresponding prerequisite implementation and real-world testing.

## Unresolved questions

The interfaces, compatibility strategy, and initial scope in the current proposal have been reviewed and approved, leaving no architectural forks for implementation to decide. The fact that the 0081 task environment has not yet been implemented is an explicit prerequisite, not an open question that can be silently skipped; insufficient runtime environments or materials for the initial adapters are implementation acceptance limitations and must be recorded individually in the verification report.

## Future possibilities

The independent Harness evaluation executor could later reuse the same adapter, with more suites or custom acceptance modules added. Batch grading can schedule the existing single-run command without introducing a new grading lifecycle. Once trustworthy measurement records and official artifacts are available, paired reports across different rounds, interaction modes, and Harness versions become possible, but the grading plans and task sources must remain comparable, and technical improvement cannot be inferred directly from user experience.
