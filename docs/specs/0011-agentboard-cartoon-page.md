---
number: "0011"
title: "AgentBoard: A Cartoon-Style Active Agent Page"
issue: 19
slug: agentboard-cartoon-page
summary: "This group adds an independent **AgentBoard** page to the observation dashboard frontend: it displays currently active agents in real time in cartoon form (emoji avatars + CSS animations), shows their identities, and supports clicking, replacing the plain collapsible panel `AgentsPanel` previously embedded at the top of every page. The data source continues to use the existing `/api/agents` (a read-only projection of `data/live/agents.json`, polled every 2 seconds), with **zero backend changes and zero new dependencies**—the cartoon presentation is implemented with emoji + CSS keyframes, consistent with Occam’s razor."
tasks:
  - id: T1
    title: "AgentBoard cartoon page + cards + shared utilities, remove the old panel"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0007/T4
        type: note
    parallel: false
    files:
      - frontend/src/pages/AgentBoard.tsx
      - frontend/src/components/AgentCard.tsx
      - frontend/src/lib/agentHealth.ts
      - frontend/src/lib/avatar.ts
      - frontend/src/main.tsx
      - frontend/src/index.css
      - frontend/src/components/AgentsPanel.tsx
    scope: "Add an independent /agentboard route page and navigation entry; represent agents with emoji avatars + CSS animations; both types of cards are clickable. Remove the persistent AgentsPanel from Shell and delete that component. Zero new dependencies, zero backend changes. Do not change the agents.json structure, add session_id, or touch the benchmark."
    acceptance: "npm run build passes with no type errors; the AgentBoard entry appears in navigation and the old top panel no longer appears on any page; given an agents.json containing running/completed users + a developer, the page displays emoji avatars, identities, status animations, and refreshes every 2 seconds; clicking a running user card navigates to its latest session details, while clicking a developer card expands detail in place; pytest remains fully green (no backend changes)."
---

# 0011 · AgentBoard: A cartoon-style page for active agents

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level rust-RFC overview in 9 sections. -->

## Summary

This group adds a standalone **AgentBoard** page to the observability dashboard frontend: it displays
currently active agents in real time in cartoon form (emoji avatars + CSS animations), shows their identities, and supports clicking, replacing the plain collapsible panel `AgentsPanel` previously embedded at the top of every page.
The data source remains the existing `/api/agents` (a read-only projection of `data/live/agents.json`, polled every 2 seconds), with **zero backend changes and
zero new dependencies**—the cartoon presentation uses emoji + CSS keyframes, following the principle of Occam's razor.

Data-flow backbone:

```
run.py loop ─update_agent→ data/live/agents.json
        │  (User agent: agent_id=user-{identity}, label=identity, turns[]
        │   Developer agent: agent_id=dev-N, label=dev#N, detail)
        ▼
  /api/agents (existing read-only endpoint) ──poll every 2s──► useLiveData(getAgents)
        ▼
  AgentBoard page (T1): card wall split into two groups by role
        ├─ AgentCard: emoji avatar(hash(label)) + role styling + identity + status + health animation
        └─ Click: user card → match persona_identity===label to the latest entry in /api/sessions → navigate to /sessions/:id
                  developer card → expand status/detail in place (no session to navigate to; reflects the available data)
```

A single Task delivers this (a frontend page + extracted shared utilities + removal of the old panel from Shell): **T1** implements
the `/agentboard` route page, `AgentCard` cartoon cards, `lib/agentHealth` (health assessment + fmtDur, extracted from the old
`AgentsPanel` for reuse), and `lib/avatar` (deterministic emoji avatars), removes the persistent
`AgentsPanel` from `main.tsx`, deletes `AgentsPanel.tsx`, and adds an AgentBoard entry to navigation.

Held-out discipline is unaffected: this group performs read-only observation, does not touch benchmarks, does not change training signals, and does not write any authoritative state.

## Motivation

