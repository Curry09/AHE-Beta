# Ordinary N=1/N=4 Five-Round Experiment Migration Runbook

This document is the operational contract for migrating the experiment to another machine or handing it to another operator. See the official configuration at
[`configs/ordinary-1-4-five-rounds.json`](configs/ordinary-1-4-five-rounds.json).
See the paper’s main experiment, quantity scaling, and other ablation groups at
[`EXPERIMENT-MATRIX.md`](EXPERIMENT-MATRIX.md). N=1/N=4 is an engineering pilot and is not automatically equivalent to the paper matrix’s stratified S4.

## 1. Experimental Question and Fixed Variables

This experiment compares two independent harness evolution tracks:

| Experiment | Tasks | Interaction per round | Rounds |
|---|---|---|---:|
| `ordinary-1-glm53-v0-r5` | O03 | Simulated user | 5 |
| `ordinary-4-glm53-v0-r5` | O03, O09, O14, O18 | O03 simulated user, O09 direct output, O14 simulated user, O18 benchmark-native user | 5 |

Both tracks start from `baseline-v0-cade14d`, but must not share subsequent revisions, Gitea, sessions, checkpoints, or artifacts. This makes it possible to compare the effect of task scale on closed-loop evolution, rather than results contaminated by interaction between the two tracks.

Fixed roles and models:

- Harness inside Harbor tasks: Boyue `glm-5.3-flash`.
- Historical user simulation inside Harbor tasks: Boyue `glm-5.3-flash`.
- Designer/developer inside Harbor tasks: Boyue `glm-5.3`.
- PM/divergent: disabled, `N_DIVERGENTS=0`.
- Owner: mechanical acceptance, `review=false`; does not call an LLM.

## 2. Timeout and Round Semantics

For each task, the agent time budget should preferentially use the official task metadata; if no official budget is available, use 1800 seconds. The Harbor outer watchdog is fixed at:

```text
outer_timeout = official_agent_timeout + 600 seconds
```

The additional 600 seconds are only for writing artifacts/checkpoints to disk; model execution must not continue. Five rounds are not five independent baselines: round 1 starts from v0, and round `r+1` uses the harness revision released after the round `r` owner gate. If a round does not release a revision, continue using the previous revision.

The boundary for each round is:

1. Harbor Docker tasks execute all tasks for the round and collect harness transcripts, user traces, patches, and grader outputs.
2. Write sessions, user feedback, and objective grader results to the round’s checkpoint.
3. The local designer reads only the frozen inputs for this round and produces design deliverables.
4. The local developer modifies the current harness revision based on the design and traces.
5. The mechanical owner runs the gate; if it passes, release a new revision; otherwise, retain the old revision.
6. Write `round-{r}.json` and a compressed checkpoint, then proceed to the next round.

Recovery may only resume from the latest complete checkpoint; do not recover from the in-memory state of a partially completed process, and do not rewrite completed trials. Rerun any incomplete round in its entirety, idempotently.

## 3. Machine and Credential Preparation

At the repository root, prepare Python 3.12, Harbor 0.23.0, Docker, and this repository’s dependencies. Store credentials only in the execution machine’s environment or in a local ignored file; never write them to JSON, logs, or git:

```bash
export BOYUE_API_KEY='...'
export HARNESS_LLM_API_KEY="$BOYUE_API_KEY"
export USER_LLM_API_KEY="$BOYUE_API_KEY"
export DESIGNER_LLM_API_KEY="$BOYUE_API_KEY"
export DEVELOPER_LLM_API_KEY="$BOYUE_API_KEY"
export HARNESS_LLM_BASE_URL='https://api.boyuerichdata.opensphereai.com/v1'
export USER_LLM_BASE_URL='https://api.boyuerichdata.opensphereai.com/v1'
export DESIGNER_LLM_BASE_URL='https://api.boyuerichdata.opensphereai.com/v1'
export DEVELOPER_LLM_BASE_URL='https://api.boyuerichdata.opensphereai.com/v1'
export HARNESS_LLM_MODEL='glm-5.3-flash'
export USER_LLM_MODEL='glm-5.3-flash'
export DESIGNER_LLM_MODEL='glm-5.3'
export DEVELOPER_LLM_MODEL='glm-5.3'
export ANTHROPIC_BASE_URL='https://api.boyuerichdata.opensphereai.com'
export ANTHROPIC_AUTH_TOKEN="$BOYUE_API_KEY"
export ANTHROPIC_MODEL='glm-5.3'
export ANTHROPIC_SMALL_FAST_MODEL='glm-5.3'
export PYTHONPATH="$PWD"
```

