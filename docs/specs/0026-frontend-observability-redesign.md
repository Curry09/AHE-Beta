---
number: "0026"
title: "Complete observability dashboard frontend redesign: switchable light/dark themes + visible triager + persona display + design tokens"
issue: 0
slug: frontend-observability-redesign
summary: "Completely redesign the observability dashboard frontend from \"pure black background + white text, four columns, SR-001 identifier only\" into an interface with a design system: ① Introduce a design token layer (colors/spacing/type scale/border radii/shadows/stacking levels) + switchable light/dark themes (follow the system, persist in localStorage); ② Add the triager room to the dashboard—all five roles in the a→d1(triage)→d2(architect)→b loop are visible, with consistent accent colors for each role; ③ User cards display persona (identity + level/domain/goal), not just SR-001; standardize issue/commit card layouts on top of the 0025 badges; ④ Refresh the detail panel information architecture + persona block; ⑤ Visualize user experience/backlog curves (consume the existing /api/overview); ⑥ Responsive layout (no horizontal page scrolling, wide content scrolls internally) + contrast/focus states for both themes. Only minor backend changes: add triager ordering to live, and include a persona summary in user agent activity payloads. Read-only observability only; do not change closed-loop semantics or introduce benchmarks."
tasks:
  - id: T1
    title: "Backend: add triager ordering to live + include a persona summary in user agent activity payloads"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/loop/live.py
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/loop/test_live.py
    scope: "Add triager to _ROLE_ORDER in live.py (after user and before architect); add optional meta(dict) to update_agent—read-only passthrough for frontend display, excluded from all decisions; pass the persona summary (identity/level/domain/goal) into meta in the user status callback in run.py; include triager in read_agents ordering. Only complete the observability data; do not change the closed loop."
    acceptance: "In read_agents, triager sorts between user and architect; user agent slots carry persona summary meta; existing calls without meta fall back to None without crashing; test_live covers ordering and meta passthrough."
  - id: T2
    title: "Design token layer + light/dark themes (follow the system + persist in localStorage) + global CSS"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - frontend/src/styles.css
      - frontend/src/hooks/useTheme.ts
      - frontend/src/components/ThemeToggle.tsx
    scope: "Refactor styles.css into design tokens (CSS variables: palette bg/surface/surface-raised/border/text/text-dim/text-faint/accent + accent colors for four roles, spacing scale, type scale, border radii, shadows, stacking levels); all semantic colors use tokens, and components no longer hardcode hex values. :root defines the light theme, and :root[data-theme=dark] overrides it for the dark theme (replace pure black with a soft dark blue-gray); consolidate global responsive styles and focus states in styles.css as well (the page body never scrolls horizontally; wide content has its own overflow-x). The useTheme hook reads/writes localStorage, reads prefers-color-scheme on initial render, and sets data-theme on html; ThemeToggle component (mounted by T3's TopBar). Retain existing style class names, with coherent styling in both themes."
    acceptance: "Both light/dark themes have coherent styling (meeting contrast requirements); useTheme switches immediately and persists across refreshes; no hardcoded colors remain (key classes use tokens); no horizontal page scrolling; npm build passes."
  - id: T3
    title: "Application shell + types (AgentRole triager / Agent.meta) + TopBar (theme toggle) + overview curves"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - frontend/src/types.ts
      - frontend/src/App.tsx
      - frontend/src/components/TopBar.tsx
      - frontend/src/components/Charts.tsx
    scope: "Add triager to AgentRole and optional meta (persona summary, for T4) to Agent in types.ts; insert the \"Triage\" room into App.ROLES (order: User→Triage→Architect→Developer, aligned with the a→d1→d2→b loop) and lay out using the new tokens; mount T2's ThemeToggle in TopBar; add a Charts component (inline SVG line charts consuming feeling_trend and issue_curve[backlog definition 0025/T7] from the existing /api/overview, with colors for both themes and no horizontal overflow), placed in the overview area."
    acceptance: "The frontend includes a triage room slot; the theme toggle works; both curves are clear in light/dark themes without overflowing; build passes."
  - id: T4
    title: "Role columns + cards: triager room rendering + role accent colors + persona on user cards + standardized issue/commit cards"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/AgentColumn.tsx
      - frontend/src/components/Card.tsx
    scope: "The AgentColumn/Card role→accent color mapping includes triager (using T2 role tokens), rendering activity and archives by round in the triage room; the main line of user cards shows identity, the secondary line shows level·domain, and goal appears in a tooltip/secondary position (with older backends lacking meta, fall back to showing identity only without crashing); standardize issue/commit card layouts on top of the 0025/T8 badges (alignment, whitespace, truncation)."
    acceptance: "triager activity/archives are visible in the triage room; user cards display the three persona elements instead of only SR-001, with graceful fallback and no crash when meta is missing; role accent colors form a coherent set; issue/commit card layouts are tidy; build passes."
  - id: T5
    title: "Refresh detail panel information architecture (agent/session/issue/commit + sidebar) + persona block"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - frontend/src/components/detail/AgentRunDetail.tsx
      - frontend/src/components/detail/SessionDetail.tsx
      - frontend/src/components/detail/IssueDetail.tsx
      - frontend/src/components/detail/CommitDetail.tsx
      - frontend/src/components/SidePanel.tsx
    scope: "Refresh the layouts of the four detail views + sidebar using the new tokens (sections/hierarchy/whitespace/monospace blocks), add a persona information block to SessionDetail (identity/level/domain/goal + experience score and reasons), and improve readability of the process flow/comment timeline; add no backend endpoints, only rearrange existing data."
    acceptance: "The four detail types + sidebar have a clear information hierarchy and are readable in both themes; SessionDetail has a persona block; build passes."
