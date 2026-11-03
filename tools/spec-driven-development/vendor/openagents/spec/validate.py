"""spec validation: JSON Schema + semantic rules (files overlap / DAG acyclic / lineage references).

Spec-0014/T2: spec validate (schema + semantic validation)

run six validation chains in order (decision D7: same-group files overlap is error, cross-group files overlap is warning only):
  1. JSON Schema validation for all task / metadata / history (structure + enum)   -> error
  2. status and history consistency (snapshot contains no abandoned, history version monotonic increasing)  -> error
  3. same-group files do not overlap (collaboration mode no-conflict prerequisite)                        -> error
  4. global depends-on DAG (cross-group included) acyclic                              -> error
  5. lineage / cross-group references (depends-on/relates-to/supersedes/...) point to existing Task -> error
  6. cross-group files overlap (collaboration signal, enter OVERVIEW file conflict report)          -> warning

no error means ok=True (warning does not affect ok). pure function, unaware of git / GitHub (principle 10 decoupling).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from openagents.spec import model
from openagents.spec.model import Group
from openagents.spec.schema import GROUP_FRONTMATTER_SCHEMA

_ERROR = "error"
_WARNING = "warning"

# issue #69: single spec self-contained + overview-first quality gate.
# required overview sections (attr, human-readable title)—these four sections support "read once and understand, no need to read other specs".
_REQUIRED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("summary", "Summary"),
    ("motivation", "Motivation"),
    ("reference_level", "Reference-level explanation"),
    ("rationale_alternatives", "Rationale and alternatives"),
)
# Suspected bare cross-spec reference: `Spec-0012`, `Spec-0012 decision 8`, `Spec-0012/T2`; prompt to restate needed context.
_BARE_REF_RE = re.compile(r"Spec-\d{4}(?:\s+[Dd]ecision\s+\d+|/T\w+)?")


@dataclass(frozen=True)
class ValidationIssue:
    """Spec-0014/T2: single validation issue."""

    # Spec-0014/T2：error | warning
    level: str
    # Spec-0014/T2: locator string, "0009/T3" or file path
    where: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Spec-0014/T2: summary of one validation run. no error means ok (warning does not affect ok)."""

    ok: bool
    issues: list[ValidationIssue]


def validate(*, specs_root: Path) -> ValidationReport:
    """Run the full schema + semantic validation chain over a specs tree.

    Spec-0014/T2: run six chains in order, summarize issues; no error means ok=True.
    """
    issues: list[ValidationIssue] = []

    # 1. JSON Schema: validate structure and enum for raw YAML files (before model loose normalization).
    issues.extend(_schema_checks(specs_root=specs_root))

    # subsequent semantic validation based on model-loaded structured objects.
    groups = model.load_all(specs_root=specs_root)

    # 2. status and history consistency.
    issues.extend(_status_checks(groups=groups))
    # 3. same-group files do not overlap (error); 6. cross-group files overlap (warning).
    issues.extend(_file_overlap_checks(groups=groups))
    # 4. global depends-on DAG acyclic.
    issues.extend(_dag_acyclic_checks(groups=groups))
    # 5. lineage / cross-group references point to existing Task.
    issues.extend(_reference_checks(groups=groups))
    # 7. metadata.summary non-empty (Spec-0015/T3: each feature must have human-readable TL;DR).
    issues.extend(_summary_checks(groups=groups))
    # 8. required overview sections non-empty (issue #69: overview first).                          -> error
    issues.extend(_overview_required_checks(groups=groups))
    # 9. suspected bare cross-spec references in overview (issue #69: single spec self-contained).         -> warning
    issues.extend(_self_contained_checks(groups=groups))

    ok = not any(issue.level == _ERROR for issue in issues)
    return ValidationReport(ok=ok, issues=issues)


def _overview_required_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """issue #69: each group's required overview sections non-empty after whitespace removal, else error (overview first, read and understand)."""
    issues: list[ValidationIssue] = []
    for group in groups:
        for attr, label in _REQUIRED_SECTIONS:
            if not getattr(group.overview, attr).strip():
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=f"{group.number}/overview",
                        message=f"Required overview section '{label}' is empty (self-contained spec, overview first)",
                    )
                )
    return issues