The old AgentsPanel crams agent activity into a plain collapsible list at the top of every page, with low information density, unclear identities, and persistent use of top-of-page space.
The user wants a standalone page that “displays active agents in cartoon form, shows their identities, and supports clicking”: cartoon avatars make “who is running, in what role, and whether they are healthy”
clear at a glance, while a standalone page decouples agent observation from individual application pages. Choosing emoji + CSS instead of introducing an avatar generation library (such as DiceBear) follows
CLAUDE.md's principle of Occam's razor—a minimal viable cartoon presentation with zero new dependencies; the data source is already available, so no backend or registry schema changes are needed.

## Guide-level explanation

Add a standalone AgentBoard page (/agentboard) to the observability dashboard frontend to display currently active agents in cartoon form in real time and support clicking,
replacing the plain collapsible AgentsPanel previously embedded at the top of every page. The data source remains the existing read-only endpoint /api/agents (a projection of data/live/agents.json,
polled every 2s), with zero backend changes and zero new dependencies. Deliver four frontend files + changes to two existing files + one deletion: ① pages/AgentBoard.tsx
—poll getAgents, split agents into user/developer groups by role, render a card wall for each, and show an empty-state message; ② components/AgentCard.tsx—a cartoon card for a single
agent: emoji avatar + role decoration + identity (Chinese role name + label) + one line of status + CSS animations driven by health state; clicking
dispatches by role (user cards navigate to a session, developer cards expand in place); ③ lib/agentHealth.ts—health assessment extracted from the old AgentsPanel,
health(a, now) (error > stalled > running > completed), plus fmtDur and STALE_MS, for reuse and deduplication; ④ lib/avatar.ts—deterministic emoji
avatars (hash(label) determines the face + role determines the badge). Also remove the persistent AgentsPanel from Shell in main.tsx, add the AgentBoard route and
navigation entry, and delete components/AgentsPanel.tsx (referenced only here).

## Reference-level explanation

- Directories: pages/AgentBoard.tsx (page), components/AgentCard.tsx (card), lib/agentHealth.ts and lib/avatar.ts
  (pure-function utilities). Separate responsibilities into three layers: page/card/utilities (principle 2: decoupling; principle 3: structure).
- Data contract (reuse Agent from types.ts without changes): agent_id · role("user"|"developer") · label · running · status ·
  turns[] · detail · started_at · updated_at. A user agent's label === persona_identity from the backend _summarize
  (in run.py, mp.identity=sp.persona_id, label=identity; all three share the same source), which provides the association used for navigation when a user card is clicked.
- AgentBoard: useLiveData(getAgents, 2000) retrieves live data → now=Date.now() → split into users/devs groups by role →
  render each as a flex-wrap card wall. On error, show “Load failed: {error}”; when both groups are empty, show “No active agents (they appear in real time after running the closed loop)”.
- agentHealth.ts: extract the old AgentsPanel's health(a, now) (error > stalled > running > completed, STALE_MS=330_000) and fmtDur
  unchanged as shared pure functions; cards and any future consumers share one assessment implementation to prevent logic drift. Fall back to updated_at when started_at is missing.
- avatar.ts: a simple string hash, hash(label), maps to one of a fixed set of emoji faces (the same agent always has the same face); role determines the badge
  (🙋 overlaid for users, 🛠️ for developers). Pure functions, stateless, and unit-testable.
- AgentCard: receives {agent, now}, computes health → renders avatar + Chinese role name (User Agent/Developer Agent) + label +
  one line of status; health states map to animation classes: ok floats vertically with a green halo / warn sways slowly in yellow / err shakes in red / idle dims with 😴
  and no animation (CSS keyframes go in index.css, reusing the existing ok/warn/err/idle palette). Clicking uses a controlled state toggle to expand inline,
  providing consistent interaction for both card types (without <details>).
- Click dispatch: user card → call the existing getSessions() → filter persona_identity===label → sort by created_at descending and take the first →
  navigate('/sessions/:session_id'); if there is no match (this persona has no persisted session yet), fall back to expanding in place, without errors or navigation to a blank page.
  Developer card → no session to navigate to (the actual data situation), so clicking expands status/detail in place.
- main.tsx: remove <AgentsPanel /> from Shell; add <Route path="/agentboard" element={<AgentBoard/>} /> to Routes;
  add <Link to="/agentboard">AgentBoard</Link> to nav (after “Overview”). Delete components/AgentsPanel.tsx.

