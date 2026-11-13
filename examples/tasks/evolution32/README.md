# Evolution task materials

[简体中文](README.zh-CN.md)

This collection supplies the 32 scenarios used by the U8 mixed/direct, U16 mixed, and U32 mixed examples. The first 8 and first 16 entries form the smaller groups. Run configuration selects task packages and interaction modes; this manifest records material identities and provenance.

The examples start a new run from the current seed. Input files, runtime recipes, and image digests are frozen during preparation. Historical payloads and explicitly reconstructed upstream sources retain separate provenance. These scenarios drive Harness evolution; exported Harnesses can be evaluated independently through `evaluation.yaml`.

## Contents

- `manifest.json`: ordered task keys, original benchmark identifiers, hashes of the current task definitions and instructions, persona bindings, and material publication status.
- `<task-key>/instruction.md`: the original task request, with a terminal newline added when needed.
- `<task-key>/task.json`: executable schema-3 environment and artifact declarations, with pinned image digests and input checksums.
- `recipes/initialize.py`: restore a genuine original Git baseline and verified ignored input files.
- `recipes/verify.py`: check inputs and runtime availability before an Actor starts.
- `recipes/finalize.py`: collect the independent KV measurement and a separate public summary after the Actor exits.
- `recipes/collect_directory.py` and task-specific collectors: preserve existing task files and outputs after the Actor exits.
- `recipes/freeze_initial_git.py`: record declared initial files in the prepared Git baseline before execution.

Publication and validation status are recorded in `manifest.json`. The [versioned material Release](https://github.com/Curry09/AHE-Beta/releases/tag/evolution32-task-materials-v1) contains 37 input assets plus `materials.lock.json`, `SHA256SUMS`, and a README. Preparation downloads only the selected tasks' assets and verifies their hashes and file inventories. The repository is currently private; authenticated download is checked separately, and anonymous material download will be verified after it becomes public. No GitHub authentication is added to the generic task-material loader.

Use the manifest in your checkout to verify its task definitions. The Release's `materials.lock.json` records the definitions at the Release tag, and its `SHA256SUMS` verifies the downloadable files. Later changes to execution settings can reuse the same inputs and images.

All 32 task images use `ghcr.io/mmjzmy/ahe-beta-tasks:<lowercase-task-key>-v<version>`, such as `m04-v1`, `o03-v1`, and `kv-live-surgery-v1`. Executable task definitions pin the image digest; source revisions, dependency versions, and build recipes remain in the manifest.

All 32 task images and four companion service images are public. Each passed anonymous download, image identity checks, and tool startup in clean E2B environments. All 32 final task recipes also passed real local Docker initialization, readiness, finalization, and collection checks without an Actor. The [manifest](manifest.json) records material identities and validation receipts; the [verification guide](../../../docs/VERIFICATION.md) lists checks users can rerun on this checkout.

## Material boundaries

Raw build inputs remain management material. In particular, the KV server source and benchmark-author README are used to build its stripped binary and are not staged into the Actor workspace. The KV load generator runs in an independent companion. Its raw measurements and logs remain management evidence; an explicit projection exposes the public speedup, correctness, and liveness observations.

Where an original Git baseline exists, patches are reviewed against that source. M01, M03, and Pretrain additionally record the supplied initial files in a deterministic prepared commit; their provenance records identify both revisions, and source/data bytes are unchanged. Native non-Git tasks retain their original environment and use source archives or declared outputs. Workbook and service outputs also use declared artifacts. Each attempt receives a fresh environment. Services stay alive until measurement finalization and artifact collection finish.

The fixed task recipes contain scenario preparation logic. The experiment controller, E2B provider, and Docker driver use the shared environment contract without task-key branches. A new task can declare its own inputs, image, commands, services, and artifacts.

See the [evolution tutorial](../../../docs/tutorials/evolution32.md) for model/provider configuration and launching the four examples.

## Task order

| Key | Source family | Original task identifier |
| --- | --- | --- |
| O03 | SWE-bench | `pvlib__pvlib-python-1478` |
| O09 | Terminal-Bench | `production-planning` |
| O14 | TUA-Bench | `010-pivot-product-revenue` |
| M03 | mechanism | `superset-goal-discovery` |
| O01 | SWE-bench | `pylint-dev__astroid-2240` |
| kv-live-surgery | Terminal-Bench | `kv-live-surgery` |
| tinydb | NL2Repo | `tinydb` |
| M01 | mechanism | `sqlfluff-subagent-review` |
| O05 | SWE-bench | `marshmallow-code__marshmallow-1229` |
| O06 | SWE-bench | `sqlfluff__sqlfluff-2336` |
| vf2-speedup-networkx | Terminal-Bench | `vf2-speedup-networkx` |
| pretrain-shard-corruption | Terminal-Bench | `pretrain-shard-corruption` |
| 091-add-receipts-bookkeeping | TUA-Bench | `091-add-receipts-bookkeeping` |
| flask-restful | NL2Repo | `flask-restful` |
| M05 | mechanism | `permission-schema-migration` |
| M09 | mechanism | `plan-blocked-dependency` |
| O02 | SWE-bench | `pydicom__pydicom-1334` |
| O04 | SWE-bench | `pyvista__pyvista-3750` |
| astroid-1030 | SWE-bench | `astroid-1030` |
| sqlfluff-3608 | SWE-bench | `sqlfluff-3608` |
| marshmallow-2123 | SWE-bench | `marshmallow-2123` |
| payments-pipeline-fix | Terminal-Bench | `payments-pipeline-fix` |
| wal-recovery-ordering | Terminal-Bench | `wal-recovery-ordering` |
| vba-userform-port | Terminal-Bench | `vba-userform-port` |
| react-lead-form | Terminal-Bench | `react-lead-form` |
| 080-convert-novel-epub | TUA-Bench | `080-convert-novel-epub` |
| cookiecutter | NL2Repo | `cookiecutter` |
| tqdm | NL2Repo | `tqdm` |
| M02 | mechanism | `superset-ci-loop` |
| M04 | mechanism | `dbt-direction-negotiation` |
| M07 | mechanism | `memory-project-constraints` |
| M10 | mechanism | `review-verifier-catches-regression` |