def _self_contained_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """issue #69: scan overview 9 sections, hit "see Spec-NNNN" style bare reference → warning (prompt to restate in place)."""
    issues: list[ValidationIssue] = []
    for group in groups:
        for _, attr in model._OVERVIEW_SECTIONS:
            text = getattr(group.overview, attr)
            for match in _BARE_REF_RE.finditer(text):
                issues.append(
                    ValidationIssue(
                        level=_WARNING,
                        where=f"{group.number}/overview/{attr}",
                        message=(
                            f"Possible bare cross-spec reference {match.group(0)!r}: "
                            "ensure the context needed to understand this spec is restated here (issue #69)"
                        ),
                    )
                )
    return issues


def _summary_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Spec-0015/T3: each group's metadata.summary non-empty after whitespace removal, else error."""
    issues: list[ValidationIssue] = []
    for group in groups:
        if not group.metadata.summary.strip():
            issues.append(
                ValidationIssue(
                    level=_ERROR,
                    where=f"{group.number}/frontmatter",
                    message="metadata.summary is empty (each feature needs a plain-language TL;DR)",
                )
            )
    return issues


def _schema_checks(*, specs_root: Path) -> list[ValidationIssue]:
    """Validate the frontmatter of each group's markdown file using JSON Schema; one error per violation."""
    issues: list[ValidationIssue] = []
    if not specs_root.is_dir():
        return issues

    for md_path in sorted(specs_root.glob("*.md")):
        if not model._is_group_file(name=md_path.name):
            continue
        meta, _body = model._split_frontmatter(text=md_path.read_text(encoding="utf-8"))
        number = md_path.name[:4]
        issues.extend(
            _validate_doc(
                data=meta,
                json_schema=GROUP_FRONTMATTER_SCHEMA,
                where=f"{number}/frontmatter",
            )
        )
    return issues


def _status_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Snapshots must not contain abandoned; if history exists, version numbers must be strictly increasing and the current version must exceed the last historical version."""
    issues: list[ValidationIssue] = []
    for group in groups:
        for task in group.tasks:
            where = model.qualified_id(group=group.number, task_id=task.id)
            # abandoned can only appear in history, not in snapshots (Decision D2).
            if task.status == "abandoned":
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message="A Task with status=abandoned must leave the snapshot; history is retained in git",
                    )
                )
            history = group.history.get(task.id, [])
            if not history:
                continue
            versions = [item.version for item in history]
            # Historical versions must be strictly increasing.
            if any(b <= a for a, b in zip(versions, versions[1:], strict=False)):
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message=f"History version numbers are not strictly increasing: {versions}",
                    )
                )
            # Current version must be greater than the last historical version.
            if task.version <= max(versions):
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=where,
                        message=f"Current version v{task.version} does not exceed the latest historical version v{max(versions)}",
                    )
                )
    return issues


def _file_overlap_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Overlapping files within the same group → error; overlapping files across groups → warning (Decision D7)."""
    issues: list[ValidationIssue] = []
    # file -> {group_number -> [task_id, ...]}
    owners: dict[str, dict[str, list[str]]] = {}
    for group in groups:
        for task in group.tasks:
            for path in task.files:
                owners.setdefault(path, {}).setdefault(group.number, []).append(task.id)

    for path, by_group in sorted(owners.items()):
        # Multiple Tasks in the same group using the same file → error.
        for number, task_ids in sorted(by_group.items()):
            if len(task_ids) > 1:
                joined = ", ".join(sorted(task_ids))
                issues.append(
                    ValidationIssue(
                        level=_ERROR,
                        where=number,
                        message=f"File {path} is owned by multiple Tasks in the same group: {joined}",
                    )
                )
        # File shared by ≥2 groups → warning (collaboration signal).
        if len(by_group) > 1:
            groups_str = ", ".join(sorted(by_group))
            issues.append(
                ValidationIssue(
                    level=_WARNING,
                    where=path,
                    message=f"File {path} overlaps across groups: {groups_str}",
                )
            )
    return issues