The four roles inside Harbor tasks share the Boyue gateway, but each role still uses a separate model variable for auditing and recovery. Inject credentials only through Harbor secrets/env; do not write them to task artifacts. The official path uses Harbor Docker; the current Harbor 0.23.0 has no E2B environment adapter, so E2B must not be described as a connected official backend.

The historical v0 harness archive must be retrieved by the operator from the controlled artifact store, and the following must be verified:

```text
HSE_HARNESS_ARCHIVE=.artifacts/harness-v0-cade14d.tar.gz
sha256 = dd7cdd91a4dc170af3662cdca28d2ed9fbd0dd2676e57ce9a4041146a488e011
```

NexAU is uploaded to the sandbox at startup with a frozen snapshot of the official source code, and installed locally in editable mode in `/opt/hse-venv`; it does not rely on PyPI’s `nexau==0.4.1` (this package has not been published to the current PyPI).

## 4. Run a Canary First, Then the Formal Trials

`harbor-ordinary-o03` in the repository is a pipeline canary. Its `tests/test.sh` only verifies that `session.json` and `model.patch` exist, and writes reward `1`; this reward is not official SWE accuracy and must not be included in the paper’s main table.

After preparing the archive, run:

```bash
mkdir -p .artifacts
# Place the artifact store from the controlled source into .artifacts/harness-v0-cade14d.tar.gz
sha256sum .artifacts/harness-v0-cade14d.tar.gz

uvx --from harbor==0.23.0 harbor run \
  --config evaluation/harness-suite-20260920/harbor-ordinary-o03/config.json \
  --jobs-dir evaluation/harness-suite-20260920/harbor-canary-jobs \
  --job-name ordinary-1-o03-historical-user-canary \
  --env docker --n-concurrent 1 --yes \
  --override-cpus 2 --override-memory-mb 6144 --override-storage-mb 10240 \
  --agent-env 'HSE_HARNESS_ARCHIVE=${HSE_HARNESS_ARCHIVE}' \
  --agent-env 'BOYUE_API_KEY=${BOYUE_API_KEY}' \
  --agent-env 'HARNESS_LLM_API_KEY=${HARNESS_LLM_API_KEY}' \
  --agent-env 'USER_LLM_API_KEY=${USER_LLM_API_KEY}' \
  --agent-env 'DESIGNER_LLM_API_KEY=${DESIGNER_LLM_API_KEY}' \
  --agent-env 'DEVELOPER_LLM_API_KEY=${DEVELOPER_LLM_API_KEY}' \
  --agent-env 'HARNESS_LLM_BASE_URL=${HARNESS_LLM_BASE_URL}' \
  --agent-env 'USER_LLM_BASE_URL=${USER_LLM_BASE_URL}' \
  --agent-env 'DESIGNER_LLM_BASE_URL=${DESIGNER_LLM_BASE_URL}' \
  --agent-env 'DEVELOPER_LLM_BASE_URL=${DEVELOPER_LLM_BASE_URL}' \
  --agent-env 'HARNESS_LLM_MODEL=${HARNESS_LLM_MODEL}' \
  --agent-env 'USER_LLM_MODEL=${USER_LLM_MODEL}' \
  --agent-env 'DESIGNER_LLM_MODEL=${DESIGNER_LLM_MODEL}' \
  --agent-env 'DEVELOPER_LLM_MODEL=${DEVELOPER_LLM_MODEL}' \
  --agent-env 'ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL}' \
  --agent-env 'ANTHROPIC_AUTH_TOKEN=${ANTHROPIC_AUTH_TOKEN}' \
  --agent-env 'ANTHROPIC_MODEL=${ANTHROPIC_MODEL}' \
  --agent-env 'ANTHROPIC_SMALL_FAST_MODEL=${ANTHROPIC_SMALL_FAST_MODEL}' \
  --agent-env HSE_OFFICIAL_AGENT_TIMEOUT_SECONDS=1800 \
  --agent-env HSE_OUTER_AGENT_TIMEOUT_SECONDS=2400 \
  --agent-env HSE_PERSONA_ID=sr-01-willison \
  --agent-env HSE_TASK_INSTANCE=pvlib__pvlib-python-1478
```

