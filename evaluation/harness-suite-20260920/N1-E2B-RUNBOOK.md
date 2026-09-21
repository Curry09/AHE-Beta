# N=1 E2B evolution run

This is the frozen pilot for `O03` (`pvlib__pvlib-python-1478`). It runs the
existing baseline `harness-v0-cade14d`, one simulated user (`sr-15-swyx`), and
the existing user → triage → designer → OpenAgents developer loop for five
rounds. User, harness, designer, and developer execute in the same E2B
sandbox; the experiment gets one private Gitea repository on the VPS.

The experiment is not started by a dry-run. First create an ignored Gitea env
file (never commit it):

```text
GITEA_URL=http://38.47.121.235:3000
GITEA_USER=hseadmin
GITEA_TOKEN=<token from /root/auto-designer-gitea.credentials on the VPS>
```

Use HTTPS for a formal run. The current VPS smoke deployment is HTTP, so an
explicit opt-in is required:

```bash
chmod 600 /path/to/gitea.env
python evaluation/harness-suite-20260920/run_n1_e2b.py --dry-run
ALLOW_INSECURE_GITEA=1 bash evaluation/harness-suite-20260920/start_n1_e2b.sh \
  --gitea-env /path/to/gitea.env
```

The launcher reads `.e2b` and `.boyue` from the workspace. It accepts the
historical `.e2b` spelling `API_KET` as well as `API_KEY`; no key is printed.
On success it prints a `run_id`, E2B sandbox ID, and the local state file under
`evaluation/harness-suite-20260920/runs/`.

To continue an interrupted run, use the recorded run ID. Resume checks the
config hash, reconnects the original sandbox, reuses the same recovery
identity and Gitea repository, and refuses to create a replacement sandbox:

```bash
ALLOW_INSECURE_GITEA=1 bash evaluation/harness-suite-20260920/resume_n1_e2b.sh \
  20260922T000000Z-a1b2c3 --gitea-env /path/to/gitea.env
```

The controller does not run a second command after `/opt/hse-run/exit_code`
exists. Remote artifacts are written below `/opt/hse-run`; the local state
points to the sandbox and run identity. The N=1 config is
`configs/n1-e2b-20260922.json`; it pins O03's revision, persona, v0 archive
hash, five rounds, `official_agent_timeout=1800`, and `outer_timeout=2400`.
Official SWE-bench grading is a separate fresh-container step after the
evolution run; this E2B launcher sets objective evaluation to `0` so a nested
Docker grader cannot be mistaken for a valid score.