def _dag_acyclic_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Global depends-on graph (including cross-group) must be acyclic; report error if cycle exists."""
    # 1. Build graph: nodes = current-version Task qualified IDs; edges = depends-on (resolved to qualified IDs).
    current_ids = _current_ids(groups=groups)
    adjacency: dict[str, list[str]] = {}
    for group in groups:
        for task in group.tasks:
            node = model.qualified_id(group=group.number, task_id=task.id)
            targets = [_resolve_ref(ref=ref, group=group.number) for ref in task.depends_on]
            # Only connect edges to existing nodes; references to non-existent nodes are reported by reference validation.
            adjacency[node] = [t for t in targets if t in current_ids]

    # 2. Detect cycles using DFS.
    cycle = _find_cycle(adjacency=adjacency)
    if cycle is None:
        return []
    return [
        ValidationIssue(
            level=_ERROR,
            where=cycle[0],
            message=f"depends-on contains a cycle: {' -> '.join(cycle)}",
        )
    ]


def _reference_checks(*, groups: list[Group]) -> list[ValidationIssue]:
    """Tasks referenced in depends-on / relates-to / lineage fields must exist (in current version or history)."""
    known = _known_ids(groups=groups)
    issues: list[ValidationIssue] = []
    for group in groups:
        for task in group.tasks:
            where = model.qualified_id(group=group.number, task_id=task.id)
            refs: list[tuple[str, str]] = []
            refs.extend(("depends-on", ref) for ref in task.depends_on)
            refs.extend(("relates-to", rel.ref) for rel in task.relates_to)
            refs.extend(("supersedes", ref) for ref in task.supersedes)
            refs.extend(("merged-from", ref) for ref in task.merged_from)
            refs.extend(("derived-from", ref) for ref in task.derived_from)
            if task.split_from:
                refs.append(("split-from", task.split_from))
            for field_name, ref in refs:
                resolved = _resolve_ref(ref=ref, group=group.number)
                if resolved not in known:
                    issues.append(
                        ValidationIssue(
                            level=_ERROR,
                            where=where,
                            message=f"{field_name} refers to a nonexistent Task: {ref}",
                        )
                    )
    return issues


def _validate_doc(*, data: object, json_schema: dict, where: str) -> list[ValidationIssue]:
    """Run JSON Schema on each individual document; produce one error issue per schema violation."""
    validator = Draft202012Validator(json_schema)
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(data), key=str):
        location = "/".join(str(part) for part in error.absolute_path)
        prefix = f"{where}:{location}" if location else where
        issues.append(ValidationIssue(level=_ERROR, where=prefix, message=error.message))
    return issues


def _current_ids(*, groups: list[Group]) -> set[str]:
    """Set of qualified IDs for all current-version Tasks."""
    return {
        model.qualified_id(group=group.number, task_id=task.id)
        for group in groups
        for task in group.tasks
    }


def _known_ids(*, groups: list[Group]) -> set[str]:
    """Known Task qualified IDs = current version ∪ historical versions (lineage can reference abandoned/old-version Tasks)."""
    known = _current_ids(groups=groups)
    for group in groups:
        for task_id in group.history:
            known.add(model.qualified_id(group=group.number, task_id=task_id))
    return known


def _resolve_ref(*, ref: str, group: str) -> str:
    """Shorthand T3 within a group → qualified ID group/T3; if already containing '/', treat as cross-group qualified ID and return as-is."""
    return ref if "/" in ref else model.qualified_id(group=group, task_id=ref)


def _find_cycle(*, adjacency: dict[str, list[str]]) -> list[str] | None:
    """Use DFS to find one cycle path (node sequence with matching endpoints); return None if acyclic."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}
    stack: list[str] = []

    def _dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        stack.append(node)
        for nxt in adjacency.get(node, []):
            if color.get(nxt, BLACK) == GRAY:
                # Gray node encountered → cycle detected; extract the segment from that node to the current position in the stack.
                idx = stack.index(nxt)
                return [*stack[idx:], nxt]
            if color.get(nxt, BLACK) == WHITE:
                found = _dfs(nxt)
                if found is not None:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(adjacency):
        if color[node] == WHITE:
            found = _dfs(node)
            if found is not None:
                return found
    return None
