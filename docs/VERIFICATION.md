# Verify this checkout

English | [简体中文](VERIFICATION.zh-CN.md)

Run these checks from the repository root to validate the current code and public experiment definitions. Pull request CI also performs frontend and cross-repository checks; see [Contributing](../CONTRIBUTING.md) for the development workflow.

```bash
uv sync --locked --extra experiments --extra dev --extra harbor-evaluation
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -q
.venv/bin/python backend/scripts/check_nexau_dependency.py --installed
.venv/bin/python backend/scripts/check_experiment_repository.py
tools/spec-driven-development/spec validate
```

The repository check covers every public experiment and batch definition. To inspect one configuration without starting cloud resources or requesting a model:

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py check \
  --config examples/experiments/u8-mixed-e2b.json --offline
```

Offline checks validate configuration and material declarations. Downloaded materials are verified during preparation; backend access, model responses and complete experiments need their respective runtime checks.

Follow the [evolution tutorial](tutorials/evolution32.md) for a live run, then inspect that run's status, logs and collected artifacts. Material hashes and environment identities are recorded in the [task manifest](../examples/tasks/evolution32/manifest.json). Independent Harness evaluation has its own [setup and run instructions](../evaluation/README.md).
