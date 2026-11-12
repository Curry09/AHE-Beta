# AHE-Beta

**Evolve coding-agent harnesses through simulated use and structured feedback.**

[English](README.md) · [简体中文](README.zh-CN.md) · [Quickstart](docs/QUICKSTART.md) · [Evaluation](evaluation/docs/harbor.md) · [Contributing](CONTRIBUTING.md)

Python 3.12+ · Linux / WSL2 · [MIT](LICENSE)

AHE-Beta evolves coding-agent harnesses by simulating how users try a product, give feedback, and developers improve it. Simulated users work on tasks with the Harness and report problems. Triage and Architect turn that feedback into proposals, and [OpenAgents](https://github.com/Curry09/OpenAgents) implements the code changes. The updated Harness enters the next round of use, continuing the feedback and improvement cycle.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/harness-evolution-en-dark.svg">
    <img src="assets/harness-evolution-en-light.svg" alt="An animated sequence highlights round 1, round 2 and the final round in turn. Moving signals highlight each node on arrival. Feedback and OpenAgents delivery update the Harness between rounds; the final trial is followed by independent held-out Harbor evaluation." width="100%">
  </picture>
</p>

This repository orchestrates experiments, while OpenAgents implements code changes. Each experiment starts with the seed Harness in `backend/harness_template/`, evolves its source code, and saves the Harness version and execution records for each round.

## Offline demo

The offline demo uses scripted simulated users and a scripted Harness to demonstrate an interaction and its feedback. It requires no model API or experiment infrastructure. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) before running:

```bash
git clone https://github.com/Curry09/AHE-Beta.git
cd AHE-Beta
uv run --locked python backend/scripts/offline_demo.py
```

The script finishes with:

```text
Offline demo complete: scripted sessions only; no model, forge or delivery invoked.
```

To run a complete evolution experiment with models, follow the steps below.

## Run a Harness evolution experiment

Experiments are managed through `backend/scripts/experiment.py`, with a choice of local or cloud execution:

| Backend | Runtime | Repository hosting | Requirements |
| --- | --- | --- | --- |
| `local` | Local Docker | Local Gitea started automatically | Docker Engine with Compose |
| `e2b` | E2B sandbox | Your Gitea.com account | `E2B_API_KEY` and a Gitea.com token |

Both backends require model endpoints. Simulated users, the Harness and requirements agents use OpenAI-compatible APIs; OpenAgents delivery uses an Anthropic-compatible API. Select models in the experiment JSON and enter their endpoint URLs and keys in `.env.experiment`. See the [Quickstart](docs/QUICKSTART.md) for the configuration fields.

Start with the U1 example: one simulated user tries the same task each round for five rounds. The first four include feedback processing and code delivery; the final round tries the updated Harness. Run these commands from the repository root:

```bash
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment

CONFIG=examples/experiments/u1-local.json
# For E2B, use:
# CONFIG=examples/experiments/u1-e2b.json

uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --offline
# Fill .env.experiment and confirm the configured model names, then start:
uv run --locked --extra experiments python backend/scripts/experiment.py run --config "$CONFIG" --secrets-file .env.experiment
```

`check --offline` checks the configuration and local material declarations. `run --config` then prepares materials, provisions resources and starts the experiment. Use the printed run ID to check progress (`status`), read logs (`logs`) or collect artifacts (`collect`). The [U1 walkthrough](docs/tutorials/u1-experiment.md) covers the complete workflow, expected outputs, and stop/resume operations.

### Multi-user experiments

The U4 examples provide a smaller multi-user experiment with four user sessions across two tasks over two rounds. Choose [`u4-local.json`](examples/experiments/u4-local.json) or [`u4-e2b.json`](examples/experiments/u4-e2b.json) and follow the [multi-user tutorial](docs/tutorials/multi-user-experiment.md).

For larger six-round experiments, use these E2B configurations:

