"""spec end-to-end verification signpost: extract e2e script from group-level Overview of a spec group and render signpost.

issue #53 (replaces RFC-0008/RFC-0013's rfc.py): migrate "understands document structure only, extracts e2e clues" responsibility
from RFC Markdown parsing to spec group. From issue #69, design narrative moves up to group-level rust-RFC 9-section overview,
e2e script clues extracted from Overview instead (typically falls in Reference-level explanation). Read only spec source data,
unaware of git / GitHub / orchestrator (principle 10 decoupling); any missing/anomalies return None.
"""

from __future__ import annotations

import re
from pathlib import Path

from openagents.spec import model

# Integration test script relative path: scripts/….sh, take the first one (same convention as legacy rfc.py).
_SCRIPT_RE = re.compile(r"scripts/[^\s`)」]+\.sh")

# Spec-0028/T1: PR body embedded overview digest—extract only the three highest-information-density sections (what / why / how),
# truncate each section if it exceeds the line limit to avoid body bloat obscuring Closes/signposts (Reference-level / Drawbacks mitigation).
_DIGEST_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Summary", "summary"),
    ("Motivation", "motivation"),
    ("Reference-level explanation", "reference_level"),
)
# conservative line limit per section (Unresolved questions: initial conservative value, can be adjusted later based on PR feedback).
_DIGEST_MAX_LINES = 12
# continuation hint for over-limit truncation—explicitly tell reviewers to read the complete content in the spec file.
_DIGEST_TRUNCATED_HINT = "… (see the spec file for the full text)"


def script_path_for_group(*, group_path: Path) -> str | None:
    """Scan a spec group's group-level Overview 9 sections for the first `scripts/*.sh`.

    issue #69: script clues extracted from group-level overview (in _OVERVIEW_SECTIONS order, typically in Reference-level)
    group is now single file NNNN-slug.md; group unreadable/no script → None.
    """
    if not group_path.is_file():
        return None
    try:
        group = model.load_group(path=group_path)
    except (OSError, ValueError):
        return None
    for _, attr in model._OVERVIEW_SECTIONS:
        match = _SCRIPT_RE.search(getattr(group.overview, attr) or "")
        if match:
            return match.group(0)
    return None


def overview_digest_for_group(*, group_path: Path) -> str | None:
    """Spec-0028/T1: extract the three highest-information-density sections from a group's 9-section overview, render as the "## spec overview" block in PR body.

    co-equal with signpost_for_group (only understands spec document structure, extracts for PR body, returns None if missing, unaware of
    git / GitHub / orchestrator, principle 10 decoupling). take Summary / Motivation / Reference-level,
    truncate each section by _DIGEST_MAX_LINES (keep first N lines + continuation hint if exceeds), separate three sections with `### <section heading>`.
    group_path not a file / load_group raises OSError|ValueError → None (zero regression: PR body byte-for-byte same as today).
    """
    if not group_path.is_file():
        return None
    try:
        group = model.load_group(path=group_path)
    except (OSError, ValueError):
        return None

    blocks: list[str] = []
    for heading, attr in _DIGEST_SECTIONS:
        body = _truncate_section(text=getattr(group.overview, attr) or "")
        if body:
            blocks.append(f"### {heading}\n{body}")
    if not blocks:
        # all three sections empty (rare, e.g., overview not yet filled): do not render empty block, fall back to no digest (zero regression).
        return None

    header = f"## Spec overview (from docs/specs/{group_path.name})"
    return "\n\n".join([header, *blocks])


def _truncate_section(*, text: str) -> str:
    """Truncate an overview section by _DIGEST_MAX_LINES; keep first N lines and append continuation hint if exceeds. return empty string for empty section."""
    stripped = text.strip("\n")
    if not stripped.strip():
        return ""
    lines = stripped.split("\n")
    if len(lines) <= _DIGEST_MAX_LINES:
        return stripped
    return "\n".join([*lines[:_DIGEST_MAX_LINES], _DIGEST_TRUNCATED_HINT])


def signpost_for_group(*, group_path: Path) -> str | None:
    """Render the "## end-to-end verification" signpost block for a spec group markdown file.

    if script exists, provide directly executable command; otherwise point back to the spec group's Task tests; detailed steps always point to that group file
    (single source of truth, no full text duplication). return None when group unreadable.
    """
    if not group_path.is_file():
        return None
    number = group_path.name[:4]
    spec_id = f"Spec-{number}"
    script = script_path_for_group(group_path=group_path)

    run_line = (
        f"- Run: `bash {script}`"
        if script
        else f"- Run: see Reference-level explanation in the {spec_id} overview"
    )
    detail_line = f"- Detailed manual steps: see the group overview and each Task's `acceptance` in docs/specs/{group_path.name}"
    return "\n".join(["## End-to-end verification", run_line, detail_line])
