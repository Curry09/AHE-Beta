# Grade completed user sessions

English | [简体中文](post-run-grading.zh-CN.md)

`experiment.py grade` scores outputs from user sessions in a collected, sealed round. Local and E2B experiments use the same command. A private grading plan selects each task's scorer and locks its materials. Direct and simulated-user sessions are eligible when their original execution and artifact receipts satisfy the scorer's contract.

This evaluates tasks already attempted during evolution. It does not rerun the Harness or measure its general capabilities on new tasks. Use the independent [Harness evaluation tools](../../evaluation/README.md) for that purpose. Grading never feeds results into evolution, changes user reviews or updates Gitea issues.

## 1. Collect the experiment and prepare the grading host

Complete the [U1](u1-experiment.md) or [multi-user](multi-user-experiment.md) workflow and collect the stopped controller's complete archive. The selected round must be sealed, and the collection must have a verified terminal `COMPLETE` receipt. Archive completeness does not prove valid interactions or successful task execution; grading checks those separately.

For E2B experiments, download the archive and grade on a Docker host. Grading does not restart E2B, use nested Docker or make model calls. No model, Gitea or E2B credentials are needed. A destroyed experiment remains gradable if its frozen run directory and complete archive are retained.

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
RUNS_DIR=.experiments
RUN_ID=REPLACE_WITH_COLLECTED_RUN_ID
PLAN=/absolute/path/to/grading-plan.json
```

A batch member uses its child root, for example `.experiments/.batches/<batch_id>/children/u1`, as `RUNS_DIR`. Keep the original frozen controller and inputs. Upgrading this checkout does not upgrade an existing run or invent missing receipts.

## 2. Prepare a private grading plan

Start with a template:

| Template | Purpose |
| --- | --- |
| [swebench.json](../../examples/grading/swebench.json) | The public pvlib SWE example |
| [mixed-benchmarks.json](../../examples/grading/mixed-benchmarks.json) | Separate rules for production planning, Excel and TinyDB |
| [custom.json](../../examples/grading/custom.json) | An operator-defined file verifier |

These are templates, not bundled official datasets or runnable benchmark packs. Replace every material path, placeholder hash, image digest and task/artifact ID with actual inputs. Task IDs must already occur in the frozen run; a plan cannot add tasks or replace their source. Each task can match at most one grader. Tasks without a selected grader are reported as `not_configured`.

A SWE-only plan looks like this:

```json
{
  "schema_version": 1,
  "materials": {
    "dataset": {
      "path": "/absolute/path/to/official-dev.parquet",
      "sha256": "REPLACE_WITH_THE_FILE_SHA256"
    }
  },
  "graders": [
    {
      "adapter": "swebench",
      "contract_version": 1,
      "task_ids": ["pvlib__pvlib-python-1478"],
      "inputs": {"dataset": "dataset"},
      "timeout_seconds": 1800,
      "config": {}
    }
  ]
}
```

`materials` names local regular files with SHA-256 checksums. Directories are not material inputs; task bundles are tar archives. Relative paths resolve from the plan's directory. `inputs` maps adapter input names to material names. `timeout_seconds` is the limit for each selected session; there is no global CLI timeout override. `config` contains adapter-specific options. Run, task digest, session and trial Harness SHA come from the verified archive rather than being copied into the plan.

Use `sha256sum /path/to/material` and verify bytes against a trusted source. A checksum fixes bytes; it does not prove official provenance. Grading does not discover or download datasets. Keep gold patches, hidden tests, expected answers and plans outside public experiment inputs and issue evidence. Evaluation attempts can contain hidden grading materials and should not be published as user feedback.

The public pvlib instance belongs to the [SWE-bench dev split](https://huggingface.co/datasets/princeton-nlp/SWE-bench/tree/e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6/data), rather than Verified or Lite. The pinned dev parquet's SHA-256 is `d758d54540aa4140d0274ed0cc93b8288aa6f323c3c603e2557e7666a47fc41b`. Each instance must uniquely match its frozen repository and base commit.

The old `grade --dataset ... --dataset-sha256 ...` interface has been removed. Even SWE-only invocations require `--plan`; the dataset remains a material inside that plan.

## 3. Check inputs without executing a grader

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" \
  grade "$RUN_ID" --plan "$PLAN" --offline
```

Omit `--round` to select `config.rounds.count`, the configured final round. Grading never silently falls back to an earlier round. The selected round must be positive and sealed.

Offline checks validate plan/material integrity, original archive and session bindings, and the evidence required by configured adapters. They allocate no container, call no model/provider and write no attempt. Passing does not prove that Docker or an official environment will work, or that any output passes tests.

Full SWE predictions need original baseline, path, byte-length and hash receipts. Other outputs require the session's `workspace_evidence.evaluation_artifacts` receipts, binding the original user trial's Harness SHA and collected bytes. A plan cannot turn a file copied in later into original execution evidence. Missing, truncated or oversized outputs remain ungradable; old logs or the latest remote code cannot fill the gap.

