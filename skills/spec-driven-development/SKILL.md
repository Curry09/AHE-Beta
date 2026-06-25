---
name: spec-driven-development
description: >
  Spec-driven development for OpenAgents: requirements clarification → Spec design as a
  living snapshot (a docs/specs/ group of Task YAML files, each Task carrying an explicit
  file list) → implementation with verification. Use this skill whenever the user wants to
  plan, design, or architect a non-trivial feature — even without saying "spec". Triggers on:
  "spec", "design doc", "technical design", "plan a feature", "break this down",
  "architect this", or any task involving multiple components, trade-offs, or cross-module
  changes that benefits from design-before-code. Supersedes rfc-driven-development.
  Supports multi-agent parallelism via Task DAG + file allocation.
---

> **auto-designer 适配说明（vendored from OpenAgents）**
> - `spec` CLI 未作为 console_script 安装；在本仓用启动器调用：`./skills/spec-driven-development/spec <子命令>`。
> - CLI 源码 vendored 在 `skills/spec-driven-development/vendor/openagents/spec/`，依赖装在仓库 `.venv`（ruamel.yaml + jsonschema）。
> - specs 根用 CLI 原生默认 `docs/specs/`（`--specs-root` 仅部分子命令生效，勿依赖）。
> - 本仓暂无 CI drift-check；`spec render` 后请手动确认 `OVERVIEW.md` 与各组 `summary.md` 已更新再提交。
> - 下文提到的 `openagents/spec` 包路径、CLAUDE.md「设计理念 5–6」「多 worktree」等为 OpenAgents 语境，本仓按需对照，不强求一致。

# Spec-Driven Development

Structured workflow for OpenAgents: **Requirements -> Spec Design (Task DAG + File Allocation) -> Implementation & Verification**.

This skill **supersedes `rfc-driven-development`** (Spec-0014 / RFC-0014). The unit of design moved from a single RFC Markdown file to a **living snapshot**: a `docs/specs/<NNNN-slug>/` group whose basic unit is a **Task** (stable id, self-contained, one-to-one with live code). You never hand-edit an RFC `.md` — you drive the `spec` CLI, which writes canonical YAML and re-renders the human view.

Each phase requires human approval before proceeding. Within each phase, work autonomously.

## Language Convention

This skill's instructions are in English for model comprehension. Spec prose fields
(summary/design/…) are written in Chinese (read by the team). Code comments may be English
or Chinese — clarity first (see `references/code-comment-conventions.md`).

**Prose style — 精简、精确、学术化.** Spec prose fields (especially `summary`, which is
surfaced verbatim in the human-facing `summary.md`) MUST use concise, precise, academic
language. Define terms with their canonical names; describe mechanisms and contracts
directly. Do NOT pad with metaphors, analogies, hand-holding, or colloquial phrasing —
readability comes from precision and structure, not from dumbing concepts down. One idea
per clause; no filler. This applies to every prose field, not just `summary`.

## Core Principles

