# Harness evaluation suite (2026-09-20)

`task-manifest.json` contains the task freeze for the ordinary pilot. The
machine-readable freeze receipt is [`freeze-record.json`](freeze-record.json).
It freezes task IDs, source revisions/material hashes, grader contracts, model
roles, and the v0 harness archive for `ordinary_1` and `ordinary_4`.

Execution and preparation rules are specified in [`SPEC-experiment-preparation-and-sandbox-execution.md`](SPEC-experiment-preparation-and-sandbox-execution.md).

The planned run is Harbor-runnable: Harbor owns the complete batch,
checkpoint/artifact lifecycle, user/harness interaction, design, development,
and grading phases in Harbor Docker task environments. The model gateway for every role is
Boyue; formal configuration must not use OpenRouter or move design/development
to the local controller. E2B-to-Boyue connectivity was validated separately,
but Harbor 0.23.0 has no E2B environment adapter, so E2B is not the formal
backend in this revision.

The pilot configuration is [configs/ordinary-pilot.json](configs/ordinary-pilot.json).
The portable five-round N=1/N=4 control-plane configuration is
[configs/ordinary-1-4-five-rounds.json](configs/ordinary-1-4-five-rounds.json).
The migration and execution procedure is
[EXPERIMENT-RUNBOOK-ordinary-1-4-five-rounds.md](EXPERIMENT-RUNBOOK-ordinary-1-4-five-rounds.md).
The parallel preparation plan for the first three scaling points is
[configs/ordinary-scaling-1-4-8.json](configs/ordinary-scaling-1-4-8.json).
Its current gate status is recorded in
[n8-preflight-20260921.json](n8-preflight-20260921.json).
It declares three independent experiment IDs and isolation requirements; it is
not a formal freeze until the pending N=8 task records are resolved.
Trial and batch output are schema-defined under [schemas](schemas), and the
deterministic headline aggregation is `tools/summarize_results.py`. Checkpoint
writes must go through `tools/checkpoint_store.py`; free-form log interpretation
is not a scoring path.

The Boyue gateway connectivity and Harbor adapter smoke are recorded in
[`harbor-integration-canary-20260920.json`](harbor-integration-canary-20260920.json).
Both OpenAI-compatible `/v1/chat/completions` and Anthropic-compatible
`/v1/messages` returned the requested GLM5.3 models. Harbor 0.23.0 passed a
local Docker dry-run, a one-trial `nop` lifecycle smoke, and a one-trial
end-to-end `harness-v0` run with verifier reward `1.0`. The Daytona reward-zero
trial is retained as a connectivity diagnostic, not a benchmark score.

The current pilot freeze uses `baseline-v0-cade14d` as the harness under test,
`glm-5.3-flash` for the harness and user simulator, and `glm-5.3` for design
and development. The formal gateway is Boyue (OpenAI-compatible and
Anthropic-compatible endpoints). The frozen ordinary pilot tasks are `O03`, `O09`, `O14`, and
`O18`; Owner is mechanical (`review=false`), and the remaining ordinary slots
are not yet frozen.

For concurrent runs, use the per-experiment stack generated from
`backend/deploy/experiment/docker-compose.yml`. Do not use the legacy fixed
singleton stack in `backend/deploy/gitea/docker-compose.yml`: its fixed
container names, ports, and network are intentionally incompatible with
parallel experiments.

All model roles use Boyue in this scaling plan: harness and simulated user use
`glm-5.3-flash`; designer and developer use `glm-5.3`. Credentials are injected
into the Harbor task from the ignored `.boyue` file or equivalent secret store.
OpenRouter is not a formal fallback. Historical OpenRouter/Daytona canaries are
diagnostic artifacts only and must not enter score aggregation.

## Composition

- Ordinary pool: 20 tasks (`O01`–`O20`), balanced across SWE, Terminal, TUA, and tau3.
- Mechanism pool: 12 interactive seeds (`M01`–`M12`).
- Full mixed set: `O01`–`O20` + `M01`–`M12` (32 tasks).

The mechanism pool is not folded into the ordinary benchmark score. It is included in the mixed headline run, but every result retains `stratum=ordinary|mechanism` and `mechanism` metadata.

## Scaling

The ordinary-only pilot curve is 1/4/8/12/20. The mixed curve is 16/24/32:

```text
1  = ordinary_1  = [O03]
4  = ordinary_4  = [O03, O09, O14, O18]
8  = ordinary_8  = [O03, O09, O14, O18, O06, O12, O15, NL2Repo-01]
```

```text
16 = ordinary_12 + mechanism_4
24 = ordinary_16 + mechanism_8
32 = ordinary_20 + mechanism_12
```

`mechanism_4 ⊂ mechanism_8 ⊂ mechanism_12`, and the ordinary subsets are also nested. The 24-task point is optional; the 32-task point is the main experiment.

## Freeze status

The four tasks used by the current pilot are frozen. The freeze receipt is
deliberately separate from a run result: it does not claim that a formal score
has been produced. Before launch, the runner still has to resolve immutable
Harbor Docker image digests and pass the full-loop Boyue canary. `O01`–`O02`, `O04`–`O08`, `O10`–`O13`, and
`O16`–`O20` remain `needs-dev-freeze` and must not silently enter this pilot.
