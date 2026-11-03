"""spec data layer: Task / Overview / Metadata / Group models with **markdown single-file** round-trip read/write.

issue #69 rust-RFC form (overview-first + self-contained single spec):
One spec group = one markdown file `docs/specs/NNNN-slug.md`:
- **YAML frontmatter** (machine-read): group metadata number/title/issue/slug/summary + tasks list
  (structured fields + scope/acceptance; `files` = single-writer ownership declaration, reserved for issue #71).
- **Markdown body** (human/agent read): group-level rust-RFC 9-section overview (Summary…Future possibilities),
  feature scope self-contained in narrative, DAG + file allocation moved into Reference-level; no per-Task subsections.

Pure module that understands only docs/specs/ source data structure (principle 10 decoupling), unaware of git / GitHub.
Per-task version history mechanism retired (decision D3), history delegated to git + dated design docs, Group.history always empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

# Unified YAML round-trip example (for frontmatter).
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096
_yaml.indent(mapping=2, sequence=4, offset=2)

# Structured field order for each Task in frontmatter (yaml_key, attr). dump always follows this order, key order stable.
# Note: version/lineage/change-reason etc. retired with history mechanism (decision D3), no longer in frontmatter.
# issue #69: Tasks are work-breakdown rows, with short scope/acceptance fields in frontmatter;
# the design narrative belongs in the group-level Overview.
_TASK_FM_ORDER: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("title", "title"),
    ("status", "status"),
    ("priority", "priority"),
    ("tags", "tags"),
    ("depends-on", "depends_on"),
    ("relates-to", "relates_to"),
    ("parallel", "parallel"),
    ("files", "files"),
    ("scope", "scope"),
    ("acceptance", "acceptance"),
)

# issue #69: group-level body = rust-RFC 9-section overview (markdown heading, Overview attribute), dump follows this order.
# Single spec self-contained and readable, overview-first: feature scope covered in these 9 sections, Tasks are only frontmatter work-breakdown rows.
_OVERVIEW_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Guide-level explanation", "guide_level"),
    ("Reference-level explanation", "reference_level"),
    ("Drawbacks", "drawbacks"),
    ("Rationale and alternatives", "rationale_alternatives"),
    ("Prior art", "prior_art"),
    ("Unresolved questions", "unresolved_questions"),
    ("Future possibilities", "future_possibilities"),
)
_SECTION_BY_HEADING = {heading: attr for heading, attr in _OVERVIEW_SECTIONS}

# Body section delimiters: group-level section headers `## Summary` / `## Reference-level explanation` …
_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")

# spec new scaffold placeholder: non-empty (to form section headings), but _strip_placeholder normalizes to empty string.
_PLACEHOLDER = "<!-- TODO -->"


@dataclass(frozen=True)
class RelatesTo:
    """Non-blocking cross-feature association (render draws dashed lines)."""

    # Cross-group scoped ID, e.g., "0012/T2"
    ref: str
    # Association type extends | supersedes | note
    type: str


@dataclass
class Task:
    """A single spec Task —— work-breakdown row for DAG + file allocation (primarily structured fields after issue #69).

    Structured fields (status/priority/depends-on/files…) go in frontmatter, machine-verifiable;
    from issue #69 onward, feature design narrative moves to group-level Overview, Task retains only two short one-line prose
    (scope/acceptance), and both also go in frontmatter—`files` is single-writer ownership declaration
    (principle 6 / issue #71 runtime owner check structured source).

    version/lineage fields preserved in data class (with defaults) to minimize render changes (decision D2),
    but after history mechanism retirement no longer populated from frontmatter, Group.history always empty.
    """

    # ── Identity and status ──
    id: str
    title: str
    status: str
    priority: str
    tags: list[str] = field(default_factory=list)
    # ── Relations ──
    depends_on: list[str] = field(default_factory=list)
    relates_to: list[RelatesTo] = field(default_factory=list)
    parallel: bool = False
    files: list[str] = field(default_factory=list)
    # ── Evolution / lineage (defaults preserved, decision D3 inactive after retirement) ──
    version: int = 1
    updated: str = ""
    change_reason: str = ""
    supersedes: list[str] = field(default_factory=list)
    split_from: str | None = None
    merged_from: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    # ── Work-breakdown short prose (goes in frontmatter; design narrative moves to group-level Overview) ──
    scope: str = ""
    acceptance: str = ""


@dataclass(frozen=True)
class Overview:
    """Group-level rust-RFC 9-section overview (issue #69) —— self-contained narrative of feature scope, placed in markdown body.

    Single spec self-contained: reading these 9 sections fully explains the feature, no need to open other specs;
    DAG + file allocation moved into reference_level. Field names correspond one-to-one with attr in `_OVERVIEW_SECTIONS`.
    """

    summary: str = ""
    motivation: str = ""
    guide_level: str = ""
    reference_level: str = ""
    drawbacks: str = ""
    rationale_alternatives: str = ""
    prior_art: str = ""
    unresolved_questions: str = ""
    future_possibilities: str = ""


@dataclass(frozen=True)
class Metadata:
    """Group-level metadata (one spec group = one issue/feature)."""

    title: str
    issue: int
    slug: str
    # Spec-0015: group-level human-readable TL;DR (entire feature's "what/why/what we produce").
    # Defaults to empty string for backward compatibility; non-empty enforced by validate's _summary_checks.
    summary: str = ""


@dataclass(frozen=True)
class Group:
    """All source data for one spec group. history always empty in markdown form (decision D3)."""

    # Four-digit number "0009" (1:1 compatible with legacy RFC numbers)
    number: str
    metadata: Metadata
    # Current version Task snapshot (status includes done; completed work remains in snapshot)
    tasks: list[Task]
    # issue #69: group-level rust-RFC 9-section overview (feature scope, placed in body)
    overview: Overview = field(default_factory=Overview)
    # Retired: fields preserved so render/validate need no changes, always empty dict
    history: dict[str, list[Task]] = field(default_factory=dict)


def qualified_id(*, group: str, task_id: str) -> str:
    """Build a cross-group qualified task id like "0009/T3"."""
    return f"{group}/{task_id}"


def group_path(*, specs_root: Path, number: str, slug: str) -> Path:
    """Assemble markdown file path for a spec group: docs/specs/NNNN-slug.md."""
    return specs_root / f"{number}-{slug}.md"


def load_group(*, path: Path) -> Group:
    """Load one spec group from a markdown file (frontmatter + body).

    Frontmatter provides group metadata and structured Task fields; body is split by RFC section headings into a group-level
    Overview with 9 sections (issue #69).
    """
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text=text)
    number = str(meta.get("number") or path.name[:4]).zfill(4)
    metadata = Metadata(
        title=str(meta.get("title", "")),
        issue=int(meta.get("issue", 0)),
        slug=str(meta.get("slug", "")),
        summary=str(meta.get("summary", "")),
    )

    overview = _parse_body(body=body)
    tasks = [task_from_mapping(data=raw) for raw in meta.get("tasks") or []]

    return Group(number=number, metadata=metadata, tasks=tasks, overview=overview, history={})


def load_all(*, specs_root: Path) -> list[Group]:
    """Load every spec group markdown file under specs_root (sorted by number).

    Only recognize group files `NNNN-slug.md` (slug starts with letter, excluding dated design docs `YYYY-MM-DD-*.md`
    and OVERVIEW.md / ARCHITECTURE.md / README.md); return [] for empty repository.
    """
    if not specs_root.is_dir():
        return []
    groups: list[Group] = []
    for md_path in sorted(specs_root.glob("*.md")):
        if _is_group_file(name=md_path.name):
            groups.append(load_group(path=md_path))
    return groups


def dump_group(*, group: Group, path: Path) -> None:
    """Write a Group to a markdown file (frontmatter + body), deterministically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_group(group=group), encoding="utf-8")


def render_group(*, group: Group) -> str:
    """Serialize a Group to markdown text (frontmatter + body). Pure."""
    fm = CommentedMap()
    fm["number"] = DoubleQuotedScalarString(group.number)
    fm["title"] = group.metadata.title
    fm["issue"] = group.metadata.issue
    fm["slug"] = group.metadata.slug
    fm["summary"] = group.metadata.summary
    fm["tasks"] = [_task_frontmatter(task=task) for task in group.tasks]

    buf = StringIO()
    _yaml.dump(fm, buf)
    fm_text = buf.getvalue()

    title = group.metadata.title or group.metadata.slug
    head = (
        f"---\n{fm_text}---\n\n"
        f"# {group.number} · {title}\n\n"
        "<!-- Maintained by the spec tool: frontmatter is the structured source (including the Task DAG); "
        "the body is the group-level, nine-section RFC overview. -->\n"
    )
    body = _render_body(group=group)
    return head + ("\n" + body if body else "") + "\n"


def next_number(*, specs_root: Path) -> str:
    """Return the next free 4-digit group number (max existing + 1, "0001" if none)."""
    highest = 0
    for group in load_all(specs_root=specs_root):
        try:
            highest = max(highest, int(group.number))
        except ValueError:
            continue
    return f"{highest + 1:04d}"


def task_from_mapping(*, data: object) -> Task:
    """Build a Task from a frontmatter task mapping (structured fields only)."""
    raw = data or {}
    relates = [
        RelatesTo(ref=str(item.get("ref", "")), type=str(item.get("type", "")))
        for item in (raw.get("relates-to") or [])
    ]
    return Task(
        id=str(raw.get("id", "")),
        title=str(raw.get("title", "")),
        status=str(raw.get("status", "")),
        priority=str(raw.get("priority", "")),
        tags=_str_list(value=raw.get("tags")),
        depends_on=_str_list(value=raw.get("depends-on")),
        relates_to=relates,
        parallel=bool(raw.get("parallel", False)),
        files=_str_list(value=raw.get("files")),
        scope=str(raw.get("scope", "")),
        acceptance=str(raw.get("acceptance", "")),
    )


def _task_frontmatter(*, task: Task) -> CommentedMap:
    """Task → frontmatter CommentedMap (structured fields only, fixed key order)."""
    out = CommentedMap()
    for yaml_key, attr in _TASK_FM_ORDER:
        value = getattr(task, attr)
        if attr == "relates_to":
            out[yaml_key] = [
                CommentedMap([("ref", item.ref), ("type", item.type)]) for item in value
            ]
        else:
            out[yaml_key] = value
    return out


def _render_body(*, group: Group) -> str:
    """Group-level rust-RFC 9-section overview (issue #69): output all section headings and fill empty sections with placeholders.

    Always materialize all 9 sections to provide scaffolding for authors (spec new) and keep "overview-first" structure stable for assertions and validation.
    """
    chunks: list[str] = []
    for heading, attr in _OVERVIEW_SECTIONS:
        text = getattr(group.overview, attr).rstrip()
        chunks.append(f"## {heading}\n\n{text or _PLACEHOLDER}\n")
    return "\n".join(chunks)


def _split_frontmatter(*, text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter (first block --- … ---) and body text following it. Return ({}, text) if no frontmatter."""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    meta = _yaml.load(fm_text) if fm_text.strip() else None
    return (meta or {}), body


def _parse_body(*, body: str) -> Overview:
    """Body → group-level Overview (issue #69). Split by RFC section headings; placeholder sections normalize to empty string."""
    sections: dict[str, str] = {}
    current_attr: str | None = None
    buffer: list[str] = []

    def _flush() -> None:
        if current_attr is not None:
            sections[current_attr] = _strip_placeholder(text="\n".join(buffer).strip("\n"))

    for line in body.split("\n"):
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match and heading_match.group(1) in _SECTION_BY_HEADING:
            _flush()
            current_attr = _SECTION_BY_HEADING[heading_match.group(1)]
            buffer = []
            continue
        buffer.append(line)
    _flush()
    return Overview(**sections)


def _strip_placeholder(*, text: str) -> str:
    """Normalize the English scaffold placeholder to an empty section."""
    return "" if text.strip() == _PLACEHOLDER else text


def _is_group_file(*, name: str) -> bool:
    """Is filename a group file `NNNN-slug.md` (four digits + '-' + slug starting with letter)?

    Exclude dated design docs `YYYY-MM-DD-*.md` (digit at position 6) and generated/README files.
    """
    return bool(re.match(r"^\d{4}-[A-Za-z][^/]*\.md$", name))


def _str_list(*, value: object) -> list[str]:
    """Normalize list fields to list[str]; None → []."""
    if value is None:
        return []
    return [str(item) for item in value]
