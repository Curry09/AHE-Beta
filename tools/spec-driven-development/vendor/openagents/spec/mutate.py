"""spec new / add-task / abandon: add or modify Tasks on group markdown file + auto-render.

2026-06-24 spec-markdown-form (replaces Spec-0014/T4):
- new: create `docs/specs/NNNN-slug.md` (frontmatter + empty tasks), auto-render.
- add-task: load group → append one Task → write back → auto-render.
- abandon: load group → remove Task from tasks → write back → auto-render.

Legacy mechanisms retired (decision D3): no more `spec amend` (edit group markdown directly), version evolution tracked by git
history, rationale for changes tracked by dated design docs. Decoupled from git / GitHub (principle 10).
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group, Metadata, Task
from openagents.spec.render import write_overview
from openagents.spec.reservation import reserve_number


def create_group(
    *, specs_root: Path, slug: str, title: str, issue: int, summary: str, number: str | None
) -> Path:
    """Scaffold a new spec group markdown file, return its path; auto-render.

    Shared Git workspace pre-allocates number on remote atomically; local workspace reuses next number.
    Spec-0015: summary is a required input parameter (plain-English TL;DR brought forward to group creation).
    """
    group_number = reserve_number(specs_root=specs_root, issue=issue, slug=slug, number=number)
    path = model.group_path(specs_root=specs_root, number=group_number, slug=slug)
    if path.exists():
        raise FileExistsError(f"Spec group already exists: {path}")
    group = Group(
        number=group_number,
        metadata=Metadata(title=title, issue=issue, slug=slug, summary=summary),
        tasks=[],
        history={},
    )
    model.dump_group(group=group, path=path)
    write_overview(specs_root=specs_root)  # OVERVIEW never expires.
    return path


def add_task(
    *,
    specs_root: Path,
    group: str,
    task_id: str,
    title: str,
    priority: str,
    status: str,
    files: list[str],
    depends_on: list[str],
    scope: str,
    acceptance: str,
) -> Task:
    """Add a new Task to an existing group markdown file, return it; auto-render.

    Raise FileNotFoundError if group does not exist; raise FileExistsError if task id already exists.
    """
    path = _group_path(specs_root=specs_root, group=group)
    grp = model.load_group(path=path)
    if any(task.id == task_id for task in grp.tasks):
        qid = model.qualified_id(group=grp.number, task_id=task_id)
        raise FileExistsError(f"Task already exists: {qid} (edit the group Markdown to change it)")
    task = Task(
        id=task_id,
        title=title,
        status=status,
        priority=priority,
        files=list(files),
        depends_on=list(depends_on),
        scope=scope,
        acceptance=acceptance,
    )
    grp.tasks.append(task)
    model.dump_group(group=grp, path=path)
    write_overview(specs_root=specs_root)
    return task


def abandon(*, specs_root: Path, group: str, task_id: str, reason: str) -> None:
    """Abandon a Task: remove it from the group snapshot; auto-render.

    History left to git (decision D3): removed versions remain queryable in git history. Raise FileNotFoundError if task does not exist.
    """
    path = _group_path(specs_root=specs_root, group=group)
    grp = model.load_group(path=path)
    remaining = [task for task in grp.tasks if task.id != task_id]
    if len(remaining) == len(grp.tasks):
        qid = model.qualified_id(group=grp.number, task_id=task_id)
        raise FileNotFoundError(f"Task does not exist: {qid} ({path})")
    grp.tasks[:] = remaining
    model.dump_group(group=grp, path=path)
    write_overview(specs_root=specs_root)


def _group_path(*, specs_root: Path, group: str) -> Path:
    """Parse group markdown file by number (NNNN) or filename (NNNN-slug[.md]); raise FileNotFoundError if not found."""
    # Direct filename match.
    for candidate in (specs_root / group, specs_root / f"{group}.md"):
        if candidate.is_file() and model._is_group_file(name=candidate.name):
            return candidate
    # Match by NNNN prefix.
    if specs_root.is_dir():
        for md_path in sorted(specs_root.glob("*.md")):
            if model._is_group_file(name=md_path.name) and md_path.name[:4] == group:
                return md_path
    raise FileNotFoundError(f"Spec group does not exist: {group} (under {specs_root})")
