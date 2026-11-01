# Append rounds to a completed experiment

English | [简体中文](experiment-continuation.zh-CN.md)

This tutorial creates a child experiment from a completed experiment archive and adds user rounds. The child inherits the final Harness and the parent’s final task/persona/interaction pairs. It processes the final feedback and waits for admitted work to be delivered before starting new trials. The child configuration selects models, roles, backend and runtime policies.

This uses the existing check/prepare/run/status/stop/resume/collect/destroy commands. `resume` continues the same run; continuation creates a new identity and repository. Only current schema-2 / workload-contract-1 archives containing the new continuation export are accepted. Previously frozen controllers and archives without that export are not upgraded.

## 1. Install and choose the parent

Run from the repository root with Python 3.12+ and uv. Start with a parent prepared using a controller that produces the current continuation export, and wait for it to reach `COMPLETED`. The [U1 tutorial](u1-experiment.md) covers creating that parent on local Docker or E2B.

```bash
uv sync --locked --extra experiments
RUNS_DIR="$PWD/.experiments"
WORK_DIR="$(mktemp -d)"
PARENT_RUN_ID=REPLACE_WITH_COMPLETED_PARENT_RUN_ID
ADD_ROUNDS=2
```

Use the actual root if the parent was prepared with a custom `--runs-dir`. Keep this shell and the generated files until preparation freezes the child inputs.

## 2. Collect a usable parent archive

Use the parent's explicit credential profile for infrastructure access. Collection does not require model credentials.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" status "$PARENT_RUN_ID" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py --json --runs-dir "$RUNS_DIR" collect "$PARENT_RUN_ID" --secrets-file .env.experiment > "$WORK_DIR/parent-collection.json"
```

The receipt must show `collection_state: COMPLETE`, `controller.experiment_complete: true` and `continuation_ready: true`. `COMPLETE` alone describes consistent collection and can also describe a stopped or failed experiment. An unavailable final tree or changed executable material makes the archive unsuitable for continuation; preserve its ordinary results and inspect the receipt. Missing or unverifiable native observations remain declared evidence gaps.

The archive contains a versioned `runtime/continuation-export.json` bound to the last round's exact SHA, plus its task materials, persona cards, sessions and forge evidence. Source validation checks the archive SHA and per-file hashes before any child resources are created. A retained complete archive can be used after the parent's compute is destroyed.

## 3. Generate complete local and E2B child definitions

This command copies each maintained U1 definition and replaces its Harness/workload inputs with the validated parent source. It preserves the template's complete model, role, runtime and policy settings. It reads the parent's last-round session count rather than assuming U1, and writes absolute archive paths so moving the child JSON does not change their meaning.

```bash
uv run --locked --extra experiments python - "$WORK_DIR" "$ADD_ROUNDS" <<'PYCODE'
import hashlib
import json
import sys
import tarfile
from pathlib import Path

work_dir = Path(sys.argv[1]).resolve()
additional_rounds = int(sys.argv[2])
if additional_rounds < 1:
    raise SystemExit("ADD_ROUNDS must be a positive integer")
receipt = json.loads((work_dir / "parent-collection.json").read_text(encoding="utf-8"))
if not (
    receipt.get("collection_state") == "COMPLETE"
    and receipt.get("controller", {}).get("experiment_complete") is True
    and receipt.get("continuation_ready") is True
):
    raise SystemExit("Parent must be complete and continuation_ready")
parent_archive = Path(receipt["archive"]).resolve()
with parent_archive.open("rb") as handle:
    archive_sha = hashlib.file_digest(handle, "sha256").hexdigest()
if archive_sha != receipt["archive_sha256"]:
    raise SystemExit("Parent archive differs from its collection receipt")
with tarfile.open(parent_archive, "r:gz") as archive:
    export = json.load(archive.extractfile("runtime/continuation-export.json"))
sessions = len(export["boundary"]["sessions"])
for backend in ("local", "e2b"):
    template = Path(f"examples/experiments/u1-{backend}.json")
    config = json.loads(template.read_text(encoding="utf-8"))
    config["name"] = f"continuation-{backend}"
    config["harness"] = {"source": "continuation"}
    config["workload"] = {"source": "parent"}
    config["continuation"] = {"archive": str(parent_archive), "sha256": archive_sha}
    config["rounds"] = {
        "count": additional_rounds,
        "sessions_per_round": sessions,
        "max_parallel_users": sessions,
    }
    destination = work_dir / f"child-{backend}.json"
    destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
