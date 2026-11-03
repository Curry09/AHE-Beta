# Verification Checklist

Use this checklist during implementation and verification. Commands assume the
repository root and its configured `.venv`. See the repository
[contribution guide](../../../CONTRIBUTING.md) for setup and additional checks.

## Automated Checks

- [ ] Lint passes: `.venv/bin/ruff check .`.
- [ ] Formatting passes: `.venv/bin/ruff format --check .`.
- [ ] Relevant unit tests pass: `.venv/bin/python -m pytest -q`. Meet the project
  coverage threshold, or at least 80% coverage on changed files where applicable.
- [ ] Integration tests cover the Task's behavior and interfaces.
- [ ] Specs validate without errors:
  `./tools/spec-driven-development/spec validate`.
- [ ] Generated views are current:

  ```bash
  ./tools/spec-driven-development/spec render
  ./tools/spec-driven-development/spec graph --package-root backend/ahe_beta
  ./tools/spec-driven-development/spec graph --package-root backend/ahe_beta --check
  ```

  Review and include intended generated changes. Once they are recorded,
  regeneration must leave `docs/specs/OVERVIEW.md` and
  `docs/specs/ARCHITECTURE.md` unchanged; CI checks for drift under `docs/specs/`.

## Code and Spec Quality

- [ ] Code references the relevant Spec at module, API, step, or field level as
  appropriate; see [Code Comment Conventions](code-comment-conventions.md).
- [ ] Only files allocated to this Task were touched; ownership does not overlap
  other Tasks in the group.
- [ ] The PR contains no unrelated changes or hardcoded credentials.
- [ ] Python follows repository conventions: no positional-only `/` parameters;
  private functions beginning with `_` (except dunder methods) require explicit
  arguments rather than defaults.
- [ ] Active Spec prose is English, necessary context is restated in the group,
  and the exact Chinese originals remain preserved under `docs/specs-zh-CN/`.
- [ ] The group overview, Task rows, DAG, and acceptance criteria match the
  implementation.

## Git Hygiene

- [ ] The branch is rebased on the current base (`test`) with linear history.
- [ ] Affected checks pass after rebasing.
- [ ] Commit messages follow Conventional Commits and reference the Spec ID.
- [ ] Each Task is kept to a focused PR.

## Human Verification

- [ ] Provide an AI review summary with findings and material limitations.
- [ ] Provide concrete, step-by-step human verification instructions.
- [ ] Obtain human verification before merging. Reuse authorization already given
  for work inside the current phase; this checklist adds no intermediate gates.

## Failure Handling

Fix a failed check and re-run affected checks. If the Task plan is fundamentally
flawed, document the issue, revert the affected implementation, and edit the
current Task frontmatter and group overview with the corrected design. Previous
definitions remain in git; there is no `amend` command or per-Task history tree.
Return to the applicable design approval phase when the design changes. Never
merge a failing PR.