1. **Spec is a living snapshot, the single source of truth** — `docs/specs/` is always a snapshot of the repo. Every Task in the snapshot maps to currently-live code, so the snapshot never contains legacy. Done Tasks stay in the snapshot (`status: done`); only a refactored Task's *old version* or an *abandoned* Task leaves the snapshot into `history/`. The Task DAG lives in the spec so any agent session can read it.
2. **Source data vs generated view are separated** — `docs/specs/<group>/` holds only structured YAML source (`metadata.yaml`, `tasks/T*.yaml`, `history/T*.yaml`). `spec render` produces two derivative human views: the global board `docs/specs/OVERVIEW.md` (cross-group dashboard) and a per-group plan `docs/specs/<group>/summary.md` (that group's Tasks rendered as a readable scheme — aggregates each Task's prose + the DAG). OVERVIEW.md contains, in order: 名词解释 (glossary) · 全局看板 · 跨 feature 关系图 · 文件冲突报告 · **设计文件结构** (the designed file tree, union of all Tasks' `files`, each annotated with its owner Task) · 各 feature 详情. The file tree is fully derived from Task `files` — to change it, change a Task's `files` and re-render. The **only** hand-maintained source feeding OVERVIEW is the repo-level **`docs/specs/glossary.yaml`** (term/category/def list; rendered into the 名词解释 block, skipped if absent). Both rendered views are committed for GitHub visibility and CI drift-checks them. Never hand-edit OVERVIEW.md or any summary.md — edit the Task YAML (or glossary.yaml) and re-render.
3. **Drive the `spec` CLI, never hand-write the tree** — use `spec new` / `spec add-task` / `spec amend` / `spec abandon`. They keep canonical key order, append history, and auto-render. Hand-editing risks schema/drift failures.
4. **Spec id as code index** — new code references `# Spec-NNNN/T*` in comments so other agents can trace code to design. Existing `# RFC-NNNN` comments are grandfathered (spec group NNNN ≡ old RFC NNNN). See `references/code-comment-conventions.md`.
5. **Human-in-the-loop at phase gates** — humans approve phase transitions; agents execute within phases.
6. **Parallelism through DAG + file allocation** — each Task declares `depends-on` and the `files` it owns. In collaborative mode (one worktree) agents avoid conflicts by only touching files allocated to their Task.

## Work Modes

OpenAgents has two parallelism layers (CLAUDE.md 设计理念 5–6):

- **协同工作模式（collaborative, same worktree）** — multiple agents implement one spec group together; conflict-free because each Task owns a disjoint `files` set. Default within one group.
- **多 worktree 模式（across issues）** — different issues run in separate worktrees in parallel, each driving its own spec group(s).

Within a single group, always use collaborative mode and rely on the per-Task `files` list.

## Spec Scope Boundaries

### When to Create a Spec group

Create a group (`spec new`) for any of these:
- New module / service / major component
- Public interface or protocol changes (e.g. agent message protocol)
- Data model / persisted state changes
- Cross-module feature implementations
- Anything with design trade-offs worth recording

### When to Skip (Implement Directly)

Skip when ALL hold: no design decisions to document, only one module/file affected, only one Task.

### Merge into an Existing group

If a small feature is a natural extension of an existing group's scope, `spec add-task` it onto that group rather than creating a new one.

### When to Split

A group with more than 6 Tasks is too large — split into multiple focused groups.

## Disk Layout (reference)

```
docs/specs/
├── OVERVIEW.md            # global board view (spec render output; never hand-edit)
├── glossary.yaml          # repo-level term glossary (hand-maintained; rendered into OVERVIEW 名词解释)
├── README.md              # specs dir doc + numbering rules (hand-written, static)
└── <NNNN-slug>/
    ├── metadata.yaml      # group meta: title / issue / slug / overview (group-level lead prose)
    ├── summary.md         # per-group human plan (spec render output; never hand-edit)
    ├── tasks/T*.yaml      # current-version Task snapshot (one-to-one with live code)
    └── history/T*.yaml    # append-only old versions (only legacy lives here)
```

Task fields and meaning: see `references/task-fields.md`.

## Workflow

### Phase 1: Requirements Clarification

Same as before — iteratively clarify before designing.

1. Read the request carefully; identify ambiguities, missing details, implicit assumptions.
2. Present 3–5 focused questions with selectable options where possible.
3. Repeat until requirements are clear; summarize for confirmation.
4. Cover: scope boundaries, affected modules, performance, backward compatibility.
5. Do NOT persist requirements separately — they get absorbed into the spec's prose fields.

### Phase 2: Spec Design (Task DAG + File Allocation)

The spec group is the core artifact. Author it via the CLI — never hand-write YAML.

1. **Create the group:**
   ```
   spec new <slug> --issue <N> --title "<组标题>"
   ```
   The number is auto-assigned as local-max + 1. Cross-PR number conflicts are caught by CI (`check-spec-number-conflicts.py`); in shared-repo work, push the group skeleton and open a draft PR early so the number is visible to other agents. If you must pin a number, pass `--number NNNN`.
2. **Explore the codebase** thoroughly before designing — use subagents for parallel context gathering.
3. **Decompose into a Task DAG** and add each Task:
   ```
   spec add-task <NNNN> --id T1 --title "<标题>" --priority P1 \
     --files openagents/x.py,tests/test_x.py \
     --depends-on T0 \
     --scope "<这个 Task 改什么>" --acceptance "<可验证的验收标准>"
   ```
   - **Task count must not exceed 6.** If it does, split into multiple groups.
   - **`files` across Tasks must be disjoint** — this is what makes collaborative mode conflict-free. If two Tasks must touch one file, merge them or split that file's changes into its own Task.
   - `depends-on` declares the DAG (cross-group refs use qualified ids like `0012/T2`). Tasks with no mutual dependency run in parallel.
   - New Tasks start `status: pending`.
4. **Fill design prose** on the relevant Tasks by editing the `tasks/T*.yaml` prose fields (`summary`/`motivation`/`design`/`interface`/`tradeoffs`/`tests`/`references`/`open-questions`) — block scalars carrying Markdown (mermaid allowed in `design`). Keep it architectural: **what & why, NOT implementation code**. After editing prose by hand, run `spec validate` then `spec render`.
   - **Write a group-level `overview`** so the rendered `summary.md` opens with narrative, not a raw Task DAG. It is the lead a human reads first: where this group sits in the bigger picture, what it delivers, and the data-flow spine that threads T1…Tn (a small ascii/mermaid diagram mapping each box to a Task works well). It also renders into OVERVIEW's per-feature section, threading the groups into one story. Set it via CLI (prose with diagrams → `--file`):
     ```
     spec set-overview <NNNN> --file overview.md   # or --text "<short lead>"
     ```
     `spec new` also accepts `--overview`. Without an overview, summary.md jumps straight into the DAG and reads as foggy.
5. **Confirm open questions with the user** before writing any `open-questions` prose — only questions the user chooses to keep are recorded.
6. **Validate & render:**
   ```
   spec validate          # must be error-free
   spec render            # regenerates OVERVIEW.md + each group's summary.md
   ```
   Review the group's `summary.md` as the human-readable plan; if it reads poorly, fix the
   underlying Task prose (keep it 精简/精确/学术化, see Language Convention) and re-render.
7. Present the group (Tasks + DAG + file lists, via OVERVIEW.md) to the user for review. Collect ALL feedback at once; apply in one pass. Repeat until approved.

**Quality bar:**
- Design prose focuses on architecture, key decisions, interface contracts — not code.
- `tradeoffs` includes at least one alternative considered.
- Every Task is independently implementable/verifiable, has a disjoint `files` list, clear `depends-on`, and an `acceptance` criterion.
- `tests` covers unit + integration for the Task's scope.

### Phase 3: Implementation & Verification

Execute Tasks according to the DAG.

**Before starting:** identify executable Tasks (`status: pending`, all `depends-on` are `done`). Present them. Independent Tasks can run in parallel sessions (collaborative mode), each reading the group for context and touching only its `files`.

**Per Task:**
1. **Claim** — mark in-progress:
   ```
   spec amend <NNNN> <Tn> --reason "claim: start implementing"
   ```
   then set `status: in-progress` in `tasks/Tn.yaml` and re-`spec validate`/`render`. (`amend` snapshots the prior version into history and bumps `version`.)
2. **Plan** — design the detailed implementation in your working session, NOT in the spec.
3. **Implement** — write code, touching ONLY this Task's `files`. Reference the spec id in comments: `# Spec-NNNN/Tn: …`.
4. **Verify** — `references/verification-checklist.md`: ruff check + ruff format --check, pytest, spec comment present, `spec validate` clean, OVERVIEW drift-free (`spec render` then no git diff), rebase on latest base and re-run tests.
5. **Complete** — set `status: done` (via `spec amend … --reason "done"` + edit) and re-validate/render. The Task **stays in the snapshot** as `done` (it maps to live code). Only use `spec abandon` if the Task is dropped entirely.
6. **AI Review + Human Test Plan** — summarize changes/concerns; write manual verification steps. Collect ALL feedback at once; fix in one pass.

**Evolution (the core differentiator):**
- Redefining a Task → `spec amend` (old version goes to `history/`, snapshot keeps only the current version). Set `change-reason` / lineage fields (`supersedes`/`split-from`/`merged-from`/`derived-from`) so `spec render` can draw the evolution graph.
- Dropping a Task → `spec abandon` (tombstoned into history, removed from snapshot).
- Never leave a stale old definition in the snapshot — that's the流水账 problem this model exists to kill.

**Failure handling:** tests fail → fix and re-verify, do not merge. Fundamentally flawed Task → document what went wrong, revert, `spec amend` the Task definition with lessons learned, restart.

## Phase Gate Summary

```
[Requirements]   --human approves-->  [Spec group + Task DAG + File Allocation]
[Spec + DAG]     --human approves-->  [Implementation per Task]
[Implementation] --human verifies-->  [Merge to base (test)]
```

Never skip a phase gate. If blocked, ask the human rather than proceeding with assumptions.

## References

- `references/task-fields.md` — Task YAML field reference (structured + prose fields, lineage)
- `references/verification-checklist.md` — Phase 3 implementation verification checklist
- `references/code-comment-conventions.md` — code comment style with `Spec-NNNN/T*` referencing
