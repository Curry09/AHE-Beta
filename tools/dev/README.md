# Maintenance tools / 开发维护工具

These tools inspect or replay existing evidence; they are not experiment launchers.
Use `backend/scripts/experiment.py` for new local/E2B experiments. Run the commands
below from the repository root with `PYTHONPATH=backend .venv/bin/python -m ...`.
Every listed module supports `--help` without model/provider calls.

这些工具用于探针、证据回放、审计和交付验证，不注册新的实验配置格式。
`offline` in a filename means a local fake tracker, **not** a model-free run.
The online tools consume only `--secrets-file` or injected environment. Gitea tools
also require `--run-dir` to select a prepared v2 run; only its `manifest.json`,
`resources.json` and run-local `secrets/provider.env` are consulted. External
credential paths recorded in historical manifests are never automatically read.
Models come from explicit `USER_LLM_*`, `HARNESS_LLM_*`, `DEMAND_LLM_*` values,
optionally a supplied common `LLM_*` profile for a standalone probe, or the selected
run's model mappings. Selected run roles never fall back to unrelated host role/common
credentials when a mapped field is missing. Harness-to-`LLM_*` mapping is scoped to
spawning its child process and does not change another role's profile.
No tool selects a developer's private model or shared Docker network.

凭证显式指定；远端操作会创建或修改仓库/Issue，执行前查看对应工具的参数。
回放不会重新执行原始用户对话，产物也不能当作新一轮用户评估。

## Probes

For each row, its safe help command is `PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.<module> --help`.

| Module | Purpose / 目的 | Inputs | Model / remote writes | Output |
| --- | --- | --- | --- | --- |
| `probe_d43_quality_fail` | Compare quality-failure strategies against scripted Harness | `--d43`, USER profile | USER model; no remote writes | stdout |
| `probe_ontrack_new_harness` | Compare expert/blind waiting with a new manual contract | USER profile, optional `--manual` | USER model; no remote writes | stdout |
| `probe_peek_decision_trace` | Inspect raw judge/intent/action after `/status` | USER profile, optional `--persona-library`/`--persona` | USER model; no remote writes | stdout |
| `probe_persona_reframe` | Check persona orthogonality and scripted state transitions | no credentials | no model/provider calls | stdout, nonzero on failure |
| `probe_persona_wait_matrix` | Compare persona cards across scripted waiting scenarios | `--personas`, `--scenarios`, optional `--persona-library`, USER profile | USER model; no remote writes | stdout and `backend/data/probe_persona_wait_matrix.json` |
| `probe_swebench_persona` | Run one real Harness/persona SWE scenario | required `--dataset`, `--harness-repo`, `--instance`; optional `--persona-library`/`--persona`; USER/HARNESS profiles | both models; Git clone/dependency setup and workspace changes | stdout, isolated workspace, `backend/data/sessions/_probe_swebench_persona` |
| `probe_timeout_to_synthesizer` | Follow scripted timeout signals through real user and synthesizer | USER/DEMAND profiles | both models; fake tracker only | stdout and printed temporary evidence directory |
| `probe_wait_progress` | Observe waiting decisions against scripted progress | USER profile | USER model; no remote writes | stdout |

The three library-based probes default to `examples/personas/library.json` and
accept an explicit `--persona-library`. Their `--check-inputs` mode validates local
files and selected persona IDs, without loading credentials or invoking a model.
For SWE, supply the dataset, Harness repo and instance even in preflight mode.

```bash
PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_persona_wait_matrix --check-inputs
PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_peek_decision_trace --check-inputs
```

Model-free smoke:

```bash
PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_persona_reframe
```

Example online diagnostic (fill a USER profile in the explicitly chosen file):

```bash
PYTHONPATH=backend .venv/bin/python -m tools.dev.probes.probe_persona_wait_matrix \
  --secrets-file /path/to/chosen.env --personas sr-01-willison --scenarios ON-TRACK
```

## Replay

For each row, its safe help command is `PYTHONPATH=backend .venv/bin/python -m tools.dev.replay.<module> --help`.

