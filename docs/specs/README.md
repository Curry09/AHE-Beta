# Specs

This directory contains the maintained English design specifications for AHE-Beta. The [original Chinese specifications](../specs-zh-CN/README.md) are preserved unchanged in a separate archive. The spec CLI reads and generates views for this directory.

Specifications describing the retired frontend record historical implementations. The current read-only JSON observation API is described in [Spec-0072](0072-experiment-capability-migration.md).

The workflow is managed by the repository's `spec-driven-development` skill, adapted from OpenAgents. Each spec group is one `NNNN-slug.md` file with:

- **YAML frontmatter:** group metadata (`number`, `title`, `issue`, `slug`, `summary`) and a `tasks` list. Each Task declares its identity, status, priority, dependencies, owned files, scope, and acceptance criteria.
- **A Markdown design overview:** nine RFC sections that explain the feature without requiring other Specs for essential context. Include the Task DAG and file allocation in the Reference-level explanation.

Use these sections in order: Summary, Motivation, Guide-level explanation, Reference-level explanation, Drawbacks, Rationale and alternatives, Prior art, Unresolved questions, and Future possibilities. Validation requires non-empty **Summary**, **Motivation**, **Reference-level explanation**, and **Rationale and alternatives** sections.

Write concise, precise English. The frontmatter `summary` should explain the feature in plain language; it is required by `spec new` and must be non-empty for validation.

## Create and update a Spec

Run the CLI from the repository root to create groups, add Tasks, or remove abandoned Tasks:

```bash
./tools/spec-driven-development/spec new <slug> --issue <N> --title "<Title>" --summary "<What changes and why>"
# Reserve a number before renumbering an existing PR.
./tools/spec-driven-development/spec reserve-number --issue <N> --slug <slug>
./tools/spec-driven-development/spec add-task <NNNN> --id T1 --title ... --priority P1 --files ... --scope ... --acceptance ...
./tools/spec-driven-development/spec validate
./tools/spec-driven-development/spec render
./tools/spec-driven-development/spec graph --package-root backend/ahe_beta
# Remove a Task from the current snapshot; Git retains its history.
./tools/spec-driven-development/spec abandon <NNNN> <Tx> --reason "..."
```

Edit existing Task fields and the design overview directly in the group Markdown file, then validate and regenerate the views. The `amend` and `set-overview` commands and per-Task history directories are retired; revisions are recorded in Git.

## Generated views

- `OVERVIEW.md` contains feature summaries, the Task board, relationships, file conflicts, and feature details. Generate it with `spec render`.
- `ARCHITECTURE.md` maps the code's components and dependencies using the import graph and module docstrings under `backend/ahe_beta/`. Generate it with `spec graph`.

Edit the source specifications or docstrings to update these files. **Do not edit the generated views manually.** Commit regenerated views with their source changes.

## Numbering rules

- In a shared Git repository, `spec new` selects the next number from local groups, the remote main branch, and existing reservations. It atomically reserves `spec-reservations/NNNN` on the remote before creating the file. A remote failure stops creation. Directories without a remote use the local maximum plus one.
- Keep each group to at most six Tasks; split larger designs into focused groups.
- Tasks within a group must own disjoint `files` lists so they can be implemented concurrently without competing writes.
- `backend/scripts/check-spec-number-conflicts.py` checks local groups and open PRs for conflicting `NNNN-slug.md` numbers.
