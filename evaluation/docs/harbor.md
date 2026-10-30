# Unified Harbor Index evaluation

[简体中文](harbor.zh-CN.md)

Use one [`evaluation.yaml`](../../evaluation.yaml), from the repository root. Credentials belong in the ignored `.env` file. Supported harnesses: v0, u8, u8-direct, u16, u32, Claude Code 2.1.119 and pinned Meta-Harness. Both direct and simulated-user execution are available; arbitrary third-party harnesses require an adapter.

## Install

On Linux/WSL with Python 3.12, download `harbor-evaluation-runtime-v1.0.0.zip` from the [framework release](https://github.com/Curry09/auto-designer/releases/tag/harbor-evaluation-framework-v1.0.0) and extract it into the repository root, creating `runtime/`. Download `harnesses.zip` from the [harness release](https://github.com/Curry09/auto-designer/releases/tag/harbor-evaluation-results-20261030), extracting it next to this repository, or update `paths.harnesses`.

```bash
uv venv --python 3.12.13 --managed-python --seed .venv-evaluation
source .venv-evaluation/bin/activate
pip install --require-hashes -r evaluation/requirements.lock
pip install --no-deps -e ./evaluation
cp .env.example .env
# Fill credentials and edit evaluation.yaml; start with one harness and one task.
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
```

Preparation downloads and verifies the pinned official task definitions, and creates one archive per custom harness source version. It does not start solving sandboxes or call a paid model. Default `published38` selects the published 38 tasks; an explicit task list or `all` is also supported. `all` may include tasks that exceed E2B limits; infrastructure failures remain separate from task failures.

## Execution and recovery

The official task metadata defines the shared solver/user wall-clock limit. Each solver API request uses that task limit, and the remaining overall budget still bounds execution. No provider-wait correction is applied. Actor processes are stopped and submissions frozen before collection and verification. Task-owned tests, resources and grader models remain unchanged. `time_adaptation` controls the custom harness budget protocol; native CC/Meta retain their native behavior.

`stream: native` preserves harness behavior. Custom harnesses also accept explicit streaming/non-streaming; pinned Meta consumes complete responses and CC owns its CLI streaming. Model settings are explicit: providers must support the configured effort and output allowance. Claude Code requires `actor.anthropic_base_url`; judge credentials are separate.

The simulated user sees completed replies and public git diffs, can give feedback or accept, and cannot execute commands or edit code. The first request matches the official public instruction. Its model/endpoint/key reference can be configured separately. After freezing, a uniform reviewer scores experience from the original persona and saved public dialogue, without task grades, hidden tests or internal actor reasoning. Missing evidence stays missing.

```bash
python -m evaluation resume runs/<run-id>
python -m evaluation report runs/<run-id>
python -m evaluation review runs/<run-id>
python -m evaluation regrade runs/<run-id> --trial <trial-id>
```

Resume keeps the frozen manifest and existing worker identity; it requires the original paths, framework and materials. Review retries only missing/failed experience ratings. Regrade reuses immutable submissions and requires a separate verifier environment. Valid scores do not cause actor resampling. Use `run --new-run` only to explicitly start a new experimental run.

## Records and limits

Runs save manifests, state, official results, submissions, interaction records, experience requests/responses, elapsed time and token accounting. A valid official positive score remains a pass even when execution reached its deadline; the timeout flag is retained independently. Infrastructure and grader failures are distinct from valid failures.

Custom Python harnesses, Meta and the user process capture interceptable raw API requests/responses, including returned reasoning and full tool data. Interrupted calls retain received bytes and interruption events. CC stores its native CLI trajectory; its Node HTTP layer is not captured. Token accounting exposes missing usage and totals actor plus live user tokens, excluding official judges and post-session ratings. Runtime records can contain private task content; publication needs a separate sanitized export.

The task source is pinned to Harbor Index `35f01ec42b14c2b5da476099f5b0d209240bca5b`. Meta is pinned to `57fefdb2ff84af3fd81b69d67814acbe69bd0743` and uses a compatibility adapter with Harbor 0.24 / LiteLLM 1.104.2. Original custom source files remain unchanged; runtime configuration is injected into generated copies.

```bash
pip install -e './evaluation[test]'
PYTHONPATH=. python -m pytest -q -c /dev/null -p no:cacheprovider evaluation/tests
```

Validation is offline; this consolidation has not launched a new paid end-to-end evaluation. The framework is independent of evolution experiments under `backend/scripts/experiment.py`. Validation records are in `evaluation/verification/`.