---

# 0026 · Complete observability dashboard frontend redesign: switchable light/dark themes + visible triager + persona display + design tokens

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level, nine-section rust-RFC overview. -->

## Summary

Redesign the read-only observability dashboard frontend from a “pure black background + white text, four columns, agents showing only identity labels such as SR-001” into an interface with a design system and more accessible information. Four areas: **design tokens + switchable light/dark themes**, **add the missing triager room so all five roles in the closed loop are visible**, **display personas on user cards (not just identifiers)**, and **finish detail/chart visualizations and responsiveness**. Backend changes are limited to small additions to observability data (include triager in live ordering and persona summaries in user agent activity payloads), without changing any closed-loop semantics or introducing benchmarks.

## Motivation

There are currently three user experience/usability issues, all within the read-only dashboard layer:

1. **A pure black background + white text is too harsh**, with no hierarchy or emphasis, and is tiring to look at for extended periods; colors are hex values hardcoded per component, with no design tokens, leaving no foundation for changing themes or adding a light theme.
2. **The triage agent (triager) is completely invisible in the frontend**: the closed loop is already a→d1(triage)→d2(architect)→b, but frontend ROLES only has three rooms: user/architect/developer. `role="triager"` activities emitted by triager are filtered out directly—users cannot see what triage is doing, and therefore cannot determine whether an “issue stuck in needs-triage” means triage never ran, crashed, or produced no output (currently occurring in production).
3. **Agent cards only show identity labels (such as SR-001)**, without showing who the persona is (level/domain/goal), leaving interactions without context.

These are presentation issues in the observability interface, not closed-loop logic issues; create a separate frontend spec for the redesign, decoupled from backend evolution.

## Guide-level explanation

After the redesign, users see:

- **A theme toggle in the top bar**: switch between light / dark with one click, follow the system preference on the first visit, and persist the choice in localStorage across refreshes. Dark mode uses a soft dark blue-gray instead of pure black, with layered surfaces and subtle borders; light mode uses clean white/light-gray backgrounds + dark text.
- **Five dashboard areas**: four role columns, user → triage → architect → developer, + the Issues·Main sidebar on the right, ordered to match the a→d1→d2→b closed loop. Each role has a consistent accent color (color dots, card highlights, column headers). The triage room shows in real time which issues triager is triaging and the results, with archives by round for later review.
- **User cards display personas**: the primary line shows identity, the secondary line shows “level·domain,” and the goal appears in a tooltip/secondary position; opening details reveals a full persona block (including the experience score and reasons).
- **Issue/commit cards** retain the kind/priority/round/coverage badges from 0025/T8, with neater layouts and more comfortable spacing.
- **Two additional charts in the top overview**: user experience over time + actionable backlog over time (using the 0025/T7 definition), consuming the existing `/api/overview` directly.
- **Responsive** throughout: narrow screens do not cause page overflow; wide content (tables/charts/long code) scrolls horizontally within its own container, and the page body never scrolls horizontally.

For backend consumers: the only additions are a read-only field allowing “user agent activity to carry a persona summary” and a sorting position for triager in the activity list; everything else remains unchanged.

## Reference-level explanation

**Backend (T1, minimal changes)**: add `triager` to `_ROLE_ORDER` in `loop/live.py` (between user and architect); add an optional `meta: dict | None` to `update_agent` (read-only passthrough, defaults to None, existing calls unaffected), stored in the agent slot; the user status callback in `run.py` puts the persona summary (identity/level/domain/goal) into meta. These are purely observability fields, used in no decisions and touching neither tracker nor git.