PYCODE
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/child-local.json" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/child-e2b.json" --offline
```

The three input selectors must appear together: `harness.source=continuation`, `workload={"source":"parent"}`, and `continuation={"archive":...,"sha256":...}`. Do not add task packages, a persona library, persona IDs or an interaction plan to the inherited workload. Every new round repeats the parent's final pairs in their original order; task content, persona content and `direct`/`simulated_user` interaction remain fixed. `sessions_per_round` must match that boundary. Reduce `max_parallel_users` if desired. Pending reports require at least one Triage and one Synthesizer.

Offline check reports the parent identity, boundary, pairs, reports and evidence gaps. It does not start models or providers, prepare task environments, or prove task success. The generated local and E2B files are alternative child configurations; choose one to run.

## 4. Prepare and start the new run

Edit the selected child's models and policies before preparation. Its explicit credential profile supplies current model/provider access; credentials and grants from the parent are not inherited. Local requires Docker/Compose and provisions a fresh localhost Gitea. E2B requires its own API key and Gitea.com account. Normal task preparation still applies to inherited source archives and dependency locks.

```bash
CONFIG="$WORK_DIR/child-local.json"
# CONFIG="$WORK_DIR/child-e2b.json"
cp examples/experiment.env.example .env.continuation
chmod 600 .env.continuation
# Fill the child model and provider credentials before continuing.
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --json --runs-dir "$RUNS_DIR" prepare --config "$CONFIG" --secrets-file .env.continuation > "$WORK_DIR/child-prepared.json"
CHILD_RUN_ID="$(uv run --locked --extra experiments python -c 'import json,sys; print(json.load(open(sys.argv[1]))["run_id"])' "$WORK_DIR/child-prepared.json")"
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" run "$CHILD_RUN_ID" --secrets-file .env.continuation
```

Preparation atomically freezes the selected parent inputs and current controller/OpenAgents sources under the new identity. The child seed commit has the same Git tree as the parent boundary; its commit SHA is new because parent Git history is not imported. `manifest.lineage` records that relationship and configuration differences.

The `continuation-bootstrap` phase maps pending parent reports into the child repository, runs the shared feedback pipeline and seals its result. It does not count as a new user round or copy parent users into the child ledger. Closed, rejected or already delivered reports remain background evidence. Zero admissions produce an explicit `no_admissions` seal; they do not prove code delivery. A blocked delivery keeps new users from starting. Even `rounds.count: 1` enables delivery for this initialization.

`rounds.count` counts **new user rounds**. For a parent ending at logical R5, the default `ADD_ROUNDS=2` produces child local R1/R2 at logical R6/R7. Local R1 processes its own feedback before local R2; local R2 remains users-only. Parent sessions, ratings and usage do not enter the child's new-user totals. Optional engineering CI follows the child configuration; the templates keep it disabled, and E2B CI remains unsupported.

## 5. Observe, stop and resume the child

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" status "$CHILD_RUN_ID" --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" logs "$CHILD_RUN_ID" --tail 100 --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" stop "$CHILD_RUN_ID" --secrets-file .env.continuation
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" resume "$CHILD_RUN_ID" --secrets-file .env.continuation
```

Status exposes initialization separately from ordinary rounds, which include `local_round` and `lineage_round`. Stop/resume operates on this child and its frozen inputs. Completed initialization is reconciled without repeating report creation, model calls or delivery. An interruption during initialization resumes its independent checkpoint domain before opening user rounds; the parent's completed ledger stays unchanged.

## 6. Collect, append again and clean up

Wait for the child to reach `COMPLETED`, then collect its own final export.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json --runs-dir "$RUNS_DIR" collect "$CHILD_RUN_ID" --secrets-file .env.continuation > "$WORK_DIR/child-collection.json"
uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$RUNS_DIR" destroy "$CHILD_RUN_ID" --confirm "$CHILD_RUN_ID" --secrets-file .env.continuation
```

For another addition, use the child's complete receipt as `parent-collection.json`, set `ADD_ROUNDS=1`, and repeat steps 3–4 to create another new run. A child ending at logical R7 becomes the next parent; the next local R1 displays logical R8. The next source selects that direct parent's own final users and feedback. Ancestor identity/hash summaries are retained without recursively embedding complete parent archives.

`destroy` releases the named child’s resources and preserves collected evidence. Manage parent resources separately with the parent run ID and credentials. `grade --round` and batch operations use each run’s local round numbers. See [configuration](../CONFIGURATION.md) for the full input contract and [Verification](../VERIFICATION.md) for development checks.