| Module | Purpose / 目的 | Inputs | Model / remote writes | Output |
| --- | --- | --- | --- | --- |
| `replay_observation_lifecycle` | Verify private evidence grants, version isolation and delivery reads | `--run-dir`, `--openagents-source`, optional images/credential file | no models; creates private Gitea test repo, Docker containers | retained temporary evidence, stdout; remote test repo retained |
| `replay_observation_synthesis` | Replay PM/Synthesizer against fixed evidence | `--sessions`, `--observations`, `--proposals`, `--repo`, `--output`, DEMAND profile | DEMAND model; fake tracker | output directory with traces and summary |
| `replay_owner_from_repo` | Replay historical issues numbered ≤ 14 and rerun Owner; requires original issue numbers to match contiguously | `--run-dir`, source/target repo, sessions, Harness repo, output | DEMAND model; creates target repo/issues | output directory |
| `replay_pm_synthesizer_owner_offline` | Continue a fixed triage summary locally | source summary, sessions, output, DEMAND profile | DEMAND model; fake tracker | output directory |
| `replay_role_invocations` | Diff frozen demand invocations using replacement agent definition | `--run-dir` (invocation evidence root), `--role`, `--agent-def`, optional repo/output, DEMAND profile | DEMAND model; never starts Gitea/delivery | stdout or explicit output |
| `replay_roles_from_sessions` | Copy reports and replay the demand pipeline | prepared `--run-dir`, source/target repo, sessions, output | DEMAND model; creates target repo/issues | output directory |
| `replay_roles_offline` | Replay saved sessions through four demand roles locally | sessions, output, DEMAND profile | DEMAND model; fake tracker | output directory |
| `replay_synthesizer_owner_from_repo` | Restore selected proposals then rerun Synthesize/Owner | prepared `--run-dir`, repo, issue selections, sessions, Harness repo, output | DEMAND model; updates selected remote issues | output directory |

`replay_role_invocations --run-dir` selects its existing invocation-store layout;
it does not require a v2 provider manifest. All other Gitea tools require a prepared
v2 run. The observation lifecycle's Docker delivery check gets its network/address
from that run, with explicit `--delivery-network`/`--internal-url` overrides available.

## Audit

For each row, its safe help command is `PYTHONPATH=backend .venv/bin/python -m tools.dev.audit.<module> --help`.

| Module | Purpose / 目的 | Inputs | Model / remote writes | Output |
| --- | --- | --- | --- | --- |
| `audit_sim_action_integrity` | Compare terminal actions with explicit persona trace actions | session files/directories; optional output/source/model pins | no models or remote writes; inputs stay unchanged | JSON on stdout/explicit output |
| `evaluate_role_traces` | Check trace violations and optional input-size deltas | trace JSONL, optional baseline | no models or remote writes | JSON on stdout; nonzero for violations |
| `canary_spec0048_final_check` | Check real persona final-check/rejudge/reintent behavior | USER profile, explicit optional token/wall limits | USER model; no remote writes | JSON on stdout |

Read-only evidence audit:

```bash
PYTHONPATH=backend .venv/bin/python -m tools.dev.audit.audit_sim_action_integrity \
  /path/to/collected/sessions --output /path/to/separate-audit.json
```

## Delivery validation

For each row, its safe help command is `PYTHONPATH=backend .venv/bin/python -m tools.dev.delivery.<module> --help`.

| Module | Purpose / 目的 | Inputs | Model / remote writes | Output |
| --- | --- | --- | --- | --- |
| `prepare_openagents_from_summary` | Materialize a frozen local summary into a fresh delivery repo | prepared run, summary, Harness repo, target repo, manifest output | no models; creates repo/commits/issues | explicit manifest |
| `prepare_openagents_validation` | Copy a backlog to a fresh repo with selected deliverable issues | prepared run, source/target repo, deliver issue numbers, manifest | no models; creates repo/commits/issues | explicit manifest |
| `run_openagents_validation` | Start an isolated Docker delivery validator | prepared run, repo, config dir, **new container name**, optional network/image overrides | delivery model via OpenAgents; code/remote changes | detached container; use `docker logs <name>` |

The validator uses the run's delivery model/key mapping or standard Anthropic
variables. It does not read WIS-specific fields or a developer gateway file.
Network, image and container-accessible Gitea URL come from selected run resources;
if unavailable (such as an E2B run), supply `--network` and `--image` explicitly.
It refuses to reuse the run's delivery container. Tokens pass to Docker through
environment variable names, not command-line values. Delivery preparation and replay
Git URLs contain no credentials; URL-scoped Basic authentication passes in the child
environment, and raw Git failure diagnostics are withheld to prevent credential leaks.
