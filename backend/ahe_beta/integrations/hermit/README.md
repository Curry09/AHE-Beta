# Hermit integration

This optional module exposes native AHE user sessions and feedback rounds to an
external rollout host. It does not import Hermit or manage Harbor containers.
The host supplies `simulate(task, agent, workspace, params)` with a conversation,
a workspace transport and a frozen task/persona/version assignment.

- `session.py` runs the existing direct or simulated-user lifecycle, collects frozen
  outputs, performs terminal review and retains the complete native Session.
- `conversation.py` implements the native heartbeat/message contract over a mailbox.
- `workspace.py` implements native workspace and artifact operations over host calls.
  Private service measurements are saved separately on the host; they are never
  included in the simulated user's workspace or terminal-review snapshot.
- `export.py` converts verified container task recipes and complete cohort plans to
  Harbor task packages. Source images, hashes, budgets and services remain explicit.
- `feedback.py` imports complete rounds and reuses native report publication, demand
  roles and the delivery gate. Infrastructure failures must not become training scores.

Run `python -m ahe_beta.integrations.hermit.export --help` with `PYTHONPATH=backend`
from the repository root. Host setup, configuration and smoke recipes are documented
in the companion Hermit branch's `examples/ahe_beta/README.md`.

The evolving product in this integration is a Codex adapter, not the builtin NexAU
Harness. Optional artifact guidance is scoped to each demand invocation. Existing
tracker-backed AHE experiments retain their original report-publication behavior.