**Frontend design system (T2, foundation)**: refactor `styles.css` into CSS variable tokens—palette (bg/surface/surface-raised/border/text/text-dim/text-faint/accent + accent colors for four roles), spacing scale, type scale, corner radii, shadows, and stacking levels. `:root` defines light mode as the baseline, and `:root[data-theme="dark"]` overrides it for dark mode; the `useTheme` hook reads/writes localStorage, reads `prefers-color-scheme` on initial render, and sets `data-theme` on `<html>`; mount `ThemeToggle` in TopBar. Components no longer hardcode colors; all colors use tokens.

**Frontend structure and information (T3/T4/T5)**:
- T3 (shell/types/overview): add `triager` to `AgentRole` and optional `meta` to `Agent`; insert “Triage” in `App.ROLES` and lay it out using tokens; mount `ThemeToggle` in `TopBar`; add `Charts` (inline SVG, consuming `/api/overview`).
- T4 (columns and cards): include triager in the role→accent-color mapping in `AgentColumn`/`Card` and render the triage room; render the three persona elements on user cards (fall back to identity only when meta is missing); standardize issue/commit card layouts.
- T5 (details/sidebar): rearrange the four detail views + `SidePanel` using the new tokens; add a persona block to `SessionDetail`.

**DAG**: T1 and T2 have no dependencies (can start in parallel); T3←T2; T4←T1+T3; T5←T2+T3. **Files belong to a single task, with no overlap**: T1=live/run/test_live, T2=styles.css/useTheme/ThemeToggle, T3=types/App/TopBar/Charts, T4=AgentColumn/Card, T5=detail/*+SidePanel. Cross-group overlap (types.ts with 0020/0025) is an informational warning only and does not block work.

**Non-goal**: do not change closed-loop a/d/b/c semantics; do not add backend observability endpoints (charts use the existing /api/overview, details use the existing /api/*); do not introduce benchmarks; do not implement authentication/multi-user support; do not change the issue schema or triage/architect/dev logic (that belongs to 0025).

## Drawbacks

- The frontend change has a large scope in one pass (full token conversion of styles.css + multiple components), with higher review/regression costs than a local change; manage risk by splitting it into 6 tasks, each requiring `npm build` to pass + graceful mock fallback without crashes for acceptance.
- Dual themes require maintaining two sets of color values, and future components must support both themes (tokens keep the cost manageable).
- The backend gains an `meta` field, slightly expanding the observability surface (but it is read-only and defaults to None, so risk is low).

## Rationale and alternatives

- **Why switchable light/dark themes (rather than only a refined dark theme)**: the user explicitly requested two switchable themes; tokens keep the maintenance cost manageable and provide flexibility for different environments (projection/daytime).
- **Why pass persona summaries through backend meta (rather than associating sessions in the frontend)**: live cards are temporary slots for running agents, and no persisted session_id exists yet, so the frontend cannot associate them; carrying a lightweight summary in backend activity callbacks is the most direct approach, and is read-only and decoupled.
- **Why a separate spec (rather than merging into 0025)**: 0025 covers the issue triage funnel (backend closed-loop semantics), while this redesign covers observability interface presentation; the concerns differ and the files largely do not overlap, so separation enables independent review and rollback.
- **Alternative**: a small, “focused” change that only adds the triager room + fixes colors—the user has already confirmed “complete redesign + switchable light/dark themes,” so the full scope is selected.

## Prior art

- Existing 0011 (agentboard cartoon page) established the four-column dashboard and card pattern; this spec adds a design system and theming on top.
- 0025/T8 already added kind/priority/coverage badges and grouping to issue/commit cards; this spec reuses them and standardizes their appearance.
- Theme tokens + `data-theme` switching and following `prefers-color-scheme` are common frontend practices (light themes in Linear/Notion, dark themes in various dashboards).

## Unresolved questions

- Exact role accent colors await finalization in T2/T3 (must meet contrast requirements in both light/dark themes).
- The chart component format (mini sparklines vs line charts with axes) will be determined in T6 based on overview space; initially prioritize “clear, no overflow, dual themes.”
- Which persona information to show on cards (level·domain or domain·goal on the secondary line) will be determined in T4 based on card width.

## Future possibilities

- Themes can expand to high-contrast/eye-comfort modes and more; the cost is low once the token layer is ready.
- Charts can add interactions (hover values, annotations by round for RFC implementation points).
- Add a round timeline overview and an issue funnel (needs-triage→triaged→RFC→closed) conversion view to better align with the observability metrics in CLAUDE.md.