**Interfaces**

Route: GET /agentboard (frontend route).
Components: <AgentBoard /> (no props, page-level); <AgentCard agent={Agent} now={number} />.
Utilities (lib):
- agentHealth.ts: health(a: Agent, now: number) -> {cls, text}; fmtDur(ms: number) -> string; STALE_MS.
- avatar.ts: avatarFor(label: string, role: string) -> {face: string, badge: string}.
Data: reuse the existing getAgents()/getSessions() in api.ts and hooks/useLiveData; backend contracts /api/agents and /api/sessions remain unchanged.

**Tests**

The frontend is a lightweight SPA with no existing unit test framework; acceptance is based on a build + manual smoke tests (see acceptance):
- npm run build (tsc --noEmit && vite build) passes with no type errors.
- An AgentBoard entry appears in navigation; the old top-of-page AgentsPanel no longer appears on any page (overview/sessions/dashboard).
- Create data/live/agents.json (with several running user agents, completed user agents, and developer agents) → start the backend + frontend → visually verify cartoon avatars,
  identities, the four types of status animations, and 2s refresh.
- Click a running user card → navigate to that persona's latest session details; click a developer card → expand detail in place; click a user card with no matching session → expand in place without errors.
The backend is unchanged, so pytest (including backend/tests/web/test_api.py, which covers /api/agents) should remain fully green, serving only as a regression check.

**Files (single-writer ownership)**

  - `frontend/src/pages/AgentBoard.tsx`
  - `frontend/src/components/AgentCard.tsx`
  - `frontend/src/lib/agentHealth.ts`
  - `frontend/src/lib/avatar.ts`
  - `frontend/src/main.tsx`
  - `frontend/src/index.css`
  - `frontend/src/components/AgentsPanel.tsx`

Dependency DAG: all Tasks are independent, with no dependencies.

## Drawbacks

<!-- TODO -->

## Rationale and alternatives

- emoji + CSS vs introducing an avatar generation library (DiceBear/boring-avatars): choose the former. It achieves a cartoon presentation with zero new dependencies (Occam's razor), at the cost of
  limited avatar variety (a fixed set of faces), which is sufficient for an internal observability dashboard.
- Standalone page vs retaining the persistent top panel: choose a standalone page and remove the old panel. This avoids displaying the same agents twice and taking up space at the top of every page; the cost is
  switching to the AgentBoard page to view agent activity (acceptable, since this is an observation action).
- Matching persona_identity on the frontend when a user card is clicked vs adding session_id to agents.json on the backend: choose frontend matching. Zero backend changes,
  and label and persona_identity already share the same source; the cost is one additional /api/sessions fetch and matching step (acceptable given the small data volume).
- Asymmetry because developer cards have no session to navigate to: accept “expand detail in place” instead of disabling clicks. Both card types are clickable with consistent interaction, matching the user's “both should be clickable”.

## Prior art

Existing implementations: frontend/src/components/AgentsPanel.tsx (source of the original health/fmtDur/STALE_MS logic, deleted after extraction in this Task),
frontend/src/types.ts (Agent DTO contract), frontend/src/hooks/useLiveData.ts, frontend/src/api.ts
(getAgents/getSessions), frontend/src/pages/SessionDetail.tsx (click navigation destination), frontend/src/index.css
(existing ok/warn/err/idle palette and dot/badge styles). Backend: backend/ahe_beta/web/api.py (/api/agents,
/api/sessions), loop/live.py (writes agents.json), run.py (agent_id/label conventions).

## Unresolved questions

- Avatar face set size: a fixed set of emoji faces is sufficient for the initial version; whether a larger face library or coloring by domain is needed as personas increase will be decided after observation.
- Session matching on user-card clicks uses the “latest entry”: when the same persona has multiple sessions, navigation goes only to the most recent one; selecting a specific session would be a future enhancement.
- If agents.json gains a session_id field in the future, user cards can navigate directly and skip /api/sessions matching; this group does not make that backend change.

## Future possibilities

<!-- TODO -->

