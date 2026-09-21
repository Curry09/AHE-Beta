# Scaling E2B launcher contract

Scope: preparation and parallel launch/resume of the latest mixed N=1/4/8/16/32
plan. This change does not authorize starting a model experiment. It does not
replace the historical persona loop, Owner, or developer delivery protocol.

## Roles and capacity

Model/API budgets come from the mixed-scaling role configuration; effective values, hashes,
task assignments and role counts are resolved into each run's config snapshot.
Triage uses the current shared DESIGNER model configuration; inconsistent values
must fail validation. Owner is mechanical and PM is off. Designer grouping is
enabled, at most six proposals per batch, one Designer worker.

Each N is an independent terminal process; there is deliberately no
all-N supervisor. The five terminals are started with the five `start_scaling_n*.sh`
wrappers (and resumed with the matching `resume_scaling_n*.sh` wrapper). Each has its own
Gitea repository, E2B runtime, run ID, artifact directory and recovery identity.
N counts user sessions per round, not worker processes. The role roster is
explicitly different per N and is passed as `N_USERS`, `N_TRIAGERS`,
`N_DESIGNERS`, `N_DIVERGENTS` (PM), `N_OWNERS`, and `N_DEVELOPERS`.

| N | user | triage | designer | PM/divergent | developer | owner |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 1 | 1 | 0 | 1 | 0 |
| 4 | 4 | 2 | 1 | 0 | 2 | 0 |
| 8 | 8 | 4 | 1 | 1 | 4 | 0 |
| 16 | 16 | 8 | 1 | 1 | 4 | 0 |
| 32 | 32 | 16 | 2 | 2 | 8 | 0 |

The N=16 triage/developer anchor follows the historical mixed16 roster
(triage=8, developer=4); the remaining profiles are explicit scaling policy,
not an accidental global cap. Five rounds means four design/delivery transitions
and a final user-only round.

Use one terminal per N, for example:

```bash
bash evaluation/harness-suite-20260920/start_scaling_n1_e2b.sh --executor '...'
bash evaluation/harness-suite-20260920/start_scaling_n4_e2b.sh --executor '...'
bash evaluation/harness-suite-20260920/start_scaling_n8_e2b.sh --executor '...'
bash evaluation/harness-suite-20260920/start_scaling_n16_e2b.sh --executor '...'
bash evaluation/harness-suite-20260920/start_scaling_n32_e2b.sh --executor '...'
```

Each command validates and starts only its own N. A failed terminal cannot
terminate sibling terminals. `--executor` is the prepared per-N runtime entry
point; it is intentionally required until the corresponding bundle receipt is
materialized.

## Lifecycle

Read-only dry-run resolves the configurations and reports missing runtime bundles.
Start validates **all** selected experiments before creating any remote resource.
It then uses bounded concurrent workers. A partial infrastructure failure records
each experiment separately; successful siblings are not destroyed or relaunched.

A local flock excludes duplicate controllers for a run. A second flock inside
E2B excludes duplicate runtime processes, including reconnect after controller
failure. Save intent before side effects and save sandbox identity before upload
or process start. Resume only the recorded sandbox and Gitea repository; never
reset main, create a replacement sandbox, or replay a completed run. A missing
sandbox requires explicit recovery work, not an automatic fresh measurement.

The E2B runtime supervisor holds the remote lock, records running/failed/completed
status atomically, and invokes the bundle's existing closed-loop entrypoint with
fresh/resume identity envs. Model execution has no SDK's accidental 120-second
whole-experiment timeout. E2B lifetime is separate from per-task deadlines and
must cover the experiment, or an operator must pause/renew before expiry.

## Task runtime readiness

There is no validated general mixed-task E2B bundle in the repository yet. The
old N1 launcher also has unvalidated runtime/resume seams. Neither a wrapper nor
a JSON field is evidence that the full loop runs. The new launcher therefore
requires a trusted preparation receipt under prepared/scaling-e2b-20260922/nN/:

- immutable E2B template ID and build ID;
- bundle.tar.gz with bin/run (the real closed-loop runtime, not a placeholder);
- exact effective config SHA and archive SHA;
- per-task revision, prompt SHA, environment SHA, grader SHA, and provenance
  affirming it is not held-out test material;
- per-task inner/outer timeout, mode, persona and task ID matching the config;
- a passed full-loop canary receipt with evidence SHA.

The bundle must implement both historical simulated-user and true one-message
direct modes; direct creates no user LLM/heartbeat. It must retain sessions,
traces, role runs, usage, phase checkpoints, and sealed harness SHAs, and recover
using the existing recovery ledger. Grading stays separate from training signals.
Hidden graders/solutions cannot be packaged into a user-readable task workspace.
The runtime writes exportable non-secret files to /opt/hse-run/artifacts; secrets
and raw working repos are not included in automated collection.

The 600-second grace is only for persistence/teardown after a trial's agent
deadline; environment setup and grader execution have their own budgets. This
launcher does not implement task deadlines by setting unused environment vars:
the prepared runtime must demonstrate actual deadline enforcement in its canary.

Missing receipt/task material/template/canary causes a nonzero preflight result
before credentials, network access or cost. No flag skips this gate.
