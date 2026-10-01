# Experiment configuration

English | [简体中文](CONFIGURATION.zh-CN.md)

New experiments use JSON with `schema_version: 2` and the unified entry described in [Quickstart](QUICKSTART.md). Copy either [local](../examples/experiments/synthesizer-n1-local.json) or [E2B](../examples/experiments/synthesizer-n1-e2b.json) example. Unknown fields are rejected; old evaluation schemas are not automatically converted.

## Files you supply

| Input | Format | Example |
| --- | --- | --- |
| Experiment | v2 JSON: backend, Harness, workload, rounds, roles, models | `examples/experiments/synthesizer-n1-local.json` |
| Task | v1 JSON: instruction, source, setup script, dependency lock | `examples/tasks/pvlib-1478/task.json` |
| Instruction | UTF-8 task text, without a solution or hidden tests | `examples/tasks/pvlib-1478/instruction.md` |
| Setup | Trusted shell script; creates the isolated task environment | `examples/tasks/pvlib-1478/setup.sh` |
| Task dependencies | Fully pinned requirements with SHA-256 hashes | `examples/tasks/pvlib-1478/requirements.lock` |
| Personas | JSON array following the repository persona schema | `examples/personas/n1.json` |
| Credentials | Explicit environment variables or a mode-0600 env file | `examples/experiment.env.example` |

Paths in the experiment are relative to that JSON; task paths are relative to the task package. `prepare` generates the roster, task pool, interaction plan, single-instance SWE Parquet when needed, source/Harness archives and hash manifest. You do not need to handcraft these.

## Experiment fields

| Field | Meaning |
| --- | --- |
| `name` | Display name; a unique `run_id` is generated automatically |
| `runtime.backend` | `local` or `e2b` |
| `runtime.gitea` | Provider `localhost` for local, `gitea.com` for E2B; repository prefix |
| `runtime.local` | Optional image overrides and `ci_enabled: false`; enabling an unregistered CI runner is unsupported |
| `runtime.e2b` | Requested `cpu_count`, `memory_mb`, `timeout_seconds` (300–86400); optional compatible template |
| `harness.source` | `builtin`, or `archive` with an archive path and SHA-256 |
| `workload` | `kind`, task package, persona library and actual persona IDs |
| `rounds` | `count`, `sessions_per_round`, `max_parallel_users` |
| `roles` | Triage/Synthesizer/divergent/developer counts; `owner_mode: mechanical` |
| `models` | User, Harness, shared demand and Claude Code delivery settings |
| `evaluation.official_grading` | `false`; official grading runs separately |
| `source` | Optional credential-free HTTPS repository and full immutable revisions; defaults come from `release/compatibility.json` |

The initial single-task schema supports one session per round. Personas may rotate across rounds. The N=1 examples select one persona, one Triage, one Synthesizer, zero divergent PMs, one delivery worker, and five rounds. The last round is always user-only.

`builtin` freezes this checkout's `backend/harness_template/`. It is not the historical `cade14d` Harness. To reproduce that baseline, supply its actual archive and checksum explicitly.

## Models and credentials

Each model setting contains a model name, `base_url_env` and `api_key_env`. These are names of variables, never keys or URLs containing credentials. Model names live in the JSON and are frozen by `prepare`; environment files supply connection credentials.

| Role | Example variables | Protocol |
| --- | --- | --- |
| Simulated user | `USER_LLM_BASE_URL`, `USER_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| Harness | `HARNESS_LLM_BASE_URL`, `HARNESS_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| Triage, Synthesizer, PM | `DEMAND_LLM_BASE_URL`, `DEMAND_LLM_API_KEY` | OpenAI-compatible Chat Completions |
| OpenAgents delivery | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` | Anthropic-compatible Claude Code |
| E2B infrastructure | `E2B_API_KEY` | E2B API |
| Gitea.com | `GITEA_TOKEN`; optional `GITEA_USER` | Account resolved by API |

For standard Anthropic API keys change delivery's `api_key_env` to `ANTHROPIC_API_KEY` and provide that variable. Do not put a Chat Completions-only endpoint in the delivery setting. A shared provider key can be repeated in the required env variables; dotenv interpolation is not enabled.

The explicit `--secrets-file` overrides identically named process variables. No implicit `backend/.env`, user Claude settings or personal trial directory is read. The protected file path may be recorded for later management; secret contents are excluded from material snapshots and archives. To move credentials, pass another `--secrets-file` to the management command. Status, collection and destruction do not require model keys, but cloud operations still need provider credentials.

## Task package

The public example contains:

```json
{
  "schema_version": 1,
  "kind": "swebench",
  "id": "pvlib__pvlib-python-1478",
  "instruction_file": "instruction.md",
  "source": {
    "kind": "git",
    "url": "https://github.com/pvlib/pvlib-python.git",
    "revision": "3f397ed44075b01f4ba535750356859195a51b2d",
    "repo": "pvlib/pvlib-python"
  },
  "setup": {"script": "setup.sh", "requirements_lock": "requirements.lock"},
  "difficulty": "15 min - 1 hour"
}
```

An ordinary custom task uses `kind: ordinary`, explicitly sets `not_in_benchmark: true`, and can use fixed Git source or `source: {"kind": "local", "path": "./my-task"}`. A SWE task must use a fixed Git revision and must not declare `not_in_benchmark`. Both the workload and task package must declare the same kind.

Setup runs in the task checkout with `TASK_ROOT`, `TASK_PYTHON`, `REQUIREMENTS_LOCK`, `VIRTUAL_ENV` and `UV_BIN` provided. `TASK_PYTHON` is the managed interpreter; `VIRTUAL_ENV` points to the task's independent `.venv`. Install the hash-locked task dependencies there, then install the task source without downloading undeclared dependencies. Controller and OpenAgents have separate locked environments.

## Backend boundaries and lifecycle

Local execution starts per-experiment Gitea and an egress proxy, then owned Vigil and user-session containers. Gitea's host port is dynamically allocated on loopback; status reports its actual URL. Model domains/ports come from the explicit endpoints. Engineering CI is skipped in this version; no empty-token runner is started.

E2B runs the controller and delivery processes inside one sandbox without nested Docker. Task directories are isolated within that sandbox; this differs from local per-session container isolation. Actual CPU, memory, template/build identity and expiry are checked and recorded. The default example requests 4 CPUs and 8192 MiB. Model usage and cloud runtime determine cost and duration.

Local evidence uses the negotiated gzip/direct transport; Gitea.com uses ZIP and constrained R2 downloads. Preflight checks the actual pinned OpenAgents reader, disables self-update, and verifies publishing and reading before the user experiment. Original self-hosted gzip handles remain supported.

Frozen `manifest.json` describes inputs. Mutable `runtime.json` and provider/controller receipts describe observations. The three state axes are independent: experiment `COMPLETED` can coexist with resources `DESTROYED` and collection `COMPLETE`. An unreachable provider is an unknown observation, not proof of completion. Resume requires the original identity, repository, resources and recovery data. Normal completion releases dedicated compute only after complete collection; stopping E2B processes alone does not release its sandbox.

Use global `--runs-dir /absolute/path/runs` before the command to select another run root. Always use the same root for subsequent management. Editing the original JSON or source checkout after preparation does not change an existing run. For a changed experiment, prepare a new run.

Historical `backend/.env`, model profiles and evaluation launchers are retained for their original schemas. They are not an alternative configuration source for v2.

The pvlib recipe includes a build-only shim for its historical Versioneer on Python 3.12. It restores removed `configparser` aliases during editable installation without patching the frozen task source, then removes the shim. The task environment includes hash-pinned pytest for user-side checks.