| Configuration | Sessions per round | Simulated-user interaction / direct |
| --- | ---: | ---: |
| [`u8-mixed-e2b.json`](examples/experiments/u8-mixed-e2b.json) | 8 | 6 / 2 |
| [`u8-direct-e2b.json`](examples/experiments/u8-direct-e2b.json) | 8 | 0 / 8 |
| [`u16-mixed-e2b.json`](examples/experiments/u16-mixed-e2b.json) | 16 | 12 / 4 |
| [`u32-mixed-e2b.json`](examples/experiments/u32-mixed-e2b.json) | 32 | 25 / 7 |

Each configuration fixes its task packages, persona pairings and round schedule. Simulated-user sessions allow follow-up interaction; direct sessions let the Harness work autonomously after receiving the task. R1–R5 include trials, feedback processing and delivery; R6 tries the final Harness. Per-round official grading is disabled by default. See the [six-round tutorial](docs/tutorials/evolution32.md) and [task catalog](examples/tasks/evolution32/README.md) for materials and startup instructions, or the [batch tutorial](docs/tutorials/batch-experiment.md) to schedule several experiments.

## Evaluate an existing Harness

After evolution, use the independent Harbor evaluation workflow to assess the Harness on benchmark tasks. Configure it in [`evaluation.yaml`](evaluation.yaml) and launch it with `python -m evaluation`. It supports Harbor Index tasks and standard Harbor task packages on E2B.

Choose a released Harness (`v0`, `u8`, `u8-direct`, `u16` or `u32`), or an integrated agent (Claude Code or Meta-Harness). Set `user.enabled: false` for direct solving. With `true`, a simulated user participates in follow-up interaction and can ask questions or assess the response.

Download the pinned runtime and Harness archives described in the [evaluation guide](evaluation/docs/harbor.md), then create a separate evaluation environment:

```bash
uv venv --python 3.12.13 --managed-python --seed .venv-evaluation
source .venv-evaluation/bin/activate
pip install --require-hashes -r evaluation/requirements.lock
pip install --no-deps -e ./evaluation
cp .env.example .env
```

Configure model names and endpoint URLs in `evaluation.yaml`, and enter API keys and E2B credentials in `.env`. The default configuration selects 38 tasks and two Harnesses. Start with one task and one Harness to verify your setup before expanding the run. For example, change these fields and keep the remaining settings:

```yaml
tasks: [swebenchpro-fix-file-suffix-chooser]
harnesses: [v0]
user:
  enabled: false
```

Once configured, validate, prepare and run:

```bash
python -m evaluation validate
python -m evaluation prepare
python -m evaluation run
```

`validate` checks the configuration, `prepare` prepares task and Harness materials, and `run` starts solving and grading. The run directory retains task scores, execution traces and usage records, along with interaction records when simulated users are enabled. Some tasks require an official judge model and its credentials. Task failures, infrastructure failures and judge failures are recorded separately.

This workflow evaluates the evolved Harness; its scores do not feed back into evolution. See the [evaluation guide](evaluation/docs/harbor.md) for resuming runs, viewing reports and regrading submissions.

## Documentation

| Topic | Guide |
| --- | --- |
| First local or E2B experiment | [Quickstart](docs/QUICKSTART.md) |
| Experiment configuration, task packages and credentials | [Configuration](docs/CONFIGURATION.md) |
| Six-round U8/U16/U32 experiments | [Six-round tutorial](docs/tutorials/evolution32.md) |
| Harbor evaluation setup and execution | [Evaluation guide](evaluation/docs/harbor.md) |
| Development checks and verification commands | [Verification](docs/VERIFICATION.md) |
| System architecture and design documents | [Architecture](docs/ARCHITECTURE.md) · [Specs](docs/specs/README.md) |

Further workflows cover [importing your own tasks](docs/tutorials/seed-task-import.md), [appending experiment rounds](docs/tutorials/experiment-continuation.md), [grading saved session artifacts](docs/tutorials/post-run-grading.md) and [enabling per-round assessment](docs/tutorials/evolution-feedback.md).

To participate in development, see [Contributing](CONTRIBUTING.md). Report security issues as described in [Security](SECURITY.md). Project code is [MIT licensed](LICENSE); third-party licenses and sources are documented in [THIRD_PARTY.md](THIRD_PARTY.md).
