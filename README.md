# auto-designer

English | [简体中文](README.zh-CN.md)

A research framework for evolving coding-agent harnesses through simulated user feedback.
Python 3.12+ · Linux / WSL2 · MIT. Start with the offline demo below; live experiments need separately configured models and infrastructure.

auto-designer simulates users interacting with a harness, turns their usage traces into requirements, and delegates implementation to the separate [OpenAgents](https://github.com/Curry09/OpenAgents) project. After each delivery round is finalized, users try the updated harness. The final round evaluates the harness without another delivery. User impressions, technical acceptance results, and held-out benchmarks are recorded separately.

This repository is the **experiment controller**; OpenAgents is the **delivery CLI**; `backend/harness_template/` contains the **initial source code of the product being evolved**. Harnesses produced by experiments should be released as separate, versioned artifacts.

## Installation and offline demo

You need Git, Python 3.12+, and uv. Run these commands from the repository root:

```bash
uv sync --locked --extra dev
uv run --locked python backend/scripts/offline_demo.py
uv run --locked --extra dev pytest -q
```

The demo uses a synthetic persona and a scripted harness. It prints the interaction and the reason it ended, without calling a model, creating issues, or starting containers. It checks the user-simulation entry point; it does not validate a complete live evolution run.

Run auto-designer from source; a PyPI installation entry point is not yet available. `uv.lock` pins the NexAU commit and compatible dependencies. Validate both repositories together when changing these versions.

## Integration and documentation

The detailed guides below are currently in Chinese:

- [Joint quickstart](docs/QUICKSTART.md): install both repositories, check their configuration contract offline, start live experiments, and stop or resume runs.
- [Configuration](docs/CONFIGURATION.md): model roles, credentials, delivery flows, and default quality gates.
- [Architecture](docs/ARCHITECTURE.md): boundaries between requirements, delivery, and artifacts.
- [Public snapshots](docs/EXPORTING.md): publish coarse progress while keeping raw conversations local.
- [Joint release checklist](docs/RELEASING.md): version freezing, outstanding live acceptance checks, and publication steps.

Project policies: [Contributing](CONTRIBUTING.md), [Security](SECURITY.md), [Third-party sources](THIRD_PARTY.md) (Chinese), and [Changelog](CHANGELOG.md).

Frontend development requires Node.js 22. Run `npm ci`, `npm test`, and `npm run build` in `frontend/`. The live API is intended for a trusted local environment; static Pages deployment is a separate publication path.

## Supported scope and research materials

The initial release preparation covers the Python core, offline simulation, the configuration contract between the repositories, and frontend tests and builds. Live Docker/Gitea delivery, paid models, E2B scaling, and benchmarks require separate acceptance checks; unit tests do not replace them.

`docs/specs/` stores design contracts and task mappings. `evaluation/` and dated scripts preserve research workflows. Historical experiment configurations may contain machine-specific paths and task sources: use them with their corresponding versions, rather than as general-purpose examples. Redistribution review of personas and third-party tasks is still in progress; see [THIRD_PARTY.md](THIRD_PARTY.md).

## License

Project code is licensed under the [MIT License](LICENSE). Third-party material retains its own terms; see [THIRD_PARTY.md](THIRD_PARTY.md).
