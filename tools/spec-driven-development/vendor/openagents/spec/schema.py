"""spec JSON Schema — single source of truth for group markdown frontmatter / Task structure validation.

Spec-0014/T1 (2026-06-24 spec-markdown-form update):
Use JSON Schema draft 2020-12 declaratively describe source data shape and enumerations (decision D8):
- TASK_SCHEMA: single Task object in frontmatter `tasks` list
- GROUP_FRONTMATTER_SCHEMA: group markdown file frontmatter (number/title/issue/slug/summary/tasks)

Validation logic in validate.py calls these two schemas; only declarations stored here to maintain single source of truth.
"""

from __future__ import annotations

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# Spec-0014/T1: enumerations centrally defined, schema and (future) documentation share source.
STATUS_VALUES = ("pending", "in-progress", "done", "abandoned")
PRIORITY_VALUES = ("P0", "P1", "P2", "P3")
RELATES_TYPE_VALUES = ("extends", "supersedes", "note")

# issue #69: Tasks are work-breakdown rows; scope and acceptance are their two short prose fields in frontmatter.
# Narrative redesign moves up to group-level Overview 9 sections (body text, not in frontmatter, thus not in this schema).
_PROSE_KEYS = (
    "scope",
    "acceptance",
)

_RELATES_TO_SCHEMA = {
    "type": "object",
    "properties": {
        "ref": {"type": "string"},
        "type": {"enum": list(RELATES_TYPE_VALUES)},
    },
    "required": ["ref", "type"],
    "additionalProperties": False,
}

# Spec-0014/T1: schema for single Task object. id/title/status/priority required, rest optional.
TASK_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "id": {"type": "string", "pattern": r"^T[0-9A-Za-z]+$"},
        "title": {"type": "string"},
        "status": {"enum": list(STATUS_VALUES)},
        "priority": {"enum": list(PRIORITY_VALUES)},
        "tags": {"type": "array", "items": {"type": "string"}},
        "depends-on": {"type": "array", "items": {"type": "string"}},
        "relates-to": {"type": "array", "items": _RELATES_TO_SCHEMA},
        "parallel": {"type": "boolean"},
        "files": {"type": "array", "items": {"type": "string"}},
        "version": {"type": "integer", "minimum": 1},
        "updated": {"type": "string"},
        "change-reason": {"type": "string"},
        "supersedes": {"type": "array", "items": {"type": "string"}},
        "split-from": {"type": ["string", "null"]},
        "merged-from": {"type": "array", "items": {"type": "string"}},
        "derived-from": {"type": "array", "items": {"type": "string"}},
        **{key: {"type": "string"} for key in _PROSE_KEYS},
    },
    # issue #69: files (single writer ownership) + acceptance (verifiable) each line required.
    "required": ["id", "title", "status", "priority", "files", "acceptance"],
    "additionalProperties": False,
}

# 2026-06-24 spec-markdown-form: group markdown file frontmatter schema (replaces metadata + history).
# Group metadata number/title/issue/slug + tasks list (each item reuses TASK_SCHEMA).
GROUP_FRONTMATTER_SCHEMA: dict = {
    "$schema": _DRAFT,
    "type": "object",
    "properties": {
        "number": {"type": ["string", "integer"]},
        "title": {"type": "string"},
        "issue": {"type": "integer"},
        "slug": {"type": "string"},
        # Spec-0015: group-level plain-English TL;DR. schema declares type only; non-empty enforced by validate's _summary_checks.
        "summary": {"type": "string"},
        "tasks": {"type": "array", "items": TASK_SCHEMA},
    },
    "required": ["number", "title", "issue", "slug", "tasks"],
    "additionalProperties": False,
}
