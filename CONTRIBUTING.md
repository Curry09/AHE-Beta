# Contributing

English | [简体中文](CONTRIBUTING.zh-CN.md)

We welcome reproducible bug reports, documentation fixes, and focused implementation changes. Read the [README](README.md) and [spec guide](docs/specs/README.md) (Chinese) first. Update the relevant design contract before adding a feature or changing behavior across modules. Do not manually edit the generated `docs/specs/OVERVIEW.md` or `docs/specs/ARCHITECTURE.md` files.

## Local checks

From the repository root:

```bash
uv sync --locked --extra experiments --extra dev
uv run --locked --extra experiments --extra dev pytest -q
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
PYTHONPATH=tools/spec-driven-development/vendor uv run --locked python -m openagents.spec.cli validate
PYTHONPATH=tools/spec-driven-development/vendor uv run --locked python -m openagents.spec.cli render
PYTHONPATH=tools/spec-driven-development/vendor uv run --locked python -m openagents.spec.cli graph --package-root backend/auto_designer
```

The frontend requires Node.js 22. Run `npm ci`, `npm test`, and `npm run build` in `frontend/`. For OpenAgents desktop checks, see its [contribution guide](https://github.com/Curry09/OpenAgents/blob/main/CONTRIBUTING.md).

Commit lockfile updates together with dependency changes; routine CI uses `--locked`. When changing the delivery contract, run the cross-repository configuration check in auto-designer and record both repository commits. Ordinary PRs do not need model API keys. For live model canary runs, record costs, versions, and sanitized evidence separately.

## Commits and review

Use Conventional Commits, for example `fix(runtime): preserve resume identity`. Describe the problem, resulting behavior, validation commands, and limitations in the PR. Keep experiment traces, credentials, and machine-specific configuration out of source changes. Reserve new spec numbers through the repository CLI and regenerate the views after editing specs. Do not rewrite existing experiment results as part of cleanup PRs.

By contributing, you confirm that you have the right to submit your contribution and agree to distribute it under the project's MIT license. Preserve the licenses and attribution of third-party material. Check [THIRD_PARTY.md](THIRD_PARTY.md) (Chinese) before contributing personas or benchmark content.

## Bilingual documentation

The root README, CONTRIBUTING, and SECURITY documents each have an English version (`.md`) and a Simplified Chinese version (`.zh-CN.md`). When editing either version, update the content, commands, and links in the other version as well, and retain the language switch at the top. Detailed design documents are currently mostly in Chinese.
