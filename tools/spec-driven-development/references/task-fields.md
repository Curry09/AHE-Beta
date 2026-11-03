# Spec Fields Reference

A spec group is one English Markdown file, `docs/specs/NNNN-slug.md`:

- YAML frontmatter holds group metadata and the `tasks` work breakdown.
- The body holds the self-contained, group-level rust-RFC nine-section overview.

Use `./tools/spec-driven-development/spec new` and `add-task` to create records.
Edit existing frontmatter fields and body sections directly; preserve the CLI's
key order. Then run `validate`, `render`, and
`graph --package-root backend/ahe_beta` through the same launcher. There are no
per-Task YAML files or `amend` command. Previous definitions live in git history.

## Group Frontmatter

| Field | Type | Meaning |
|---|---|---|
| `number` | string or integer | Four-digit group number; the CLI writes a quoted string. |
| `title` | string | English group title. |
| `issue` | integer | Associated issue number. |
| `slug` | string | English kebab-case filename suffix. |
| `summary` | string | Required non-empty, one-line explanation of what changes and why. |
| `tasks` | list[Task] | Current Task rows, including completed Tasks that map to live code. |

The schema requires `number`, `title`, `issue`, `slug`, and `tasks`. Semantic
validation also requires a non-empty `summary`.

## Group Overview

Write the feature's whole design before breaking it into Tasks. A reader must
understand the feature without opening another Spec. Restate required background
and decisions; other Spec IDs are context, not substitutes for explanation.
`new` scaffolds these headings in this order:

| Section (`## heading`) | Content |
|---|---|
| `Summary` | What the feature does. **Required.** |
| `Motivation` | Current behavior, the problem, and why change is needed. Restate background here. **Required.** |
| `Guide-level explanation` | Explain usage as if the feature already exists, with examples. |
| `Reference-level explanation` | Technical design, interfaces, Task DAG, file-allocation table, and relevant end-to-end script paths such as `backend/scripts/*.sh`. **Required.** |
| `Drawbacks` | Costs, limitations, and reasons against the design. |
| `Rationale and alternatives` | Why this design was chosen and at least one alternative considered. **Required.** |
| `Prior art` | Relevant projects, languages, or papers; state when there is none. |
| `Unresolved questions` | Questions intentionally left open after discussion. |
| `Future possibilities` | Natural follow-up work. |

Validation errors on empty required sections and warns about suspected bare
cross-Spec references, such as `Spec-0012` or `Spec-0012/T2`. A warning calls for
checking that the needed explanation is present in this Spec.

## Task Identity and Status

A Task is a work-breakdown and file-ownership row. Its design rationale belongs
in the group overview.

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Group-local ID matching `T[0-9A-Za-z]+`, usually `T1`; qualified references use `NNNN/T1`. |
| `title` | string | Short English Task title. |
| `status` | enum | `pending`, `in-progress`, or `done` in the current snapshot. |
| `priority` | enum | `P0`, `P1`, `P2`, or `P3`. |
| `tags` | list[str] | Optional labels. |

`done` Tasks remain in the snapshot while they map to live code. Although the
status enum recognizes `abandoned`, semantic validation rejects it in a current
group. Use `abandon` to remove that Task; git retains earlier definitions.

## Task Relations and File Ownership

| Field | Type | Meaning |
|---|---|---|
| `depends-on` | list[str] | Blocking dependencies. Use local IDs or qualified `NNNN/Tn` IDs; the global DAG must be acyclic. |
| `relates-to` | list[{ref,type}] | Non-blocking links; `type` is `extends`, `supersedes`, or `note`. |
| `parallel` | bool | Hint that a Task can run alongside siblings; dependencies still govern execution. |
| `files` | list[str] | Exact repository-relative paths owned by this Task. Required and disjoint within the group. |

The `files` list is the single-writer ownership declaration and the structured
source for issue #71's runtime ownership checks. Same-group overlap is a
validation error; cross-group overlap is a warning requiring coordination.
Combine Tasks that need the same file, or allocate that file to a separate Task.

## Task Scope and Acceptance

| Field | Type | Meaning |
|---|---|---|
| `scope` | string | One-line explanation of what the Task changes. |
| `acceptance` | string | Required, verifiable acceptance criterion. |

The Task schema requires the keys `id`, `title`, `status`, `priority`, `files`, and
`acceptance`. Supply concrete paths and meaningful acceptance criteria; schema
presence checks alone do not establish a complete plan. Optional lists and prose
default to empty, and `parallel` defaults to `false`.

Keep groups to at most six Tasks as a design guideline. The current CLI does not
maintain per-Task history fields (`version`, `updated`, `change-reason`, or lineage
fields); do not use those fields to record revisions. Edit the current Task and
use git plus dated design documents for history.
