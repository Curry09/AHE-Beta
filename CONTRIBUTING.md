# Contributing

English | [简体中文](CONTRIBUTING.zh-CN.md)

Contributions are welcome, including bug reports, documentation improvements and code changes. Start with the [README](README.md) for the project workflow and the [architecture guide](docs/ARCHITECTURE.md) for the main components. Design specifications are maintained in English under [docs/specs](docs/specs/README.md); the original Chinese specifications are preserved under [docs/specs-zh-CN](docs/specs-zh-CN/README.md).

## Report a bug

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) and include the commit or release, your environment, reproduction steps, and the expected and actual behavior. Attach only the logs needed to reproduce the problem, with credentials and private content removed. Report security vulnerabilities through the channel described in [SECURITY.md](SECURITY.md).

## Prepare a change

Keep each pull request focused on one problem or feature. For a new feature or a behavior change across modules, create or update the relevant design document before implementation. The [spec guide](docs/specs/README.md) explains how to create a spec and reserve its number.

Write new code comments, docstrings and specifications in English. Keep comments focused on intent, constraints and behavior that are not clear from the code itself.

When changing dependencies, include the updated lockfile in the same pull request. When changing the delivery interface or evidence transport, also validate against the corresponding OpenAgents revision and record both repository commits. See the [OpenAgents contribution guide](https://github.com/Curry09/OpenAgents/blob/main/CONTRIBUTING.md) for changes in that repository.

## Run local checks

Use Python 3.12+ and run the following from the repository root. The dependency selection includes the experiment and Harbor evaluation tests used by CI:

```bash
uv sync --locked --extra experiments --extra dev --extra harbor-evaluation
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -q backend/tests
PYTHONPATH=. .venv/bin/python -m pytest -q -c /dev/null -p no:cacheprovider evaluation/tests
```

CI runs the backend suites in parallel. Run the evaluation suite separately so it uses the user engine bundled with the evaluator.

After editing specs, validate them and regenerate the indexes:

```bash
tools/spec-driven-development/spec validate
tools/spec-driven-development/spec render
tools/spec-driven-development/spec graph --package-root backend/ahe_beta
```

Commit the generated changes to `docs/specs/OVERVIEW.md` and `docs/specs/ARCHITECTURE.md` with the source specs. Generate these files through the CLI rather than editing them manually.

Routine checks do not require model API keys. If a change needs validation with real models, record the model and framework versions, commands, costs and results, and remove private content from any evidence you share. More checks are listed in [Verification](docs/VERIFICATION.md).

## Submit a pull request

Use [Conventional Commits](https://www.conventionalcommits.org/), for example `fix(runtime): preserve resume identity`. Describe the problem, how the change addresses it, and the checks you ran. Include relevant limitations or checks that remain incomplete.

Keep credentials, local configuration and raw experiment traces out of commits. Changes to documentation or repository organization should preserve the meaning of existing experiment results.

The README, CONTRIBUTING and SECURITY documents each have an English version (`.md`) and a Simplified Chinese version (`.zh-CN.md`). Update both versions together, including commands and links, and retain the language switch at the top.

## Licensing

By submitting a contribution, you confirm that you have the right to share it and agree to license your original contribution under the project's [MIT License](LICENSE). Third-party material retains its own license and attribution. Check [THIRD_PARTY.md](THIRD_PARTY.md) before contributing third-party code, personas or benchmark materials.
