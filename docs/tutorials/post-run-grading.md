# Grade collected SWE task predictions

English | [简体中文](post-run-grading.zh-CN.md)

`grade` evaluates the full patch produced by each SWE task session in a selected, sealed round. It runs after experiment collection, through the same `backend/scripts/experiment.py` entry for local and E2B runs. Ordinary task sessions are listed as not applicable.

This is a score for tasks users already tried during evolution. **It is not a new held-out test of the Harness's general capabilities.** Use the independent [evaluation tools](../../evaluation/README.md) for that separate question. Scores do not enter feedback, proposals, delivery decisions or CI gates; user impressions and acceptance records remain unchanged.

## 1. Prepare the collected run and grading host

Complete the [N1](n1-experiment.md) or [multi-user](multi-user-experiment.md) workflow and collect the stopped controller's artifacts. Grading requires a verified terminal `COMPLETE` collection and a sealed selected round. A collection marked COMPLETE alone does not establish successful user sessions or official test results. Grading validates session identities, task bindings and recovery records before scoring.

Run grading on a host with Docker, including for E2B experiments: download the complete archive first, then score it locally. Grading does not run nested Docker in E2B or restart experiment resources. A destroyed run can be graded if its frozen materials and complete archive remain available. No model, Gitea or E2B credentials are needed by `grade`.

From the repository root:

```bash
uv sync --locked --extra experiments --extra dev --extra evaluation
RUNS_DIR=.experiments
RUN_ID=REPLACE_WITH_COLLECTED_RUN_ID
DATASET=/absolute/path/to/official-dataset.parquet
DATASET_SHA256=REPLACE_WITH_VERIFIED_SHA256
```

For a batch member, set `RUNS_DIR` to its child root, for example `.experiments/.batches/<batch_id>/children/n1`, rather than the outer batch root. Keep the original frozen controller and inputs; resume does not upgrade them.

## 2. Supply the official dataset separately

Provide a local official dataset in JSON, JSONL or parquet format, with a verified SHA-256 for its exact bytes. Each selected SWE instance must match exactly one row, including its repository and base commit. A different task revision, duplicate selected instance, changed dataset or wrong checksum is rejected before evaluation.

Check the bytes you obtained with `sha256sum "$DATASET"` and compare them with the source you trust. A checksum pins those bytes; it does not prove that an arbitrary file is an official dataset. The grading command does not download or discover datasets for you.

The public example `pvlib__pvlib-python-1478` belongs to the [SWE-bench dev split](https://huggingface.co/datasets/princeton-nlp/SWE-bench/tree/e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6/data), not Verified or Lite. Use the official dev file containing that instance; an arbitrary Verified file will not match this example. The dataset revision used for validation is `e48e2bd1e9fecd5bbd641e9414ac59da9f2e69f6`; `data/dev-00000-of-00001.parquet` has SHA-256 `d758d54540aa4140d0274ed0cc93b8288aa6f323c3c603e2557e7666a47fc41b`.

Keep the dataset outside the committed experiment materials. Its gold patch and hidden tests belong only to this post-run evaluation; never place them in task instructions, task packages, persona inputs, experiment JSON or issue evidence. Selected official rows are copied into the independent grading attempt directory, so that directory contains hidden evaluation material and should not be published as ordinary experiment feedback.

## 3. Verify inputs without invoking Docker

```bash
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" grade "$RUN_ID" --dataset "$DATASET" --dataset-sha256 "$DATASET_SHA256" --offline
```

Offline grading checks frozen identities, the collected archive, session predictions and dataset bindings. It does not call Docker, models, Gitea or E2B, and writes no grading attempt. Passing this check does not mean the patch passes official tests.

New controllers preserve full predictions with path, SHA-256 and byte-length receipts. Older frozen controllers may have kept only a diff hash or a truncated review preview. Those sessions cannot be scored from their logs or current remote code; start a new run to obtain complete predictions. A missing prediction is different from a successfully exported empty patch.

Export is relative to the session’s initial Git baseline and includes committed changes, staged changes and nonignored new files. Grading binds `diff_base_commit` to the frozen SWE source revision; a hash without that baseline binding is insufficient.

The pinned official evaluator lists empty predictions in `empty_patch_ids`, rather than as completed tests. See [SWE-bench 4.1.0 reporting](https://github.com/SWE-bench/SWE-bench/blob/v4.1.0/swebench/harness/reporting.py). An intact empty-patch receipt therefore passes prediction-integrity checks but receives `not_evaluated` with reason `official_empty_prediction`, no pass/fail verdict and no fresh test container. It does not count as complete scoring (`ok: false`).

## 4. Run official fresh-container grading

```bash
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" grade "$RUN_ID" --dataset "$DATASET" --dataset-sha256 "$DATASET_SHA256"
# Select an earlier sealed round and override the per-session timeout:
uv run --locked --extra experiments --extra evaluation python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" --json grade "$RUN_ID" --dataset "$DATASET" --dataset-sha256 "$DATASET_SHA256" --round 1 --timeout-seconds 1800
```

Without `--round`, grading selects `config.rounds.count`, the configured final round; it does not silently select an earlier available round. `--round` must be positive and already sealed. `--timeout-seconds` defaults to 1800 for each evaluated session. The initial implementation scores sessions serially; it does not schedule whole batches.

The locked evaluation extra supplies the official SWE-bench evaluator. Docker must be available and able to obtain required images. Image downloads, builds and tests can take substantial disk space and time. Each applicable nonempty prediction is evaluated in a fresh official instance environment. No model calls are made during grading.

## 5. Read results without changing the experiment

Each formal invocation creates a new directory under `<runs-dir>/<run_id>/evaluation/<attempt_id>/`, preserving prior attempts. It contains the grading intent, predictions, selected dataset rows, evaluator logs and reports, and a summary linked to the original run, archive, plan, session and Harness identities. An interrupted attempt remains incomplete; rerunning creates another attempt.

The summary distinguishes a completed official pass or fail from missing predictions, unavailable infrastructure, a crashed evaluator and timeout. An unknown or malformed official report is not a normal test failure. Ordinary tasks are not scored as SWE instances, and invalid sessions are not promoted to valid by archive completeness or user acceptance.

Exit code `0` and summary `ok: true` mean the grading operation completed with complete results, including official test failures. They do not mean every prediction passed. Inspect the summary's separate passed counts and per-session verdicts. Missing or ungradable predictions do not count as complete scoring.

Grading does not rewrite original sessions, manifest, checkpoints, seals or collected archive, and does not update Gitea issues. Compare technical results with the separately recorded user experience rather than replacing one with the other. The experiment field `evaluation.official_grading` remains `false`: it keeps grading out of the evolution loop, while this explicit command provides independent post-run scoring.

See the [validation report](../validation/post-run-grading.md) for the distinction between offline tests with evaluator substitutes and any actual official Docker evaluation. The command examples describe the supported workflow; they do not claim the example experiment passed official tests.

An official summary can still label a startup/collection failure unresolved. When the test log contains an explicit pytest startup diagnostic, grading records `crashed / official_test_start_failed` instead of a completed task failure. The current official `pvlib-1478` image reproduced a NumPy 2 incompatibility with the old project; see the validation report and do not interpret it as Harness performance.
