"""spec — "Spec Live Snapshot" data layer and tooling (Markdown single-file form).

Spec-0014 + 2026-06-24 spec-markdown-form: Replace RFC with "Spec Live Snapshot".

One spec group = one Markdown file docs/specs/NNNN-slug.md: frontmatter holds structured source data
(machine-readable), body holds each Task design prose (human/agent-readable); the basic unit is Task, with one-to-one correspondence to live code.
Evolution history is delegated to git + dated design documents (decision D3, per-task history retired).

This package is a pure functional data layer + thin CLI (principle 1 Occam, principle 10 decoupling), unaware of git / GitHub /
orchestrator, only reads and writes files under docs/specs/:
- model: load/write group Markdown (frontmatter + body round-trip)
- schema: JSON Schema for Task / frontmatter (single source of truth)
- validate: schema + semantic validation (file overlap / DAG acyclic / lineage references)
- render: generate unique human-readable view OVERVIEW.md (kanban / relationship graph / conflicts / DAG / evolution diagram)
- graph: generate ARCHITECTURE.md from code import graph + docstrings (unique code mapping)
- mutate: new / add-task / abandon (update snapshot + auto-render)
- cli: console_script `spec`
"""
