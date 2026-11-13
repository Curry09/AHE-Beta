# Unified Harbor evaluation

[简体中文](README.zh-CN.md) · [Guide](docs/harbor.md)

Use one [`evaluation.yaml`](../evaluation.yaml), from the repository root. Credentials belong in the ignored `.env` file. Supported harnesses: v0, u8, u8-direct, u16, u32, Claude Code 2.1.119, pinned Meta-Harness and pinned AHE. Both direct and simulated-user execution are available; arbitrary third-party harnesses require an adapter.

## Install

For AHE-only evaluation, use the self-contained [AHE setup](#ahe-over-anthropic-messages) below; the legacy binary downloads are not needed.

On Linux/WSL with Python 3.12, download `harbor-evaluation-runtime-v1.0.0.zip` from the [framework release](https://github.com/Curry09/AHE-Beta-Legacy/releases/tag/harbor-evaluation-framework-v1.0.0) and extract it into the repository root, creating `runtime/`. Download `harnesses.zip` from the [harness release](https://github.com/Curry09/AHE-Beta-Legacy/releases/tag/harbor-evaluation-results-20261030), extracting it next to this repository, or update `paths.harnesses`.

```bash
python3.12 -m venv .venv-evaluation
source .venv-evaluation/bin/activate
pip install --require-hashes -r evaluation/requirements.lock
pip install --no-deps -e ./evaluation
cp .env.example .env
# Fill credentials and edit evaluation.yaml; start with one harness and one task.
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
```

Preparation acquires tasks through the selected source and creates one archive per custom harness source version. It does not start solving sandboxes or call a paid model. The default `task_source: harbor_index` downloads the pinned official definitions; `published38` selects the published 38 tasks, with an explicit task list or `all` also supported. `task_source: harbor` instead accepts local task-package paths without Index rules; see the guide. Tasks may exceed E2B limits; infrastructure failures remain separate from task failures.

## AHE over Anthropic Messages

`ahe` selects the upstream [agentic-harness-engineering evolved harness](https://github.com/china-qijizhifeng/agentic-harness-engineering/tree/182ea06e578df7b1d503eca537503c1e4c5a8a58/experiments/evolved_harness), fixed at `182ea06e578df7b1d503eca537503c1e4c5a8a58`. Prompts, memory, tools, risk middleware and the 300-iteration limit are preserved. Only transport, model operating parameters and observation are adapted; the upstream evolution loop is not invoked.

For AHE-only runs, skip the legacy runtime and harness downloads. Install the Python dependencies as above using uv-managed CPython 3.12 (3.12.13 is recommended), and install Git and uv. Run from the repository root:

```bash
python -m evaluation.harness.ahe --destination ../harnesses/ahe --build-runtime
cp examples/evaluation/ahe-messages.yaml evaluation.yaml
# Edit endpoints in evaluation.yaml and fill the required credentials in .env.
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
```

The command refuses existing source/runtime destinations. It builds NexAU at `28511d9f0362191a6c378fd441b2be55309a9e32` into `runtime/ahe/`, without changing the controller SDK. Alternatively use `--runtime-wheel PATH` to import an existing native wheel. Package bytes must match the fixed upstream fingerprint; wheel ZIP metadata may vary. Material hashes and the frozen dependency lock are checked again during preparation. The kit also includes a Python archive: an existing base archive is reused when present, otherwise the current uv-managed CPython 3.12 installation is packaged. Use --python-archive PATH to supply an existing archive explicitly. AHE-only preparation needs no legacy release assets. Generated kits stay outside Git.

Copy the template to the root before editing: its paths are relative to the root configuration. It starts with one task and one repetition. Select `tasks: published38` or set `execution.repetitions` explicitly when needed. `actor.api_type: anthropic_chat_completion` is supported only with `harnesses: [ahe]`; `actor.base_url` is the native SDK's Messages service root. The user uses a separate OpenAI-compatible endpoint. Store ACTOR_API_KEY, USER_API_KEY, E2B_API_KEY and any required JUDGE_API_KEY in `.env`. The example explicitly selects `reasoning_effort: max`, `max_output_tokens: 65536`, `thinking: true` and native streaming; the provider must support them. Omitting api_type preserves upstream Responses; explicit openai_responses and openai_chat_completion are also supported.

Keep `execution.time_adaptation: false`: AHE has no remaining-time adapter. Shared task budgets and HTTP/read timeouts still apply. `user.enabled: true` uses the existing reply-follow-up policy; false runs directly. Both current task sources remain supported. Native signed thinking/tool history is preserved, cache usage is counted once, streams without message_stop remain incomplete, and output exhaustion is recorded as ModelOutputLimit without extra adapter retries. Full traces and credentials are private run artifacts.

Local HTTP fixtures test the real pinned agent and shell tools, streaming, feedback, signed-thinking replay and error handling. Live model/provider evaluations require separate campaign records.

Actual-agent tests require the pinned NexAU SDK on the test host; otherwise those tests are skipped. The repository CI installs and verifies it through `uv sync --locked --extra experiments --extra dev --extra harbor-evaluation` before running the suite. Fixture tests need no model credentials.

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
python -m pytest evaluation/tests
```

Offline regression tests and a real E2B run of the standard Terminal-Bench task `fix-code-vulnerability` passed. That run used `task_source: harbor`, the current seed and GLM-5.3-Flash; its original 367 repository tests and 6 task tests passed with reward 1.0. The framework is independent of evolution experiments under `backend/scripts/experiment.py`. Validation records are in `evaluation/verification/`.
