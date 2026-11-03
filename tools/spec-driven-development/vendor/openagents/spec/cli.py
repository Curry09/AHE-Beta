"""spec CLI (console_script: `spec`): new / add-task / render / validate / abandon / graph.

2026-06-24 spec-markdown-form: spec group changed to single Markdown file; `spec amend` retired (edit group
Markdown directly, history goes to git); new `spec graph` generates "unique code mapping" ARCHITECTURE.md.

Thin routing layer (principle 1 Occam): dispatch subcommands to mutate / render / validate / graph, no business logic in CLI itself.
- spec new      <slug> --issue --title    → mutate.create_group
- spec add-task <group> --id --title …    → mutate.add_task
- spec render                             → write OVERVIEW.md
- spec validate                           → non-zero exit code if errors
- spec abandon  <group> <task> --reason   → mutate.abandon (remove from snapshot, history in git)
- spec graph    [--check]                 → write ARCHITECTURE.md / validate docstring + drift

Default specs root is docs/specs (can override with --specs-root); graph scans openagents package by default.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from openagents.spec import graph, mutate
from openagents.spec.render import write_overview
from openagents.spec.reservation import reserve_number
from openagents.spec.schema import PRIORITY_VALUES, STATUS_VALUES
from openagents.spec.validate import validate

_DEFAULT_SPECS_ROOT = Path("docs/specs")
_DEFAULT_PACKAGE_ROOT = Path("openagents")


def _csv(value: str) -> list[str]:
    """Comma-separated string → list of non-empty items with whitespace stripped (for --files / --depends-on)."""
    return [item.strip() for item in value.split(",") if item.strip()]


def main(*, argv: list[str] | None = None) -> int:
    """Entry point for the `spec` console_script. Returns process exit code (0 success / non-zero failure)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    specs_root = args.specs_root
    if args.command == "new":
        return _cmd_new(
            specs_root=specs_root,
            slug=args.slug,
            title=args.title,
            issue=args.issue,
            summary=args.summary,
            number=args.number,
        )
    if args.command == "reserve-number":
        print(
            reserve_number(
                specs_root=specs_root,
                issue=args.issue,
                slug=args.slug,
                number=args.number,
            )
        )
        return 0
    if args.command == "add-task":
        return _cmd_add_task(specs_root=specs_root, args=args)
    if args.command == "render":
        return _cmd_render(specs_root=specs_root)
    if args.command == "validate":
        return _cmd_validate(specs_root=specs_root)
    if args.command == "abandon":
        return _cmd_abandon(
            specs_root=specs_root, group=args.group, task=args.task, reason=args.reason
        )
    if args.command == "graph":
        return _cmd_graph(specs_root=specs_root, package_root=args.package_root, check=args.check)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """Construct argparse parser. --specs-root in shared parent parser, subcommands can add arguments before and after."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--specs-root",
        type=Path,
        default=_DEFAULT_SPECS_ROOT,
        help="Spec source root (default: docs/specs)",
    )

    parser = argparse.ArgumentParser(prog="spec", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command")

    new = sub.add_parser("new", help="Create a spec group (one Markdown file)", parents=[common])
    new.add_argument("slug", help="Group slug (short English kebab-case name)")
    new.add_argument("--issue", type=int, required=True, help="Associated issue number")
    new.add_argument("--title", required=True, help="Group title")
    # Spec-0015: Plain-language TL;DR mandatory—make "write summary" a required hard step in group creation.
    new.add_argument("--summary", required=True, help="Plain-language group TL;DR (required)")
    new.add_argument(
        "--number",
        default=None,
        help="Group number NNNN (reserved remotely in shared repositories)",
    )

    reserve = sub.add_parser(
        "reserve-number", help="Reserve a new number for an existing spec", parents=[common]
    )
    reserve.add_argument("--issue", type=int, required=True, help="Associated issue number")
    reserve.add_argument("--slug", required=True, help="Group slug")
    reserve.add_argument(
        "--number", default=None, help="Requested number NNNN (default: next available number)"
    )

    add = sub.add_parser("add-task", help="Add a Task to a spec group", parents=[common])
    add.add_argument("group", help="Group number NNNN or filename")
    add.add_argument("--id", required=True, dest="task_id", help="Task ID, such as T1")
    add.add_argument("--title", required=True, help="Task title")
    add.add_argument("--priority", choices=list(PRIORITY_VALUES), required=True, help="Priority")
    add.add_argument(
        "--status", choices=list(STATUS_VALUES), default="pending", help="Status (default: pending)"
    )
    add.add_argument("--files", type=_csv, default=[], help="Owned files (comma-separated)")
    add.add_argument(
        "--depends-on",
        type=_csv,
        default=[],
        dest="depends_on",
        help="Dependencies (comma-separated)",
    )
    add.add_argument("--scope", default="", help="Task scope (Markdown)")
    add.add_argument("--acceptance", default="", help="Acceptance criteria (Markdown)")

    sub.add_parser("render", help="Render OVERVIEW.md", parents=[common])
    sub.add_parser("validate", help="Validate specs (schema + semantics)", parents=[common])

    abandon = sub.add_parser(
        "abandon", help="Remove a Task from the snapshot (history stays in git)", parents=[common]
    )
    abandon.add_argument("group", help="Group number NNNN or filename")
    abandon.add_argument("task", help="Task ID, such as T3")
    abandon.add_argument(
        "--reason", required=True, help="Reason for removal (record in the commit message)"
    )

    g = sub.add_parser(
        "graph", help="Generate/check ARCHITECTURE.md (the code map)", parents=[common]
    )
    g.add_argument(
        "--package-root",
        type=Path,
        default=_DEFAULT_PACKAGE_ROOT,
        help="Package to scan (default: openagents)",
    )
    g.add_argument(
        "--check", action="store_true", help="CI mode: check docstring completeness and drift"
    )

    return parser


def _cmd_new(
    *, specs_root: Path, slug: str, title: str, issue: int, summary: str, number: str | None
) -> int:
    """new subcommand: forward to mutate.create_group, print newly created file."""
    path = mutate.create_group(
        specs_root=specs_root, slug=slug, title=title, issue=issue, summary=summary, number=number
    )
    print(f"✓ Created spec group {path.name} ({path})")
    return 0


def _cmd_add_task(*, specs_root: Path, args: argparse.Namespace) -> int:
    """add-task subcommand: forward to mutate.add_task."""
    task = mutate.add_task(
        specs_root=specs_root,
        group=args.group,
        task_id=args.task_id,
        title=args.title,
        priority=args.priority,
        status=args.status,
        files=args.files,
        depends_on=args.depends_on,
        scope=args.scope,
        acceptance=args.acceptance,
    )
    print(f"✓ Added Task {args.group}/{task.id} ({task.status})")
    return 0


def _cmd_render(*, specs_root: Path) -> int:
    """render subcommand: write OVERVIEW.md and print path."""
    path = write_overview(specs_root=specs_root)
    print(f"✓ Generated {path}")
    return 0


def _cmd_validate(*, specs_root: Path) -> int:
    """validate subcommand: print issues; return 1 if errors, 0 if only warnings."""
    report = validate(specs_root=specs_root)
    for issue in report.issues:
        print(f"[{issue.level}] {issue.where}: {issue.message}")
    if not report.ok:
        print("✗ Spec validation failed (errors found)")
        return 1
    print("✓ Spec validation passed")
    return 0


def _cmd_abandon(*, specs_root: Path, group: str, task: str, reason: str) -> int:
    """abandon subcommand: forward to mutate.abandon."""
    mutate.abandon(specs_root=specs_root, group=group, task_id=task, reason=reason)
    print(f"✓ Abandoned {group}/{task}")
    return 0


def _cmd_graph(*, specs_root: Path, package_root: Path, check: bool) -> int:
    """graph subcommand: --check validates docstring completeness + drift; otherwise generate ARCHITECTURE.md."""
    if not check:
        path = graph.write_architecture(specs_root=specs_root, package_root=package_root)
        print(f"✓ Generated {path}")
        return 0

    # --check: 1) docstrings complete; 2) ARCHITECTURE.md and code have no drift.
    missing = graph.missing_docstrings(package_root=package_root)
    current = specs_root / graph.ARCHITECTURE_FILENAME
    expected = graph.render_architecture(package_root=package_root)
    drift = (not current.is_file()) or current.read_text(encoding="utf-8") != expected

    for path_str in missing:
        print(f"[error] {path_str}: missing docstring (file/module documentation convention)")
    if drift:
        print(f"[error] {current}: differs from the code; run `spec graph` to regenerate")
    if missing or drift:
        print("✗ Graph validation failed")
        return 1
    print("✓ Graph validation passed (docstrings complete, no drift)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