Pass criteria: sandbox creation succeeds, a model transcript is produced, the user loop can read and write the same `/testbed`, the artifact downloads completely, and there are no Harbor exceptions. Only after the canary passes may it be replaced with the formal task package and official grader.

## 5. Formal Five-Round Execution Order

The operator must create the following resources independently for each experiment track:

```text
experiment process
Compose project
Gitea instance + volume
act-runner / Vigil
session store
checkpoint root
artifact root
```

Do not use the fixed singleton stack in `backend/deploy/gitea/docker-compose.yml`; for parallel experiments, use `backend/deploy/experiment/docker-compose.yml` to generate unique project names and ports.

The pseudocode-level execution order is as follows; actual task provisioning is handled by the benchmark-specific Harbor executor:

```text
for experiment in [ordinary-1-glm53-v0-r5, ordinary-4-glm53-v0-r5]:
    revision = baseline-v0-cade14d
    for round in 1..5:
        freeze(round, experiment, revision, task_ids, interaction_assignment)
        run every task in a fresh Harbor task environment
        download transcript/user_trace/patch/official_grader
        checkpoint(round, inputs, outputs, revision)
        design in the Harbor task with Boyue glm-5.3
        develop in the Harbor task with Boyue glm-5.3
        mechanical owner gate (review=false)
        revision = released_revision or revision
        checkpoint(round, revision)
```

Task results must record: task ID, benchmark, revision, model, interaction mode, persona seed, official/outer timeout, provider, sandbox ID, grader version, reward, end_reason, artifact hashes, and infrastructure status. Infrastructure failures must not be counted as task failures in accuracy, but must be reported separately.

## 6. Results and Recovery

Save at least the following for each round:

```text
runs/<experiment_id>/round-<r>/trials/<task_id>/result.json
runs/<experiment_id>/round-<r>/trials/<task_id>/session.json
runs/<experiment_id>/round-<r>/trials/<task_id>/trace.jsonl
runs/<experiment_id>/round-<r>/trials/<task_id>/grader.json
runs/<experiment_id>/checkpoints/round-<r>.json
runs/<experiment_id>/checkpoints/round-<r>.tar.gz
runs/<experiment_id>/summary.json
```

The main table must report: task success, harness completion, user experience, interaction failure, official deadline, and infrastructure failure. Do not report only Harbor’s average reward, and do not treat the canary reward as benchmark accuracy.

If the process is interrupted: read the latest checkpoint, confirm that artifact hashes for completed trials are unchanged, and rerun only the currently incomplete round; do not regenerate the manifest, change the task revision, change the persona seed, or feed the release revision from the other experiment track back into this one.

## 7. Pre-Migration Checklist

- [ ] `configs/ordinary-1-4-five-rounds.json` hash has been recorded.
- [ ] The task revisions, graders, and image digests for O03/O09/O14/O18 match the freeze record.
- [ ] `baseline-v0-cade14d` archive hash is correct.
- [ ] Boyue `glm-5.3-flash` and `glm-5.3` probes succeed from the Harbor task environment.
- [ ] The Harbor full-loop canary executes the user, harness, designer, developer, and owner phases in one task.
- [ ] The selected Harbor environment creates, starts, uploads/downloads artifacts, and deletes cleanly.
- [ ] PM is closed; Owner is mechanical `review=false`.
- [ ] N=1 and N=4 use different artifact/Gitea/revision lineages.
- [ ] Official timeout and outer timeout are recorded separately.
- [ ] Canary and official grader results are stored and reported separately.
- [ ] A global configuration check confirms there is no OpenRouter endpoint, key, or model.
