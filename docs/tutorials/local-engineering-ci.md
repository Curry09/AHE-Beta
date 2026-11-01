# Enable local engineering CI

English | [简体中文](local-engineering-ci.zh-CN.md)

Local Docker + localhost Gitea can run a dedicated Gitea Actions runner for each experiment. Set `runtime.local.ci_enabled: true` before preparation and keep using `backend/scripts/experiment.py`. CI is disabled by default; E2B + Gitea.com does not support this runner contract.

Engineering CI checks the Harness's code structure and artifacts. The builtin [smoke workflow](../../backend/harness_template/.gitea/workflows/smoke.yml) compiles Python, checks required files and rejects private runtime files. CI makes no model calls and runs no benchmark. Official SWE session `grade` and independent held-out Harness evaluation remain separate post-run workflows. Each run uses its own Docker daemon and job storage for trusted Harness engineering code.

## 1. Install and copy the local configuration

Run from the repository root on Linux or WSL2 with Python 3.12+, uv, Docker and Docker Compose. Docker must support the privileged container used for the nested CI daemon; backend preflight checks actual readiness. Keep the commands in the same shell. Use the existing [credential template](../../examples/experiment.env.example); the runner registration token is created privately by the backend, not added to this file.

```bash
uv sync --locked --extra experiments
if [ ! -e .env.experiment ]; then
  cp examples/experiment.env.example .env.experiment
fi
chmod 600 .env.experiment
WORK_DIR="$(mktemp -d)"
CONFIG="$WORK_DIR/experiment-local-ci.json"
```

Fill `.env.experiment` with the model credentials described in [configuration](../CONFIGURATION.md). If you already have a filled protected file, keep using it. The next command copies the maintained local U1 template and enables CI. Because the copy lives in a temporary directory, it resolves the original task and persona paths to absolute paths. The builtin Harness needs no path rewrite. Review models, rounds and workload in the resulting configuration before preparation; this template runs five rounds and uses models during the experiment.

```bash
uv run --locked --extra experiments python - "$CONFIG" <<'PYCODE'
import json
import sys
from pathlib import Path

template = Path("examples/experiments/u1-local.json").resolve()
config = json.loads(template.read_text(encoding="utf-8"))
config["name"] = "u1-local-ci"
config["runtime"].setdefault("local", {})["ci_enabled"] = True
workload = config["workload"]
for field in ("task_package", "persona_library"):
    workload[field] = str((template.parent / workload[field]).resolve())
destination = Path(sys.argv[1]).resolve()
destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(destination)
PYCODE
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
```

The offline check validates configuration and local materials. It does not prove Docker, registration, Actions checkout or status reporting works. Keep the temporary directory until preparation has frozen its contents; use a persistent configuration path for long-term work.

## 2. Choose images and freeze the experiment

The defaults use `gitea/act_runner:0.2.11` and a digest-pinned `catthehacker/ubuntu` job image. Optional `runtime.local.runner_image` and `runtime.local.ci_job_image` overrides require `ci_enabled: true` and an explicit version tag or SHA-256 digest. Unversioned references and `:latest` are rejected. Leave both fields absent to use the defaults. Preparation records actual image IDs for the run.

The backend also freezes the internal `docker:27.5.1-dind` daemon recipe by actual image ID. The runner connects to that run's daemon through an internal `DOCKER_HOST` endpoint; the daemon has no published host port, and the runner receives no host Docker socket. Each daemon owns its job containers, tool cache and storage, so runner-generated names remain within that run. Job network mode `host` refers to the private daemon's network namespace on the run's CI network. The daemon runs privileged on the local Docker host; this setup is intended for trusted code and does not provide hostile-code isolation.

For a custom Harness, include a `.gitea/workflows/*.yml` or `.yaml` workflow with an unfiltered `pull_request` event: no branch, path or event-type filters. Provide at least one unconditional job using `runs-on: ubuntu-latest`, with executable `run` or `uses` steps. For that job and all its steps, omit `if` and `continue-on-error`; omit the job's `strategy`. These conditions let the precheck establish that every PR can receive a required check. The dedicated runner maps `ubuntu-latest` to the frozen job image, which must provide your workflow's tools, including Node for checkout actions and Python for the smoke probe. A missing compatible workflow fails preparation. Changing the original configuration or Harness after prepare does not alter that run; prepare a new run for changed inputs.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
```

Backend preflight checks the owned runner's registration, daemon, images, storage and network identity, then creates a temporary technical probe repository and a real PR. Its workflow executes checkout and Python smoke; readiness requires at least one check and `success` for the PR's current head SHA. Probe feedback is not user feedback. The backend removes only its own temporary probe repository.

OpenAgents receives `ci: agent` only after the verified readiness receipt matches the enabled run. Registration, workflow, API failure or timeout blocks startup and preserves diagnostics. It does not downgrade an enabled run to `skip`. The subsequent experiment uses the configured models; the technical CI probe itself does not.

## 3. Inspect current CI evidence

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py logs "$RUN_ID" --follow --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID" --secrets-file .env.experiment
```

Status reports CI independently from experiment, resource and collection state, including the non-sensitive runner identity and readiness evidence. A running runner container alone does not prove readiness. Use the actual Gitea URL from status to inspect Harness PR checks. An OpenAgents CI gate follows the PR's current head: zero or pending checks wait, failures require repair, and a new commit must receive its own result. A previous head's green result cannot clear a newer head.

Collected forge evidence includes main and PR current SHAs and their commit statuses, plus the CI readiness receipt. Runner registration secrets and private registration files are not copied into collected artifacts. A complete collection records evidence; it does not mean the experiment or every PR succeeded.

## 4. Stop, resume and clean up the same run

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py stop "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py resume "$RUN_ID" --secrets-file .env.experiment
```

Stop first halts the controller and Vigil, then pauses the dedicated runner, handles its owned jobs and stops the private daemon. It preserves Gitea data, runner registration and daemon storage for recovery. Resume reuses the original registration and verifies the original images, storage, network and identity before a new readiness probe. It does not re-register the runner, upgrade frozen code or import historical rounds. If ownership or stopping cannot be verified, the backend retains the uncertain resources and reports the error.

After terminal collection is complete, inspect state and destroy owned execution resources:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py collect "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py status "$RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py destroy "$RUN_ID" --confirm "$RUN_ID" --secrets-file .env.experiment
```

Destroy handles only jobs and resources verified as belonging to this run, removing its private daemon and CI job storage. It retains the Gitea repository/data volume and the private runner registration volume, with names and reasons in the resource receipt. The private runner volume contains registration credentials; keep it with private runtime data. Other experiments' daemons, runners, jobs and existing Gitea services are outside this cleanup. A failed job cleanup cannot be reported as `DESTROYED`.

These commands describe the implementation contract. Actual offline and live coverage is recorded in the [CI validation report](../validation/local-engineering-ci.md); documented steps alone are not evidence of a completed live CI experiment. A manually constructed red/green probe demonstrates engineering status behavior, not model-driven repair or benchmark improvement.
