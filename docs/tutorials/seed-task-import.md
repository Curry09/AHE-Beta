# Import a seed library or a text task

English | [简体中文](seed-task-import.zh-CN.md)

Use this workflow when you have an explicitly supplied non-benchmark seed library or your own UTF-8 task instruction. `task import-seeds` and `task from-text` create ordinary task packages for the existing local/E2B lifecycle. They do not start an experiment, fetch Git, call models/providers, read credentials, or execute setup. This tutorial gets both backend configuration copies through a complete offline check.

## 1. Install and choose fresh output directories

From the repository root on Linux or WSL2, use Python 3.12+ and uv. Dependency installation may use the network; conversion and `check --offline` need no network, credentials, Docker daemon or E2B account once dependencies are installed. Keep these commands in the same shell.

```bash
uv sync --locked --extra experiments
WORK_DIR="$(mktemp -d)"
```

The converter requires an output directory that does not yet exist, even if an existing directory is empty or a symlink. The parent temporary directory above exists; its `seeds` and `text` children do not. Keep the directory until preparation has frozen its materials. For a lasting workflow, use a persistent parent directory and fresh child names.

## 2. Convert the supplied materials

[The public library](../../examples/seed-inputs/library.json) contains one synthetic plaintext checklist task explicitly marked non-benchmark. It is a small input-format example, not a historical research card collection. [The instruction](../../examples/seed-inputs/instruction.md) describes a weekly notes tool; replace its text with your own task if needed, and confirm that it is not from a benchmark before using the required declaration.

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json task import-seeds examples/seed-inputs/library.json --output "$WORK_DIR/seeds" --seed plaintext-checklist > "$WORK_DIR/seeds-result.json"
uv run --locked --extra experiments python backend/scripts/experiment.py --json task from-text --instruction examples/seed-inputs/instruction.md --id weekly-notes --output "$WORK_DIR/text" --not-in-benchmark --interaction direct > "$WORK_DIR/text-result.json"
```

The seed example defaults to `simulated_user`; the text example selects `direct`. Both commands accept `--interaction direct|simulated_user`. With a larger library, repeat `--seed ID` for distinct IDs, or omit it to import all cards in their library order. Duplicate selections are rejected; output stays in library order. Place the parent's `--json` before `task` to capture a machine-readable result.

Libraries may be a bare array or an object with a `seeds` array. Each selected card needs a safe unique `id`, `source.not_in_benchmark: true` and non-empty `task.prompt`. Missing input, empty libraries, invalid selected cards and benchmark cards fail. Rejected cards and adapted SeedScenario envelopes are not seed-library input. A repository card requires `source.repo` as an owner/repo identifier (resolved to GitHub HTTPS) or a credential-free HTTPS owner/repo URL, and a fixed 40-character lowercase Git SHA in `env.repo_at`. Conversion checks the declaration without cloning it; later preparation verifies the source.

Both examples produce ordinary v1 task packages with instruction, setup and requirements files. A task without a repository gets a local `source/` scratch directory containing a README that explains the starting workspace. That README makes the initial material hashable; it contains no task solution. `task.prompt` becomes the instruction verbatim without appending `task.context`; text import preserves the supplied UTF-8 instruction.

Only the permitted prompt/source/setup mapping is exported. `oracle`, `env.test_cmd`, `gates` and `provenance` are not copied into packages, indexes or hidden sidecars. The source summary keeps input byte digests, IDs and source kinds. Old `env.setup` strings are preserved in order for later execution under the current task-venv contract. The importer does not automatically lock those dependencies or restore old base images, external services, budgets or pairing metadata. Review generated setup and requirements before prepare; importing does not prove the original environment is reproducible.

## 3. Copy the absolute package array into both experiment templates

Each command's JSON result supplies an absolute `task_packages` array. The generated `tasks.json` is a relative-path index rooted at the output directory, with source summaries and ordering. It is not a new experiment definition: do not put the index path in `workload.task_packages`. Use the result's actual package paths; if moving the packages, update their references.

The following code combines the two result arrays and copies one existing N1 template for each backend. It removes the old single-package fields and any old task-specific plan, then installs the new array. It also resolves the template's persona path because the copied JSON is in a different directory. Models, personas, role counts and five-round settings still come from the N1 templates. One user session per round alternates the two tasks; use an explicit new plan if you need another assignment.

```bash
uv run --locked --extra experiments python - "$WORK_DIR" <<'PYCODE'
import json
import sys
from pathlib import Path

work_dir = Path(sys.argv[1]).resolve()
task_packages = []
for result_name in ("seeds-result.json", "text-result.json"):
    result = json.loads((work_dir / result_name).read_text(encoding="utf-8"))
    task_packages.extend(result["task_packages"])

for backend in ("local", "e2b"):
    template = Path(f"examples/experiments/synthesizer-n1-{backend}.json").resolve()
    config = json.loads(template.read_text(encoding="utf-8"))
    workload = config["workload"]
    workload["persona_library"] = str(
        (template.parent / workload["persona_library"]).resolve()
    )
    for key in ("kind", "task_package", "interaction_plan"):
        workload.pop(key, None)
    workload["task_packages"] = task_packages
    config["name"] = f"imported-tasks-{backend}"
    destination = work_dir / f"experiment-{backend}.json"
    destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(destination)
PYCODE
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/experiment-local.json" --offline
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$WORK_DIR/experiment-e2b.json" --offline
```

Both checks should exit successfully and show an unfrozen allocation preview. They validate packages, persona references and session assignments; they do not prove task success, Git availability, setup execution or backend readiness. No real local/E2B experiment is demonstrated by these checks.

## 4. Continue with check, prepare and run

After reviewing the generated materials, choose a backend, fill model/provider credentials using [configuration](../CONFIGURATION.md), and meet the infrastructure requirements in [Quickstart](../QUICKSTART.md). The example below uses the ordinary lifecycle; online checking and preparation can contact providers and fetch sources, and running uses models and compute.

```bash
CONFIG="$WORK_DIR/experiment-local.json"
# CONFIG="$WORK_DIR/experiment-e2b.json"
cp examples/experiment.env.example .env.experiment
chmod 600 .env.experiment
# Fill model and provider credentials before continuing.
uv run --locked --extra experiments python backend/scripts/experiment.py check --config "$CONFIG" --secrets-file .env.experiment
uv run --locked --extra experiments python backend/scripts/experiment.py prepare --config "$CONFIG" --secrets-file .env.experiment
RUN_ID=REPLACE_WITH_PRINTED_RUN_ID
uv run --locked --extra experiments python backend/scripts/experiment.py run "$RUN_ID" --secrets-file .env.experiment
```

Local requires Docker/Compose and provisions localhost Gitea; E2B requires its API key and a Gitea.com account. Wait for preparation to finish and use its printed run ID. Follow [the N1 tutorial](n1-experiment.md) for progress, stopping/resuming the same run, collection and cleanup. Task conversion adds an input path to the existing lifecycle; it does not import historical results to append rounds. Optional local engineering CI uses a dedicated runner and private Docker daemon as described in the [CI tutorial](local-engineering-ci.md); historical continuation still requires separate design.
