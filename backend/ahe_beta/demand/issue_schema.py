# Spec-0025/T1: platform-layer standard issue schema—declarative fields per kind, split USER/TRIAGE sections, validation + deterministic rendering.
"""Standard issue format, owned by the platform and inaccessible to the harness.

The issue format is a platform artifact; harness changes cannot redefine it.
**The LLM supplies field values; render guarantees the layout.** Formatting does not depend
on the model following a template or on Gitea forms: all issues are submitted through the
API, while Gitea's ISSUE_TEMPLATE affects only the Web UI and cannot validate API requests.

Spec-0027/T1: the schema contains only normalized output fields populated after investigation
by triage / architect agents (root-cause region/boundary/acceptance, RFC questions/root-causes/…).
These fields define the developer's Definition of Ready. A user-reported issue **body is free text**;
a real persona does not fill out a template. The unused USER section template has been removed.
Machine validation is delegated to nexau's tool layer (see demand/agent_contract.py), which
generates submit-tool input_schema from these SCHEMAS.

`validate(kind, fields)` checks required fields. `render(kind, fields)` produces `### <label>`
Markdown sections for triage comments / RFC bodies. The `section` parameter now has only one
value and remains for backward compatibility. Adding a kind requires only a SCHEMAS entry,
with no changes to validate/render logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

USER = "user"
TRIAGE = "triage"

# Priority enum, highest first: **triage agent** combines severity with user experience in the session (Spec-0025/T3).
# Stored as labels rather than a body field, for dispatch and frontend badges.
PRIORITIES = ("P0", "P1", "P2", "P3")

# ---- Three-plane labels (Spec-0029/T1): claimability uses these labels; new writes use only this vocabulary. ----
REPORT = "report"  # Plane 1: free-text report from the user simulation; not claimable
PROPOSAL = "proposal"  # Plane 2: proposal from triage/architect/divergent; never claimable
READY = "ready"  # Plane 3: claimable work queue, entered only after Owner admission
# Spec-0032/T3: Owner admission applies this delivery handoff label for OpenAgents vigil to discover, rather than applying ready directly.
# vigil `_intake` skips ready issues; curator sorts dependencies only for newly admitted issues. If Owner applied
# ready directly, curator would miss them. vigil applies ready idempotently on discovery; both labels project to the READY plane.
OPENAGENTS = "openagents"
# Terminal labels (replace plane labels on close; write-side ensures plane labels and terminal labels never coexist)
DECLINED = (
    "declined"  # Closed: triage reject/needs_info or Owner decline; reason in comment/close reason
)
MERGED = "merged"  # Merged by Architect's covers; a merged-into machine-readable line links the parent issue
# provenance labels (attribute, not involved in qualification): who produced this proposal
FROM_TRIAGE = "from-triage"
FROM_ARCHITECT = "from-architect"
FROM_DIVERGENT = "from-divergent"
OBSERVATION_GAP = "observation-gap"

# ---- Legacy workflow labels (Spec-0025/0028 write-side retired; constants retained for read-side mapping legacy data, see plane()) ----
NEEDS_TRIAGE = "needs-triage"  # Legacy: new user-simulation report awaiting triage → maps to report
TRIAGED = "triaged"  # Legacy: triage complete and claimable by a developer → maps to ready
REJECTED = "rejected"  # Legacy: triage rejected and closed → terminal
NEEDS_INFO = "needs-info"  # Old: insufficient info closed → terminal state
RFC_LABEL = "RFC"  # Legacy: structural proposal, claimable by a developer → maps to ready
SUPERSEDED = "superseded"  # Old: superseded by RFC → terminal state
DIVERGENT = "divergent"  # Old: product candidate not claimable → mapped to proposal
GATE_DROPPED = "gate-dropped"  # Old: gate dropped closed → terminal state


def round_label(round_no: int) -> str:
    """Return `round-<N>` for user-created issues, incremental triage, and per-round observation curves."""
    return f"round-{int(round_no)}"


# ---- Label → semantic projection (platform-layer single source of truth for web / metrics / dev / frontend) ----
# Issue kind / round / triage status / priority determined entirely by labels; centralized projection here to avoid duplication elsewhere.

_ROUND_RE = re.compile(r"^round-(\d+)$")


def issue_kind(labels: list[str]) -> str:
    """Infer issue kind from labels: RFC overrides type; otherwise use the first USER_KINDS match, or 'bug' as a provisional fallback."""
    ls = list(labels or [])
    if RFC_LABEL in ls:
        return "rfc"
    for k in USER_KINDS:
        if k in ls:
            return k
    return "bug"


def round_of(labels: list[str]) -> int | None:
    """Return the round number N from a `round-N` label, or None if absent."""
    for x in labels or []:
        m = _ROUND_RE.match(str(x))
        if m:
            return int(m.group(1))
    return None


def filter_current_round(items, *, round_no: int | None):
    """Keep only issues belonging to the active round.

    New issues are stamped with a ``round-N`` label.  If a collection contains
    any such labels, unlabelled issues are excluded as well: their round cannot
    be inferred safely and allowing them would reintroduce cross-round input
    leakage.  Collections made entirely of legacy, unlabelled issues are kept
    unchanged for backwards compatibility with old repositories and fixtures.
    """
    if type(round_no) is not int or round_no <= 0:
        return list(items)
    values = list(items)
    if not any(round_of(item.labels) is not None for item in values):
        return values
    return [item for item in values if round_of(item.labels) == round_no]


def filter_architect_round(items, *, round_no: int | None):
    """Include pending diagnostic proposals even when their creator omitted a round label.

    A gap from an earlier round still needs design.  A future-labelled issue must
    not enter the current round.  Callers exclude the independent PM route first.
    """
    values = list(items)
    selected = filter_current_round(values, round_no=round_no)
    seen = {item.number for item in selected}
    for item in values:
        issue_round = round_of(item.labels)
        if (
            item.number not in seen
            and OBSERVATION_GAP in item.labels
            and plane(item.labels) == PROPOSAL
            and (round_no is None or issue_round is None or issue_round <= round_no)
        ):
            selected.append(item)
            seen.add(item.number)
    return selected


def priority_of(labels: list[str]) -> str | None:
    """Return the highest P0-P3 priority present, or None; PRIORITIES is ordered from highest to lowest."""
    present = [p for p in PRIORITIES if p in (labels or [])]
    return present[0] if present else None


def triage_status(labels: list[str]) -> str | None:
    """Label → triage status (single value): most decisive wins — rejected/needs-info/gate-dropped(terminal close) > superseded >
    divergent(candidate not claimable) > triaged(executable) > needs-triage(pending); none → None."""
    ls = list(labels or [])
    for s in (REJECTED, NEEDS_INFO, GATE_DROPPED, SUPERSEDED, DIVERGENT, TRIAGED, NEEDS_TRIAGE):
        if s in ls:
            return s
    return None


# ---- Three-plane projection (Spec-0029/T1: single source of truth for qualification) ----

# Terminal labels (new and old combined): hitting any excludes from all planes.
_TERMINAL_LABELS = frozenset({DECLINED, MERGED, REJECTED, NEEDS_INFO, GATE_DROPPED, SUPERSEDED})


def plane(labels: list[str]) -> str | None:
    """Map labels to report/proposal/ready, or None when no plane applies.

    New plane labels take precedence; legacy labels map as follows:
    needs-triage→report, triaged|RFC→ready, divergent→proposal. Terminal labels, both new and old,
    are checked before legacy mapping. This preserves triage_status's precedence: a legacy
    triaged+superseded issue is terminal rather than ready.

    Spec-0032/T3: `openagents` (Owner's delivery handoff token after admission) and `ready`
    (the execution token applied by vigil) both map to the READY plane. Admission places an issue
    in the work queue; vigil's later idempotent ready update does not affect the projected plane.
    Metrics, backpressure alerts, and frontend grouping all use this projection.
    """
    ls = set(labels or [])
    if READY in ls or OPENAGENTS in ls:
        return READY
    if PROPOSAL in ls:
        return PROPOSAL
    if REPORT in ls:
        return REPORT
    if ls & _TERMINAL_LABELS:
        return None
    if DIVERGENT in ls:
        return PROPOSAL
    if TRIAGED in ls or RFC_LABEL in ls:
        return READY
    if NEEDS_TRIAGE in ls:
        return REPORT
    return None


def is_ready(*, labels: list[str], state: str) -> bool:
    """Allow developers to claim only open issues in the ready plane; new workflow labels default to unclaimable (fail-closed)."""
    return state == "open" and plane(labels) == READY


def is_backlog_by_labels(labels: list[str]) -> bool:
    """Check whether labels place an issue in the executable backlog: the ready plane.

    plane() applies the same rules to new and legacy labels. Open/closed state is ignored here
    because event-based observation curves account for closure with a cancelling event.
    """
    return plane(labels) == READY


def is_executable_backlog(*, labels: list[str], state: str) -> bool:
    """Count an issue in the current executable backlog only when it is open and in the ready plane, so developers can claim it."""
    return is_ready(labels=labels, state=state)


def provenance_of(labels: list[str]) -> str | None:
    """Label → proposal source (from-triage/from-architect/from-divergent); none → None."""
    for p in (FROM_TRIAGE, FROM_ARCHITECT, FROM_DIVERGENT):
        if p in (labels or []):
            return p
    return None


# ---- covers / merged-into machine-readable lines; one parser for Architect coverage and parent-issue links. ----

# covers line (coverage declaration in proposal body, written at creation, not updated after): `covers: #5 #6`; multiple takes last.
_COVERS_LINE_RE = re.compile(r"^covers:((?:\s*#\d+)+)\s*$", re.MULTILINE)
# merged-into line (in comment / close reason of merged ticket): `merged-into: #7`; multiple takes last.
_MERGED_INTO_RE = re.compile(r"^merged-into:\s*#(\d+)\s*$", re.MULTILINE)


def parse_covers_line(body: str) -> list[int]:
    """Return issue numbers from the last covers line in body, or an empty list if none exists."""
    last: str | None = None
    for m in _COVERS_LINE_RE.finditer(body or ""):
        last = m.group(1)
    if last is None:
        return []
    return [int(x) for x in re.findall(r"#(\d+)", last)]


def format_covers_line(numbers: list[int]) -> str:
    """Format issue numbers as a covers machine-readable line; return an empty string for an empty list."""
    nums = [int(n) for n in numbers or []]
    return f"covers: {' '.join(f'#{n}' for n in nums)}" if nums else ""


def parse_merged_into(text: str) -> int | None:
    """Return the parent issue number from the last merged-into line in comment/close reason text, or None if absent."""
    last: int | None = None
    for m in _MERGED_INTO_RE.finditer(text or ""):
        last = int(m.group(1))
    return last


def format_merged_into(number: int) -> str:
    """Format a parent issue number as a merged-into machine-readable line."""
    return f"merged-into: #{int(number)}"


@dataclass(frozen=True)
class Field:
    """Declare a canonical wire key, an independent English display label, and validation rules.

    Tool schemas and parsers use key; label is presentation only.
    """

    key: str
    label: str
    section: str
    required: bool = True


# Per-kind field declarations, in render order. Spec-0027/T1 retains only normalized output fields populated by triage/RFC
# agents after investigation. User reports remain free text: users do not fill templates, so no USER section is declared.
# All fields belong to TRIAGE. The section argument remains only for validate/render backward compatibility.
SCHEMAS: dict[str, tuple[Field, ...]] = {
    "bug": (
        Field("root_cause", "Root cause", TRIAGE),
        Field("boundary", "Boundary", TRIAGE),
        Field("acceptance", "Acceptance criteria", TRIAGE),
    ),
    "feature": (
        Field("boundary", "Boundary", TRIAGE),
        Field("deliverable", "Deliverable", TRIAGE),
        Field("acceptance", "Acceptance criteria", TRIAGE),
    ),
    # chore/document: Streamline startup fields (rare in harness evolution scenarios, placeholder for now, extensible).
    "chore": (
        Field("boundary", "Boundary", TRIAGE, required=False),
        Field("acceptance", "Acceptance criteria", TRIAGE),
    ),
    "document": (Field("acceptance", "Acceptance criteria", TRIAGE, required=False),),
    # RFC: Structural comprehensive proposal (produced by architect agent), fields independent and populated by agent.
    "rfc": (
        Field("problem", "Problem", TRIAGE),
        Field("root_cause", "Root cause", TRIAGE),
        Field("related", "Related issues", TRIAGE),
        Field("direction", "Direction", TRIAGE),
        Field("acceptance", "Acceptance criteria", TRIAGE),
    ),
}

# kind values producible on user sim side (RFC produced by architect agent, not by user).
USER_KINDS = ("bug", "feature", "chore", "document")


def kinds() -> tuple[str, ...]:
    """All declared kinds."""
    return tuple(SCHEMAS)


def fields_of(*, kind: str, section: str | None = None) -> tuple[Field, ...]:
    """Get fields for a given kind (section limits to a specific area, None gets all, preserving declaration order); returns empty for unknown kind."""
    schema = SCHEMAS.get(kind)
    if schema is None:
        return ()
    if section is None:
        return schema
    return tuple(f for f in schema if f.section == section)


def output_contract_schema() -> dict:
    """Spec-0025: JSON Schema output by triage agent—constrains decoding via response_format=json_schema, making
    **this schema the single source of truth for agent output contracts** (no more manual copying in system prompts + patching parse boundaries).

    Enforcement: top-level keys restricted to issue/disposition/kind/priority/fields/of/reason (additionalProperties=false,
    preventing custom fields like triage_decision/flat root_cause/summary); disposition ∈ four values, kind ∈ USER_KINDS,
    priority ∈ P0-P3 (enum constraint, cannot emit "high"); keys in fields = union of TRIAGE fields across all kinds.
    Per-kind required fields and validity still validated by driver's validate pass (json_schema only locks structure, not kind-conditional requirements).
    """
    triage_keys: list[str] = []
    for k in USER_KINDS:
        for f in fields_of(kind=k, section=TRIAGE):
            if f.key not in triage_keys:
                triage_keys.append(f.key)
    item = {
        "type": "object",
        "properties": {
            "issue": {"type": "integer"},
            "disposition": {
                "type": "string",
                "enum": ["accept", "duplicate", "reject", "needs_info"],
            },
            "kind": {"type": "string", "enum": list(USER_KINDS)},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "fields": {
                "type": "object",
                "properties": {key: {"type": "string"} for key in triage_keys},
                "additionalProperties": False,
            },
            "of": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["issue", "disposition"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"dispositions": {"type": "array", "items": item}},
        "required": ["dispositions"],
        "additionalProperties": False,
    }


def validate(*, kind: str, fields: dict, section: str | None = None) -> list[str]:
    """Validate canonical machine keys, string values, and required fields for a kind.

    section restricts validation to one section; None checks all sections. Separate validation lets
    T2 validate user fields with validate(section='user') and T3 validate triage fields with
    validate(section='triage').
    """
    if kind not in SCHEMAS:
        return [f"Unknown issue kind: {kind!r} (must be one of {tuple(SCHEMAS)})"]
    if not isinstance(fields, dict):
        return ["Fields must be an object keyed by canonical machine names"]
    errors: list[str] = []
    allowed = {f.key for f in SCHEMAS[kind]}
    for key, value in fields.items():
        if key not in allowed:
            errors.append(f"Unknown field {key!r} for kind {kind!r}")
        elif not isinstance(value, str):
            errors.append(f"Field {key!r} must be a string")
    for f in SCHEMAS[kind]:
        if section is not None and f.section != section:
            continue
        if not f.required:
            continue
        val = fields.get(f.key)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"Missing required field {f.key} ({f.label}, section {f.section})")
    return errors


# Rendering placeholder for unfilled fields (T2 creates issue with empty triage section → placeholder; triage fills it later and render overwrites).
_PLACEHOLDER = "_(to be filled)_"


def render(*, kind: str, fields: dict, section: str | None = None) -> str:
    """Render `### <label>\\n\\n<value>` sectioned markdown per schema declaration order (single layout).

    section limits rendering to a specific area: T2 body = render(section='user'); T3 triage supplement = render(section='triage').
    Missing fields render as placeholders (no error—leave blank for triage when user data is rough). Unknown kind raises ValueError.
    """
    schema = SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"Unknown issue kind: {kind!r} (must be one of {tuple(SCHEMAS)})")
    parts: list[str] = []
    for f in schema:
        if section is not None and f.section != section:
            continue
        val = fields.get(f.key)
        text = str(val).strip() if val is not None and str(val).strip() else _PLACEHOLDER
        parts.append(f"### {f.label}\n\n{text}")
    return "\n\n".join(parts)
