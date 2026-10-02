# auto-designer

English | [简体中文](README.zh-CN.md)

A research framework for evolving coding-agent harnesses through simulated user feedback.
Python 3.12+ · Linux / WSL2 · MIT. Choose local Docker or E2B in the Quickstart.

auto-designer simulates users interacting with a harness, turns their usage traces into requirements, and delegates implementation to the separate [OpenAgents](https://github.com/Curry09/OpenAgents) project. After each delivery round is finalized, users try the updated harness. The final round evaluates the harness without another delivery. User impressions, technical acceptance results, and held-out benchmarks are recorded separately.

This repository is the **experiment controller**; OpenAgents is the **delivery CLI**; `backend/harness_template/` contains the **initial source code of the product being evolved**. Harnesses produced by experiments should be released as separate, versioned artifacts.

The **Synthesizer** combines related proposals into structural improvements; it does not implement code. Triage, Synthesizer, and PM share the `auto_designer.demand` package and `DEMAND_LLM_*` model configuration. Active file-access, repository-integrity, and Harness commit-boundary checks live in `auto_designer.guards`.

Current code and development configuration use `synthesizer`, `N_SYNTHESIZERS`, and `SYNTHESIZER_GROUPING` directly. See [configuration](docs/CONFIGURATION.md) and [grouped synthesis](docs/synthesizer-grouping.md) (Chinese).

## Run an experiment

Choose local Docker + automatically provisioned localhost Gitea, or E2B + your own Gitea.com account. Both use `backend/scripts/experiment.py` and the same v2 experiment format. The current task-package schema supports one task and one user session per round; multi-task N4/N8 plans and adding a round to imported historical results are not supported by this entry. The checked-in N=1 examples run five rounds on a fixed pvlib task: R1–R4 include delivery, and R5 only tries the final Harness.

```bash
uv sync --locked --extra experiments
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
# Fill credentials; choose synthesizer-n1-local.json for local Docker.
uv run --locked --extra experiments python backend/scripts/experiment.py check --config examples/experiments/synthesizer-n1-e2b.json --offline
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config examples/experiments/synthesizer-n1-e2b.json --secrets-file .env.experiment
# Copy the generated run ID:
uv run --locked --extra experiments python backend/scripts/experiment.py run <run_id>
```

Start with [Quickstart](docs/QUICKSTART.md), then follow the [complete N=1 tutorial](docs/tutorials/n1-experiment.md). They explain the required materials, model protocols, provider credentials, progress, stop/resume, collection and cleanup. Preparation fetches pinned OpenAgents automatically; no sibling checkout is required. The [validation report](docs/validation/spec-0069-new-user.md) records actual checks separately from the documented workflow.

For an offline scripted demo without models or infrastructure:

```bash
uv run --locked python backend/scripts/offline_demo.py
```

Run from source; a PyPI entry point is not yet available. `uv.lock` pins NexAU and compatible dependencies.

## Documentation and development

- [Configuration](docs/CONFIGURATION.md): v2 JSON, task packages, personas and credentials.
- [Architecture](docs/ARCHITECTURE.md): requirements, delivery and artifact boundaries (Chinese).
- [Public snapshots](docs/EXPORTING.md): publish coarse progress while keeping raw conversations local (Chinese).
- [Developer tools](tools/dev/README.md): probes, evidence replay and delivery validation.
- [Research archive](research/README.md): historical configurations, source versions and migration inventory.
- [Joint release checklist](docs/RELEASING.md): version freezing and publication (Chinese).
- [Contributing](CONTRIBUTING.md), [Security](SECURITY.md), [Third-party sources](THIRD_PARTY.md) and [Changelog](CHANGELOG.md).

```bash
uv sync --locked --extra experiments --extra dev
uv run --locked --extra experiments --extra dev pytest -q
```

Frontend development requires Node.js 22: run `npm ci`, `npm test` and `npm run build` in `frontend/`. The live API is intended for a trusted local environment; static Pages publication is separate. The default development API does not automatically select a v2 run; use experiment `status`/`logs` for current progress. See the [frontend guide](frontend/README.md).

Repository layout:

```text
examples/experiments/                    # Runnable v2 local/E2B definitions
examples/tasks/, examples/personas/      # Task packages and persona inputs
backend/auto_designer/experiment/        # Lifecycle and internal controllers
backend/scripts/                        # Public entry, demo, export, CI/build checks
tools/dev/                              # Maintained diagnostics and replay tools
evaluation/                             # Independent held-out grading and adapters
research/archives/                      # Frozen historical research records
.experiments/                           # Ignored run outputs
```

`docs/specs/` stores design contracts and task mappings. Historical research is indexed in `research/inventory.json`; reproduce it using its recorded source revision in a separate checkout, rather than running archived launchers from the current tree. User impressions and closed-loop completion do not imply official benchmark success; held-out grading remains a separate workflow.

## License

Project code is licensed under the [MIT License](LICENSE). Third-party material retains its own terms; see [THIRD_PARTY.md](THIRD_PARTY.md).

The unified entry supports runtime policies, direct interaction, explicit round plans and `dashboard RUN_ID`. See [configuration](docs/CONFIGURATION.md) and [migration validation](docs/validation/spec0072-capability-migration.md). Multi-task/N4/N8 and historical round import remain pending.