V2 task packages can declare public workspace artifacts and size limits; v3 container tasks can also collect declared service artifacts through the environment driver. Declarations contain no hidden tests or expected answers. Managed-service measurements require runtime support and trusted receipts from the original execution. Grading checks the adapter’s requirements and retains an ungradable result when capabilities or evidence are missing; ordinary files cannot replace that evidence. See [task packages](../CONFIGURATION.md#task-package) for environment formats.

For example, a new custom file task can add the following to its version 2 task package before the experiment starts. The `output` ID then matches `custom.json`'s `artifact_map`; the task must actually produce this file. The size limit is an explicit operator choice, not an automatic benchmark default.

```json
{
  "artifacts": {
    "version": 1,
    "exports": [
      {
        "id": "output",
        "source": "workspace",
        "path": "output.json",
        "content_type": "application/json",
        "required": true,
        "max_bytes": 1048576
      }
    ]
  }
}
```

This is an excerpt, not a complete task package. Use the existing instruction/source/setup fields for the actual task. NL2Repo's `generated_repository` must similarly be a declared archive produced before collection; grading does not package a directory from the current remote repository.

The current container runner limits each material/artifact and unpacked tar to 256 MiB, tar entries to 10,000 files, and verifier logs to 16 MiB. These are runner resource limits, not official benchmark rules. Task packages still set their own `max_bytes`; an oversized input is rejected, never truncated into a successful grade.

## 4. Execute the selected graders

```bash
uv run --locked --extra experiments --extra evaluation \
  python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" \
  --json grade "$RUN_ID" --plan "$PLAN"
```

Sessions are graded serially on the local host. Docker downloads, builds and tests may take substantial disk space and time. Task-produced code is not executed on the host.

| Adapter | Execution and required evidence |
| --- | --- |
| `swebench` | Locked official 4.1.0 CLI and fresh instance environment; full prediction and matching dataset row. |
| `terminal-bench` | Pinned official task bundle and verifier mode. Production planning replays submitted SQL in clean databases. KV requires trusted original load-generator measurements; new load tests cannot substitute. |
| `tua-bench` | Official verifier/reward semantics and frozen expected materials. Only reconstructable supported environments can be graded after collection; original-environment evidence is not silently replaced. |
| `nl2repo` | Pinned official post-processing, commands, counts and original tests from the task image. Reports official pass rate; without a declared binary policy, `passed` is null. Operator thresholds are identified separately. |
| `custom` | Fixed script in an isolated container. It writes `/logs/verifier/result.json`, for example `{"passed": true, "score": 1}`; results remain explicitly custom. |

An adapter name does not mean every task or version of its suite is supported. Unknown sources or unsupported execution modes are rejected. See the [verification guide](../VERIFICATION.md) for current checks; fixture tests are not official benchmark results.

An official bundle preserves the pinned task root (`task.toml`, `tests/`, `environment/`) in one tar archive. Terminal/TUA require `build_official_environment: true` to build the frozen environment and record its actual image identity before verification. NL2Repo/custom specify immutable images. External expected answers and dependency materials must also be fixed; pinning a script alone does not freeze its downloaded URLs.

## 5. Read the separate report

Each execution creates `<runs-dir>/<run_id>/evaluation/<attempt_id>/`, keeping the frozen plan, material identities, per-session logs/raw reports and normalized summary. Interrupted attempts stay incomplete; rerunning creates a new attempt. The original archive, Session, manifest, checkpoints and seals remain unchanged.

| Status | Interpretation |
| --- | --- |
| `completed` | Valid scoring execution, with a pass/failure or a continuous score without a binary verdict |
| `not_configured`, `unsupported` | No selected rule or unsupported source/contract |
| `missing_artifact`, `ungradable` | Missing output or unsatisfied evidence/environment contract |
| `unavailable`, `crashed`, `timed_out` | Grader infrastructure, execution or parsing failure |
| `not_evaluated` | Official scorer skipped evaluation, such as an empty SWE prediction |

Noncompleted results have `passed: null`; infrastructure failures are not normal task failures. An intact empty SWE patch is `not_evaluated / official_empty_prediction`, not a missing patch or completed failure. Raw official metrics and their denominator remain separate from coverage diagnostics; excluding skipped/error cases must not inflate an alleged official success rate.

Exit code `0` and `ok: true` indicate complete scoring, which can include valid task failures. Inspect individual verdicts and scores; they do not mean every task passed.

The report adds `acceptance_assessment` without changing original acceptance. `valid_accept` requires valid interaction, original acceptance, verified execution and `passed: true`. Accepted failures are `false_accept`; missing verification or score-only results are `unverified_accept`; no acceptance is `not_applicable`. Direct acceptance uses the completed original review, not the Harness's success claim.

The experiment's `evaluation.official_grading` stays `false`, keeping hidden graders outside evolution. This post-run command and the independent Harness benchmark framework remain separate workflows.
